"""
Modelo User - Magic Chatbot v2
===============================
Representa a un usuario de Telegram registrado en el bot.

Cada usuario tiene un telegram_id único que sirve como clave primaria.
Mantiene relaciones con sus compras (Purchase), suscripciones (Subscription)
y el servicio actualmente seleccionado (SelectedService).
"""

from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, Column, String
from sqlalchemy.orm import relationship

from models.base import BaseModel

if TYPE_CHECKING:
    from models.purchase import Purchase
    from models.selected_service import SelectedService
    from models.subscription import Subscription


class User(BaseModel):
    """
    Usuario del bot de Telegram.

    Attributes:
        telegram_id (int): ID único de Telegram del usuario (PK).
        telegram_name (str | None): Nombre visible en Telegram (first_name).
        purchases (list[Purchase]): Compras realizadas por el usuario.
        subscriptions (list[Subscription]): Suscripciones del usuario.
        selected_service (SelectedService | None): Servicio actualmente
            seleccionado en el flujo de compra.
    """

    __tablename__ = "users"

    telegram_id = Column(BigInteger, primary_key=True, nullable=False)
    telegram_name = Column(String(255), nullable=True)

    # ------------------------------------------------------------------
    # Relaciones
    # ------------------------------------------------------------------

    purchases: list["Purchase"] = relationship(
        "Purchase",
        back_populates="user",
        lazy="selectin",
    )

    subscriptions: list["Subscription"] = relationship(
        "Subscription",
        back_populates="user",
        lazy="selectin",
    )

    selected_service: Optional["SelectedService"] = relationship(
        "SelectedService",
        back_populates="user",
        uselist=False,
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return (
            f"User(telegram_id={self.telegram_id}, "
            f"telegram_name={self.telegram_name!r})"
        )
