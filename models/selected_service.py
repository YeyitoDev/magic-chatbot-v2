"""
Modelo SelectedService - Magic Chatbot v2
==========================================
Registro dinámico del servicio que un usuario tiene seleccionado
actualmente en el flujo de compra/suscripción dentro del bot.

Se utiliza para:
- Recordar qué servicio quiere comprar el usuario mientras envía la captura.
- Controlar el envío de recordatorios de compra (campo `reminder`).
- Limpiar la selección una vez que la compra se completa o expira.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer
from sqlalchemy.orm import relationship

from models.base import BaseModel

if TYPE_CHECKING:
    from models.user import User


class SelectedService(BaseModel):
    """
    Servicio actualmente seleccionado por un usuario en el bot.

    Representa el estado temporal del flujo de compra: el usuario elige
    un servicio (Stake, Grupo VIP), y este registro guarda esa elección
    hasta que la compra se completa, se cancela, o expira por inactividad.

    Attributes:
        user_telegram_id (int): FK al usuario que seleccionó el servicio (PK).
        service_id (int): FK al servicio seleccionado.
        selected_date (datetime): Fecha y hora en que se realizó la selección.
        reminder (int): Contador de recordatorios enviados.
            0 = sin recordatorios enviados aún.
            1 = primer recordatorio enviado (foto + precios).
            2 = segundo recordatorio enviado (video).
        user (User): Relación inversa al usuario dueño de esta selección.
    """

    __tablename__ = "selected_services"

    # ------------------------------------------------------------------
    # Columnas
    # ------------------------------------------------------------------

    user_telegram_id = Column(
        BigInteger,
        ForeignKey("users.telegram_id"),
        primary_key=True,
        nullable=False,
        doc="ID de Telegram del usuario (PK y FK a users)",
    )
    service_id = Column(
        Integer,
        ForeignKey("services.service_id"),
        nullable=True,
        doc="ID del servicio seleccionado por el usuario",
    )
    selected_date = Column(
        DateTime,
        nullable=False,
        default=datetime.now,
        doc="Fecha y hora en que el usuario seleccionó este servicio",
    )
    reminder = Column(
        Integer,
        default=0,
        nullable=False,
        doc="Contador de recordatorios enviados (0, 1, 2). Se reinicia al cambiar de servicio.",
    )

    # ------------------------------------------------------------------
    # Relaciones
    # ------------------------------------------------------------------

    user: Optional["User"] = relationship(
        "User",
        back_populates="selected_service",
        uselist=False,
        lazy="selectin",
    )

    # ------------------------------------------------------------------
    # Métodos de utilidad
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"SelectedService(user_telegram_id={self.user_telegram_id}, "
            f"service_id={self.service_id}, "
            f"selected_date={self.selected_date!r}, "
            f"reminder={self.reminder})"
        )

    def has_reminders_pending(self) -> bool:
        """
        Verifica si aún hay recordatorios pendientes por enviar.

        El sistema envía hasta 2 recordatorios (reminder 0 → 1, 1 → 2).
        Cuando reminder >= 2, ya no hay más recordatorios pendientes.

        Returns:
            True si reminder < 2 (aún se pueden enviar recordatorios).
        """
        return self.reminder < 2

    def is_expired(self, max_minutes: int = 1440) -> bool:
        """
        Verifica si la selección ha expirado por inactividad.

        Si el usuario seleccionó un servicio pero no completó la compra
        dentro del tiempo máximo, la selección se considera expirada.

        Args:
            max_minutes: Tiempo máximo en minutos antes de considerar
                         la selección como expirada. Por defecto 1440 (24 horas).

        Returns:
            True si han pasado más de max_minutes desde la selección.
        """
        from datetime import timedelta

        cutoff = datetime.now() - timedelta(minutes=max_minutes)
        return self.selected_date < cutoff
