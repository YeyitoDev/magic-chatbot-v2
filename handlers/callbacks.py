"""
Callback Handlers - Magic Chatbot v2
======================================
Handlers para los callbacks de botones inline de Telegram.

Procesa todas las interacciones del usuario con los teclados inline:
- Selección de servicio (Stake, Grupo VIP).
- Validación de pagos (validar, rechazar, monto incorrecto).
- Navegación del calendario.
- Preguntas frecuentes.
- Confirmación de compra.
- Navegación de menú (regresar, etc.).

Principios:
- Thin Handlers: solo orquestan; la lógica de negocio está en los servicios.
- Dependency Injection: reciben servicios por constructor.
- Single Responsibility: cada método maneja un tipo de callback.

Uso:
    from handlers.callbacks import CallbackHandlers

    cb = CallbackHandlers(user_service, subscription_service, payment_service)
    app.add_handler(CallbackQueryHandler(cb.handle_button))
"""

import logging
import os
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from services.media_service import media_service

logger = logging.getLogger(__name__)

# Motivos de /delete (marcar una compra como inválida)
REASON_LABELS = {
    "duplicada": "Venta duplicada",
    "estafa": "Estafa",
    "otros": "Otros motivos",
}
REASON_NOTES = {
    "duplicada": "Compra marcada como venta duplicada por validador",
    "estafa": "Compra marcada como estafa por validador",
    "otros": "Compra marcada como inválida (otros motivos) por validador",
}
SERVICES_NAMES_BY_ID = {1: "Stake", 2: "Grupo VIP"}


class CallbackHandlers:
    """
    Handlers para todos los callbacks de botones inline del bot.

    Centraliza la lógica de routing de callbacks y la delegación
    a los servicios de dominio correspondientes.

    Attributes:
        user_service: Servicio de gestión de usuarios.
        subscription_service: Servicio de suscripciones/compras.
        payment_service: Servicio de validación de pagos.
        vision_service: Servicio de Google Cloud Vision.
        sheets_service: Servicio de Google Sheets.
        promotion_service: Servicio de promociones.
        settings: Configuración centralizada.
    """

    def __init__(
        self,
        user_service,
        subscription_service,
        payment_service,
        vision_service=None,
        sheets_service=None,
        promotion_service=None,
        settings=None,
    ):
        """
        Inicializa los handlers de callback con los servicios necesarios.

        Args:
            user_service: UserService.
            subscription_service: SubscriptionService.
            payment_service: PaymentService.
            vision_service: GoogleVisionService (opcional).
            sheets_service: GoogleSheetsService (opcional).
            promotion_service: PromotionService (opcional).
            settings: Configuración centralizada (opcional).
        """
        self.user_service = user_service
        self.subscription_service = subscription_service
        self.payment_service = payment_service
        self.vision_service = vision_service
        self.sheets_service = sheets_service
        self.promotion_service = promotion_service

        if settings is None:
            from config.settings import settings as s

            self.settings = s
        else:
            self.settings = settings

    async def _safe_edit_message(self, query, text: str, reply_markup=None):
        """Edits a message safely, handling both text and photo messages."""
        logger.info(f"[_safe_edit_message] Editing message. Has reply_markup: {reply_markup is not None}")
        try:
            if query.message.photo:
                await query.edit_message_caption(
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                )
                logger.info("[_safe_edit_message] Caption edited successfully")
            else:
                await query.edit_message_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                )
                logger.info("[_safe_edit_message] Text edited successfully")
        except Exception as e:
            error_msg = str(e)
            if (
                "not modified" in error_msg.lower()
                or "message is not modified" in error_msg.lower()
            ):
                logger.debug(f"Mensaje no modificado (ignorado): {e}")
                return  # Not an error, content is the same
            logger.warning(f"No se pudo editar mensaje: {e}")

    # ------------------------------------------------------------------
    # Router principal de callbacks
    # ------------------------------------------------------------------

    async def handle_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Router principal de callbacks. Despacha según el prefijo del callback_data.

        Formato de callback_data: "context_button:action:param1:param2:..."

        Args:
            update: Update de Telegram.
            context: Contexto de la aplicación.
        """
        query = update.callback_query
        # answer() puede fallar con "Query is too old" si el callback quedó en
        # cola (bot lento/reiniciando) y se procesa pasados los ~15s que da
        # Telegram. No es un error real: solo significa que el clic expiró.
        # Lo capturamos para no escalar al error handler global (que enviaría
        # al usuario un mensaje genérico de error por un simple botón viejo).
        try:
            await query.answer()
        except Exception as e:
            logger.warning(f"No se pudo responder el callback (probablemente expirado): {e}")

        data = query.data.split(":")
        if not data:
            logger.warning("Callback sin datos recibido.")
            return

        context_button = data[0]
        user_id = int(query.from_user.id)
        nombre_usuario = query.from_user.first_name or "Usuario"

        logger.info(f"[handle_button] Callback recibido: button={context_button}, user={user_id}, data={data}")

        # Registrar interacción del usuario
        await self._register_user_interaction(user_id, nombre_usuario)

        try:
            # --- Menú principal / Información de servicio ---
            if context_button == "informacion_servicio":
                await self._handle_service_info(update, context, data)

            elif context_button == "consulta_tipo_servicio":
                await self._handle_service_selection(update, context, data)

            elif context_button == "preguntas_frecuentes":
                await self._handle_faq(update, context, data)

            elif context_button == "regresar_menu_principal":
                await self._handle_back_to_menu(update, context, data)

            # --- Compra de servicio ---
            elif context_button == "comprar_servicio":
                await self._handle_buy_service(update, context, data)

            # --- Validación de pago ---
            elif context_button == "validar_monto":
                await self._handle_payment_validation(update, context, data)

            elif context_button == "buttom_validar_monto":
                await self._handle_manual_service_confirm(update, context, data)

            # --- Calendario ---
            elif context_button.startswith("cal_"):
                await self._handle_calendar_callback(update, context, data)

            # --- Eliminación por estafa (/delete) ---
            elif context_button == "delete_confirm":
                await self._handle_delete_confirm(update, context, data)

            elif context_button == "delete_cancel":
                await self._handle_delete_cancel(update, context, data)

            # --- Ignorar ---
            elif context_button == "cal_ignore":
                pass  # Callback ignorado intencionalmente

            else:
                logger.warning(f"Callback no reconocido: {context_button}")
                await query.edit_message_text(
                    text="Opción no reconocida. Usa /start para volver al menú."
                )

        except Exception as e:
            error_msg = str(e)
            if (
                "not modified" in error_msg.lower()
                or "message is not modified" in error_msg.lower()
            ):
                logger.debug(f"Mensaje no modificado: {e}")
                return  # Ignore, content didn't change
            logger.error(f"Error en callback '{context_button}': {e}", exc_info=True)
            await self._safe_edit_message(
                query,
                text="Ocurrió un error procesando tu solicitud. "
                "Intenta de nuevo o contacta a @magic_peru.",
            )

    # ------------------------------------------------------------------
    # Información de servicio
    # ------------------------------------------------------------------

    async def _handle_service_info(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: list
    ) -> None:
        """Muestra información detallada de un servicio."""
        query = update.callback_query
        action = data[1] if len(data) > 1 else "general"
        user_id = query.from_user.id

        if action == "stake" or action == "Stake":
            mensaje = (
                "El stake de máxima seguridad consta de una apuesta con una "
                "probabilidad de acierto mayor al 96% en el partido indicado. "
                "Nosotros estamos entrando con S/. 20,000 a esta jugada. "
                "GARANTIZADA DE VICTORIA."
            )
            await media_service.send_photo(context, user_id, "stake_maximo", caption=mensaje)

        elif action == "grupo_vip" or action == "Grupo VIP":
            mensaje = (
                "En el grupo VIP recibirás diariamente entre 3 a 4 pronósticos "
                "estadísticos con la probabilidad más alta de ganar. En este grupo "
                "solo realizamos apuestas 100% estadísticas seleccionadas por "
                "nuestros analistas donde también tendrás asesoría directa por "
                "ellos para colocar las jugadas."
            )
            await media_service.send_photo(context, user_id, "grupo_vip_1")
            await media_service.send_photo(context, user_id, "grupo_vip_2", caption=mensaje)

        elif action == "general":
            from utils.keyboards import service_info_keyboard

            await query.edit_message_text(
                text=(
                    "<b>📋 Nuestros Servicios</b>\n\n"
                    "<b>🎯 Grupo VIP:</b> Pronósticos diarios premium con asesoría directa.\n"
                    "<b>🎲 Stake:</b> Apuesta de máxima seguridad con &gt;96% de acierto.\n\n"
                    "Selecciona uno para más información:"
                ),
                parse_mode="HTML",
                reply_markup=service_info_keyboard("general"),
            )

    # ------------------------------------------------------------------
    # Selección de servicio
    # ------------------------------------------------------------------

    async def _handle_service_selection(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: list
    ) -> None:
        """Procesa la selección de un tipo de servicio por el usuario."""
        query = update.callback_query
        user_id = query.from_user.id
        tipo_servicio = data[1] if len(data) > 1 else None

        if tipo_servicio == "preguntas_frecuentes":
            await self._handle_faq(update, context, data)
            return

        # Send service images FIRST (like original code)
        if tipo_servicio in ("Stake", "stake"):
            await media_service.send_photo(
                context,
                user_id,
                "stake_maximo",
                caption="El stake de máxima seguridad consta de una apuesta con una probabilidad de acierto mayor al 96% en el partido indicado. Nosotros estamos entrando con S/. 20,000 a esta jugada. GARANTIZADA DE VICTORIA.",
            )
        elif tipo_servicio in ("Grupo VIP", "grupo_vip"):
            await media_service.send_photo(context, user_id, "grupo_vip_1")
            await media_service.send_photo(
                context,
                user_id,
                "grupo_vip_2",
                caption="En el grupo VIP recibirás diariamente entre 3 a 4 pronósticos estadísticos con la probabilidad más alta de ganar. En este grupo solo realizamos apuestas 100% estadísticas seleccionadas por nuestros analistas donde también tendrás asesoría directa por ellos para colocar las jugadas.",
            )

        # Then show pricing message with dynamic prices
        await self._send_service_pricing(
            update=update,
            context=context,
            user_id=user_id,
            tipo_servicio=tipo_servicio,
        )

        # Guardar la selección del usuario
        service_name = "Grupo VIP" if tipo_servicio in ("Grupo VIP", "grupo_vip") else tipo_servicio
        from core.database import SessionLocal
        from repositories.selected_service_repo import SelectedServiceRepository

        session = SessionLocal()
        try:
            repo = SelectedServiceRepository(session)
            service = self.subscription_service._service_repo.get_by_name(service_name)
            if service:
                repo.upsert(user_telegram_id=user_id, service_id=service.service_id)
                logger.info(f"Usuario {user_id} seleccionó servicio: {service_name}")
        finally:
            session.close()

    async def _send_service_pricing(self, update, context, user_id, tipo_servicio):
        """Envía info de precios usando precios dinámicos desde BD y file_id."""
        # Obtener PricingService del contenedor
        from core.container import container as app_container

        pricing = app_container.resolve("pricing_service")

        # Determinar service_id
        if tipo_servicio in ("Stake", "stake"):
            service_id = 1
            photo_key = "stake_pricing"
        else:
            service_id = 2
            photo_key = "vip_pricing"

        # Generar mensaje dinámico desde BD
        mensaje = pricing.generate_pricing_message(service_id)

        await media_service.send_photo(
            context,
            user_id,
            photo_key,
            caption=mensaje,
            parse_mode="HTML",
        )

        # Follow-up message (igual que en mensaje_inicial_don_gato original)
        await context.bot.send_message(
            chat_id=user_id,
            text="<strong>OJO SI HAS REALIZADO TU PAGO SIMPLEMENTE ENVÍAMELO ACÁ</strong> 📲",
            parse_mode="HTML",
        )

    # ------------------------------------------------------------------
    # FAQ
    # ------------------------------------------------------------------

    async def _handle_faq(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: list
    ) -> None:
        """Muestra preguntas frecuentes y respuestas."""
        query = update.callback_query
        action = data[1] if len(data) > 1 else "general"

        faq_respuestas = {
            "grupo_vip": {
                "caption": (
                    "<b>¿Qué es el Grupo VIP?</b> 🔥\n\n"
                    "👉 Acá te lo explico.\n\n"
                    "<b>Aprieta el botón y adquiere tu suscripción VIP</b>"
                ),
                "video": "./videos_promocionales/GRUPO_VIP_EXPLICACION.mp4",
                "service": "Grupo VIP",
            },
            "stake": {
                "caption": (
                    "<b>¿Qué es el Stake Máximo?</b> 🔥\n\n"
                    "👉 Acá te lo explico.\n\n"
                    "<b>Aprieta el botón y adquiere tu stake</b>"
                ),
                "video": "./videos_promocionales/STAKE_MAXIMA_SEGURIDAD_EXPLICACION.mp4",
                "service": "Stake",
            },
        }
        if action in faq_respuestas:
            info = faq_respuestas[action]
            if os.path.exists(info["video"]):
                from utils.keyboards import faq_video_keyboard

                # Enviar mensaje inmediato antes del video
                await context.bot.send_message(
                    chat_id=query.from_user.id,
                    text="⏳ Enviando información del servicio seleccionado...",
                )

                await context.bot.send_video(
                    chat_id=query.from_user.id,
                    video=open(info["video"], "rb"),
                    caption=info["caption"],
                    parse_mode="HTML",
                    reply_markup=faq_video_keyboard(info["service"]),
                )
        else:
            from utils.keyboards import faq_keyboard

            await query.edit_message_text(
                text="Selecciona el servicio que deseas consultar",
                parse_mode="HTML",
                reply_markup=faq_keyboard(),
            )

    # ------------------------------------------------------------------
    # Volver al menú principal
    # ------------------------------------------------------------------

    async def _handle_back_to_menu(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: list
    ) -> None:
        """Retorna al usuario al menú principal."""
        from utils.keyboards import main_menu_don_gato_keyboard

        query = update.callback_query
        await query.edit_message_text(
            text=(
                "¡Hola, mi gato! 🔥\n\n"
                "Soy <b>Don Gato</b>, el Bot Asistente Virtual de <b>Magic Apuestas</b> 🐱.\n\n"
                "¿Deseas más información sobre nuestros servicios?\n\n"
                "¡Haz clic en la opción que prefieras! 👇"
            ),
            parse_mode="HTML",
            reply_markup=main_menu_don_gato_keyboard(),
        )

    # ------------------------------------------------------------------
    # Compra de servicio
    # ------------------------------------------------------------------

    async def _handle_buy_service(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: list
    ) -> None:
        """Procesa la confirmación de compra y redirige al envío de captura."""
        query = update.callback_query
        user_id = query.from_user.id
        nombre_usuario = query.from_user.first_name or "Usuario"
        respuesta_compra = data[1] if len(data) > 1 else "no"
        tipo_servicio = data[2] if len(data) > 2 else ""

        # Recuperar file_id de la imagen pendiente (guardado en handle_image)
        pending_file_id = context.user_data.pop("pending_file_id", None)

        if respuesta_compra == "si":
            if pending_file_id:
                # Ya envió captura: reenviar al validador usando file_id
                await self._process_existing_image(
                    update, context, user_id, nombre_usuario, tipo_servicio, pending_file_id
                )
            else:
                # No ha enviado captura: mostrar precios
                await self._send_service_pricing(update, context, user_id, tipo_servicio)

                # Guardar selección (like production)
                from core.database import SessionLocal
                from repositories.selected_service_repo import SelectedServiceRepository

                session = SessionLocal()
                try:
                    repo = SelectedServiceRepository(session)
                    service_name = (
                        "Grupo VIP"
                        if tipo_servicio in ("Grupo VIP", "grupo_vip")
                        else tipo_servicio
                    )
                    service = self.subscription_service._service_repo.get_by_name(service_name)
                    if service:
                        repo.upsert(user_telegram_id=user_id, service_id=service.service_id)
                finally:
                    session.close()

        elif respuesta_compra == "no":
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "Seguro la próxima te animas mi gato, te recomiendo seguir jugando "
                    "las apuestas gratis que enviamos por el grupo y te regalo un bono "
                    "de S/ 40 en la mejor casa de apuestas del mundo"
                ),
            )
            await media_service.send_photo(context, user_id, "betsafe_logo")
            from utils.keyboards import main_menu_keyboard

            await context.bot.send_message(
                chat_id=user_id,
                text=self.settings.BETSAFE_PROMO_LINK,
                reply_markup=main_menu_keyboard(),
            )

    async def _process_existing_image(
        self, update, context, user_id, nombre_usuario, tipo_servicio, file_id
    ):
        """Procesa una imagen de comprobante ya existente usando file_id."""

        await context.bot.send_message(
            chat_id=user_id,
            text="<strong>Recibí tu voucher de pago, en un minuto procederé a validar tu pago ✅</strong>",
            parse_mode="HTML",
        )

        # Extraer texto de la imagen desde file_id (sin archivo local)
        texto_extraido = ""
        if self.vision_service:
            try:
                photo_file = await context.bot.get_file(file_id)
                image_bytes = await photo_file.download_as_bytearray()
                texto_extraido = self.vision_service.detect_text_from_bytes(bytes(image_bytes))
            except Exception as e:
                logger.warning(f"No se pudo hacer OCR desde file_id: {e}")

        # Extraer monto y fecha
        from utils.text_parser import extract_amount, extract_date

        monto = extract_amount(texto_extraido)
        if monto is None:
            logger.warning(f"No se pudo extraer monto del comprobante de user={user_id}. Enviando al validador para validación manual.")
            monto = 0.0  # Valor 0 indica que el validador debe ingresar el monto manualmente
        fecha = extract_date(texto_extraido)

        # Construir mensaje para el validador
        mensaje = self.payment_service.build_validation_message(
            telegram_id=user_id,
            telegram_name=nombre_usuario,
            amount=monto,
            extracted_date=fecha,
        )

        # No se verifica duplicados: tanto Stake como VIP permiten múltiples compras
        # VIP renueva/extiende la suscripción con cada compra

        # Enviar al validador
        from utils.keyboards import payment_validation_keyboard

        reply_markup = payment_validation_keyboard(
            user_id=user_id, amount=monto, source="telegram", extra_data=fecha
        )

        for validator_id in self.payment_service.get_validator_ids():
            try:
                await context.bot.send_photo(
                    chat_id=int(validator_id),
                    photo=file_id,
                    caption=mensaje,
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                )
                logger.info(f"Imagen enviada al validador {validator_id}")
            except Exception as e:
                logger.error(f"Error al enviar al validador {validator_id}: {e}")

        await context.bot.send_message(
            chat_id=user_id,
            text="Para cualquier duda, consulta o problema contáctate con @magic_peru 📲",
        )

    # ------------------------------------------------------------------
    # Validación de pago
    # ------------------------------------------------------------------

    async def _handle_payment_validation(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: list
    ) -> None:
        """
        Procesa la acción de validación del validador (validar, rechazar,
        monto incorrecto).
        """
        query = update.callback_query
        await query.answer()  # Responder al callback para evitar "Loading..."
        validator_id = query.from_user.id
        # query.message puede ser None si el botón pertenece a un mensaje
        # muy antiguo (>48h) o inaccesible. Evita 'NoneType' has no attribute.
        message_id = query.message.message_id if query.message else None

        # Parsear datos del callback
        action = data[1] if len(data) > 1 else ""
        target_user_id = int(data[2]) if len(data) > 2 else 0
        monto = float(data[3]) if len(data) > 3 else 0.0

        # El 5to segmento (data[4]) puede ser el marcador de canal "wsp"
        # o la fecha extraída (ddmmyyyy). Distinguir ambos casos para no
        # perder la detección del canal WhatsApp.
        raw_extra = data[4] if len(data) > 4 else ""
        if raw_extra == "wsp":
            source = "wsp"
            extra = ""
        else:
            extra = raw_extra
            source = data[5] if len(data) > 5 else "telegram"

        logger.info(
            f"[_handle_payment_validation] action={action}, user={target_user_id}, "
            f"monto={monto}, extra={extra}, source={source}, message_id={message_id}"
        )

        # Obtener file_id del mensaje de foto (sin archivo local)

        # Prevenir auto-validación del propio pago (excepto en testing)
        if validator_id == target_user_id:
            from config.settings import settings
            if settings.ENVIRONMENT != "testing":
                await query.answer("No puedes validar tu propio pago.", show_alert=True)
                logger.warning(f"Auto-validación bloqueada: validator={validator_id} intentó validar su propio pago")
                return
            else:
                logger.info(f"TEST: Permitida auto-validación para validator={validator_id}")

        logger.info(
            f"Validación: action={action}, validator={validator_id}, "
            f"target={target_user_id}, monto={monto}, source={source}"
        )

        # No se verifica duplicados: tanto Stake como VIP permiten múltiples compras
        # VIP renueva/extiende la suscripción con cada compra

        if action == "valid":
            await self._process_valid_payment(
                update, context, query, target_user_id, monto, source, extra
            )
        elif action == "not_valid":
            await self._process_rejected_payment(
                update, context, query, target_user_id, monto, message_id
            )
        elif action == "monto_no_reconocido":
            await self._process_incorrect_amount(
                update, context, query, target_user_id, monto, source, message_id
            )

    async def _process_valid_payment(self, update, context, query, user_id, monto, source, extra):
        """Procesa un pago validado exitosamente."""
        message_id = query.message.message_id if query.message else None

        # Registrar la compra. validate_payment verifica que el monto
        # corresponda a un precio definido; payment_ref impide registrar dos
        # veces el mismo comprobante (doble click o varios validadores).
        from services.payment_service import voucher_payment_ref

        result = self.payment_service.validate_payment(
            telegram_id=user_id,
            amount=monto,
            from_channel=source,
            purchase_date=extra if extra and extra != "wsp" else None,
            payment_ref=voucher_payment_ref(query.message),
        )

        if result.is_duplicate:
            await self._safe_edit_message(
                query,
                text="⚠️ Este comprobante ya fue validado anteriormente. No se registró de nuevo.",
            )
            return

        if not result.success:
            # Si el fallo es porque el monto no corresponde a un precio
            # definido, insistir al validador para que ingrese el correcto
            # (no se registra la venta).
            invalid_amount_errors = {
                "undefined_price",
                "invalid_amount",
                "invalid_vip_amount",
            }
            if any(e in invalid_amount_errors for e in (result.errors or [])):
                logger.info(
                    f"Monto S/ {monto:.2f} no corresponde a un precio definido; "
                    f"se solicita corrección al validador {query.from_user.id}."
                )
                await self._process_incorrect_amount(
                    update, context, query, user_id, monto, source, message_id
                )
                return

            await self._safe_edit_message(query, text="❌ No se pudo registrar la venta.")
            await context.bot.send_message(
                chat_id=query.from_user.id,
                text=f"❌ Error al registrar compra: {result.message}",
            )
            return

        # Determinar tipo de servicio
        tipo_servicio = (
            result.service_type if result.service_type else ("grupo_vip" if monto > 50 else "stake")
        )
        service_display = "Grupo VIP" if tipo_servicio in ("grupo_vip", "Grupo VIP") else "Stake"

        # Registro exitoso: ahora sí marcar la venta como validada.
        success_text = (
            f"✅ <b>PAGO VALIDADO CON ÉXITO</b>\n\n"
            f"👤 Usuario: <code>{user_id}</code>\n"
            f"💵 Monto: S/ {monto:.2f}\n"
            f"📦 Servicio: {service_display}\n\n"
            f"<i>El usuario ha sido notificado y recibirá su acceso.</i>"
        )
        await self._safe_edit_message(query, text=success_text)

        # Actualizar WSP si corresponde
        if source == "wsp" and self.sheets_service:
            self.sheets_service.update_wsp_payment_review_status(telegram_id=user_id)

        # Obtener link de invitación
        invite_link = await self._get_invite_link(context, tipo_servicio)

        # 1) Confirmación de pago al comprador
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                f"✅ <b>¡PAGO CONFIRMADO!</b>\n\n"
                f"💵 <b>Monto:</b> S/ {monto:.2f}\n"
                f"📦 <b>Servicio:</b> {service_display}\n\n"
                f"<i>Gracias por tu compra. A continuación recibirás "
                f"tu acceso al grupo y información importante.</i>"
            ),
            parse_mode="HTML",
        )

        # 2) Betsafe registration
        await media_service.send_photo(
            context,
            user_id,
            "betsafe_logo",
            caption=(
                "<b>🔗 LINK EXCLUSIVO BETSAFE</b>\n\n"
                "Todas nuestras apuestas estadísticas son realizadas en Betsafe, "
                "la casa que nos da las mejores opciones en todas las ligas.\n\n"
                "<b>Regístrate aquí para evitar bloqueos en tu cuenta:</b>\n"
                f"👉 {self.settings.BETSAFE_PROMO_LINK}"
            ),
            parse_mode="HTML",
        )
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "<b>🎁 BONO DE BIENVENIDA</b>\n\n"
                "Regístrate con el link exclusivo, haz tu primer depósito "
                "de mínimo S/ 40 y recibe <b>70 soles gratis</b>.\n\n"
                f"<a href='{self.settings.BETSAFE_PROMO_LINK}'>"
                "� OBTENER MIS 70 SOLES GRATIS</a>"
            ),
            parse_mode="HTML",
        )

        # 3) Invite link
        if invite_link:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"🚀 <b>TU ACCESO A {service_display.upper()}</b>\n\n"
                    f"<a href='{invite_link}'>👉 UNIRME AL GRUPO AHORA</a>\n\n"
                    f"<b>⚠️ Importante:</b>\n"
                    f"• El link es de <b>un solo uso</b>\n"
                    f"• Expira en <b>24 horas</b>\n"
                    f"• No lo compartas con nadie"
                ),
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

            # 4) Instrucciones post-link
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "<b>📌 INSTRUCCIONES PARA INGRESAR</b>\n\n"
                    "1️⃣ Toca el link de arriba\n"
                    "2️⃣ Presiona <b>«Unirse al grupo»</b>\n"
                    "3️⃣ Lee las reglas del grupo\n"
                    "4️⃣ ¡Listo, empieza a ganar! 🏆\n\n"
                    "<i>Si el link no funciona o expiró, contacta a "
                    "@magic_peru2 para que te envíe uno nuevo.</i>"
                ),
                parse_mode="HTML",
            )
        else:
            # No se pudo obtener el link: derivar al usuario a soporte.
            logger.warning(
                f"No se pudo obtener link de {service_display} para user={user_id}. "
                f"Se deriva a soporte."
            )
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"⚠️ <b>No pudimos generar tu link de acceso a {service_display} "
                    f"automáticamente.</b>\n\n"
                    f"Por favor, solicita tu link de acceso a soporte: @magic_peru2"
                ),
                parse_mode="HTML",
            )

        # Confirmar al validador
        user = self.user_service.get_user(user_id)
        user_name = user.telegram_name if user else str(user_id)

        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=(
                f"✅ <b>PAGO REGISTRADO CORRECTAMENTE</b>\n\n"
                f"👤 <b>Usuario:</b> {user_name}\n"
                f"🆔 <b>ID:</b> <code>{user_id}</code>\n"
                f"💵 <b>Monto:</b> S/ {monto:.2f}\n"
                f"📦 <b>Servicio:</b> {tipo_servicio.title()}\n\n"
                f"<i>El usuario recibirá su acceso automáticamente.</i>"
            ),
            parse_mode="HTML",
        )

        # Limpiar
        from core.database import SessionLocal
        from repositories.selected_service_repo import SelectedServiceRepository

        session = SessionLocal()
        try:
            repo = SelectedServiceRepository(session)
            repo.delete_by_user(user_id)
        finally:
            session.close()

        # Sin archivo local que eliminar: las imágenes fluyen por file_id de Telegram

    async def _process_rejected_payment(self, update, context, query, user_id, monto, message_id):
        """Procesa un pago rechazado."""
        logger.info(
            f"[_process_rejected_payment] Iniciando rechazo: user_id={user_id}, "
            f"monto={monto}, message_id={message_id}"
        )
        user = self.user_service.get_user(user_id)
        user_name = user.telegram_name if user else str(user_id)

        await self._safe_edit_message(query, text="❌ Pago no validado.")

        await context.bot.send_message(
            chat_id=query.from_user.id,
            text=(f"❌ No se validó el pago de {user_name} ({user_id}) con monto S/ {monto:.2f}"),
            reply_to_message_id=message_id,
        )
        logger.info("[_process_rejected_payment] Mensaje de rechazo enviado a validador")

        # Mensaje al comprador
        await context.bot.send_message(
            chat_id=user_id,
            text=self.payment_service.build_rejection_message(user_id),
            parse_mode="HTML",
        )
        logger.info("[_process_rejected_payment] Mensaje de rechazo enviado a comprador")

        # Sin archivo local que eliminar: las imágenes fluyen por file_id de Telegram

    async def _process_incorrect_amount(
        self, update, context, query, user_id, monto, source, message_id
    ):
        """Procesa cuando el monto no es reconocido."""
        user = self.user_service.get_user(user_id)
        user_name = user.telegram_name if user else str(user_id)
        validator_id = query.from_user.id

        if source == "telegram":

            # Get PricingService from container for dynamic keyboard
            container = getattr(context, "container", None)
            if container is None:
                from core.container import container
            pricing = (
                container.resolve("pricing_service")
                if container.is_registered("pricing_service")
                else None
            )

            logger.info(f"[_process_incorrect_amount] pricing available: {pricing is not None}")

            mensaje = (
                f"🔍 <b>CONFIRMACIÓN DE PAGO</b>\n\n"
                f'👤 <a href="tg://user?id={user_id}">{user_name}</a>\n'
                f"💵 <b>Monto detectado:</b> S/ {monto:.2f}\n\n"
                f"<b>✏️ Ingresa el monto manualmente con el comando. "
                f"Reemplaza <code>{int(monto)}</code> por el monto real transferido:</b>\n"
                f"<code>/vm {user_id} &lt;MONTO_TRANSFERIDO&gt;</code>\n\n"
                f"<i>Ejemplo: /vm {user_id} 125</i>\n\n"
                f"<i>O seleccione el servicio directamente:</i>"
            )

            # Use dynamic pricing keyboard if available
            if pricing:
                reply_markup = pricing.generate_confirmation_keyboard(user_id=user_id, amount=monto)
                logger.info(f"[_process_incorrect_amount] Dynamic keyboard generated: {reply_markup is not None}")
            else:
                from utils.keyboards import service_confirmation_keyboard

                reply_markup = service_confirmation_keyboard(
                    user_id=user_id, monto=monto, message_id=message_id, source=source
                )
                logger.info(f"[_process_incorrect_amount] Fallback keyboard generated: {reply_markup is not None}")

            # Editar el caption del mensaje de foto existente (sin reenviar desde disco)
            await self._safe_edit_message(query, mensaje, reply_markup)
            return

        elif source == "wsp":
            await context.bot.send_message(
                chat_id=validator_id,
                text=(
                    f"Ingrese el monto correcto para el usuario {user_name}.\n"
                    f"El monto detectado fue S/ {monto:.2f}.\n\n"
                    f"Responda con el formato:\n"
                    f"/vm {user_id} {message_id} wsp [monto_correcto]"
                ),
            )

        await self._safe_edit_message(query, text="Se ha solicitado la validación del monto.")

    # ------------------------------------------------------------------
    # Confirmación manual de servicio
    # ------------------------------------------------------------------

    async def _handle_manual_service_confirm(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: list
    ) -> None:
        """
        Procesa la confirmación manual del servicio cuando el validador
        selecciona directamente el tipo de servicio (Stake o plan VIP).

        Flujo de dos pasos:
        1. select: El validador selecciona un precio → se muestra confirmación.
        2. valid: El validador confirma → se procesa el pago.
        """
        query = update.callback_query
        await query.answer()
        action = data[1] if len(data) > 1 else ""
        target_user_id = int(data[2]) if len(data) > 2 else 0
        monto = float(data[3]) if len(data) > 3 else 0.0
        validator_id = query.from_user.id

        # Limpiar cualquier entrada manual de monto pendiente
        context.user_data.pop("pending_manual_amount", None)

        if action == "select":
            # Paso 1: Mostrar confirmación del precio seleccionado
            service_name = self._get_service_name_for_price(monto)

            confirm_text = (
                f"🔍 <b>PASO 2: CONFIRMA TU SELECCIÓN</b>\n\n"
                f"👤 <b>Usuario:</b> <code>{target_user_id}</code>\n"
                f"💵 <b>Monto seleccionado:</b> S/ {monto:.2f}\n"
                f"📦 <b>Servicio:</b> {service_name}\n\n"
                f"<i>Revisa que todo esté correcto antes de confirmar.</i>"
            )

            from telegram import InlineKeyboardButton, InlineKeyboardMarkup

            confirm_keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ CONFIRMAR PAGO",
                        callback_data=f"buttom_validar_monto:valid:{target_user_id}:{int(monto)}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔄 CAMBIAR MONTO",
                        callback_data=f"buttom_validar_monto:change:{target_user_id}:{int(monto)}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ CANCELAR VALIDACIÓN",
                        callback_data=f"buttom_validar_monto:cancel:{target_user_id}",
                    )
                ],
            ])

            await self._safe_edit_message(query, confirm_text, confirm_keyboard)
            return

        elif action == "valid":
            # Paso 2: Procesar como pago validado
            await self._process_valid_payment(
                update, context, query, target_user_id, monto, "telegram", ""
            )

        elif action == "change":
            # Volver a mostrar la lista de precios
            container = getattr(context, "container", None)
            if container is None:
                from core.container import container
            pricing = (
                container.resolve("pricing_service")
                if container.is_registered("pricing_service")
                else None
            )

            from utils.keyboards import service_confirmation_keyboard
            if pricing:
                reply_markup = pricing.generate_confirmation_keyboard(
                    user_id=target_user_id, amount=monto
                )
            else:
                reply_markup = service_confirmation_keyboard(
                    user_id=target_user_id, monto=monto, source="telegram"
                )

            change_text = (
                f"🔍 <b>PASO 1: SELECCIONA EL SERVICIO</b>\n\n"
                f"👤 <b>Usuario:</b> <code>{target_user_id}</code>\n"
                f"💵 <b>Monto detectado:</b> S/ {monto:.2f}\n\n"
                f"<i>Elige el servicio que corresponde a este pago:</i>"
            )
            await self._safe_edit_message(query, change_text, reply_markup)
            return

        elif action == "cancel":
            # Cancelar validación
            user = self.user_service.get_user(target_user_id)
            user_name = user.telegram_name if user else str(target_user_id)

            await self._safe_edit_message(
                query,
                text=(
                    f"❌ <b>VALIDACIÓN CANCELADA</b>\n\n"
                    f"👤 Usuario: <code>{target_user_id}</code>\n"
                    f"💵 Monto: S/ {monto:.2f}\n\n"
                    f"<i>El validador canceló esta validación.</i>"
                ),
            )

            await context.bot.send_message(
                chat_id=validator_id,
                text=(
                    f"❌ Validación cancelada\n"
                    f"Usuario: {user_name}\n"
                    f"Monto: S/ {monto:.2f}"
                ),
            )

            await context.bot.send_message(
                chat_id=target_user_id,
                text=self.payment_service.build_rejection_message(target_user_id),
                parse_mode="HTML",
            )

            # Sin archivo local que eliminar: las imágenes fluyen por file_id de Telegram

    # ------------------------------------------------------------------
    # Calendario
    # ------------------------------------------------------------------

    async def _handle_calendar_callback(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: list
    ) -> None:
        """Maneja los callbacks de navegación del calendario."""
        query = update.callback_query
        action = data[0]  # cal_prev, cal_next, cal_select, cal_today, cal_cancel

        from utils.keyboards import CalendarKeyboard

        cal = CalendarKeyboard()

        if action in ("cal_prev", "cal_next"):
            year = int(data[1])
            month = int(data[2])
            user_id = int(data[3]) if data[3] != "None" else None
            message_id = int(data[4]) if data[4] != "None" else None

            if action == "cal_next":
                year, month = cal.obtener_mes_siguiente(year, month)
            else:
                year, month = cal.obtener_mes_anterior(year, month)

            await query.edit_message_reply_markup(
                reply_markup=cal.crear_calendario(
                    year=year,
                    month=month,
                    user_id=user_id,
                    message_id=message_id,
                )
            )

        elif action == "cal_select":
            year = int(data[1])
            month = int(data[2])
            day = int(data[3])
            user_id = int(data[4]) if data[4] != "None" else None
            message_id = int(data[5]) if data[5] != "None" else None

            fecha_seleccionada = f"{day:02d}/{month:02d}/{year}"
            await query.edit_message_text(text=f"📅 Fecha seleccionada: {fecha_seleccionada}")

        elif action == "cal_today":
            from utils.datetime_utils import get_lima_time_formatted

            fecha = get_lima_time_formatted()["dd/mm/yyyy"]
            await query.edit_message_text(text=f"📅 Fecha de hoy: {fecha}")

        elif action == "cal_cancel":
            await query.edit_message_text(text="❌ Selección de fecha cancelada.")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _register_user_interaction(self, user_id: int, user_name: str) -> None:
        """Registra la interacción del usuario (get-or-create)."""
        try:
            self.user_service.get_or_create_user(user_id, user_name)
        except Exception as e:
            logger.error(f"Error al registrar interacción de {user_id}: {e}")

    def _get_service_name_for_price(self, price: float) -> str:
        """Obtiene el nombre del servicio a partir del precio (usando rangos)."""
        try:
            from core.container import container
            if container.is_registered("pricing_service"):
                pricing = container.resolve("pricing_service")
                plan = pricing.match_price(price)
                if plan and plan.service:
                    return plan.service.name
        except Exception:
            pass
        # Fallback por precio conocido
        if price == 50:
            return "Stake"
        if price in (125, 175, 225):
            return "Grupo VIP"
        return "Servicio desconocido"

    async def _get_invite_link(
        self, context: ContextTypes.DEFAULT_TYPE, tipo_servicio: str
    ) -> str | None:
        """
        Obtiene el link de invitación para un tipo de servicio.
        Usa python-telegram-bot para crear un link de un solo uso.
        """
        if tipo_servicio in ("grupo_vip", "Grupo VIP"):
            chat_id = self.settings.TELEGRAM_VIP_GROUP_ID

            # 1) Intentar con el bot productivo de links (admin en el grupo VIP)
            try:
                import asyncio

                from services.telegram_api import TelegramAPIService

                api = TelegramAPIService()
                invite_link = await asyncio.to_thread(
                    api.create_invite_link,
                    chat_id=int(chat_id),
                    member_limit=1,
                    name=f"Link para {tipo_servicio}",
                )
                if invite_link:
                    return invite_link.strip()
                logger.warning(
                    "Bot de links no devolvió invite link VIP; intentando con bot principal."
                )
            except Exception as e:
                logger.error(f"Error al crear invite link VIP con bot de links: {e}")

            # 2) Fallback: intentar con el bot principal (context.bot)
            try:
                invite = await context.bot.create_chat_invite_link(
                    chat_id=chat_id,
                    expire_date=datetime.now() + __import__("datetime").timedelta(hours=24),
                    member_limit=1,
                    name=f"Link para {tipo_servicio}",
                )
                return invite.invite_link.strip()
            except Exception as e:
                logger.error(f"Error al crear invite link VIP con bot principal: {e}")
                return None  # No fallback link - must be generated fresh
        else:
            # Stake: el valor almacenado en la hoja "stake" (Google Sheets) YA es
            # el link de invitación. Se obtiene y se devuelve directamente, igual
            # que en la lógica original (sheets.get_service_id("stake")).
            if self.sheets_service:
                try:
                    group_value = self.sheets_service.get_service_group_id("stake")
                    if group_value:
                        group_value = group_value.strip()
                        logger.info(f"Link Stake desde Sheets: {group_value}")
                        return group_value
                    logger.warning("No se encontró link de Stake en Google Sheets.")
                except Exception as e:
                    logger.error(f"Error al obtener link de Stake desde Sheets: {e}")
            return None

    # ------------------------------------------------------------------
    # Handlers de eliminación por estafa (/delete)
    # ------------------------------------------------------------------

    async def _handle_delete_confirm(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: list
    ) -> None:
        """
        Procesa la confirmación de eliminación por motivo.

        Callback data: delete_confirm:{target_user_id}:{purchase_id}:{reason}
        reason: duplicada | estafa | otros
        """
        query = update.callback_query
        business_user_id = int(query.from_user.id)

        if not self.payment_service.is_validator_authorized(business_user_id):
            await query.answer("No autorizado", show_alert=True)
            return

        try:
            target_user_id = int(data[1])
            purchase_id = int(data[2])
            reason = data[3] if len(data) > 3 else "otros"
        except (IndexError, ValueError):
            await self._safe_edit_message(query, "Datos de callback inválidos.")
            return

        reason_label = REASON_LABELS.get(reason, "Otros motivos")
        fraud_note = REASON_NOTES.get(reason, REASON_NOTES["otros"])

        from core.database import SessionLocal
        from models.purchase import Purchase
        from repositories.purchase_repo import PurchaseRepository
        from repositories.subscription_repo import SubscriptionRepository

        session = SessionLocal()
        try:
            purchase_repo = PurchaseRepository(session)
            sub_repo = SubscriptionRepository(session)

            success = purchase_repo.mark_as_fraud(purchase_id, fraud_note)
            if not success:
                await self._safe_edit_message(query, "Error: no se encontró la compra.")
                return

            purchase = session.query(Purchase).filter_by(purchase_id=purchase_id).first()
            if not purchase:
                await self._safe_edit_message(query, "Error: compra no encontrada tras marcar.")
                return

            service_name = SERVICES_NAMES_BY_ID.get(
                purchase.service_id, f"Servicio {purchase.service_id}"
            )

            logger.info(
                f"Compra {purchase_id} marcada como '{reason}' por validador {business_user_id}"
            )

            # Si es VIP, expulsar del grupo
            vip_kicked = False
            if purchase.service_id == 2:
                from config.settings import settings as app_settings
                from services.telegram_api import TelegramAPIService

                vip_group_id = int(app_settings.TELEGRAM_VIP_GROUP_ID)
                try:
                    api = TelegramAPIService()
                    result = api.remove_user_allow_rejoin(
                        chat_id=vip_group_id, user_id=target_user_id
                    )
                    vip_kicked = result.get("kick_success", False)
                    if vip_kicked:
                        logger.info(f"Usuario {target_user_id} expulsado del grupo VIP ({reason}).")
                    else:
                        logger.warning(
                            f"No se pudo expulsar a {target_user_id} del grupo VIP: {result}"
                        )
                except Exception as e:
                    logger.error(f"Error al expulsar del grupo VIP: {e}")

            # Desactivar suscripción si existe
            try:
                sub = sub_repo.get_sub_by_user_and_service(
                    user_telegram_id=target_user_id,
                    service_id=purchase.service_id,
                )
                if sub:
                    sub.is_active = False
                    sub_repo.commit()
                    logger.info(f"Suscripción {sub.subscription_id} desactivada ({reason}).")
            except Exception as e:
                logger.warning(f"No se pudo desactivar la suscripción: {e}")

            # Enviar mensaje al usuario
            try:
                if purchase.service_id == 2 and vip_kicked:
                    user_msg = (
                        "❌ <b>Has sido eliminado del Grupo VIP.</b>\n\n"
                        f"Motivo: {reason_label}.\n"
                        "Si crees que esto es un error, contáctate con @magic_peru"
                    )
                elif purchase.service_id == 2 and not vip_kicked:
                    user_msg = (
                        "⚠️ <b>Tu suscripción VIP ha sido desactivada.</b>\n\n"
                        f"Motivo: {reason_label}.\n"
                        "Si crees que esto es un error, contáctate con @magic_peru"
                    )
                else:
                    user_msg = (
                        "⚠️ <b>Tu compra ha sido marcada como inválida.</b>\n\n"
                        f"Motivo: {reason_label}.\n"
                        "Si crees que esto es un error, contáctate con @magic_peru"
                    )
                await context.bot.send_message(
                    chat_id=target_user_id,
                    text=user_msg,
                    parse_mode="HTML",
                )
            except Exception as e:
                logger.warning(f"No se pudo enviar mensaje al usuario {target_user_id}: {e}")

            # Editar el mensaje del validador con el resultado
            confirm_msg = (
                f"✅ <b>Compra marcada como inválida</b>\n\n"
                f"👤 Usuario: <code>{target_user_id}</code>\n"
                f"📦 Servicio: {service_name}\n"
                f"💵 Monto: S/ {purchase.price:.2f}\n"
                f"🆔 Compra ID: {purchase_id}\n"
                f"📝 Motivo: {reason_label}\n"
            )
            if purchase.service_id == 2:
                confirm_msg += (
                    f"🚪 VIP: {'Expulsado del grupo' if vip_kicked else 'No se pudo expulsar (ver logs)'}\n"
                )
            else:
                confirm_msg += "ℹ️ Stake: No se puede expulsar del grupo (solo marca)\n"

            await self._safe_edit_message(query, confirm_msg)

        except Exception as e:
            logger.error(f"Error en delete_confirm callback: {e}", exc_info=True)
            await self._safe_edit_message(query, f"❌ Error: {str(e)}")
        finally:
            session.close()

    async def _handle_delete_cancel(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: list
    ) -> None:
        """
        Procesa la cancelación de eliminación por estafa.

        Callback data: delete_cancel:{target_user_id}:{purchase_id}
        """
        query = update.callback_query
        await self._safe_edit_message(
            query,
            "🚫 <b>Operación cancelada.</b>\n\nLa compra no fue marcada como estafa.",
        )
