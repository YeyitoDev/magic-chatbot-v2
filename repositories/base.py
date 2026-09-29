"""
Repositorio Base Genérico - Magic Chatbot v2
=============================================
Proporciona operaciones CRUD mínimas encapsulando la sesión de SQLAlchemy.
Las subclases heredan estos métodos y añaden consultas específicas del dominio.

Principios:
- Encapsulación: la sesión de BD (_session) es privada; los métodos públicos
  no exponen detalles de implementación de SQLAlchemy.
- Composición sobre herencia: los repositorios reciben la sesión por constructor
  (Dependency Injection), no la crean internamente.

Uso:
    from repositories.base import BaseRepository

    class UserRepository(BaseRepository):
        def get_by_id(self, user_id: int) -> Optional[User]:
            return self._session.query(User).filter_by(id=user_id).first()
"""

from typing import Any

from sqlalchemy.orm import Session


class BaseRepository:
    """
    Repositorio base con operaciones atómicas sobre la sesión de BD.

    Proporciona métodos transaccionales básicos (add, delete, commit, rollback)
    que las subclases pueden usar para construir consultas de más alto nivel.

    Attributes:
        _session (Session): Sesión de SQLAlchemy inyectada al instanciar.
    """

    def __init__(self, session: Session) -> None:
        """
        Inicializa el repositorio con una sesión activa de base de datos.

        Args:
            session: Sesión de SQLAlchemy (normalmente SessionLocal del core).
        """
        self._session: Session = session

    # ------------------------------------------------------------------
    # Operaciones CRUD básicas
    # ------------------------------------------------------------------

    def add(self, entity: Any) -> None:
        """
        Agrega una entidad a la sesión (pendiente de commit).

        La entidad no se persiste inmediatamente; se requiere llamar a
        commit() para confirmar la transacción.

        Args:
            entity: Instancia de modelo SQLAlchemy a persistir.
        """
        self._session.add(entity)

    def add_all(self, entities: list[Any]) -> None:
        """
        Agrega múltiples entidades a la sesión en una sola operación.

        Args:
            entities: Lista de instancias de modelos a persistir.
        """
        self._session.add_all(entities)

    def delete(self, entity: Any) -> None:
        """
        Marca una entidad para eliminación (pendiente de commit).

        La entidad debe estar siendo trackeada por la sesión actual.
        Si se pasa una entidad detached, no tendrá efecto.

        Args:
            entity: Instancia de modelo SQLAlchemy a eliminar.
        """
        self._session.delete(entity)

    def merge(self, entity: Any) -> Any:
        """
        Hace merge de una entidad detached a la sesión actual.

        Útil cuando se recibe una entidad de otra sesión y se necesita
        asociarla a la sesión actual para modificarla.

        Args:
            entity: Instancia de modelo en estado detached.

        Returns:
            La instancia mergeada y asociada a esta sesión.
        """
        return self._session.merge(entity)

    # ------------------------------------------------------------------
    # Control transaccional
    # ------------------------------------------------------------------

    def commit(self) -> None:
        """
        Confirma (flush + commit) todas las operaciones pendientes.

        Persiste definitivamente los cambios en la base de datos.
        Debe llamarse después de add(), delete(), o cualquier modificación
        a entidades trackeadas por la sesión.

        Si el commit falla, la sesión se revierte automáticamente para
        evitar que quede en un estado inconsistente (PendingRollbackError).
        """
        try:
            self._session.commit()
        except Exception:
            self._session.rollback()
            raise

    def rollback(self) -> None:
        """
        Revierte todas las operaciones pendientes en la sesión.

        Útil en bloques try/except para deshacer cambios ante errores.
        """
        self._session.rollback()

    def flush(self) -> None:
        """
        Ejecuta flush sin hacer commit.

        Envía las operaciones pendientes a la BD pero no las confirma.
        Útil para obtener IDs auto-generados antes del commit final.
        """
        self._session.flush()

    def expire_all(self) -> None:
        """
        Expira todos los objetos en la sesión.

        Fuerza que la próxima lectura de cualquier atributo de entidades
        trackeadas haga un SELECT fresco desde la base de datos.
        """
        self._session.expire_all()

    def refresh(self, entity: Any) -> None:
        """
        Refresca una entidad desde la base de datos.

        Recarga el estado actual de la entidad desde la BD, descartando
        cualquier modificación no commiteada.

        Args:
            entity: Instancia de modelo a refrescar desde la BD.
        """
        self._session.refresh(entity)

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """
        Verifica si la sesión está activa (conexión abierta).

        Returns:
            True si la sesión está activa y puede ejecutar queries.
        """
        return self._session.is_active

    def close(self) -> None:
        """
        Cierra la sesión y devuelve la conexión al pool.

        Debe llamarse al finalizar el uso del repositorio si la sesión
        fue creada por este repositorio (no inyectada).
        """
        self._session.close()

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(session_active={self._session.is_active})"
