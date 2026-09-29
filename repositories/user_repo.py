"""
User Repository - Magic Chatbot v2
===================================
Repositorio para operaciones de acceso a datos de la entidad User.

Operaciones:
- Búsqueda por telegram_id.
- Creación.
- get_or_create (upsert simplificado).

Uso:
    repo = UserRepository(session)
    user = repo.get_or_create(telegram_id=12345, telegram_name="Juan")
"""



from models.user import User
from repositories.base import BaseRepository


class UserRepository(BaseRepository):
    """
    Repositorio con operaciones específicas para la tabla `users`.

    Encapsula las consultas SQLAlchemy para que la lógica de negocio
    no dependa directamente del ORM.
    """

    # ------------------------------------------------------------------
    # Búsqueda
    # ------------------------------------------------------------------

    def get_by_telegram_id(self, telegram_id: int) -> User | None:
        """
        Busca un usuario por su ID de Telegram.

        Args:
            telegram_id: ID único de Telegram del usuario.

        Returns:
            User si se encuentra, None si no existe en la base de datos.
        """
        return (
            self._session.query(User)
            .filter_by(telegram_id=telegram_id)
            .first()
        )

    # ------------------------------------------------------------------
    # Creación
    # ------------------------------------------------------------------

    def create(self, telegram_id: int, telegram_name: str) -> User:
        """
        Crea y persiste un nuevo usuario.

        Args:
            telegram_id: ID único de Telegram del usuario.
            telegram_name: Nombre visible del usuario en Telegram (first_name).

        Returns:
            La instancia User recién creada y persistida.

        Note:
            Si el telegram_id ya existe, SQLAlchemy lanzará IntegrityError.
            Para evitar esto, usar get_or_create() en su lugar.
        """
        user = User(telegram_id=telegram_id, telegram_name=telegram_name)
        self.add(user)
        self.commit()
        return user

    # ------------------------------------------------------------------
    # Upsert
    # ------------------------------------------------------------------

    def get_or_create(
        self, telegram_id: int, telegram_name: str
    ) -> User:
        """
        Obtiene un usuario existente o lo crea si no existe.

        Si el usuario ya existe pero su nombre cambió (el usuario modificó
        su nombre en Telegram), se actualiza automáticamente.

        Args:
            telegram_id: ID único de Telegram del usuario.
            telegram_name: Nombre visible actual en Telegram.

        Returns:
            User existente o recién creado.
        """
        user = self.get_by_telegram_id(telegram_id)

        if user is None:
            user = self.create(telegram_id, telegram_name)
        elif user.telegram_name != telegram_name:
            # Actualizar nombre si cambió en Telegram
            user.telegram_name = telegram_name
            self.commit()

        return user

    # ------------------------------------------------------------------
    # Consultas adicionales
    # ------------------------------------------------------------------

    def exists(self, telegram_id: int) -> bool:
        """
        Verifica si un usuario existe en la base de datos.

        Args:
            telegram_id: ID de Telegram a verificar.

        Returns:
            True si el usuario está registrado.
        """
        return self.get_by_telegram_id(telegram_id) is not None
