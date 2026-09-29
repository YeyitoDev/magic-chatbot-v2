"""
Modelos Service y ServicePrice - Magic Chatbot v2
==================================================
Representan los servicios ofrecidos (Stake, Grupo VIP) y sus precios
con posibles descuentos y duración en meses.
"""


from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String
from sqlalchemy.orm import relationship

from models.base import BaseModel

if TYPE_CHECKING:
    from models.purchase import Purchase
    from models.subscription import Subscription


class Service(BaseModel):
    """
    Servicio ofrecido por el bot.

    Atributos:
        service_id (int): PK autoincremental.
        name (str): Nombre único del servicio (ej: "Stake", "Grupo VIP").
        description (str): Descripción comercial del servicio.
        is_subscription (bool): True si es suscripción recurrente, False si es pago único.
        prices (list[ServicePrice]): Precios asociados a este servicio.
        purchases (list[Purchase]): Compras realizadas de este servicio.
        subscriptions (list[Subscription]): Suscripciones activas de este servicio.
    """

    __tablename__ = "services"

    service_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(String(255), nullable=False)
    is_subscription = Column(Boolean, default=False)

    # Relaciones
    prices: list["ServicePrice"] = relationship(
        "ServicePrice", back_populates="service", lazy="selectin"
    )
    purchases: list["Purchase"] = relationship(
        "Purchase", back_populates="service", lazy="selectin"
    )
    subscriptions: list["Subscription"] = relationship(
        "Subscription", back_populates="service", lazy="selectin"
    )

    def __repr__(self) -> str:
        return (
            f"Service(service_id={self.service_id}, name={self.name!r}, "
            f"is_subscription={self.is_subscription})"
        )


class ServicePrice(BaseModel):
    """
    Precio de un servicio con posible descuento y duración.

    Atributos:
        service_price_id (int): PK autoincremental.
        service_id (int): FK al servicio.
        price (float): Precio base del servicio.
        discount (float): Descuento aplicable (0.0 si no hay descuento).
        duration_months (int): Duración en meses. 0 = pago único (Stake).
        service (Service): Relación inversa al servicio dueño de este precio.

    Propiedades:
        effective_price (float): Precio después de aplicar el descuento.
    """

    __tablename__ = "service_prices"

    service_price_id = Column(Integer, primary_key=True, autoincrement=True)
    service_id = Column(Integer, ForeignKey("services.service_id"))
    price = Column(Float, nullable=False)
    discount = Column(Float, default=0.0)
    duration_months = Column(Integer, nullable=False, default=0)

    # Relación inversa
    service: "Service" = relationship("Service", back_populates="prices")

    @property
    def effective_price(self) -> float:
        """Precio efectivo después de aplicar el descuento."""
        return self.price - self.discount

    def __repr__(self) -> str:
        return (
            f"ServicePrice(service_price_id={self.service_price_id}, "
            f"service_id={self.service_id}, price={self.price}, "
            f"discount={self.discount}, duration_months={self.duration_months})"
        )
