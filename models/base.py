"""
Modelos base de SQLAlchemy - Magic Chatbot v2
==============================================
Define:
- Base: instancia de declarative_base para todos los modelos.
- BaseModel: clase abstracta con __repr__ genérico.
- TimestampMixin: mixin que agrega created_at y updated_at automáticos.

Compatibilidad: SQLAlchemy 2.0 con __allow_unmapped__ = True.
"""

from sqlalchemy import Column, DateTime, func
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class BaseModel(Base):
    """
    Clase base abstracta para todos los modelos del proyecto.
    Proporciona __repr__ genérico y configuración SQLAlchemy 2.0.
    """

    __abstract__ = True
    __allow_unmapped__ = True

    def __repr__(self) -> str:
        class_name: str = self.__class__.__name__
        attributes: str = ", ".join(
            f"{key}={value!r}"
            for key, value in vars(self).items()
            if not key.startswith("_")
        )
        return f"{class_name}({attributes})"


class TimestampMixin:
    """
    Mixin que agrega columnas de auditoría temporal (created_at, updated_at).
    Compatible con SQLAlchemy 2.0 mediante __allow_unmapped__ = True.
    """

    __allow_unmapped__ = True

    created_at = Column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        doc="Fecha y hora de creación del registro (UTC)",
    )
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        doc="Fecha y hora de la última actualización del registro (UTC)",
    )
