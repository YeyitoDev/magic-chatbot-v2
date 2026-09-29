"""
Models Module - Magic Chatbot v2
=================================
Paquete de modelos SQLAlchemy para el bot Magic.

Expone todos los modelos y la clase Base para que puedan ser importados
directamente desde `models`.

Modelos incluidos:
- Base, BaseModel, TimestampMixin (infraestructura).
- User: Usuarios de Telegram.
- Service, ServicePrice: Servicios ofrecidos y sus precios.
- Purchase: Registro de compras.
- Subscription: Suscripciones activas.
- SelectedService: Servicio actualmente seleccionado por el usuario.

Uso:
    from models import User, Purchase, Base
    from models.base import BaseModel

    user = User(telegram_id=12345, telegram_name="Juan")
"""

from models.base import Base, BaseModel, TimestampMixin
from models.purchase import Purchase
from models.selected_service import SelectedService
from models.service import Service, ServicePrice
from models.subscription import Subscription
from models.user import User

__all__ = [
    "Base",
    "BaseModel",
    "TimestampMixin",
    "User",
    "Service",
    "ServicePrice",
    "Purchase",
    "Subscription",
    "SelectedService",
]
