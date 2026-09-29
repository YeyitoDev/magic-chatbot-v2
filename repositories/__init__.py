"""
Repositories Module - Magic Chatbot v2
=======================================
Capa de acceso a datos (Data Access Layer) que encapsula todas las
operaciones con la base de datos usando el patrón Repository.

Cada repositorio recibe una sesión de SQLAlchemy por constructor
(dependency injection) y expone métodos específicos para su entidad.

Principios:
- Single Responsibility: cada repositorio maneja una sola entidad.
- Encapsulación: la sesión de BD no se expone fuera del repositorio.
- Testabilidad: los repositorios se pueden mockear fácilmente en tests.

Uso:
    from repositories import UserRepository, PurchaseRepository

    user_repo = UserRepository(session)
    user = user_repo.get_by_telegram_id(123456)
"""

from repositories.base import BaseRepository
from repositories.purchase_repo import PurchaseRepository
from repositories.selected_service_repo import SelectedServiceRepository
from repositories.service_repo import ServiceRepository
from repositories.subscription_repo import SubscriptionRepository
from repositories.user_repo import UserRepository

__all__ = [
    "BaseRepository",
    "UserRepository",
    "ServiceRepository",
    "PurchaseRepository",
    "SubscriptionRepository",
    "SelectedServiceRepository",
]
