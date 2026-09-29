"""
Reminder Service - Magic Chatbot v2
====================================
Servicio de dominio para la gestión de recordatorios de compra.

Maneja el pipeline de recordatorios para usuarios que seleccionaron
un servicio pero no completaron la compra:

Fase 1 (reminder=0, 1min - 24h): Envía imagen + precios actualizados.
Fase 2 (reminder=1, >24h): Envía video recordatorio.
Fase 3 (reminder>=2, >24h): Elimina el registro de selección.

También gestiona el envío de mensajes de suscripción vencida a usuarios
que han sido expulsados del grupo por falta de pago.

Principios:
- Single Responsibility: solo lógica de recordatorios y notificaciones.
- Dependency Inversion: depende de repositorios y servicios externos.
- Configurable: intervalos y rutas de archivos vía settings.

Uso:
    from services.reminder_service import ReminderService

    reminder_svc = ReminderService(selected_service_repo, subscription_repo)
    await reminder_svc.process_pending_reminders()
"""

import logging
from datetime import datetime
from typing import Any

from repositories.selected_service_repo import SelectedServiceRepository
from repositories.subscription_repo import SubscriptionRepository

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Templates de mensajes
# ---------------------------------------------------------------------------

MENSAJE_SUSCRIPCION_VENCIDA_TEMPLATE = """¿QUIERES GANAR CÓMO MIS CLIENTES?

🔴 *SUSCRIPCIÓN VENCIDA*

Lamentamos informarte que tu suscripción ha expirado el *{fecha}*.

¡LA ÚNICA COMUNIDAD RENTABLE DE TODO EL PERÚ!
Que esperas para volver a unirte mi hermano 🔥

Para continuar disfrutando de nuestros servicios premium y acceder
nuevamente al grupo VIP, debes renovar tu suscripción.

📱 *¿Cómo renovar?*
Selecciona el plan que desees y vuelve a unirte! 🔮✅

Una vez completado el pago, serás agregado nuevamente al grupo.

❓ *¿Preguntas o problemas?*
Contáctame directamente: @magic_peru 📲
Estoy aquí para ayudarte 24/7 💬

¡Esperamos verte pronto! 🔮✨"""


# ---------------------------------------------------------------------------
# Reminder Service
# ---------------------------------------------------------------------------

class ReminderService:
    """
    Servicio de lógica de negocio para recordatorios y notificaciones.

    Gestiona:
    - Recordatorios de compra pendiente (fase 1 y fase 2).
    - Limpieza de selecciones expiradas.
    - Mensajes de suscripción vencida.

    Dependencias:
        selected_service_repo: Para consultar/actualizar selecciones.
        subscription_repo: Para consultar suscripciones vencidas.
    """

    def __init__(
        self,
        selected_service_repo: SelectedServiceRepository,
        subscription_repo: SubscriptionRepository,
    ) -> None:
        """
        Inicializa el servicio con sus repositorios.

        Args:
            selected_service_repo: Repositorio de servicios seleccionados.
            subscription_repo: Repositorio de suscripciones.
        """
        self._selected_repo = selected_service_repo
        self._subscription_repo = subscription_repo

    # ------------------------------------------------------------------
    # Pipeline principal de recordatorios
    # ------------------------------------------------------------------

    def process_pending_reminders(self) -> dict[str, Any]:
        """
        Procesa recordatorios: 3 mensajes de texto, cada 1 hora.
        Solo para usuarios que seleccionaron servicio pero no compraron.
        """
        from services.telegram_api import TelegramAPIService

        api = TelegramAPIService()
        stats = {"total": 0, "fase1": 0, "fase2": 0, "fase3": 0, "deleted": 0, "errors": []}

        try:
            pending = self._selected_repo.get_all()
            stats["total"] = len(pending)
            now = datetime.now()

            for selected in pending:
                user_id = selected.user_telegram_id
                elapsed_minutes = int((now - selected.selected_date).total_seconds() / 60)
                reminder = selected.reminder

                # Fase 1: reminder=0, 1 hora después → mensaje 1
                if reminder == 0 and elapsed_minutes >= 60:
                    try:
                        api.send_message(
                            chat_id=user_id,
                            text="¿QUIERES GANAR CÓMO MIS CLIENTES?\n"
                                 "Las mejores fijas estadísticas de todo el Perú, "
                                 "simplemente selecciona que servicios deseas y unete! 🔮✅"
                        )
                        self._selected_repo.increment_reminder(user_id)
                        stats["fase1"] += 1
                        logger.info(f"Recordatorio fase 1 enviado a {user_id}")
                    except Exception as e:
                        stats["errors"].append(f"fase1:{user_id}:{e}")

                # Fase 2: reminder=1, 2 horas después → mensaje 2
                elif reminder == 1 and elapsed_minutes >= 120:
                    try:
                        api.send_message(
                            chat_id=user_id,
                            text="¡LA ÚNICA COMUNIDAD RENTABLE DE TODO EL PERÚ!\n"
                                 "Que esperas para unirte mi hermano 🔥"
                        )
                        self._selected_repo.increment_reminder(user_id)
                        stats["fase2"] += 1
                        logger.info(f"Recordatorio fase 2 enviado a {user_id}")
                    except Exception as e:
                        stats["errors"].append(f"fase2:{user_id}:{e}")

                # Fase 3: reminder=2, 3 horas después → mensaje 3 + eliminar
                elif reminder == 2 and elapsed_minutes >= 180:
                    try:
                        api.send_message(
                            chat_id=user_id,
                            text="🔥 *ÚLTIMA OPORTUNIDAD* 🔥\n\n"
                                 "Los precios del Grupo VIP van a subir pronto. "
                                 "Aprovecha ahora y asegura tu acceso a los mejores "
                                 "pronósticos deportivos del Perú.\n\n"
                                 "Habla con @magic_peru para unirte hoy mismo 📲"
                        )
                        self._selected_repo.delete_by_user(user_id)
                        stats["fase3"] += 1
                        logger.info(f"Recordatorio fase 3 enviado y registro eliminado para {user_id}")
                    except Exception as e:
                        stats["errors"].append(f"fase3:{user_id}:{e}")
                        # Delete anyway if too old
                        if elapsed_minutes > 360:  # 6 hours max
                            try:
                                self._selected_repo.delete_by_user(user_id)
                                stats["deleted"] += 1
                            except Exception:
                                pass

                # Cleanup: if > 6 hours, delete without sending
                elif elapsed_minutes > 360:
                    self._selected_repo.delete_by_user(user_id)
                    stats["deleted"] += 1

        except Exception as e:
            stats["errors"].append(f"general:{e}")
            logger.error(f"Error en process_pending_reminders: {e}")

        return stats

    # ------------------------------------------------------------------
    # Mensajes de suscripción vencida
    # ------------------------------------------------------------------

    def send_expired_subscription_message(
        self,
        user_telegram_id: int,
        end_date: datetime,
    ) -> bool:
        """
        Envía un mensaje al usuario informando que su suscripción ha vencido.

        Se utiliza en el proceso de limpieza de suscripciones
        (getMembersTelethon) antes de expulsar al usuario del grupo VIP.

        Args:
            user_telegram_id: ID de Telegram del usuario.
            end_date: Fecha en la que venció la suscripción.

        Returns:
            True si el mensaje se envió correctamente, False si hubo error.
        """
        try:
            from services.telegram_api import TelegramAPIService

            # Formatear la fecha en español
            from utils.datetime_utils import format_date_spanish

            fecha_formateada = format_date_spanish(end_date)

            mensaje = MENSAJE_SUSCRIPCION_VENCIDA_TEMPLATE.format(
                fecha=fecha_formateada
            )

            api = TelegramAPIService()
            result = api.send_message(
                chat_id=user_telegram_id,
                text=mensaje,
                parse_mode="Markdown",
            )

            logger.info(
                f"Mensaje de suscripción vencida enviado a user={user_telegram_id}"
            )
            return result.get("ok", False)

        except Exception as e:
            logger.error(
                f"Error al enviar mensaje de suscripción vencida "
                f"a user={user_telegram_id}: {e}",
                exc_info=True,
            )
            return False

    # ------------------------------------------------------------------
    # Notificaciones de expiración próxima
    # ------------------------------------------------------------------

    def send_expiring_soon_notifications(self, days: int = 3) -> int:
        """
        Envía notificaciones a usuarios cuyas suscripciones están
        próximas a vencer.

        Args:
            days: Días de anticipación para la notificación (default: 3).

        Returns:
            Número de notificaciones enviadas.
        """
        expiring_subs = self._subscription_repo.get_expiring_soon(days)
        sent_count = 0

        for sub in expiring_subs:
            try:
                from services.telegram_api import TelegramAPIService
                from utils.datetime_utils import format_date_spanish

                fecha_formateada = format_date_spanish(sub.end_date)

                mensaje = (
                    f"⚠️ *Tu suscripción está por vencer*\n\n"
                    f"Tu acceso al Grupo VIP vence el *{fecha_formateada}*.\n\n"
                    f"Renueva ahora para no perder el acceso a los pronósticos "
                    f"exclusivos de Magic 🔮\n\n"
                    f"Envía un mensaje a @magic_peru para renovar."
                )

                api = TelegramAPIService()
                api.send_message(
                    chat_id=sub.user_telegram_id,
                    text=mensaje,
                    parse_mode="Markdown",
                )
                sent_count += 1

                logger.info(
                    f"Notificación de expiración enviada a user={sub.user_telegram_id}"
                )

            except Exception as e:
                logger.error(
                    f"Error al enviar notificación de expiración "
                    f"a user={sub.user_telegram_id}: {e}"
                )

        logger.info(
            f"Notificaciones de expiración: {sent_count} enviadas "
            f"(de {len(expiring_subs)} suscripciones próximas a vencer)"
        )
        return sent_count

    # ------------------------------------------------------------------
    # Limpieza de selecciones expiradas
    # ------------------------------------------------------------------

    def cleanup_expired_selections(self, max_minutes: int = 1440) -> int:
        """
        Elimina todas las selecciones de servicio que han expirado
        por inactividad prolongada.

        Args:
            max_minutes: Tiempo máximo en minutos antes de considerar
                         una selección como expirada (default: 1440 = 24h).

        Returns:
            Número de selecciones eliminadas.
        """
        deleted_count = 0
        all_selections = self._selected_repo.get_all()

        for selected in all_selections:
            if selected.is_expired(max_minutes):
                self._selected_repo.delete_by_user(selected.user_telegram_id)
                deleted_count += 1
                logger.debug(
                    f"Selección expirada eliminada: user={selected.user_telegram_id}"
                )

        logger.info(f"Limpieza de selecciones: {deleted_count} eliminadas.")
        return deleted_count
