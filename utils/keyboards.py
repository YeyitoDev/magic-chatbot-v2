"""
Inline Keyboard Builders - Magic Chatbot v2
============================================
Constructores de teclados inline para Telegram. Todos retornan
InlineKeyboardMarkup listo para usar en respuestas del bot.

Principios:
- Builder Pattern: cada función construye y retorna un teclado completo.
- Composición: _build_keyboard como helper interno que convierte estructuras
  de diccionarios a objetos InlineKeyboardMarkup.
- Centralización: todos los teclados del bot se definen aquí para mantener
  consistencia visual y facilitar cambios.

Teclados incluidos:
- Calendario interactivo (CalendarKeyboard).
- Validación de pago (payment_validation_keyboard).
- Selección de servicio (service_selection_keyboard).
- Confirmación manual de servicio (service_confirmation_keyboard).
- Menú principal (main_menu_keyboard).
- Promoción Betsafe (betsafe_promo_keyboard).
- Preguntas frecuentes (faq_keyboard).
- Compra de servicio (buy_service_keyboard).

Uso:
    from utils.keyboards import main_menu_keyboard, CalendarKeyboard

    await bot.send_message(
        chat_id=user_id,
        text="Bienvenido al menú principal:",
        reply_markup=main_menu_keyboard(),
    )
"""

import calendar as cal_module
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# ============================================================================
# Helper interno
# ============================================================================

def _build_keyboard(buttons: list[list[dict]]) -> InlineKeyboardMarkup:
    """
    Construye un InlineKeyboardMarkup a partir de una estructura declarativa.

    Formato de entrada:
        [
            [{"text": "Botón 1", "callback_data": "action_1"}],
            [
                {"text": "Sí", "callback_data": "yes"},
                {"text": "No", "callback_data": "no"},
            ],
        ]

    Cada fila es una lista de diccionarios. Cada diccionario puede tener:
    - text: str (requerido) - Texto visible del botón.
    - callback_data: str (opcional) - Data enviada al presionar.
    - url: str (opcional) - URL para abrir en navegador.
    - web_app: WebAppInfo (opcional) - Mini app de Telegram.

    Args:
        buttons: Estructura de botones organizada por filas.

    Returns:
        InlineKeyboardMarkup listo para usar en reply_markup.
    """
    keyboard: list = []
    for row in buttons:
        keyboard_row: list = []
        for btn in row:
            keyboard_row.append(
                InlineKeyboardButton(
                    text=btn["text"],
                    callback_data=btn.get("callback_data"),
                    url=btn.get("url"),
                    web_app=btn.get("web_app"),
                )
            )
        keyboard.append(keyboard_row)
    return InlineKeyboardMarkup(keyboard)


# ============================================================================
# Menú Principal
# ============================================================================

def main_menu_keyboard() -> InlineKeyboardMarkup:
    """
    Teclado del menú principal del bot Magic.

    Es el primer teclado que ve el usuario al iniciar el bot.
    Ofrece las opciones principales de navegación.

    Returns:
        InlineKeyboardMarkup con el menú principal.
    """
    buttons = [
        [
            {"text": "🎯 Grupo VIP", "callback_data": "consulta_tipo_servicio:Grupo VIP"},
        ],
        [
            {"text": "🎲 Stake", "callback_data": "consulta_tipo_servicio:Stake"},
        ],
        [
            {"text": "ℹ️ Información", "callback_data": "informacion_servicio:general"},
            {"text": "❓ Preguntas Frecuentes", "callback_data": "consulta_tipo_servicio:preguntas_frecuentes"},
        ],
    ]
    return _build_keyboard(buttons)


def main_menu_don_gato_keyboard() -> InlineKeyboardMarkup:
    """
    Versión alternativa del menú principal (estilo Don Gato).

    Incluye solo 3 opciones: Comprar VIP, Comprar Stake, Preguntas Frecuentes.

    Returns:
        InlineKeyboardMarkup con el menú estilo Don Gato.
    """
    buttons = [
        [
            {"text": "🔥 COMPRAR GRUPO VIP", "callback_data": "comprar_servicio:si:Grupo VIP"},
        ],
        [
            {"text": "🎲 COMPRAR STAKE", "callback_data": "comprar_servicio:si:Stake"},
        ],
        [
            {"text": "❓ PREGUNTAS FRECUENTES", "callback_data": "preguntas_frecuentes:general"},
        ],
    ]
    return _build_keyboard(buttons)


# ============================================================================
# Selección de Servicio
# ============================================================================

def service_selection_keyboard() -> InlineKeyboardMarkup:
    """
    Teclado para que el usuario seleccione el tipo de servicio.

    Se muestra después de que el usuario expresa interés en comprar.

    Returns:
        InlineKeyboardMarkup con opciones de servicios.
    """
    buttons = [
        [
            {"text": "🎯 Grupo VIP", "callback_data": "consulta_tipo_servicio:Grupo VIP"},
        ],
        [
            {"text": "🎲 Stake Máxima Seguridad", "callback_data": "consulta_tipo_servicio:Stake"},
        ],
        [
            {"text": "🔙 Regresar al Menú", "callback_data": "regresar_menu_principal:si"},
        ],
    ]
    return _build_keyboard(buttons)


def buy_service_keyboard(service_type: str) -> InlineKeyboardMarkup:
    """
    Teclado de confirmación de compra para un servicio específico.

    Args:
        service_type: Tipo de servicio seleccionado ("Grupo VIP" o "Stake").

    Returns:
        InlineKeyboardMarkup con opciones de compra.
    """
    buttons = [
        [
            {"text": "✅ SÍ, COMPRAR", "callback_data": f"comprar_servicio:si:{service_type}"},
        ],
        [
            {"text": "❌ NO, GRACIAS", "callback_data": f"comprar_servicio:no:{service_type}"},
        ],
        [
            {"text": "🔙 Regresar", "callback_data": "regresar_menu_principal:si"},
        ],
    ]
    return _build_keyboard(buttons)


# ============================================================================
# Información de Servicios
# ============================================================================

def service_info_keyboard(service_type: str) -> InlineKeyboardMarkup:
    """
    Teclado con opciones de información detallada de un servicio.

    Args:
        service_type: Tipo de servicio ("Grupo VIP", "Stake", o "general").

    Returns:
        InlineKeyboardMarkup con opciones de info y compra.
    """
    if service_type == "Grupo VIP":
        callback_data = "informacion_servicio:Grupo VIP"
    elif service_type == "Stake":
        callback_data = "informacion_servicio:Stake"
    else:
        callback_data = "informacion_servicio:general"

    buttons = [
        [
            {"text": "🛒 COMPRAR AHORA", "callback_data": f"comprar_servicio:si:{service_type}"},
        ],
        [
            {"text": "ℹ️ MÁS INFORMACIÓN", "callback_data": callback_data},
        ],
        [
            {"text": "🔙 Regresar al Menú", "callback_data": "regresar_menu_principal:si"},
        ],
    ]
    return _build_keyboard(buttons)


# ============================================================================
# Preguntas Frecuentes (FAQ)
# ============================================================================

def faq_keyboard() -> InlineKeyboardMarkup:
    """
    Teclado de preguntas frecuentes con opciones simplificadas.

    Returns:
        InlineKeyboardMarkup con opciones de FAQ.
    """
    buttons = [
        [
            {"text": "💎 ¿Qué es el Grupo VIP?", "callback_data": "preguntas_frecuentes:grupo_vip"},
        ],
        [
            {"text": "🎲 ¿Qué es el Stake?", "callback_data": "preguntas_frecuentes:stake"},
        ],
        [
            {"text": "🔙 Regresar al Menú", "callback_data": "regresar_menu_principal:si"},
        ],
    ]
    return _build_keyboard(buttons)


def faq_video_keyboard(service: str) -> InlineKeyboardMarkup:
    """
    Teclado mostrado después de la respuesta de FAQ con opción de compra.

    Args:
        service: Tipo de servicio sobre el que se preguntó.

    Returns:
        InlineKeyboardMarkup con opción de compra y regreso al menú.
    """
    buttons = [
        [
            {"text": "🛒 COMPRAR", "callback_data": f"comprar_servicio:si:{service}"},
        ],
        [
            {"text": "🔙 Regresar al Menú", "callback_data": "regresar_menu_principal:si"},
        ],
    ]
    return _build_keyboard(buttons)


# ============================================================================
# Validación de Pago
# ============================================================================

def payment_validation_keyboard(
    user_id: int,
    amount: float,
    source: str = "telegram",
    extra_data: str | None = None,
    is_valid_price: bool = True,
) -> InlineKeyboardMarkup:
    """
    Teclado de validación de pago para el usuario validador (admin).

    Presenta opciones para que el validador apruebe, rechace
    o indique que el monto es incorrecto.

    Si el monto no corresponde a un precio definido, oculta el botón
    de aprobación y obliga al validador a ingresar el monto manualmente.

    Args:
        user_id: ID de Telegram del usuario que envió el comprobante.
        amount: Monto detectado en el comprobante.
        source: Canal de procedencia ("telegram" o "wsp").
        extra_data: Datos adicionales (fecha extraída, etc.).
        is_valid_price: Si True, muestra botón de aprobación. Si False,
            solo permite rechazar o ingresar monto manual.

    Returns:
        InlineKeyboardMarkup con botones de acción de validación.
    """
    # Convert amount to int to avoid ".0" in callback_data (prices are whole soles)
    amount_int = int(amount)

    # Format extra_data: parse any date format, convert to ddmmyyyy (compact, no separators)
    # This ensures callback_data stays under Telegram's 64-byte limit
    extra = ""
    if extra_data:
        raw = extra_data.strip()
        parsed = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%d%m%Y", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
        if parsed:
            extra = parsed.strftime("%d%m%Y")
        else:
            extra = raw.replace("/", "").replace(" ", "").replace(":", "")[:8]

    # Build callback_data, only appending :extra if non-empty
    if extra:
        cb_valid = f"validar_monto:valid:{user_id}:{amount_int}:{extra}"
        cb_not_valid = f"validar_monto:not_valid:{user_id}:{amount_int}:{extra}"
        cb_monto = f"validar_monto:monto_no_reconocido:{user_id}:{amount_int}:{extra}"
    else:
        cb_valid = f"validar_monto:valid:{user_id}:{amount_int}"
        cb_not_valid = f"validar_monto:not_valid:{user_id}:{amount_int}"
        cb_monto = f"validar_monto:monto_no_reconocido:{user_id}:{amount_int}"

    if is_valid_price:
        buttons = [
            [
                {
                    "text": "✅ PAGO VALIDADO",
                    "callback_data": cb_valid,
                }
            ],
            [
                {
                    "text": "❌ PAGO NO VALIDADO",
                    "callback_data": cb_not_valid,
                }
            ],
            [
                {
                    "text": "🔵 VALIDAR MONTO DE PAGO",
                    "callback_data": cb_monto,
                }
            ],
        ]
    else:
        # Monto no reconocido: obligar al validador a ingresar monto manual
        buttons = [
            [
                {
                    "text": "❌ PAGO NO VALIDADO",
                    "callback_data": cb_not_valid,
                }
            ],
            [
                {
                    "text": "✏️ INGRESAR MONTO MANUAL",
                    "callback_data": cb_monto,
                }
            ],
        ]
    return _build_keyboard(buttons)


def payment_validation_wsp_keyboard(
    user_id: int,
    amount: float,
) -> InlineKeyboardMarkup:
    """
    Teclado de validación para pagos provenientes de WhatsApp (WSP).

    Similar al de Telegram pero con el marcador ':wsp' en el callback_data
    para indicar el canal de procedencia.

    Args:
        user_id: ID de Telegram del usuario.
        amount: Monto detectado.

    Returns:
        InlineKeyboardMarkup para validación de pagos WSP.
    """
    # Convert amount to int to avoid ".0" in callback_data (prices are whole soles)
    amount_int = int(amount)

    buttons = [
        [
            {
                "text": "✅ PAGO VALIDADO",
                "callback_data": f"validar_monto:valid:{user_id}:{amount_int}:wsp",
            }
        ],
        [
            {
                "text": "❌ PAGO NO VALIDADO",
                "callback_data": f"validar_monto:not_valid:{user_id}:{amount_int}:wsp",
            }
        ],
        [
            {
                "text": "🔵 VALIDAR MONTO DE PAGO",
                "callback_data": f"validar_monto:monto_no_reconocido:{user_id}:{amount_int}:wsp",
            }
        ],
    ]
    return _build_keyboard(buttons)


# ============================================================================
# Confirmación Manual de Servicio (Validador - monto no reconocido)
# ============================================================================

def service_confirmation_keyboard(
    user_id: int,
    monto: float,
    message_id: int = 0,
    source: str = "telegram",
) -> InlineKeyboardMarkup:
    """
    Teclado para el validador cuando el sistema no reconoce el monto exacto.

    Permite al validador confirmar manualmente a qué servicio y plan
    corresponde el pago recibido.

    Args:
        user_id: ID de Telegram del usuario que envió el pago.
        monto: Monto detectado (o ingresado manualmente).
        message_id: ID del mensaje original para referencia.
        source: Canal de procedencia.

    Returns:
        InlineKeyboardMarkup con opciones de confirmación manual.
    """
    buttons = [
        [
            {
                "text": "🎯 STAKE (S/ 50)",
                "callback_data": f"buttom_validar_monto:select:{user_id}:{50}",
            }
        ],
        [
            {
                "text": "💎 VIP 1 Mes (S/ 125)",
                "callback_data": f"buttom_validar_monto:select:{user_id}:{125}",
            },
        ],
        [
            {
                "text": "💎 VIP 2 Meses (S/ 175)",
                "callback_data": f"buttom_validar_monto:select:{user_id}:{175}",
            },
        ],
        [
            {
                "text": "💎 VIP 3 Meses (S/ 225)",
                "callback_data": f"buttom_validar_monto:select:{user_id}:{225}",
            },
        ],
    ]
    return _build_keyboard(buttons)


# ============================================================================
# Post-Compra
# ============================================================================

def post_purchase_keyboard(
    invite_link: str,
    betsafe_link: str = "https://bit.ly/promobetsafemagic",
) -> InlineKeyboardMarkup:
    """
    Teclado mostrado al usuario después de una compra exitosa.

    Incluye el link de invitación al grupo y la promoción de Betsafe.

    Args:
        invite_link: Link de invitación al grupo (VIP o Stake).
        betsafe_link: Link promocional de Betsafe.

    Returns:
        InlineKeyboardMarkup con links post-compra.
    """
    buttons = [
        [
            {"text": "🚀 UNIRME AL GRUPO", "url": invite_link},
        ],
        [
            {
                "text": "🎁 RECLAMAR BONO S/ 70 GRATIS",
                "url": betsafe_link,
            },
        ],
        [
            {"text": "🔙 Volver al Menú", "callback_data": "regresar_menu_principal:si"},
        ],
    ]
    return _build_keyboard(buttons)


# ============================================================================
# Promoción Betsafe
# ============================================================================

def betsafe_promo_keyboard(
    promo_link: str = "https://bit.ly/promobetsafemagic",
    button_text: str = "¡OBTÉN TUS 70 SOLES GRATIS!",
) -> InlineKeyboardMarkup:
    """
    Teclado con el botón promocional de Betsafe.

    Args:
        promo_link: URL del enlace de afiliado de Betsafe.
        button_text: Texto visible del botón.

    Returns:
        InlineKeyboardMarkup con el botón de Betsafe.
    """
    buttons = [
        [
            {"text": button_text, "url": promo_link},
        ]
    ]
    return _build_keyboard(buttons)


def betsafe_video_keyboard(
    promo_link: str = "https://bit.ly/promobetsafemagic",
    button_text: str = "¡OBTÉN TUS 70 SOLES GRATIS!",
) -> InlineKeyboardMarkup:
    """
    Teclado inline para acompañar videos promocionales de Betsafe.

    Se usa en el pipeline de promociones (DynamoDB) para enviar
    videos con un botón de CTA (Call To Action).

    Args:
        promo_link: URL del enlace de afiliado.
        button_text: Texto del botón CTA.

    Returns:
        InlineKeyboardMarkup para videos promocionales.
    """
    return betsafe_promo_keyboard(promo_link, button_text)


# ============================================================================
# Post-Validación (Validador)
# ============================================================================

def post_validation_keyboard() -> InlineKeyboardMarkup:
    """
    Teclado mostrado al validador después de procesar una validación.

    Ofrece opciones para volver al menú o revisar otras validaciones.

    Returns:
        InlineKeyboardMarkup con opciones post-validación.
    """
    buttons = [
        [
            {"text": "✅ Entendido", "callback_data": "regresar_menu_principal:si"},
        ],
    ]
    return _build_keyboard(buttons)


# ============================================================================
# Restricción por Duplicado
# ============================================================================

def duplicate_purchase_restriction_keyboard(
    service_type: str,
) -> InlineKeyboardMarkup:
    """
    Teclado mostrado al usuario cuando se detecta una compra duplicada.

    Informa que ya tiene una compra reciente y ofrece opciones.

    Args:
        service_type: Tipo de servicio de la compra duplicada.

    Returns:
        InlineKeyboardMarkup con opciones para el usuario.
    """
    buttons = [
        [
            {"text": "📲 Contactar Soporte", "url": "https://t.me/magic_peru"},
        ],
        [
            {"text": "🔙 Volver al Menú", "callback_data": "regresar_menu_principal:si"},
        ],
    ]
    return _build_keyboard(buttons)


# ============================================================================
# Recordatorio de Compra
# ============================================================================

def reminder_keyboard() -> InlineKeyboardMarkup:
    """
    Teclado para mensajes de recordatorio de compra pendiente.

    Incluye un CTA directo para comprar y opción de ignorar.

    Returns:
        InlineKeyboardMarkup para recordatorios.
    """
    buttons = [
        [
            {"text": "🛒 COMPRAR AHORA", "callback_data": "consulta_tipo_servicio:Grupo VIP"},
        ],
        [
            {"text": "🔙 Menú Principal", "callback_data": "regresar_menu_principal:si"},
        ],
    ]
    return _build_keyboard(buttons)


# ============================================================================
# Suscripción Vencida
# ============================================================================

def expired_subscription_keyboard() -> InlineKeyboardMarkup:
    """
    Teclado mostrado a usuarios con suscripción vencida.

    Les informa que su suscripción expiró y les invita a renovar.

    Returns:
        InlineKeyboardMarkup con opciones de renovación.
    """
    buttons = [
        [
            {"text": "🔄 RENOVAR SUSCRIPCIÓN", "callback_data": "consulta_tipo_servicio:Grupo VIP"},
        ],
        [
            {"text": "📲 Contactar Soporte", "url": "https://t.me/magic_peru"},
        ],
    ]
    return _build_keyboard(buttons)


# ============================================================================
# Calendario Interactivo
# ============================================================================

class CalendarKeyboard:
    """
    Constructor de calendario interactivo inline para selección de fechas.

    Permite a los usuarios seleccionar una fecha navegando por meses
    mediante botones inline de Telegram. El callback_data incluye
    toda la información necesaria para procesar la selección.

    Atributos:
        months_es: Nombres de meses en español.
        days_es: Abreviaturas de días en español (L, M, X, J, V, S, D).

    Uso:
        cal = CalendarKeyboard()
        markup = cal.crear_calendario(user_id=123456, message_id=789)
        await bot.send_message(chat_id, "Selecciona una fecha:", reply_markup=markup)
    """

    def __init__(self) -> None:
        """Inicializa el calendario con localización en español."""
        self.months_es: list[str] = [
            "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
            "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
        ]
        self.days_es: list[str] = ["L", "M", "X", "J", "V", "S", "D"]

    def crear_calendario(
        self,
        year: int | None = None,
        month: int | None = None,
        user_id: int | None = None,
        message_id: int | None = None,
    ) -> InlineKeyboardMarkup:
        """
        Crea un calendario interactivo para seleccionar una fecha.

        Args:
            year: Año a mostrar (por defecto: año actual).
            month: Mes a mostrar (1-12, por defecto: mes actual).
            user_id: ID de usuario Telegram para incluir en callback_data.
            message_id: ID del mensaje para incluir en callback_data.

        Returns:
            InlineKeyboardMarkup con el calendario completo del mes.
        """
        now: datetime = datetime.now()
        year = year or now.year
        month = month or now.month

        keyboard: list = []

        # --- Navegación de mes (◀ Mes Año ▶) ---
        keyboard.append([
            InlineKeyboardButton(
                "◀️",
                callback_data=f"cal_prev:{year}:{month}:{user_id}:{message_id}",
            ),
            InlineKeyboardButton(
                f"{self.months_es[month - 1]} {year}",
                callback_data="cal_ignore",
            ),
            InlineKeyboardButton(
                "▶️",
                callback_data=f"cal_next:{year}:{month}:{user_id}:{message_id}",
            ),
        ])

        # --- Días de la semana (L M X J V S D) ---
        keyboard.append([
            InlineKeyboardButton(day, callback_data="cal_ignore")
            for day in self.days_es
        ])

        # --- Días del mes ---
        cal: list = cal_module.monthcalendar(year, month)
        for week in cal:
            row: list = []
            for day in week:
                if day == 0:
                    # Día fuera del mes (espacio vacío)
                    row.append(
                        InlineKeyboardButton(" ", callback_data="cal_ignore")
                    )
                else:
                    # Marcar el día actual con un círculo
                    if (
                        year == now.year
                        and month == now.month
                        and day == now.day
                    ):
                        button_text = f"🔘{day}"
                    else:
                        button_text = str(day)

                    row.append(
                        InlineKeyboardButton(
                            button_text,
                            callback_data=(
                                f"cal_select:{year}:{month:02d}:{day:02d}:"
                                f"{user_id}:{message_id}"
                            ),
                        )
                    )
            keyboard.append(row)

        # --- Botones inferiores: HOY y CANCELAR ---
        keyboard.append([
            InlineKeyboardButton(
                "📅 HOY",
                callback_data=f"cal_today:{user_id}:{message_id}",
            ),
            InlineKeyboardButton(
                "❌ CANCELAR",
                callback_data=f"cal_cancel:{user_id}:{message_id}",
            ),
        ])

        return InlineKeyboardMarkup(keyboard)

    @staticmethod
    def obtener_mes_siguiente(year: int, month: int) -> tuple:
        """
        Calcula el año y mes siguiente para la navegación.

        Args:
            year: Año actual.
            month: Mes actual (1-12).

        Returns:
            Tupla (year, month) del mes siguiente.
        """
        if month == 12:
            return year + 1, 1
        return year, month + 1

    @staticmethod
    def obtener_mes_anterior(year: int, month: int) -> tuple:
        """
        Calcula el año y mes anterior para la navegación.

        Args:
            year: Año actual.
            month: Mes actual (1-12).

        Returns:
            Tupla (year, month) del mes anterior.
        """
        if month == 1:
            return year - 1, 12
        return year, month - 1


# ============================================================================
# Confirmación de eliminación por estafa (/delete)
# ============================================================================

def delete_confirm_keyboard(target_user_id: int, purchase_id: int) -> InlineKeyboardMarkup:
    """
    Teclado inline con motivos para marcar una compra como inválida.

    Args:
        target_user_id: ID de Telegram del usuario cuya compra se va a marcar.
        purchase_id: ID de la compra a marcar.

    Returns:
        InlineKeyboardMarkup con botones de motivos y cancelar.
    """
    buttons = [
        [
            {
                "text": "🔁 Venta duplicada",
                "callback_data": f"delete_confirm:{target_user_id}:{purchase_id}:duplicada",
            },
        ],
        [
            {
                "text": "🎭 Estafa",
                "callback_data": f"delete_confirm:{target_user_id}:{purchase_id}:estafa",
            },
        ],
        [
            {
                "text": "📝 Otros",
                "callback_data": f"delete_confirm:{target_user_id}:{purchase_id}:otros",
            },
        ],
        [
            {
                "text": "❌ Cancelar",
                "callback_data": f"delete_cancel:{target_user_id}:{purchase_id}",
            },
        ],
    ]
    return _build_keyboard(buttons)
