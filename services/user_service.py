"""
User Service - Magic Chatbot v2
================================
Servicio de dominio para la gestión de usuarios.

Encapsula la lógica de negocio relacionada con el registro y consulta
de usuarios de Telegram. Actúa como fachada entre los handlers y el
repositorio de usuarios.

Principios:
- Single Responsibility: solo lógica de negocio de usuarios.
- Dependency Inversion: depende de la abstracción UserRepository.

Uso:
    from repositories.user_repo import UserRepository
    from services.user_service import UserService

    user_repo = UserRepository(session)
    user_service = UserService(user_repo)
    user = user_service.get_or_create_user(12345, "Juan")
"""

import logging

from models.user import User
from repositories.user_repo import UserRepository

logger = logging.getLogger(__name__)


class UserService:
    """
    Servicio de dominio para operaciones con usuarios.

    Proporciona métodos de alto nivel para el registro, consulta
    y verificación de usuarios del bot.

    Attributes:
        _user_repo (UserRepository): Repositorio de usuarios inyectado.
    """

    def __init__(self, user_repo: UserRepository) -> None:
        """
        Inicializa el servicio con el repositorio de usuarios.

        Args:
            user_repo: Repositorio de usuarios (inyectado por el contenedor).
        """
        self._user_repo = user_repo

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------

    def register_user(
        self, telegram_id: int, telegram_name: str
    ) -> User:
        """
        Registra un nuevo usuario en el sistema.

        Si el usuario ya existe, retorna la instancia existente.
        Si el nombre cambió en Telegram, lo actualiza automáticamente.

        Args:
            telegram_id: ID único de Telegram del usuario.
            telegram_name: Nombre visible del usuario (first_name).

        Returns:
            Instancia User (nueva o existente).

        Note:
            Usa get_or_create internamente para evitar IntegrityError
            por duplicados de clave primaria.
        """
        user = self._user_repo.get_or_create(telegram_id, telegram_name)
        logger.info(
            "Usuario registrado/actualizado: telegram_id=%s, name=%s",
            telegram_id,
            telegram_name,
        )
        return user

    # ------------------------------------------------------------------
    # Consulta
    # ------------------------------------------------------------------

    def get_user(self, telegram_id: int) -> User | None:
        """
        Obtiene un usuario por su ID de Telegram.

        Args:
            telegram_id: ID de Telegram del usuario.

        Returns:
            User si está registrado, None si no se encuentra.

        Example:
            user = user_service.get_user(12345)
            if user:
                print(f"Nombre: {user.telegram_name}")
        """
        return self._user_repo.get_by_telegram_id(telegram_id)

    def get_or_create_user(
        self, telegram_id: int, telegram_name: str
    ) -> User:
        """
        Obtiene un usuario existente o lo crea si no existe.

        Versión de conveniencia que combina get_user + register_user.

        Args:
            telegram_id: ID de Telegram del usuario.
            telegram_name: Nombre visible del usuario.

        Returns:
            User existente o recién creado.
        """
        return self._user_repo.get_or_create(telegram_id, telegram_name)

    # ------------------------------------------------------------------
    # Verificación
    # ------------------------------------------------------------------

    def user_exists(self, telegram_id: int) -> bool:
        """
        Verifica si un usuario está registrado en el sistema.

        Args:
            telegram_id: ID de Telegram a verificar.

        Returns:
            True si el usuario existe en la base de datos.
        """
        return self._user_repo.exists(telegram_id)

    def is_validator(self, telegram_id: int) -> bool:
        """
        Verifica si un usuario es un validador autorizado.

        Los validadores son administradores que pueden aprobar o rechazar
        pagos. Sus IDs se configuran en TELEGRAM_VALIDATOR_IDS.

        Args:
            telegram_id: ID de Telegram a verificar.

        Returns:
            True si el usuario está en la lista de validadores.
        """
        try:
            from config.settings import settings
            return str(telegram_id) in settings.TELEGRAM_VALIDATOR_IDS
        except ImportError:
            logger.warning("No se pudo verificar validador: settings no disponible")
            return False
