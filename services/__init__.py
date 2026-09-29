"""
Services Module - Magic Chatbot v2
==================================
Capa de lógica de negocio que orquesta las operaciones del dominio.

Servicios incluidos:
- UserService: Registro y consulta de usuarios.
- SubscriptionService: Compras, suscripciones, determinación de planes.
- PaymentService: Validación de pagos, detección de duplicados.
- PricingService: Precios dinámicos desde BD con caché JSON.
- PromotionService: Pipeline de promociones (DynamoDB + BetSafe).
- ReminderService: Recordatorios de compra pendiente.
- GoogleSheetsService: Integración con Google Sheets API.
- GoogleVisionService: OCR de comprobantes de pago.
- TelegramAPIService: Wrapper de bajo nivel para la API REST de Telegram.
"""

from services.payment_service import PaymentService, ValidationResult
from services.pricing_service import PricingService, get_pricing_service
from services.subscription_service import PurchaseResult, SubscriptionService
from services.user_service import UserService

__all__ = [
    "UserService",
    "SubscriptionService",
    "PurchaseResult",
    "PaymentService",
    "ValidationResult",
    "PricingService",
    "get_pricing_service",
]
