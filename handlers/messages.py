"""
Message Handlers - Magic Chatbot v2
=====================================
Handlers para mensajes de texto que no son comandos y para imágenes
(comprobantes de pago enviados por los usuarios).

Estos handlers actúan como thin controllers: reciben la interacción del
usuario, extraen la información relevante, y delegan la lógica de negocio
a los servicios correspondientes.

Flujos manejados:
- Texto genérico en chat privado → mostrar menú principal o registrar en DynamoDB.
- Imagen (comprobante de transferencia) → OCR → extraer monto → enviar a validador.
- Comando /vm (validar monto) → procesar validación con monto corregido.

Principios:
- Thin Controllers: No contienen lógica de negocio.
- Dependency Injection: Reciben servicios por constructor.
- Early return: Validaciones tempranas para evitar anidamiento profundo.

Uso:
    from handlers.messages import MessageHandlers

    msg_handler = MessageHandlers(
        user_service=user_svc,
        payment_service=payment_svc,
        vision_service=vision_svc,
        promotion_service=promo_svc,
        container=container,
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler.echo))
    app.add_handler(MessageHandler(filters.PHOTO, msg_handler.handle_image))
"""

import logging

from telegram import Chat, Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


class MessageHandlers:
    """
    Handlers para mensajes de texto e imágenes en el bot.

    Maneja:
    - Mensajes de texto genéricos (eco / registro).
    - Imágenes de comprobantes de pago (OCR + envío a validador).
    - Comando /vm inline para validación manual de montos.

    Dependencias:
        user_service: UserService para registro de usuarios.
        payment_service: PaymentService para validación de pagos.
        vision_service: GoogleVisionService para OCR de imágenes.
        gemini_vision_service: GeminiVisionService para extracción de precios con IA.
        promotion_service: PromotionService para registro en DynamoDB.
        container: Contenedor de dependencias para resolver otros servicios.
    """

    def __init__(
        self,
        user_service,
        payment_service,
        vision_service,
        gemini_vision_service=None,
        promotion_service=None,
        container=None,
    ) -> None:
        """
        Inicializa los handlers de mensajes con sus dependencias.

        Args:
            user_service: Servicio de gestión de usuarios.
            payment_service: Servicio de validación de pagos.
            vision_service: Servicio de Google Vision para OCR.
            gemini_vision_service: Servicio de Gemini Vision para extracción de precios (opcional).
            promotion_service: Servicio de pipeline de promociones.
            container: Contenedor IoC para resolver servicios bajo demanda.
        """
        self._user_service = user_service
        self._payment_service = payment_service
        self._vision_service = vision_service
        self._gemini_vision_service = gemini_vision_service
        self._promotion_service = promotion_service
        self._container = container

        # Servicios que se resuelven lazy del contenedor
        self._subscription_service = None
        self._selected_service_repo = None
        self._telegram_api = None

    # ------------------------------------------------------------------
    # Propiedades lazy para dependencias opcionales
    # ------------------------------------------------------------------

    @property
    def subscription_service(self):
        """Obtiene SubscriptionService del contenedor (lazy)."""
        if self._subscription_service is None:
            self._subscription_service = self._container.resolve("subscription_service")
        return self._subscription_service

    @property
    def selected_service_repo(self):
        """Obtiene SelectedServiceRepository del contenedor (lazy)."""
        if self._selected_service_repo is None:
            self._selected_service_repo = self._container.resolve("selected_service_repository")
        return self._selected_service_repo

    @property
    def telegram_api(self):
        """Obtiene TelegramAPIService del contenedor (lazy)."""
        if self._telegram_api is None:
            from services.telegram_api import TelegramAPIService

            self._telegram_api = TelegramAPIService()
        return self._telegram_api

    # ------------------------------------------------------------------
    # Handler de texto genérico (eco)
    # ------------------------------------------------------------------

    async def echo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Maneja mensajes de texto que no son comandos en chats privados.

        Flujo:
        1. Registra al usuario en la base de datos (get_or_create).
        2. Registra al usuario en el pipeline de promociones (DynamoDB).
        3. Muestra el menú principal del bot.

        Args:
            update: Objeto Update de python-telegram-bot.
            context: Contexto de la conversación.
        """
        # update.message es None para mensajes editados (edited_message),
        # channel posts, etc. Ignoramos esos updates para evitar
        # 'NoneType' object has no attribute 'chat'.
        if not update.message or not update.message.from_user:
            logger.debug("echo: update sin message/from_user, ignorando.")
            return

        chat_type = update.message.chat.type
        user_id = int(update.message.from_user.id)
        user_name = update.message.chat.first_name or "Usuario"

        # Solo responder en chats privados (ignorar grupos)
        if chat_type != Chat.PRIVATE:
            return

        # Verificar si el mensaje contiene el comando /vm (validación manual)
        user_message = update.message.text or ""
        if user_message.startswith("/vm"):
            await self._handle_vm_command(update, context)
            return

        # Registrar usuario en BD
        try:
            self._user_service.register_user(
                telegram_id=user_id,
                telegram_name=user_name,
            )
            logger.debug(f"Usuario registrado/actualizado: {user_id}")
        except Exception as e:
            logger.error(f"Error al registrar usuario {user_id}: {e}")

        # Registrar en pipeline de promociones (DynamoDB)
        try:
            self._promotion_service.register_user(str(user_id))
            logger.debug(f"Usuario {user_id} registrado en pipeline de promociones")
        except Exception as e:
            logger.warning(f"No se pudo registrar usuario {user_id} en DynamoDB: {e}")

        # Mostrar menú principal
        await self._send_main_menu(update, context, user_id)

    # ------------------------------------------------------------------
    # Handler de imágenes (comprobantes de pago)
    # ------------------------------------------------------------------

    async def handle_image(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Procesa una imagen enviada por el usuario (comprobante de transferencia).

        Flujo completo:
        1. Verificar que sea un chat privado.
        2. Descargar la imagen al sistema de archivos local.
        3. Ejecutar OCR con Google Vision para extraer texto.
        4. Extraer monto y fecha del texto mediante regex.
        5. Verificar duplicados (últimas 24h).
        6. Si es duplicado → notificar al usuario y al validador.
        7. Si no es duplicado → enviar imagen + datos al validador para aprobación.
        8. Confirmar al usuario que su pago está siendo validado.

        Args:
            update: Objeto Update con la foto.
            context: Contexto de la conversación.
        """
        if not update.message:
            logger.warning("Update sin mensaje, ignorando.")
            return

        chat_type = update.message.chat.type

        # Solo procesar imágenes en chats privados
        if chat_type != Chat.PRIVATE:
            logger.debug("Imagen recibida en chat no privado, ignorando.")
            return

        user_id = int(update.message.from_user.id)
        user_name = update.message.chat.first_name or "Usuario"

        logger.info(f"Imagen recibida de usuario {user_id} ({user_name})")

        # --- Paso 1: Obtener file_id y bytes de la imagen (sin guardar en disco) ---
        file_id = update.message.photo[-1].file_id
        logger.info(f"File ID de imagen: {file_id}")
        photo_file = await update.message.photo[-1].get_file()
        image_bytes = await photo_file.download_as_bytearray()
        logger.info(f"Imagen descargada: {len(image_bytes)} bytes")

        # Guardar file_id en contexto para uso posterior (evita re-descarga)
        context.user_data["pending_file_id"] = file_id

        # --- Paso 2: Extraer precio con Gemini Vision (IA) ---
        monto_extraido = None
        fecha_extraida = None
        used_gemini = False

        if self._gemini_vision_service:
            try:
                # Guardar imagen temporalmente para Gemini Vision
                import tempfile
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                    tmp.write(image_bytes)
                    tmp_path = tmp.name

                result = await self._gemini_vision_service.extract_price_from_image(tmp_path)

                if result["success"] and result["price"]:
                    monto_extraido = result["price"]
                    used_gemini = True
                    logger.info(
                        f"Gemini Vision detectó monto=S/ {monto_extraido:.2f} "
                        f"(confidence={result['confidence']}) para user={user_id}"
                    )
                else:
                    logger.warning(
                        f"Gemini Vision no detectó precio: {result.get('error')}, "
                        f"usando fallback OCR para user={user_id}"
                    )
            except Exception as e:
                logger.error(f"Error en Gemini Vision para user={user_id}: {e}")
            finally:
                import os
                if 'tmp_path' in locals() and os.path.exists(tmp_path):
                    os.unlink(tmp_path)

        # --- Paso 3: Fallback a Google Vision OCR si Gemini falló ---
        if monto_extraido is None:
            try:
                detected_text = self._vision_service.detect_text_from_bytes(bytes(image_bytes))
                logger.debug(f"Texto detectado por OCR: {detected_text[:200]}...")

                from utils.text_parser import extract_amount, extract_date
                monto_extraido = extract_amount(detected_text)
                fecha_extraida = extract_date(detected_text)
            except Exception as e:
                logger.error(f"Error en OCR fallback para user={user_id}: {e}")

        if monto_extraido is None:
            logger.warning(f"No se pudo extraer monto del comprobante de user={user_id}. Enviando al validador para validación manual.")
            monto_extraido = 0.0  # Valor 0 indica que el validador debe ingresar el monto manualmente

        from utils.datetime_utils import get_lima_time_formatted
        fecha_actual = get_lima_time_formatted()["fecha_completa"]

        logger.info(
            f"Comprobante user={user_id}: monto=S/ {monto_extraido:.2f}, "
            f"fecha_detectada={fecha_extraida or 'No detectada'}"
        )

        # --- Paso 4: No se verifica duplicados ---
        # Tanto Stake como VIP permiten múltiples compras
        # VIP renueva/extiende la suscripción con cada compra

        # --- Paso 5: Enviar al validador ---
        logger.info(f"Enviando comprobante al validador: user_id={user_id}, monto=S/ {monto_extraido:.2f}")
        try:
            await self._send_to_validator(
                update=update,
                context=context,
                user_id=user_id,
                user_name=user_name,
                amount=monto_extraido,
                extracted_date=fecha_extraida or fecha_actual,
                file_id=file_id,
            )
            logger.info("Comprobante enviado al validador exitosamente")
        except Exception as e:
            # Si el envío al validador falla (ej. error transitorio de BD o red),
            # NO mostramos el error genérico. Pedimos al usuario que reenvíe su
            # comprobante, que es una acción simple y resuelve fallos transitorios.
            logger.error(
                f"Error al enviar comprobante de user={user_id} al validador: {e}",
                exc_info=True,
            )
            try:
                from services.telegram_api import send_error_notification
                send_error_notification(
                    f"Error al procesar comprobante de user={user_id}: {e}"
                )
            except Exception:
                pass
            await update.message.reply_text(
                "⚠️ No pude procesar tu comprobante en este momento.\n\n"
                "Por favor, <b>vuelve a enviar tu comprobante</b> en unos segundos. 🔄\n\n"
                "Si el problema persiste, contáctate con @magic_peru 📲",
                parse_mode="HTML",
            )
            return

        # --- Paso 6: Confirmar al usuario ---
        if monto_extraido == 0.0:
            await update.message.reply_text(
                "✅ Recibí tu comprobante de pago. Ha sido enviado a Magic para su revisión manual.\n"
                "En breve un asesor validará tu pago y te enviará el enlace de acceso. 📲"
            )
        else:
            await update.message.reply_text(
                "✅ Recibí tu comprobante de pago. En un momento procederé a validar tu pago."
            )
        await update.message.reply_text(
            "📲 Para cualquier duda, consulta o problema, contáctate con @magic_peru"
        )

        logger.info(f"Comprobante de user={user_id} enviado al validador para revisión.")

    # ------------------------------------------------------------------
    # Métodos auxiliares privados
    # ------------------------------------------------------------------

    async def _send_main_menu(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: int,
    ) -> None:
        """
        Envía el menú principal del bot al usuario.

        Args:
            update: Update de Telegram.
            context: Contexto de la conversación.
            user_id: ID de Telegram del usuario.
        """
        from utils.keyboards import main_menu_don_gato_keyboard

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "¡Hola, mi gato! 🔥\n\n"
                "Soy <b>Don Gato</b>, el Bot Asistente Virtual de <b>Magic Apuestas</b> 🐱.\n\n"
                "¿Deseas más información sobre nuestros servicios?\n\n"
                "¡Haz clic en la opción que prefieras! 👇"
            ),
            reply_markup=main_menu_don_gato_keyboard(),
            parse_mode="HTML",
        )

        # Follow-up message (parte del mensaje_inicial_don_gato original)
        await context.bot.send_message(
            chat_id=user_id,
            text="<strong>OJO SI HAS REALIZADO TU PAGO SIMPLEMENTE ENVÍAMELO ACÁ</strong> 📲",
            parse_mode="HTML",
        )

    async def _send_to_validator(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: int,
        user_name: str,
        amount: float,
        extracted_date: str,
        file_id: str,
    ) -> None:
        """
        Envía la imagen del comprobante y los datos extraídos a todos
        los validadores autorizados para su revisión.

        Si el monto no corresponde a un precio definido en la BD,
        oculta el botón de aprobación y obliga al validador a ingresar
        el monto manualmente.

        Args:
            update: Update de Telegram.
            context: Contexto de la conversación.
            user_id: ID de Telegram del comprador.
            user_name: Nombre del comprador.
            amount: Monto extraído del comprobante.
            extracted_date: Fecha extraída del comprobante.
            file_id: ID del archivo (file_id) de Telegram para la imagen.
        """
        from utils.keyboards import payment_validation_keyboard

        # Verificar si el monto corresponde a un precio válido (usando rangos)
        is_valid_price = False
        amount_not_detected = (amount == 0.0)  # 0.0 indica que no se detectó el monto

        if not amount_not_detected:
            try:
                if self._container.is_registered("pricing_service"):
                    pricing = self._container.resolve("pricing_service")
                    plan = pricing.match_price(amount)
                    is_valid_price = plan is not None
                    if not is_valid_price:
                        logger.warning(
                            f"Monto S/ {amount:.2f} no corresponde a un precio definido. "
                            f"Validador deberá ingresar monto manualmente."
                        )
            except Exception as e:
                logger.warning(f"No se pudo verificar precio: {e}")

        # Construir mensaje para el validador
        validation_message = self._payment_service.build_validation_message(
            telegram_id=user_id,
            telegram_name=user_name,
            amount=amount,
            extracted_date=extracted_date,
        )

        # Si el monto no es válido, agregar advertencia al mensaje
        # e incluir el comando /vm directamente para que el validador lo copie.
        if amount_not_detected or not is_valid_price:
            validation_message += (
                f"\n\n⚠️ <b>MONTO NO DETECTADO</b>\n"
                f"Selecciona el servicio correcto en los botones de abajo "
                f"o ingresa el monto manualmente con el comando. "
                f"<b>Reemplaza <code>{int(amount)}</code> por el monto real transferido por el cliente:</b>\n\n"
                f"<code>/vm {user_id} &lt;MONTO_TRANSFERIDO&gt;</code>\n\n"
                f"<i>Ejemplo: /vm {user_id} 125</i>\n"
                f"<i>También puedes agregar fecha al final: /vm {user_id} 125 {extracted_date}</i>"
            )

        # Construir teclado de validación
        if amount_not_detected or not is_valid_price:
            # Mostrar opciones de servicio directamente + PAGO NO VALIDADO.
            # No se incluye botón de ingresar monto manual ni cancelar.
            if self._container.is_registered("pricing_service"):
                pricing = self._container.resolve("pricing_service")
                reply_markup = pricing.generate_confirmation_keyboard(user_id=user_id, amount=amount)
                # Añadir botón de "PAGO NO VALIDADO" arriba
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                reject_button = InlineKeyboardButton(
                    "❌ PAGO NO VALIDADO",
                    callback_data=f"validar_monto:not_valid:{user_id}:{int(amount)}:"
                )
                reply_markup = InlineKeyboardMarkup(
                    [[reject_button]] + list(reply_markup.inline_keyboard)
                )
            else:
                from utils.keyboards import service_confirmation_keyboard
                reply_markup = service_confirmation_keyboard(
                    user_id=user_id,
                    monto=amount,
                    source="telegram",
                )
        else:
            # Monto válido: mostrar teclado tradicional (aprobar, rechazar, manual)
            reply_markup = payment_validation_keyboard(
                user_id=user_id,
                amount=amount,
                source="telegram",
                extra_data=extracted_date,
                is_valid_price=True,
            )

        # Obtener lista de validadores
        # Todos los validadores reciben la imagen, incluso si son el remitente
        validator_ids = self._payment_service.get_validator_ids()
        logger.info(f"Validadores configurados: {validator_ids}")

        user_id_str = str(user_id)
        for validator_id in validator_ids:
            logger.info(f"Procesando envío a validador: {validator_id}, user_id={user_id_str}")

            # Borrar validación anterior del mismo usuario (si existe) para
            # que solo se muestre la foto más reciente en el chat del validador
            pending_key = f"pending_validation:{user_id}:{validator_id}"
            try:
                old_msg = context.bot_data.get(pending_key)
                if old_msg:
                    old_validator_id, old_message_id = old_msg
                    await context.bot.delete_message(
                        chat_id=int(old_validator_id), message_id=old_message_id
                    )
                    logger.info(f"Validación anterior de user={user_id} borrada del chat {old_validator_id}")
            except Exception:
                pass  # Si falla el borrado, seguimos igual
            finally:
                context.bot_data.pop(pending_key, None)

            # Telegram limita captions de foto a 1024 caracteres.
            # Si el mensaje excede el límite, enviamos la foto sin caption
            # y el mensaje completo como texto separado para evitar
            # truncar tags HTML a medio abrir.
            caption = validation_message
            sent_message_id = None
            if len(caption) > 1024:
                logger.warning(
                    f"Caption de {len(caption)} chars excede límite de 1024. "
                    f"Enviando foto y mensaje por separado."
                )
                try:
                    photo_msg = await context.bot.send_photo(
                        chat_id=int(validator_id),
                        photo=file_id,
                    )
                    # Como respuesta a la foto: así el callback de validación
                    # puede leer el comprobante (clave de idempotencia).
                    text_msg = await context.bot.send_message(
                        chat_id=int(validator_id),
                        text=validation_message,
                        reply_markup=reply_markup,
                        parse_mode="HTML",
                        reply_to_message_id=photo_msg.message_id,
                    )
                    sent_message_id = text_msg.message_id
                    if is_valid_price:
                        logger.info(f"Comprobante enviado al validador {validator_id} para user={user_id}")
                    else:
                        logger.info(f"Comprobante con monto inválido enviado al validador {validator_id} para user={user_id}")
                except Exception as e:
                    logger.error(f"Error al enviar comprobante al validador {validator_id}: {e}")
                continue
            else:
                try:
                    msg = await context.bot.send_photo(
                        chat_id=int(validator_id),
                        photo=file_id,
                        caption=caption,
                        reply_markup=reply_markup,
                        parse_mode="HTML",
                    )
                    sent_message_id = msg.message_id
                    if is_valid_price:
                        logger.info(f"Comprobante enviado al validador {validator_id} para user={user_id}")
                    else:
                        logger.info(f"Comprobante con monto inválido enviado al validador {validator_id} para user={user_id}")
                except Exception as e:
                    logger.error(f"Error al enviar comprobante al validador {validator_id}: {e}")

            # Guardar referencia para poder borrarla si el usuario envía otra foto
            if sent_message_id:
                context.bot_data[pending_key] = (validator_id, sent_message_id)

    async def _handle_duplicate_payment(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: int,
        user_name: str,
        amount: float,
    ) -> None:
        """
        Maneja el caso cuando se detecta una compra duplicada.

        Notifica al usuario que su compra ya fue registrada y le proporciona
        el enlace de invitación correspondiente.

        Args:
            update: Update de Telegram.
            context: Contexto de la conversación.
            user_id: ID del comprador.
            user_name: Nombre del comprador.
            amount: Monto de la compra duplicada.
        """
        # Obtener info de la compra duplicada
        purchase_info = self._payment_service.get_recent_purchase_info(
            telegram_id=user_id,
            amount=amount,
        )

        if purchase_info is None:
            await update.message.reply_text(
                "⚠️ Parece que ya procesamos tu pago recientemente. "
                "Si crees que es un error, contacta a @magic_peru."
            )
            return

        # Determinar tipo de servicio y obtener link de invitación
        service_id = purchase_info.get("service_id", 0)
        service_name = "Grupo VIP" if service_id == 2 else "Stake"

        # Obtener link de invitación
        invite_link = None
        try:
            if service_name == "Grupo VIP":
                from config.settings import settings

                chat_id = int(settings.TELEGRAM_VIP_GROUP_ID)
                invite_link = self.telegram_api.create_invite_link(
                    chat_id=chat_id,
                    member_limit=1,
                    name=f"Reenvío para {user_name}",
                )
            elif service_name == "Stake":
                # Para Stake, el valor almacenado en la hoja "stake" (Google Sheets)
                # YA es el link de invitación. Se obtiene y se usa directamente.
                sheets_service = (
                    self._container.resolve("google_sheets_service")
                    if self._container.is_registered("google_sheets_service")
                    else None
                )
                if sheets_service:
                    group_value = sheets_service.get_service_group_id("stake")
                    if group_value:
                        invite_link = group_value.strip()
        except Exception as e:
            logger.error(f"Error al obtener link de invitación: {e}")
            invite_link = None

        # Formatear la fecha de compra
        from utils.datetime_utils import format_date_spanish

        purchase_date = purchase_info.get("purchase_date")
        formatted_date = (
            format_date_spanish(purchase_date) if purchase_date else "fecha desconocida"
        )

        # Notificar al usuario
        from utils.keyboards import duplicate_purchase_restriction_keyboard

        await update.message.reply_text(
            f"ℹ️ <b>YA TIENES UNA COMPRA REGISTRADA</b>\n\n"
            f"Detectamos que ya realizaste un pago de <b>S/ {amount:.2f}</b> "
            f"por el servicio <b>{service_name}</b> el {formatted_date}.\n\n"
            f"No es necesario que vuelvas a enviar el comprobante. "
            f"Si perdiste tu enlace de invitación, contáctanos.",
            reply_markup=duplicate_purchase_restriction_keyboard(service_name),
            parse_mode="HTML",
        )

        if invite_link:
            await update.message.reply_text(
                f"🔗 Aquí tienes tu enlace de invitación nuevamente:\n{invite_link}"
            )

    async def _handle_vm_command(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
    ) -> None:
        """
        Procesa el comando /vm (validación manual de monto).

        Formato esperado: /vm [user_id] [message_id] [monto_correcto] [fecha_opcional]

        Este comando es usado por los validadores para corregir manualmente
        el monto cuando el OCR no pudo extraerlo correctamente.

        Args:
            update: Update de Telegram.
            context: Contexto de la conversación.
        """
        business_user_id = int(update.effective_user.id)

        # Verificar que quien ejecuta el comando sea un validador autorizado
        if not self._payment_service.is_validator_authorized(business_user_id):
            await update.message.reply_text("⛔ No estás autorizado para validar pagos.")
            return

        message_text = update.message.text
        parts = message_text.split()

        if len(parts) < 3:
            await update.message.reply_text(
                "❌ Formato incorrecto. Uso:\n"
                "<code>/vm [user_id] [monto_correcto]</code>\n"
                "<code>/vm [user_id] [message_id] [monto_correcto] [fecha_correcta]</code>\n\n"
                "Ejemplo: <code>/vm 12345 125</code>\n"
                "Ejemplo: <code>/vm 12345 67890 125 15/01/2025</code>",
                parse_mode="HTML",
            )
            return

        try:
            target_user_id = int(parts[1])
            if len(parts) == 3:
                corrected_amount = float(parts[2])
            else:
                corrected_amount = float(parts[3])
        except (ValueError, IndexError) as e:
            await update.message.reply_text(
                f"❌ Error al parsear los datos: {e}\n"
                f"Formato: /vm [user_id] [monto] [fecha_opcional]"
            )
            return

        # Obtener fecha opcional
        fecha_extraida = parts[4] if len(parts) >= 5 else None

        # Verificar duplicados
        if self._payment_service.check_duplicate_payment(target_user_id, corrected_amount):
            purchase_info = self._payment_service.get_recent_purchase_info(
                telegram_id=target_user_id,
                amount=corrected_amount,
            )
            if purchase_info:
                from utils.datetime_utils import format_date_spanish

                formatted_date = (
                    format_date_spanish(purchase_info.get("purchase_date"))
                    if purchase_info.get("purchase_date")
                    else "fecha desconocida"
                )

                await update.message.reply_text(
                    f"⚠️ Este usuario ya tiene una compra registrada por "
                    f"S/ {corrected_amount:.2f} el {formatted_date}. "
                    f"No se procesará duplicado."
                )
                return

        from services.payment_service import voucher_payment_ref

        message_ref = parts[2] if len(parts) >= 4 else None
        payment_ref = voucher_payment_ref(update.message.reply_to_message) or (
            f"vm:{business_user_id}:{message_ref}" if message_ref else None
        )

        # Procesar el pago con el monto corregido
        result = self._payment_service.validate_with_corrected_amount(
            telegram_id=target_user_id,
            corrected_amount=corrected_amount,
            from_channel="telegram",
            purchase_date=fecha_extraida,
            payment_ref=payment_ref,
        )

        if result.is_duplicate:
            await update.message.reply_text(
                "⚠️ Este comprobante ya fue validado anteriormente. No se registró de nuevo."
            )
            return

        if result.success:
            await update.message.reply_text(
                f"✅ Pago validado correctamente para el usuario {target_user_id}.\n"
                f"Monto: S/ {corrected_amount:.2f}\n"
                f"Resultado: {result.message}"
            )

            # Notificar al comprador y enviar link de invitación
            await self._notify_purchase_success(
                context=context,
                user_id=target_user_id,
                result=result,
            )
        else:
            await update.message.reply_text(
                f"❌ No se pudo validar el pago para {target_user_id}:\n{result.message}"
            )

    async def _notify_purchase_success(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        user_id: int,
        result,
    ) -> None:
        """
        Notifica al comprador que su pago fue validado y envía el link
        de invitación al grupo correspondiente.

        Args:
            context: Contexto de la conversación.
            user_id: ID de Telegram del comprador.
            result: PurchaseResult con info del servicio adquirido.
        """
        try:
            from config.settings import settings

            service_type = result.service_type
            invite_link = None

            if service_type == "grupo_vip":
                chat_id = int(settings.TELEGRAM_VIP_GROUP_ID)
                invite_link = self.telegram_api.create_invite_link(
                    chat_id=chat_id,
                    member_limit=1,
                    name=f"VIP para {user_id}",
                )
            elif service_type == "stake":
                # Para Stake, el valor almacenado en la hoja "stake" (Google Sheets)
                # YA es el link de invitación. Se obtiene y se usa directamente, igual
                # que en la lógica original (sheets.get_service_id("stake")).
                try:
                    sheets_service = (
                        self._container.resolve("google_sheets_service")
                        if self._container.is_registered("google_sheets_service")
                        else None
                    )
                    if sheets_service:
                        group_value = sheets_service.get_service_group_id("stake")
                        if group_value:
                            invite_link = group_value.strip()
                except Exception as e:
                    logger.warning(f"No se pudo obtener link de Stake: {e}")

            # Enviar mensaje de confirmación al comprador
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    f"🎉 <b>¡PAGO VALIDADO CON ÉXITO!</b>\n\n"
                    f"Servicio: <b>{service_type.upper()}</b>\n"
                    f"Monto: S/ {result.purchase_result.price:.2f}\n\n"
                    f"¡Bienvenido a la comunidad más rentable del Perú! 🔮"
                ),
                parse_mode="HTML",
            )

            if invite_link:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"🔗 Aquí tienes tu enlace de invitación al grupo:\n"
                        f"{invite_link}\n\n"
                        f"⚠️ Este enlace es de <b>un solo uso</b> y expira en 24 horas."
                    ),
                    parse_mode="HTML",
                )

            # Enviar mensaje de registro a Betsafe
            from config.settings import settings

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "<b>¡TE REGALO 70 LUCAS MI KING!</b>\n\n"
                    "Regístrate con el link exclusivo, haz tu primer depósito "
                    "de mínimo S/. 40 y listo tendrás 70 soles gratis.\n\n"
                    f"<a href='{settings.BETSAFE_PROMO_LINK}'>"
                    "👉 OBTÉN TUS 70 SOLES GRATIS 👈</a>"
                ),
                parse_mode="HTML",
            )

            # Limpiar servicio seleccionado
            try:
                self.selected_service_repo.delete_by_user(user_id)
                logger.debug(f"Servicio seleccionado eliminado para user={user_id}")
            except Exception as e:
                logger.warning(f"No se pudo limpiar selección de user={user_id}: {e}")

            # Sin archivo local que eliminar: las imágenes fluyen por file_id de Telegram

        except Exception as e:
            logger.error(
                f"Error al notificar compra exitosa a user={user_id}: {e}",
                exc_info=True,
            )
