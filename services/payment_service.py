"""
Payment Service - Magic Chatbot v2
===================================
Servicio de dominio para la validación y procesamiento de pagos.

Orquesta el flujo completo de validación:
1. Detecta duplicados (misma compra en últimas 24h).
2. Procesa la decisión del validador (validar, rechazar, monto incorrecto).
3. Coordina con SubscriptionService para registrar la compra.
4. Retorna resultados estructurados para que los handlers respondan al usuario.

Principios:
- Single Responsibility: solo lógica de validación de pagos.
- Dependency Inversion: depende de abstracciones (repos, services).
- Fail-fast: valida condiciones al inicio y retorna errores descriptivos.

Uso:
    from services.payment_service import PaymentService

    service = PaymentService(purchase_repo, subscription_service, user_repo)
    result = service.validate_payment(
        telegram_id=12345, amount=150.0,
        from_channel="telegram", purchase_date="15012025"
    )
"""

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# IDs de servicio (consistentes con la tabla services)
STAKE_SERVICE_ID = 1
VIP_SERVICE_ID = 2


def voucher_payment_ref(message) -> str | None:
    """
    Clave de idempotencia de un comprobante a partir del mensaje con la foto.

    Usa ``file_unique_id``, que Telegram mantiene igual para el mismo archivo
    aunque se reenvíe a varios validadores. Si el mensaje no tiene foto, busca
    en el mensaje al que responde. None si no hay foto.
    """
    for candidate in (message, getattr(message, "reply_to_message", None)):
        photo = getattr(candidate, "photo", None) if candidate is not None else None
        if photo:
            return f"tg:{photo[-1].file_unique_id}"
    return None


# ---------------------------------------------------------------------------
# Value Objects
# ---------------------------------------------------------------------------

@dataclass
class ValidationResult:
    """
    Resultado de una operación de validación de pago.

    Attributes:
        success: True si la validación fue exitosa.
        message: Mensaje descriptivo para el usuario o para logs.
        action: Acción ejecutada ('valid', 'reject', 'incorrect_amount').
        service_type: Tipo de servicio determinado ('stake', 'grupo_vip').
        is_duplicate: True si se detectó compra duplicada.
        purchase_result: PurchaseResult del registro de compra (si success=True).
        invite_link: Link de invitación al grupo (opcional).
        errors: Lista de errores encontrados.
    """
    success: bool = False
    message: str = ""
    action: str = ""
    service_type: str = ""
    is_duplicate: bool = False
    purchase_result: Any = None
    invite_link: str | None = None
    errors: list[str] = field(default_factory=list)


@dataclass
class ValidationAction:
    """
    Representa la acción tomada por un validador sobre un pago.

    Attributes:
        action: Tipo de acción ('valid', 'reject', 'incorrect_amount').
        validator_id: ID de Telegram del validador que ejecutó la acción.
        target_user_id: ID de Telegram del usuario cuyo pago se valida.
        amount: Monto validado.
        source: Canal de procedencia del pago ('telegram', 'whatsapp', 'wsp').
        message_id: ID del mensaje original de validación.
        extra_data: Datos adicionales (fecha extraída, etc.).
    """
    action: str
    validator_id: int
    target_user_id: int
    amount: float
    source: str = "telegram"
    message_id: int | None = None
    extra_data: str | None = None


# ---------------------------------------------------------------------------
# Payment Service
# ---------------------------------------------------------------------------

class PaymentService:
    """
    Servicio de lógica de negocio para validación de pagos.

    Coordina el flujo de validación:
    1. Verificar duplicados.
    2. Procesar la acción del validador.
    3. Registrar la compra si es aprobada.

    Dependencias:
        purchase_repo: PurchaseRepository para búsqueda de duplicados.
        subscription_service: SubscriptionService para procesar compras.
        user_repo: UserRepository para búsqueda de usuarios.
    """

    def __init__(self, purchase_repo, subscription_service, user_repo, pricing_service=None):
        """
        Inicializa el servicio con sus dependencias.

        Args:
            purchase_repo: Repositorio de compras.
            subscription_service: Servicio de suscripciones/compra.
            user_repo: Repositorio de usuarios.
            pricing_service: Servicio de precios dinámico (opcional). Si se
                provee, se usa para validar que el monto corresponda a un
                precio definido en el catálogo.
        """
        self._purchase_repo = purchase_repo
        self._subscription_service = subscription_service
        self._user_repo = user_repo
        self._pricing_service = pricing_service

    # ------------------------------------------------------------------
    # Validación de monto contra el catálogo de precios
    # ------------------------------------------------------------------

    def is_defined_price(self, amount: float) -> bool:
        """
        Indica si el monto corresponde a un precio definido en el catálogo.

        Si no hay PricingService configurado, no se puede restringir y se
        asume válido (comportamiento legacy). Ante un error del catálogo,
        también se asume válido (fail-safe) para no bloquear ventas legítimas.

        Args:
            amount: Monto a verificar.

        Returns:
            True si el monto está definido (o no se puede validar), False si
            el catálogo existe y el monto no coincide con ningún precio.
        """
        if self._pricing_service is None:
            return True
        try:
            return self._pricing_service.match_price(amount) is not None
        except Exception as e:
            logger.warning(
                f"No se pudo validar el monto S/ {amount:.2f} contra el "
                f"catálogo de precios: {e}"
            )
            return True

    def _resolve_service_id(self, amount: float) -> int | None:
        """
        Resuelve el ID de servicio correspondiente a un monto vía catalogo.

        Returns:
            service_id (1=Stake, 2=Grupo VIP) o None si no se puede resolver
            (sin PricingService o monto no definido).
        """
        if self._pricing_service is None:
            return None
        try:
            plan = self._pricing_service.match_price(amount)
            return plan.service_id if plan else None
        except Exception as e:
            logger.warning(
                f"No se pudo resolver el servicio para el monto S/ {amount:.2f}: {e}"
            )
            return None

    # ------------------------------------------------------------------
    # Validación de pago
    # ------------------------------------------------------------------

    def validate_payment(
        self,
        telegram_id: int,
        amount: float,
        from_channel: str = "telegram",
        purchase_date: str | None = None,
        payment_ref: str | None = None,
    ) -> ValidationResult:
        """
        Valida un pago antes de procesarlo.

        Realiza las siguientes verificaciones:
        1. Verifica que el monto sea positivo.
        2. Verifica que el usuario exista.
        3. Verifica duplicados (misma compra en últimas 24h).
        4. Si todo OK, procesa la compra a través de SubscriptionService.

        Args:
            telegram_id: ID de Telegram del comprador.
            amount: Monto pagado.
            from_channel: Canal de origen del pago.
            purchase_date: Fecha de compra en formato ddmmyyyy (opcional).

        Returns:
            ValidationResult con el resultado de la validación.
        """

        # Validación 1: Monto positivo
        if amount <= 0:
            return ValidationResult(
                success=False,
                message="El monto debe ser mayor a S/ 0.",
                errors=["negative_amount"],
            )

        # Validación 2: Usuario existe
        user = self._user_repo.get_by_telegram_id(telegram_id)
        if user is None:
            return ValidationResult(
                success=False,
                message="Usuario no encontrado en la base de datos.",
                errors=["user_not_found"],
            )

        # Validación 3: El monto debe corresponder a un precio definido
        if not self.is_defined_price(amount):
            return ValidationResult(
                success=False,
                message=(
                    f"El monto S/ {amount:.2f} no corresponde a ningún precio "
                    f"definido. Ingrese el monto correcto."
                ),
                errors=["undefined_price"],
            )

        # Validación 4: Reglas de frecuencia de compra
        #   - Stake: sin restricción de duplicados (permitido múltiples compras)
        #   - VIP: ilimitado (cada compra renueva/extiende la suscripción).
        # No se aplica restricción de duplicados para ningún servicio

        # Validación 4: Procesar la compra
        try:
            purchase_result = self._subscription_service.process_purchase(
                telegram_id=telegram_id,
                price=amount,
                from_channel=from_channel,
                purchase_date=purchase_date,
                payment_ref=payment_ref,
            )

            if purchase_result.success:
                return ValidationResult(
                    success=True,
                    message=purchase_result.message,
                    action="valid",
                    service_type=purchase_result.service_type,
                    purchase_result=purchase_result,
                )
            else:
                return ValidationResult(
                    success=False,
                    message=purchase_result.message,
                    is_duplicate=purchase_result.is_duplicate,
                    errors=purchase_result.errors,
                )
        except Exception as e:
            logger.error(
                f"Error al procesar compra para user={telegram_id}: {e}",
                exc_info=True,
            )
            return ValidationResult(
                success=False,
                message=f"Error interno al procesar la compra: {str(e)}",
                errors=["internal_error", str(e)],
            )

    # ------------------------------------------------------------------
    # Detección de duplicados
    # ------------------------------------------------------------------

    def check_duplicate_payment(
        self,
        telegram_id: int,
        amount: float,
        hours: int = 24,
    ) -> bool:
        """
        Verifica si ya existe una compra duplicada en las últimas N horas.

        Estrategia anti-duplicados: si un usuario envía la misma captura
        de pago dos veces en menos de `hours` horas, se detecta como
        duplicado y se evita reprocesar.

        Args:
            telegram_id: ID de Telegram del comprador.
            amount: Monto exacto pagado.
            hours: Ventana de tiempo en horas (default: 24).

        Returns:
            True si existe un duplicado/límite alcanzado, False si no.
        """
        service_id = self._resolve_service_id(amount)

        # VIP: ilimitado. Cada compra renueva/extiende la suscripción,
        # por lo que nunca se considera duplicado.
        if service_id == VIP_SERVICE_ID:
            return False

        # Stake: máximo 1 por día (por service_id, sin importar el monto).
        if service_id == STAKE_SERVICE_ID:
            purchases = self._purchase_repo.get_recent_purchases_for_service(
                user_id=telegram_id,
                service_id=STAKE_SERVICE_ID,
                hours=hours,
            )
            if purchases:
                logger.info(
                    f"Límite diario de Stake alcanzado: user={telegram_id}, "
                    f"compras_encontradas={len(purchases)}"
                )
                return True
            return False

        # Sin catálogo / servicio desconocido: fallback legacy por monto exacto.
        purchases = self._purchase_repo.get_recent_purchases(
            user_id=telegram_id,
            amount=amount,
            hours=hours,
        )
        if purchases:
            logger.info(
                f"Compra duplicada detectada: user={telegram_id}, "
                f"amount={amount}, compras_encontradas={len(purchases)}"
            )
            return True
        return False

    def get_recent_purchase_info(
        self,
        telegram_id: int,
        amount: float,
    ) -> dict[str, Any] | None:
        """
        Obtiene información de la compra duplicada más reciente.

        Útil para mostrar al usuario o al validador los detalles
        de la compra que ya fue registrada.

        Args:
            telegram_id: ID de Telegram del comprador.
            amount: Monto pagado.

        Returns:
            Diccionario con info de la compra duplicada, o None si no existe.
        """
        service_id = self._resolve_service_id(amount)

        # Para Stake usamos la búsqueda por servicio (consistente con el
        # límite diario); en otros casos, por monto exacto.
        if service_id == STAKE_SERVICE_ID:
            purchases = self._purchase_repo.get_recent_purchases_for_service(
                user_id=telegram_id,
                service_id=STAKE_SERVICE_ID,
                hours=24,
            )
        else:
            purchases = self._purchase_repo.get_recent_purchases(
                user_id=telegram_id,
                amount=amount,
                hours=24,
            )
        if not purchases:
            return None

        last_purchase = purchases[0]  # La más reciente (orden desc)
        return {
            "purchase_id": last_purchase.purchase_id,
            "purchase_date": last_purchase.purchase_date,
            "service_id": last_purchase.service_id,
            "price": last_purchase.price,
            "from_channel": last_purchase.from_channel,
        }

    # ------------------------------------------------------------------
    # Procesamiento de la acción del validador
    # ------------------------------------------------------------------

    def process_validation_action(
        self,
        action: ValidationAction,
    ) -> ValidationResult:
        """
        Procesa la acción de validación ejecutada por un validador.

        Este método se llama cuando un validador presiona uno de los botones
        de validación (✅ Validar, ❌ Rechazar, 🔵 Monto incorrecto).

        Args:
            action: Objeto ValidationAction con los datos de la acción.

        Returns:
            ValidationResult con el resultado según el tipo de acción:

            - 'valid': Procesa la compra y retorna success.
            - 'reject': Retorna mensaje de rechazo.
            - 'incorrect_amount': Retorna indicación de monto no reconocido.
        """
        logger.info(
            f"Procesando acción de validador: action={action.action}, "
            f"validator={action.validator_id}, "
            f"target_user={action.target_user_id}, "
            f"amount={action.amount}, source={action.source}"
        )

        if action.action == "valid":
            return self.validate_payment(
                telegram_id=action.target_user_id,
                amount=action.amount,
                from_channel=action.source,
                purchase_date=action.extra_data,
            )

        elif action.action == "reject":
            return ValidationResult(
                success=False,
                message=(
                    f"Pago rechazado por el validador {action.validator_id}. "
                    f"Monto: S/ {action.amount:.2f}"
                ),
                action="reject",
                errors=["rejected_by_validator"],
            )

        elif action.action == "incorrect_amount":
            return ValidationResult(
                success=False,
                message=(
                    f"Monto no reconocido por el validador {action.validator_id}. "
                    f"Monto detectado: S/ {action.amount:.2f}. "
                    f"Se requiere confirmación manual del monto correcto."
                ),
                action="incorrect_amount",
                errors=["incorrect_amount"],
            )

        else:
            return ValidationResult(
                success=False,
                message=f"Acción de validación no reconocida: '{action.action}'",
                errors=["unknown_action"],
            )

    # ------------------------------------------------------------------
    # Construcción de mensajes para validación
    # ------------------------------------------------------------------

    def build_validation_message(
        self,
        telegram_id: int,
        telegram_name: str,
        amount: float,
        extracted_date: str | None = None,
    ) -> str:
        """
        Construye el mensaje HTML que se envía al validador con los
        datos del pago a validar.

        Args:
            telegram_id: ID de Telegram del comprador.
            telegram_name: Nombre del comprador en Telegram.
            amount: Monto detectado en el comprobante.
            extracted_date: Fecha extraída del comprobante (opcional).

        Returns:
            Mensaje formateado en HTML listo para enviar al validador.

        Example:
            >>> msg = service.build_validation_message(12345, "Juan", 150.0)
            >>> print(msg)
            <b>💰 NUEVO PAGO RECIBIDO</b>
            👤 <b>Usuario:</b> <a href="tg://user?id=12345">Juan</a>
            🆔 <b>ID:</b> <code>12345</code>
            💵 <b>Monto:</b> S/ 150.0
            📅 <b>Fecha:</b> 15/01/2025 14:30
        """
        from utils.datetime_utils import get_lima_time_formatted

        if not extracted_date:
            extracted_date = get_lima_time_formatted()["fecha_formateada"]

        # Determinar el servicio reconocido
        service_info = ""
        if self._pricing_service:
            plan = self._pricing_service.match_price(amount)
            if plan:
                service_name = "VIP" if plan.service_id == 2 else "Stake"
                if plan.service_id == 2:  # VIP
                    duration = f"{plan.duration_months} {'mes' if plan.duration_months == 1 else 'meses'}"
                    service_info = f"🎯 <b>Servicio:</b> {service_name} + {duration}\n"
                else:  # Stake
                    service_info = f"🎯 <b>Servicio:</b> {service_name}\n"

        message = (
            f"<b>💰 NUEVO PAGO RECIBIDO</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>Usuario:</b> <a href=\"tg://user?id={telegram_id}\">{telegram_name}</a>\n"
            f"🆔 <b>ID:</b> <code>{telegram_id}</code>\n"
            f"💵 <b>Monto:</b> S/ {amount:.2f}\n"
            f"{service_info}"
            f"📅 <b>Fecha:</b> {extracted_date or 'No detectada'}\n"
            f"━━━━━━━━━━━━━━━━━━━━"
        )
        return message

    def build_rejection_message(self, user_id: int) -> str:
        """
        Construye el mensaje que se envía al usuario cuando su pago
        es rechazado por el validador.

        Args:
            user_id: ID de Telegram del usuario.

        Returns:
            Mensaje de rechazo.
        """
        return (
            "❌ <b>PAGO RECHAZADO</b>\n\n"
            "Lo sentimos, tu pago no pudo ser validado.\n\n"
            "<b>Posibles razones:</b>\n"
            "• El comprobante no es legible\n"
            "• El monto no coincide con nuestros planes\n"
            "• El pago ya fue registrado anteriormente\n\n"
            "<b>¿Qué hacer?</b>\n"
            "Verifica que hayas transferido a una de nuestras cuentas y envía "
            "el comprobante de nuevo a este chat.\n\n"
            "¿Necesitas ayuda? Contacta a @magic_peru2 📲"
        )

    def build_incorrect_amount_prompt(
        self,
        user_id: int,
        telegram_name: str,
        amount: float,
        message_id: int,
    ) -> str:
        """
        Construye el mensaje HTML que se envía al validador cuando
        el monto no es reconocido, pidiendo que lo ingrese manualmente.

        Args:
            user_id: ID de Telegram del comprador.
            telegram_name: Nombre del comprador.
            amount: Monto detectado.
            message_id: ID del mensaje de validación original.

        Returns:
            Mensaje HTML con instrucciones y comando /vm.
        """
        from utils.datetime_utils import get_lima_time_formatted

        fecha_correcta = get_lima_time_formatted()["dd/mm/yyyy"]

        return (
            f"🔍 <b>CONFIRMACIÓN DE PAGO</b>\n\n"
            f"👤 <a href=\"tg://user?id={user_id}\">{telegram_name}</a>\n"
            f"💵 <b>Monto detectado:</b> S/ {amount:.2f}\n\n"
            f"<b>✏️ Editar:</b> <code>/vm {user_id} {message_id} &lt;MONTO_TRANSFERIDO&gt; [fecha]</code>\n"
            f"<b>💡 Ej:</b> <code>/vm {user_id} {message_id} 125 {fecha_correcta}</code>\n\n"
            f"<i>O seleccione el servicio directamente:</i>"
        )

    # ------------------------------------------------------------------
    # Validación con monto corregido
    # ------------------------------------------------------------------

    def validate_with_corrected_amount(
        self,
        telegram_id: int,
        corrected_amount: float,
        from_channel: str = "telegram",
        purchase_date: str | None = None,
        payment_ref: str | None = None,
    ) -> ValidationResult:
        """
        Procesa un pago con monto corregido manualmente por el validador.

        Similar a validate_payment pero omite la verificación de rango
        y confía en que el validador ingresó el monto correcto.

        Args:
            telegram_id: ID de Telegram del comprador.
            corrected_amount: Monto corregido por el validador.
            from_channel: Canal de origen.
            purchase_date: Fecha de compra en formato ddmmyyyy.

        Returns:
            ValidationResult con el resultado.
        """
        return self.validate_payment(
            telegram_id=telegram_id,
            amount=corrected_amount,
            from_channel=from_channel,
            purchase_date=purchase_date,
            payment_ref=payment_ref,
        )

    # ------------------------------------------------------------------
    # Verificación de validador autorizado
    # ------------------------------------------------------------------

    def is_validator_authorized(self, telegram_id: int) -> bool:
        """
        Verifica si un usuario está autorizado como validador.

        Los validadores autorizados se configuran en la variable de
        entorno TELEGRAM_VALIDATOR_IDS.

        Args:
            telegram_id: ID de Telegram a verificar.

        Returns:
            True si el usuario es un validador autorizado.
        """
        try:
            from config.settings import settings
            return str(telegram_id) in settings.TELEGRAM_VALIDATOR_IDS
        except ImportError:
            logger.warning("No se pudo verificar validador: settings no disponible")
            return False

    def get_validator_ids(self) -> list[str]:
        """
        Obtiene la lista de IDs de validadores autorizados.

        Returns:
            Lista de IDs de validadores como strings.
        """
        try:
            from config.settings import settings
            return settings.TELEGRAM_VALIDATOR_IDS
        except ImportError:
            logger.warning("No se pudo obtener validadores: settings no disponible")
            return []
