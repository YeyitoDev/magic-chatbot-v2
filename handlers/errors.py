"""
Error Handler - Magic Chatbot v2
=================================
Manejador global de errores para el bot de Telegram.

Captura todas las excepciones no manejadas que ocurren durante el
procesamiento de updates y proporciona:
- Logging detallado del error con traceback completo.
- Notificación al usuario afectado (cuando es posible).
- Notificación a los administradores/validadores para errores críticos.
- Recuperación graceful: el bot sigue funcionando después de un error.

Principios aplicados:
- Fail-safe: ningún error debe tumbar el bot.
- Observability: cada error se loguea con contexto suficiente para debugging.
- User-friendly: mensajes de error claros para el usuario final.

Basado en el patrón de error handler de python-telegram-bot v20+.

Uso:
    from handlers.errors import ErrorHandler

    error_handler = ErrorHandler(telegram_api_service, logger)
    app.add_error_handler(error_handler.handle)
"""

import html
import logging
import traceback

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from config.settings import settings

logger = logging.getLogger(__name__)


class ErrorHandler:
    """
    Manejador global de errores del bot.

    Proporciona un callback que puede registrarse en la aplicación
    de python-telegram-bot mediante `app.add_error_handler()`.

    Attributes:
        _admin_ids: Lista de IDs de Telegram de los administradores a notificar.
    """

    def __init__(self) -> None:
        """
        Inicializa el manejador de errores.

        Obtiene la lista de administradores/validadores desde settings
        para notificarles en caso de errores críticos.
        """
        self._admin_ids = settings.TELEGRAM_VALIDATOR_IDS

    # ------------------------------------------------------------------
    # Handler principal
    # ------------------------------------------------------------------

    async def handle(
        self, update: object | None, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Callback principal de manejo de errores.

        Se invoca automáticamente por python-telegram-bot cuando ocurre
        una excepción no capturada en cualquier otro handler.

        Args:
            update: Update que causó el error (puede ser None).
            context: Contexto del callback con información del error.
        """
        # Extraer el error del contexto
        error = context.error

        if error is None:
            logger.warning("Error handler llamado sin error en el contexto.")
            return

        # Construir mensaje de log detallado
        tb_list = traceback.format_exception(
            type(error), error, error.__traceback__
        )
        tb_string = "".join(tb_list)

        # Construir contexto del update para el log
        update_info = self._extract_update_info(update)

        # Loggear el error con todo el contexto disponible
        logger.error(
            f"Excepción no manejada mientras se procesaba un update:\n"
            f"Update Info: {update_info}\n"
            f"Error: {type(error).__name__}: {error}\n"
            f"Traceback:\n{tb_string}"
        )

        # Rollback de sesión de BD si es un error de SQLAlchemy para evitar
        # que la conexión quede en estado inválido (PendingRollbackError)
        self._rollback_db_session_if_needed(error)

        # Notificar al usuario afectado (si el update lo permite)
        await self._notify_user(update, context)

        # Notificar a los administradores para errores críticos
        await self._notify_admins(update, error, tb_string, context)

    # ------------------------------------------------------------------
    # Extracción de información del update
    # ------------------------------------------------------------------

    def _extract_update_info(self, update: object | None) -> str:
        """
        Extrae información relevante del update para el log de errores.

        Args:
            update: El update de Telegram que causó el error.

        Returns:
            String con información resumida del update en formato legible.
        """
        if update is None:
            return "Update is None"

        info_parts = []

        if isinstance(update, Update):
            # Update efectivo de Telegram
            if update.effective_user:
                user = update.effective_user
                info_parts.append(
                    f"User: id={user.id}, username=@{user.username}, "
                    f"first_name={user.first_name}"
                )
            if update.effective_chat:
                chat = update.effective_chat
                info_parts.append(
                    f"Chat: id={chat.id}, type={chat.type}"
                )
            if update.effective_message:
                msg = update.effective_message
                info_parts.append(
                    f"Message: id={msg.message_id}, "
                    f"text={msg.text[:100] if msg.text else '[no text]'}"
                )
            if update.callback_query:
                cb = update.callback_query
                info_parts.append(
                    f"Callback: data={cb.data[:200] if cb.data else '[no data]'}"
                )
        else:
            info_parts.append(f"Update type: {type(update).__name__}")

        return " | ".join(info_parts) if info_parts else "No info available"

    # ------------------------------------------------------------------
    # Notificación al usuario
    # ------------------------------------------------------------------

    async def _notify_user(
        self,
        update: object | None,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Intenta notificar al usuario que ocurrió un error.

        Si el update contiene información suficiente para identificar
        al usuario y al chat, se envía un mensaje amigable de error.

        Args:
            update: Update que causó el error.
            context: Contexto del bot.
        """
        if not isinstance(update, Update):
            return

        try:
            if update.effective_chat and update.effective_message:
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text=(
                        "❌ Lo siento, ocurrió un error inesperado mientras "
                        "procesaba tu solicitud.\n\n"
                        "El equipo de soporte ha sido notificado y estamos "
                        "trabajando para resolverlo.\n\n"
                        "Mientras tanto, puedes intentar de nuevo o contactar "
                        "a @magic_peru para asistencia inmediata 📲"
                    ),
                    parse_mode=ParseMode.HTML,
                )
                logger.debug(
                    f"Mensaje de error enviado al usuario "
                    f"{update.effective_user.id if update.effective_user else 'desconocido'}"
                )
        except Exception as e:
            # No podemos hacer mucho si falla la notificación al usuario
            logger.warning(f"No se pudo notificar al usuario sobre el error: {e}")

    # ------------------------------------------------------------------
    # Notificación a administradores
    # ------------------------------------------------------------------

    async def _notify_admins(
        self,
        update: object | None,
        error: Exception,
        tb_string: str,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Notifica a los administradores sobre errores críticos.

        Solo se notifican errores que NO son causados por el usuario
        (ej: no se notifican errores de validación de input).

        Args:
            update: Update que causó el error.
            error: La excepción ocurrida.
            tb_string: Traceback formateado como string.
            context: Contexto del bot.
        """
        # No notificar errores triviales o causados por el usuario
        if self._is_user_error(error):
            return

        # Construir mensaje de error para administradores
        update_info = self._extract_update_info(update)
        error_message = (
            f"<b>🚨 ERROR CRÍTICO EN EL BOT</b>\n\n"
            f"<b>Error:</b> <code>{html.escape(str(error)[:200])}</code>\n"
            f"<b>Tipo:</b> <code>{type(error).__name__}</code>\n"
            f"<b>Update:</b> {html.escape(update_info[:300])}\n\n"
            f"<b>Traceback (últimas líneas):</b>\n"
            f"<pre>{html.escape(self._truncate_traceback(tb_string, 10))}</pre>\n\n"
            f"<i>Revisa los logs del servidor para el traceback completo.</i>"
        )

        # Enviar a cada administrador configurado
        for admin_id in self._admin_ids:
            try:
                await context.bot.send_message(
                    chat_id=int(admin_id),
                    text=error_message,
                    parse_mode=ParseMode.HTML,
                )
                logger.debug(f"Notificación de error enviada a admin {admin_id}")
            except Exception as e:
                logger.warning(
                    f"No se pudo notificar al admin {admin_id} sobre el error: {e}"
                )

    # ------------------------------------------------------------------
    # Clasificación de errores
    # ------------------------------------------------------------------

    def _is_user_error(self, error: Exception) -> bool:
        """
        Determina si un error fue causado por el usuario (no es crítico).

        Los errores de usuario son aquellos causados por input inválido,
        timeouts, o acciones del usuario que no requieren intervención
        del equipo de desarrollo.

        Args:
            error: La excepción a clasificar.

        Returns:
            True si es un error causado por el usuario, False si es del sistema.
        """
        user_error_types = (
            # Errores de red / usuario bloqueó al bot
            "Forbidden",
            "Unauthorized",
            "ChatNotFound",
            # Errores de input del usuario
            "BadRequest",
            "InvalidCallbackData",
            "MessageNotModified",
            "MessageToDeleteNotFound",
            "MessageToEditNotFound",
            # Errores de rate limiting
            "RetryAfter",
            "Flood",
            # Errores de timeout
            "TimedOut",
            "NetworkError",
        )

        error_name = type(error).__name__
        return any(err_type in error_name for err_type in user_error_types)

    def _rollback_db_session_if_needed(self, error: Exception) -> None:
        """
        Hace rollback de la sesión de BD y fuerza reconexión si es necesario.

        Cuando ocurre un error durante una transacción, SQLAlchemy deja
        la sesión en estado inválido. Sin rollback, todas las operaciones
        posteriores fallan con PendingRollbackError.

        Args:
            error: La excepción ocurrida.
        """
        error_name = type(error).__name__
        error_str = str(error)

        # Solo actuar ante errores de base de datos
        sqlalchemy_errors = (
            "PendingRollbackError",
            "OperationalError",
            "IntegrityError",
            "ProgrammingError",
            "DatabaseError",
            "InterfaceError",
            "SQLAlchemyError",
        )
        is_connection_lost = (
            "Lost connection" in error_str
            or "MySQL server has gone away" in error_str
        )
        is_db_error = (
            is_connection_lost
            or any(err in error_name for err in sqlalchemy_errors)
        )
        if not is_db_error:
            return

        # PASO 1: Rollback de la sesión compartida SIEMPRE.
        # Esto es lo que limpia la transacción inválida y evita que la
        # siguiente petición falle con PendingRollbackError.
        try:
            from core.container import container
            if container.is_registered("db_session"):
                session = container.resolve("db_session")
                if hasattr(session, "rollback"):
                    session.rollback()
                    logger.info("Rollback de sesión de BD ejecutado tras error de BD.")
        except Exception as e:
            logger.warning(f"No se pudo hacer rollback de la sesión: {e}")

        # PASO 2: Si la conexión se perdió, además reciclar el pool para
        # que la próxima query obtenga una conexión fresca.
        if is_connection_lost:
            logger.warning("Conexión a MySQL perdida. Reciclando pool de conexiones...")
            try:
                from core.database import engine
                engine.dispose()
                logger.info("Pool de conexiones SQLAlchemy dispose() ejecutado.")
            except Exception as e:
                logger.error(f"No se pudo reciclar el pool de conexiones: {e}")

    def _truncate_traceback(
        self, tb_string: str, max_lines: int = 10
    ) -> str:
        """
        Trunca un traceback a las últimas N líneas para notificaciones.

        El traceback completo está disponible en los logs del servidor.
        Para notificaciones de Telegram solo enviamos las últimas líneas.

        Args:
            tb_string: Traceback completo como string.
            max_lines: Número máximo de líneas a retornar.

        Returns:
            Traceback truncado a las últimas max_lines líneas.
        """
        lines = tb_string.strip().split("\n")
        if len(lines) <= max_lines:
            return tb_string
        return "...\n" + "\n".join(lines[-max_lines:])

    # ------------------------------------------------------------------
    # Registro del handler
    # ------------------------------------------------------------------

    @staticmethod
    def register(app) -> None:
        """
        Registra este error handler en una aplicación de python-telegram-bot.

        Método de conveniencia para simplificar la configuración en main.py.

        Args:
            app: Instancia de Application de python-telegram-bot.

        Example:
            >>> from handlers.errors import ErrorHandler
            >>> ErrorHandler.register(app)
        """
        handler = ErrorHandler()
        app.add_error_handler(handler.handle)
        logger.info("Error handler global registrado en la aplicación.")
