"""
Modelo Subscription - Magic Chatbot v2
=======================================
Representa la suscripción activa de un usuario a un servicio por un periodo
determinado. Incluye propiedades para verificar vigencia y días restantes.
"""

from datetime import date, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, Column, Date, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from models.base import BaseModel
from utils.datetime_utils import today_lima

if TYPE_CHECKING:
    from models.service import Service
    from models.user import User


class Subscription(BaseModel):
    """
    Suscripción de un usuario a un servicio con fecha de inicio y fin.

    Representa el periodo durante el cual un usuario tiene acceso a un
    servicio por suscripción (ej: Grupo VIP por 1, 2 o 3 meses).

    Attributes:
        subscription_id (int): PK autoincremental.
        user_telegram_id (int): FK al usuario suscrito.
        service_id (int): FK al servicio contratado.
        start_date (date): Fecha de inicio de la suscripción.
        end_date (date): Fecha de vencimiento de la suscripción.
        is_active (bool): Columna - True si la suscripción está activa (no cancelada).
        user (User): Relación inversa al usuario.
        service (Service): Relación inversa al servicio.

    Properties:
        is_valid (bool): True si end_date >= hoy (vigente por fecha).
        days_remaining (int): Días restantes hasta el vencimiento (negativo si ya expiró).
    """

    __tablename__ = "subscriptions"
    # Una sola fila por (usuario, servicio): renovar reutiliza la fila y la
    # limpieza la desactiva. Ver migrations/001_subscription_idempotency.sql.
    __table_args__ = (
        UniqueConstraint(
            "user_telegram_id", "service_id", name="uq_subscriptions_user_service"
        ),
    )

    subscription_id = Column(
        BigInteger().with_variant(Integer(), "sqlite"),
        primary_key=True,
        autoincrement=True,
    )
    user_telegram_id = Column(
        BigInteger, ForeignKey("users.telegram_id"), nullable=False
    )
    service_id = Column(
        Integer, ForeignKey("services.service_id"), nullable=False
    )
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False, doc="True si la suscripción está activa")

    # ------------------------------------------------------------------
    # Relaciones inversas
    # ------------------------------------------------------------------

    user: "User" = relationship(
        "User",
        back_populates="subscriptions",
        lazy="selectin",
    )
    service: "Service" = relationship(
        "Service",
        back_populates="subscriptions",
        lazy="selectin",
    )

    # ------------------------------------------------------------------
    # Propiedades de dominio
    # ------------------------------------------------------------------

    @property
    def is_valid(self) -> bool:
        """True si end_date >= hoy en Lima (vigente por fecha)."""
        return self.end_date >= today_lima()

    @property
    def days_remaining(self) -> int:
        """
        Calcula los días restantes hasta el vencimiento.

        Returns:
            Número de días que faltan para que expire la suscripción.
            Puede ser negativo si ya expiró.
        """
        delta = self.end_date - today_lima()
        return delta.days

    # ------------------------------------------------------------------
    # Métodos de utilidad
    # ------------------------------------------------------------------

    def extend(self, additional_days: int) -> None:
        """
        Extiende la fecha de fin de la suscripción por N días adicionales.

        Args:
            additional_days: Número de días a agregar a end_date.
        """
        self.end_date = self.end_date + timedelta(days=additional_days)

    def renew(self, duration_days: int, paid_on: date) -> None:
        """
        Aplica un pago de ``duration_days`` pagado el ``paid_on``.

        - Si la suscripción sigue activa y no había vencido al momento del
          pago, se acumula desde su ``end_date`` (no se pierden días).
        - Si ya había vencido o fue desactivada (limpieza, fraude), empieza
          un periodo nuevo desde ``paid_on``. Extender desde un ``end_date``
          antiguo dejaba al cliente con una suscripción ya vencida.
        """
        if self.is_active and self.end_date >= paid_on:
            self.end_date = self.end_date + timedelta(days=duration_days)
        else:
            self.start_date = paid_on
            self.end_date = paid_on + timedelta(days=duration_days)
        self.is_active = True

    def __repr__(self) -> str:
        return (
            f"Subscription(subscription_id={self.subscription_id}, "
            f"user_telegram_id={self.user_telegram_id}, "
            f"service_id={self.service_id}, "
            f"start_date={self.start_date!r}, "
            f"end_date={self.end_date!r}, "
            f"is_active={self.is_active}, is_valid={self.is_valid})"
        )
