"""
Command Handlers - Magic Chatbot v2
=====================================
Handlers para comandos de Telegram (/start, /help, /vm, /id, etc.).

Cada handler es un método de la clase CommandHandlers, que recibe los
servicios necesarios por constructor (Dependency Injection).

Principios:
- Thin Controllers: Los handlers orquestan, no contienen lógica de negocio.
- SRP: Cada handler tiene una responsabilidad clara y única.
- Type-safe: Type hints en todos los parámetros y retornos.

Mapeo de comandos originales → nuevos handlers:
- /start → start()
- /vm → validar_monto()
- /wsp → registro_usuario_wsp()
- /valid → register_user_from_api()
- /id → validador_business_user_id()
- /mensaje_recordatorio → envio_mensaje_recordatorio()
- /servicio_id → servicio_id()
- /generar_link → generar_link_servicio()

Uso:
    from handlers.commands import CommandHandlers

    cmd = CommandHandlers(user_service, subscription_service, payment_service)
    app.add_handler(CommandHandler("start", cmd.start))
    app.add_handler(CommandHandler("vm", cmd.validar_monto))
"""

import logging
import os
from datetime import datetime

import pandas as pd
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

IMAGE_DIR = "./images"
CSV_SERVICES_PAYMENTS = "./csv/service_payments_api.csv"

SERVICES_NAMES_BY_ID = {
    1: "Stake",
    2: "Grupo VIP",
}


# ============================================================================
# Command Handlers
# ============================================================================


class CommandHandlers:
    """
    Handlers para todos los comandos del bot de Telegram.

    Recibe los servicios de negocio por constructor y los utiliza
    para procesar cada comando sin contener lógica de negocio propia.

    Attributes:
        _user_service: UserService para registro/consulta de usuarios.
        _subscription_service: SubscriptionService para compras/suscripciones.
        _payment_service: PaymentService para validación de pagos.
        _vision_service: GoogleVisionService (opcional) para OCR.
        _sheets_service: GoogleSheetsService (opcional) para Google Sheets.
        _promotion_service: PromotionService (opcional) para DynamoDB.
    """

    def __init__(
        self,
        user_service,
        subscription_service,
        payment_service,
        vision_service=None,
        sheets_service=None,
        promotion_service=None,
    ) -> None:
        """
        Inicializa los command handlers con los servicios requeridos.

        Args:
            user_service: Servicio de gestión de usuarios.
            subscription_service: Servicio de compras y suscripciones.
            payment_service: Servicio de validación de pagos.
            vision_service: Servicio de OCR (opcional).
            sheets_service: Servicio de Google Sheets (opcional).
            promotion_service: Servicio de promociones/DynamoDB (opcional).
        """
        self._user_service = user_service
        self._subscription_service = subscription_service
        self._payment_service = payment_service
        self._vision_service = vision_service
        self._sheets_service = sheets_service
        self._promotion_service = promotion_service

    # ==================================================================
    # /start
    # ==================================================================

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Comando /start - Registra al usuario y muestra el menú principal.

        Flujo:
        1. Obtiene telegram_id y nombre del usuario.
        2. Registra/actualiza al usuario en la base de datos.
        3. Registra al usuario en el pipeline de promociones (DynamoDB).
        4. Muestra el menú principal con opciones de compra.

        Args:
            update: Update de Telegram con la información del mensaje.
            context: Contexto de la conversación de Telegram.
        """
        user_id = int(update.message.from_user.id)
        user_name = update.message.chat.first_name or "Usuario"

        logger.info(f"/start: user_id={user_id}, name={user_name}")

        # 1. Registrar usuario en BD
        try:
            self._user_service.register_user(
                telegram_id=user_id,
                telegram_name=user_name,
            )
        except Exception as e:
            logger.error(f"Error al registrar usuario {user_id}: {e}")

        # 2. Registrar en pipeline de promociones (DynamoDB)
        if self._promotion_service:
            try:
                self._promotion_service.register_user(str(user_id))
            except Exception as e:
                logger.warning(f"No se pudo registrar promo para {user_id}: {e}")

        # 3. Mostrar menú principal estilo Don Gato
        from utils.keyboards import main_menu_don_gato_keyboard

        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "¡Hola, mi gato! 🔥\n\n"
                "Soy <b>Don Gato</b>, el Bot Asistente Virtual de <b>Magic Apuestas</b> 🐱.\n\n"
                "¿Deseas más información sobre nuestros servicios?\n\n"
                "¡Haz clic en la opción que prefieras! 👇"
            ),
            parse_mode="HTML",
            reply_markup=main_menu_don_gato_keyboard(),
        )

        # Follow-up message (parte del mensaje_inicial_don_gato original)
        await context.bot.send_message(
            chat_id=user_id,
            text="<strong>OJO SI HAS REALIZADO TU PAGO SIMPLEMENTE ENVÍAMELO ACÁ</strong> 📲",
            parse_mode="HTML",
        )

        logger.info(f"Usuario {user_id} recibió menú principal.")

    # ==================================================================
    # /version - Muestra la versión actual del bot
    # ==================================================================

    async def version(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Muestra la versión actual del bot."""
        from datetime import datetime

        from config.settings import settings

        user_id = update.message.chat.id
        msg = (
            f"🔮 <b>Magic Chatbot v2</b>\n"
            f"├ 🏷️ Versión: <code>{settings.PROJECT_VERSION}</code>\n"
            f"├ 🌐 Entorno: <code>{settings.ENVIRONMENT}</code>\n"
            f"├ 🐍 Python: <code>OK</code>\n"
            f"└ 🕐 Hora: <code>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</code>"
        )
        await context.bot.send_message(
            chat_id=user_id,
            text=msg,
            parse_mode="HTML",
        )

    # ==================================================================
    # /vm - Validar monto (corregir monto manualmente)
    # ==================================================================

    async def validar_monto(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Comando /vm - Permite al validador corregir manualmente el monto
        de un pago y registrarlo.

        Formato: /vm {user_id} {message_id} {monto_correcto} [fecha_correcta]
        También soporta: /vm {user_id} {message_id} wsp {monto_correcto}

        Args:
            update: Update de Telegram.
            context: Contexto de la conversación.
        """
        logger.info(f"/vm recibido: {update.message.text}")

        message_text = update.message.text
        data = message_text.split(" ")

        if len(data) < 3:
            await update.message.reply_text(
                "Formato incorrecto. Usar:\n"
                "<code>/vm {user_id} {monto_correcto}</code>\n"
                "<code>/vm {user_id} {message_id} {monto_correcto} [fecha_correcta]</code>\n\n"
                "Ejemplo: /vm 12345 125\n"
                "Ejemplo: /vm 12345 67890 125 15012025",
                parse_mode="HTML",
            )
            return

        try:
            user_id = int(data[1])
            message_id = None
            monto_correcto = None
            fecha_extraida = None
            canal_procedencia = "telegram"
            business_user_id = int(update.effective_user.id)

            # Verificar si el validador está autorizado
            if not self._payment_service.is_validator_authorized(business_user_id):
                await update.message.reply_text("No estás autorizado para validar pagos.")
                return

            if len(data) == 3:
                # Formato: /vm user_id price
                monto_correcto = float(data[2])
            else:
                # Formato: /vm user_id message_id price [fecha]
                message_id = str(data[2])
                monto_correcto = float(data[3])

                if len(data) == 5:
                    if data[4] == "wsp":
                        canal_procedencia = data[4]
                    else:
                        fecha_extraida = data[4]

            logger.info(
                f"Procesando /vm: user={user_id}, monto={monto_correcto}, "
                f"canal={canal_procedencia}, fecha={fecha_extraida}"
            )

            # No se verifica duplicados: tanto Stake como VIP permiten múltiples compras
            # VIP renueva/extiende la suscripción con cada compra

            # Si el pago viene de WhatsApp, actualizar estado en Sheets
            if canal_procedencia == "wsp" and self._sheets_service:
                try:
                    self._sheets_service.update_wsp_payment_review_status(telegram_id=user_id)
                    logger.info(f"Revisión WSP actualizada para user={user_id}")
                except Exception as e:
                    logger.error(f"Error al actualizar revisión WSP: {e}")

            # Clave de idempotencia: la foto del comprobante si el /vm se envía
            # como respuesta a ella; si no, el mensaje de validación indicado.
            from services.payment_service import voucher_payment_ref

            payment_ref = voucher_payment_ref(update.message.reply_to_message) or (
                f"vm:{business_user_id}:{message_id}" if message_id else None
            )

            # Procesar la compra con el monto corregido
            result = self._payment_service.validate_with_corrected_amount(
                telegram_id=user_id,
                corrected_amount=monto_correcto,
                from_channel=canal_procedencia,
                purchase_date=fecha_extraida,
                payment_ref=payment_ref,
            )

            if result.is_duplicate:
                await update.message.reply_text(
                    "⚠️ Este comprobante ya fue validado anteriormente. No se registró de nuevo."
                )
                return

            if result.success:
                # Obtener usuario para mostrar info
                user = self._user_service.get_user(user_id)
                user_name = user.telegram_name if user else "Usuario"

                # Determinar tipo de servicio
                service_type = result.service_type

                # Notificar al validador
                reply_to_message_id = (
                    int(message_id) if message_id and str(message_id).isdigit() else None
                )

                # Notificar al validador
                await context.bot.send_message(
                    chat_id=business_user_id,
                    text=(
                        f"Se ha validado el pago del usuario "
                        f"{user_name} - {user_id} con un monto de "
                        f"S/ {monto_correcto:.2f} para {service_type}"
                    ),
                    reply_to_message_id=reply_to_message_id,
                )

                # Enviar confirmación de compra
                await context.bot.send_message(
                    chat_id=business_user_id,
                    text=result.message,
                    reply_to_message_id=reply_to_message_id,
                )

                # Obtener link de invitación
                invite_link = await self._get_invite_link(
                    context=context,
                    tipo_servicio=service_type,
                )

                if invite_link:
                    # Enviar al comprador: info de Betsafe + link de invitación
                    from utils.keyboards import post_purchase_keyboard

                    await context.bot.send_message(
                        chat_id=user_id,
                        text=(
                            "✅ ¡Pago validado exitosamente!\n\n"
                            "🎁 No olvides reclamar tu bono de S/ 70 gratis "
                            "en Betsafe:"
                        ),
                        reply_markup=post_purchase_keyboard(invite_link),
                    )
                else:
                    # No se pudo obtener el link: derivar al usuario a soporte.
                    logger.warning(
                        f"No se pudo obtener link de {service_type} para user={user_id}. "
                        f"Se deriva a soporte."
                    )
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=(
                            "✅ ¡Pago validado exitosamente!\n\n"
                            "⚠️ No pudimos generar tu link de acceso automáticamente.\n"
                            "Por favor, solicita tu link de acceso a soporte: @magic_peru2"
                        ),
                    )

                # Limpiar selección de servicio pendiente
                try:
                    from core.database import SessionLocal
                    from repositories.selected_service_repo import (
                        SelectedServiceRepository,
                    )

                    session = SessionLocal()
                    selected_repo = SelectedServiceRepository(session)
                    selected_repo.delete_by_user(user_id)
                    session.close()
                    logger.info(f"Selección de servicio eliminada para user={user_id}")
                except Exception as e:
                    logger.warning(f"No se pudo eliminar selección: {e}")

                # Eliminar imagen del comprobante
                image_path = f"{IMAGE_DIR}/trans_{user_id}.jpeg"
                if os.path.exists(image_path):
                    os.remove(image_path)
                    logger.info(f"Imagen eliminada: {image_path}")

            elif "undefined_price" in (result.errors or []):
                # El monto no corresponde a un precio definido: insistir al
                # validador para que reingrese el monto correcto.
                await context.bot.send_message(
                    chat_id=business_user_id,
                    text=(
                        f"⚠️ El monto S/ {monto_correcto:.2f} no corresponde a "
                        f"ningún precio definido.\n\n"
                        f"Por favor, ingrese nuevamente el monto correcto:\n"
                        f"<code>/vm {user_id} {message_id} [monto_correcto] [fecha]</code>"
                    ),
                    reply_to_message_id=int(message_id) if message_id.isdigit() else None,
                    parse_mode="HTML",
                )

            else:
                # Notificar error al validador
                await context.bot.send_message(
                    chat_id=business_user_id,
                    text=f"No se pudo validar el pago: {result.message}",
                    reply_to_message_id=int(message_id) if message_id.isdigit() else None,
                )

        except (IndexError, ValueError) as e:
            logger.error(f"Error al parsear /vm: {e}")
            await update.message.reply_text(
                "Formato incorrecto. Usar: "
                "/vm {user_id} {message_id} {monto_correcto} [fecha_correcta]"
            )
        except Exception as e:
            logger.error(f"Error inesperado en /vm: {e}", exc_info=True)
            await update.message.reply_text(f"Ocurrió un error al procesar la validación: {str(e)}")

    # ==================================================================
    # /wsp - Registrar usuario desde WhatsApp
    # ==================================================================

    async def registro_usuario_wsp(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Comando /wsp - Registra un pago proveniente de WhatsApp.

        Formato: /wsp {codigo_whatsapp}

        Flujo:
        1. Obtiene el código de WhatsApp del mensaje.
        2. Busca en Google Sheets la URL de la captura de transferencia.
        3. Descarga la imagen de la transferencia.
        4. Aplica OCR (Vision API) para extraer monto y fecha.
        5. Envía la información al validador con botones de acción.

        Args:
            update: Update de Telegram.
            context: Contexto de la conversación.
        """
        logger.info(f"/wsp recibido: {update.message.text}")

        user_id = int(update.message.chat.id)
        nombre_usuario = update.message.chat.first_name or "Usuario"
        message_text = update.message.text
        args = message_text.split(" ")

        if len(args) != 2 or args[0] != "/wsp":
            await update.message.reply_text("Formato incorrecto. Usar: /wsp {codigo_whatsapp}")
            return

        wsp_user_id = args[1]
        image_path = f"{IMAGE_DIR}/trans_{user_id}.jpeg"

        # Notificar al usuario que se está procesando
        await context.bot.send_message(
            chat_id=user_id,
            text=(
                "<strong>Recibí tu voucher de pago, en un minuto procederé "
                "a validar tu pago ✅</strong>"
            ),
            parse_mode="HTML",
        )

        # Registrar usuario en BD
        from utils.datetime_utils import get_lima_time_formatted

        fecha_hora = get_lima_time_formatted()
        self._user_service.register_user(
            telegram_id=user_id,
            telegram_name=nombre_usuario,
        )

        # Registrar en Google Sheets
        if self._sheets_service:
            try:
                self._sheets_service.register_new_user(
                    [
                        user_id,
                        nombre_usuario,
                        fecha_hora["yyyy-mm-dd"],
                    ]
                )
                logger.info(f"Usuario {user_id} registrado en Google Sheets.")
            except Exception as e:
                logger.error(f"Error al registrar en Sheets: {e}")

        # Obtener URL de transferencia y tipo de servicio desde Sheets
        url_transferencia = None
        tipo_servicio = None

        if self._sheets_service:
            url_transferencia, tipo_servicio = self._sheets_service.get_wsp_transfer_data(
                wsp_id=wsp_user_id,
                telegram_id=user_id,
            )

        if not url_transferencia:
            await update.message.reply_text(
                "No se encontró información de transferencia para el código "
                f"WhatsApp proporcionado: {wsp_user_id}"
            )
            return

        logger.info(f"WSP: user={user_id}, url={url_transferencia}, tipo={tipo_servicio}")

        # Descargar imagen de la transferencia
        import requests

        try:
            response = requests.get(url_transferencia)
            if response.status_code == 200:
                with open(image_path, "wb") as f:
                    f.write(response.content)
                logger.info(f"Imagen descargada: {image_path}")
            else:
                logger.error(f"Error al descargar imagen: HTTP {response.status_code}")
                await update.message.reply_text(
                    "No se pudo descargar la imagen de la transferencia."
                )
                return
        except Exception as e:
            logger.error(f"Error al descargar imagen: {e}")
            await update.message.reply_text("Error al descargar la imagen de la transferencia.")
            return

        # Aplicar OCR para extraer monto
        monto_extraido = 0.0

        if self._vision_service and os.path.exists(image_path):
            try:
                texto = self._vision_service.detect_text(image_path)
                from utils.text_parser import extract_amount

                monto_extraido = extract_amount(texto) or 0.0
                logger.info(f"Monto extraído por OCR: S/ {monto_extraido:.2f}")
            except Exception as e:
                logger.error(f"Error al extraer texto de imagen: {e}")

        # Construir mensaje para el validador
        from utils.keyboards import payment_validation_wsp_keyboard

        mensaje_validacion = (
            f"@{nombre_usuario} ha enviado una captura con un monto de "
            f"S/. {monto_extraido:.2f} para {tipo_servicio or 'servicio desconocido'}"
        )

        # Enviar al validador
        validator_ids = self._payment_service.get_validator_ids()
        for vid in validator_ids:
            try:
                await context.bot.send_photo(
                    chat_id=int(vid),
                    photo=open(image_path, "rb"),
                    caption=mensaje_validacion,
                    reply_markup=payment_validation_wsp_keyboard(
                        user_id=user_id,
                        amount=monto_extraido,
                    ),
                )
                logger.info(f"Captura WSP enviada al validador {vid}")
            except Exception as e:
                logger.error(f"Error al enviar al validador {vid}: {e}")

        # Limpiar imagen
        if os.path.exists(image_path):
            os.remove(image_path)
            logger.debug(f"Imagen temporal eliminada: {image_path}")

    # ==================================================================
    # /valid - Registrar usuario desde API externa
    # ==================================================================

    async def register_user_from_api(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Comando /valid - Registra un usuario que viene de una plataforma externa.

        Formato: /valid {codigo_generado}

        Busca el código en el CSV de service_payments_api.csv y procesa
        la compra registrada por la API externa.

        Args:
            update: Update de Telegram.
            context: Contexto de la conversación.
        """
        logger.info(f"/valid recibido: {update.message.text}")

        telegram_id = int(update.message.chat.id)
        message_text = update.message.text
        args = message_text.split(" ")

        if len(args) != 2 or args[0] != "/valid":
            await update.message.reply_text("Formato incorrecto. Usar: /valid {codigo_generado}")
            return

        id_a_buscar = args[1]

        # Leer CSV de pagos de la API
        if not os.path.exists(CSV_SERVICES_PAYMENTS):
            await update.message.reply_text("Error: No se encuentra el archivo de pagos de la API.")
            return

        try:
            df_services_payments = pd.read_csv(CSV_SERVICES_PAYMENTS)
            row = df_services_payments[df_services_payments["id"] == id_a_buscar]

            if row.empty:
                await update.message.reply_text("Error: El ID no se encuentra registrado.")
                return

            if row["claimed"].values[0]:
                await update.message.reply_text(
                    "Error: El ID ya ha sido registrado. Muchas gracias."
                )
                return

            amount = float(row["amount"].values[0])
            service = row["service"].values[0]

            logger.info(f"API validation: user={telegram_id}, amount={amount}, service={service}")

            # Procesar compra
            result = self._subscription_service.process_purchase(
                telegram_id=telegram_id,
                price=amount,
                from_channel="Whatsapp",
            )

            if not result.success:
                await update.message.reply_text(f"Error al procesar la compra: {result.message}")
                return

            # Obtener link de invitación
            invite_link = await self._get_invite_link(
                context=context,
                tipo_servicio=service,
            )

            # Enviar mensaje al usuario
            if service == "grupo_vip":
                await context.bot.send_message(
                    chat_id=telegram_id,
                    text=(
                        f"Aquí tienes tu enlace de invitación mi gato, "
                        f"válido para un solo uso y expira en 24 horas:\n"
                        f"{invite_link}"
                    ),
                )
            elif service == "stake":
                await context.bot.send_message(
                    chat_id=telegram_id,
                    text=(
                        f"Gracias mi gato. Este es el enlace para unirte "
                        f"al grupo Stake:\n{invite_link}"
                    ),
                )

            # Marcar como reclamado en el CSV
            df_services_payments.loc[df_services_payments["id"] == id_a_buscar, "claimed"] = True
            df_services_payments.to_csv(CSV_SERVICES_PAYMENTS, index=False)

            logger.info(f"API validation completada: user={telegram_id}, service={service}")

        except Exception as e:
            logger.error(f"Error en /valid: {e}", exc_info=True)
            await update.message.reply_text(f"Error al procesar la validación: {str(e)}")

    # ==================================================================
    # /id - Mostrar ID del usuario validador
    # ==================================================================

    async def validador_business_user_id(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Comando /id - Muestra el ID de Telegram del usuario.

        Útil para que los validadores conozcan su propio ID y puedan
        ser agregados a la lista de validadores autorizados.

        Args:
            update: Update de Telegram.
            context: Contexto de la conversación.
        """
        user_id = int(update.message.chat.id)
        logger.info(f"/id solicitado por user={user_id}")

        await context.bot.send_message(
            chat_id=user_id,
            text=f"<b>TU USER ID ES:</b> <code>{user_id}</code>",
            parse_mode="HTML",
        )

    # ==================================================================
    # /mensaje_recordatorio - Enviar recordatorio a un usuario
    # ==================================================================

    async def envio_mensaje_recordatorio(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Comando /mensaje_recordatorio - Envía un recordatorio de compra
        a un usuario específico.

        Formato: /mensaje_recordatorio {user_id}

        Args:
            update: Update de Telegram.
            context: Contexto de la conversación.
        """
        logger.info(f"/mensaje_recordatorio recibido: {update.message.text}")

        message_text = update.message.text
        data = message_text.split(" ")

        if len(data) < 2:
            await update.message.reply_text(
                "Formato incorrecto. Usar: /mensaje_recordatorio {user_id}"
            )
            return

        try:
            user_id = int(data[1])

            # Enviar mensaje de recordatorio de venta
            from utils.keyboards import reminder_keyboard

            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "🔮 <b>¡NO TE PIERDAS LOS PRONÓSTICOS GANADORES!</b>\n\n"
                    "Nuestros clientes están ganando todos los días con las "
                    "mejores fijas estadísticas de todo el Perú.\n\n"
                    "Selecciona tu servicio y únete ahora:"
                ),
                parse_mode="HTML",
                reply_markup=reminder_keyboard(),
            )

            logger.info(f"Recordatorio enviado a user={user_id}")
        except ValueError:
            await update.message.reply_text("El ID de usuario debe ser un número.")
        except Exception as e:
            logger.error(f"Error al enviar recordatorio: {e}", exc_info=True)
            await update.message.reply_text(f"Error al enviar el recordatorio: {str(e)}")

    # ==================================================================
    # /servicio_id - Mostrar ID de grupo para un tipo de servicio
    # ==================================================================

    async def servicio_id(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Comando /servicio_id - Obtiene y muestra el ID del grupo de Telegram
        para un tipo de servicio.

        Args:
            update: Update de Telegram.
            context: Contexto de la conversación.
        """
        logger.info(f"/servicio_id recibido: {update.message.text}")

        user_id = int(update.message.chat.id)
        message_text = update.message.text
        data = message_text.split(" ")

        if len(data) < 2:
            await update.message.reply_text(
                "Formato incorrecto. Usar: /servicio_id {tipo_servicio}\n"
                "Ejemplo: /servicio_id Stake"
            )
            return

        tipo_servicio = data[1]

        if self._sheets_service:
            group_id = self._sheets_service.get_service_group_id(tipo_servicio)
            if group_id:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=(f"ID del grupo para <b>{tipo_servicio}</b>: <code>{group_id}</code>"),
                    parse_mode="HTML",
                )
            else:
                await update.message.reply_text(
                    f"No se encontró grupo para el servicio: {tipo_servicio}"
                )
        else:
            await update.message.reply_text("Servicio de Google Sheets no está disponible.")

    # ==================================================================
    # /generar_link - Generar link de invitación y enviar a usuario
    # ==================================================================

    async def generar_link_servicio(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Comando /generar_link - Genera un link de invitación para un grupo
        y lo envía a un usuario específico.

        Formato: /generar_link {tipo_servicio} {user_id}
        Ejemplo: /generar_link grupo_vip 123456789
        Ejemplo: /generar_link Stake 123456789

        Si no se especifica user_id, genera el link para quien ejecuta el comando.

        Args:
            update: Update de Telegram.
            context: Contexto de la conversación.
        """
        logger.info(f"/generar_link recibido: {update.message.text}")

        sender_id = int(update.message.chat.id)
        message_text = update.message.text
        data = message_text.split(" ")

        tipo_servicio = "grupo_vip"
        target_user_id = sender_id

        if len(data) >= 2:
            tipo_servicio = data[1]
        if len(data) >= 3:
            try:
                target_user_id = int(data[2])
            except ValueError:
                await update.message.reply_text(
                    "Formato incorrecto. Usar: /generar_link {tipo_servicio} {user_id}\n"
                    "Ejemplo: /generar_link grupo_vip 123456789"
                )
                return

        try:
            invite_link = await self._get_invite_link(
                context=context,
                tipo_servicio=tipo_servicio,
            )

            if not invite_link:
                await update.message.reply_text("No se pudo generar el link de invitación.")
                return

            # Enviar el link al usuario objetivo
            await context.bot.send_message(
                chat_id=target_user_id,
                text=(
                    f"🔗 <b>Link de invitación para {tipo_servicio}</b>\n\n"
                    f"{invite_link}\n\n"
                    f"⚠️ Este link es de un solo uso y expira en 24 horas."
                ),
                parse_mode="HTML",
            )

            # Confirmar al remitente
            if target_user_id != sender_id:
                await update.message.reply_text(
                    f"✅ Link enviado al usuario {target_user_id} para {tipo_servicio}"
                )

            logger.info(f"Link generado para {tipo_servicio} y enviado a user={target_user_id}: {invite_link}")
        except Exception as e:
            logger.error(f"Error al generar link: {e}", exc_info=True)
            await update.message.reply_text(f"Error al generar el link: {str(e)}")

    # ==================================================================
    # /delete - Marcar compra como estafa y expulsar del grupo VIP
    # ==================================================================

    async def delete_purchase(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """
        Comando /delete - Marca la última compra de un usuario como estafa.

        Formato: /delete {telegram_id}

        Flujo:
        1. Verifica que quien ejecuta el comando sea un validador autorizado.
        2. Busca la última compra activa del usuario indicado.
        3. Muestra la información de la compra al validador.
        4. Marca la compra como 'fraud' con nota de estafa.
        5. Si es VIP (service_id=2), expulsa al usuario del grupo VIP.
        6. Si es Stake (service_id=1), solo marca la compra (no se puede
           expulsar del grupo).
        7. Envía mensaje al usuario informando la eliminación.

        Args:
            update: Update de Telegram.
            context: Contexto de la conversación.
        """
        logger.info(f"/delete recibido: {update.message.text}")

        business_user_id = int(update.effective_user.id)

        if not self._payment_service.is_validator_authorized(business_user_id):
            await update.message.reply_text("⛔ No estás autorizado para usar este comando.")
            return

        message_text = update.message.text
        data = message_text.split(" ")

        if len(data) < 2:
            await update.message.reply_text(
                "Formato incorrecto. Usar:\n"
                "<code>/delete {telegram_id}</code>\n"
                "Ejemplo: <code>/delete 8158668298</code>",
                parse_mode="HTML",
            )
            return

        try:
            target_user_id = int(data[1])
        except ValueError:
            await update.message.reply_text("El ID de usuario debe ser un número.")
            return

        from core.database import SessionLocal
        from repositories.purchase_repo import PurchaseRepository

        session = SessionLocal()
        try:
            purchase_repo = PurchaseRepository(session)

            purchase = purchase_repo.get_last_active_purchase_by_user(target_user_id)

            if purchase is None:
                await update.message.reply_text(
                    f"No se encontró ninguna compra activa para el usuario {target_user_id}."
                )
                return

            service_name = SERVICES_NAMES_BY_ID.get(
                purchase.service_id, f"Servicio {purchase.service_id}"
            )
            purchase_date_str = purchase.purchase_date.strftime("%d/%m/%Y %H:%M") if purchase.purchase_date else "N/A"

            # Mostrar info de la compra al validador con botones de confirmación
            from utils.keyboards import delete_confirm_keyboard

            info_msg = (
                f"🔍 <b>Compra encontrada</b>\n\n"
                f"👤 <b>Usuario:</b> <code>{target_user_id}</code>\n"
                f"📦 <b>Servicio:</b> {service_name}\n"
                f"💵 <b>Monto:</b> S/ {purchase.price:.2f}\n"
                f"📅 <b>Fecha de compra:</b> {purchase_date_str}\n"
                f"🆔 <b>Compra ID:</b> {purchase.purchase_id}\n\n"
                f"⚠️ ¿Deseas marcar esta compra como inválida?"
            )
            await update.message.reply_text(
                info_msg,
                parse_mode="HTML",
                reply_markup=delete_confirm_keyboard(target_user_id, purchase.purchase_id),
            )
            return

        except Exception as e:
            logger.error(f"Error en /delete: {e}", exc_info=True)
            await update.message.reply_text(f"Error al procesar el comando: {str(e)}")
        finally:
            session.close()

    # ==================================================================
    # Métodos auxiliares
    # ==================================================================

    async def _get_invite_link(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        tipo_servicio: str,
    ) -> str:
        """
        Obtiene o genera un link de invitación para un tipo de servicio.

        Usa el bot de links (TELEGRAM_BOT_TOKEN_LINKS) que es admin en los
        grupos, ya que el bot principal no tiene permisos para gestionar links.

        Para Grupo VIP: crea un link temporal de un solo uso (expira en 24h).
        Para Stake: obtiene el ID del grupo desde Google Sheets y crea el link.

        Si no se puede generar con el bot de links, intenta con el bot principal
        y finalmente con el link por defecto.

        Args:
            context: Contexto de la conversación de Telegram.
            tipo_servicio: Tipo de servicio ("grupo_vip" o "Stake").

        Returns:
            URL del link de invitación.
        """
        import asyncio
        from datetime import timedelta

        from config.settings import settings
        from services.telegram_api import TelegramAPIService

        link_defecto_vip = settings.TELEGRAM_DEFAULT_VIP_LINK

        if tipo_servicio in ("grupo_vip", "Grupo VIP"):
            vip_group_id = int(settings.TELEGRAM_VIP_GROUP_ID)

            # 1) Intentar con el bot de links (admin en el grupo VIP)
            try:
                api = TelegramAPIService()
                invite_link = await asyncio.to_thread(
                    api.create_invite_link,
                    chat_id=vip_group_id,
                    member_limit=1,
                    name=f"Link para {tipo_servicio}",
                )
                if invite_link:
                    logger.info(f"Link VIP generado (bot de links): {invite_link}")
                    return invite_link.strip()
                logger.warning("Bot de links no devolvió link VIP; intentando bot principal.")
            except Exception as e:
                logger.error(f"Error al crear link VIP con bot de links: {e}")

            # 2) Fallback: bot principal
            try:
                generacion_link = await context.bot.create_chat_invite_link(
                    chat_id=vip_group_id,
                    expire_date=datetime.now() + timedelta(hours=24),
                    member_limit=1,
                    name=f"Link para {tipo_servicio}",
                )
                invite_link = generacion_link.invite_link.strip()
                logger.info(f"Link VIP generado (bot principal): {invite_link}")
                return invite_link
            except Exception as e:
                logger.error(f"No se pudo generar link VIP: {e}")
                if link_defecto_vip:
                    logger.info(f"Usando link por defecto VIP: {link_defecto_vip}")
                    return link_defecto_vip
                return None
        else:
            # Stake: el valor almacenado en la hoja "stake" (Google Sheets) YA es
            # el link de invitación. Se obtiene y se devuelve directamente, igual
            # que en la lógica original (sheets.get_service_id("stake")).
            # No se usa el link VIP por defecto: si falla, se devuelve None para
            # derivar al usuario a soporte.
            if self._sheets_service:
                try:
                    logger.info(f"Intentando obtener link de Stake desde Sheets (tipo_servicio='{tipo_servicio}')")
                    group_value = self._sheets_service.get_service_group_id("stake")
                    logger.info(f"Valor retornado por get_service_group_id('stake'): {group_value}")
                    if group_value:
                        group_value = group_value.strip()
                        logger.info(f"Link Stake desde Sheets: {group_value}")
                        return group_value
                    logger.warning("No se encontró link de Stake en Google Sheets (valor vacío o None).")
                    from services.telegram_api import send_error_notification
                    send_error_notification("No se encontró link de Stake en Google Sheets (hoja 'stake' vacía o no existe)")
                except Exception as e:
                    logger.error(f"Error al obtener link de Stake desde Sheets: {e}", exc_info=True)
                    from services.telegram_api import send_error_notification
                    send_error_notification(f"Error al obtener link de Stake desde Sheets: {e}")
            else:
                logger.error("sheets_service no está disponible en CommandHandlers")
                from services.telegram_api import send_error_notification
                send_error_notification("sheets_service no está disponible en CommandHandlers")

            logger.warning(f"No se pudo obtener link para {tipo_servicio}.")
            return None
