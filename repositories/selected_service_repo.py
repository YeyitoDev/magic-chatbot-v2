"""
SelectedService Repository - Magic Chatbot v2
==============================================
Repositorio para operaciones de acceso a datos de la entidad SelectedService.

El SelectedService representa el estado temporal del flujo de compra:
el usuario elige un servicio (Stake, Grupo VIP) y este registro guarda
esa elección hasta que la compra se completa, se cancela o expira.

Operaciones:
- upsert: inserta o actualiza el servicio seleccionado por un usuario.
- delete_by_user: elimina la selección de un usuario (tras compra exitosa).
- get_all_pending: obtiene todos los registros con recordatorios pendientes.
- increment_reminder: incrementa el contador de recordatorios enviados.
- is_service_selected_recently: verifica si la selección fue hace ≤ N minutos.
- get_by_user: obtiene el registro de selección de un usuario específico.

Uso:
    repo = SelectedServiceRepository(session)
    record = repo.upsert(user_telegram_id=12345, service_id=2)
"""

from datetime import datetime, timedelta

from sqlalchemy import update

from models.selected_service import SelectedService
from repositories.base import BaseRepository


class SelectedServiceRepository(BaseRepository):
    """
    Repositorio para la tabla `selected_services`.

    Gestiona el ciclo de vida del servicio seleccionado por cada usuario:
    creación → recordatorios → eliminación (tras compra o expiración).

    El campo `reminder` actúa como contador de recordatorios:
    - 0: sin recordatorios enviados (recién seleccionado).
    - 1: primer recordatorio enviado (foto + precios).
    - 2: segundo recordatorio enviado (video). Ya no se envían más.
    """

    # ------------------------------------------------------------------
    # Búsqueda
    # ------------------------------------------------------------------

    def get_by_user(
        self, user_telegram_id: int
    ) -> SelectedService | None:
        """
        Obtiene el servicio actualmente seleccionado por un usuario.

        Args:
            user_telegram_id: ID de Telegram del usuario.

        Returns:
            SelectedService si el usuario tiene un servicio seleccionado,
            None si no ha seleccionado ninguno.
        """
        return (
            self._session.query(SelectedService)
            .filter_by(user_telegram_id=user_telegram_id)
            .first()
        )

    def get_all(self) -> list[SelectedService]:
        """
        Obtiene todos los registros de servicios seleccionados.

        Útil para jobs que necesitan iterar sobre todos los usuarios
        con una selección activa pendiente.

        Returns:
            Lista de todos los SelectedService en la base de datos.
        """
        return self._session.query(SelectedService).all()

    # ------------------------------------------------------------------
    # Upsert (insertar o actualizar)
    # ------------------------------------------------------------------

    def upsert(
        self,
        user_telegram_id: int,
        service_id: int,
        selected_date: datetime | None = None,
    ) -> SelectedService:
        """
        Inserta o actualiza el servicio seleccionado por un usuario.

        Si el usuario ya tenía un servicio seleccionado, se actualiza
        el service_id, la fecha de selección, y se reinicia el contador
        de recordatorios (reminder = 0).

        Si no tenía selección previa, se crea un nuevo registro.

        Args:
            user_telegram_id: ID de Telegram del usuario.
            service_id: ID del servicio a marcar como seleccionado.
            selected_date: Fecha de selección (por defecto: ahora mismo).

        Returns:
            El registro SelectedService creado o actualizado.
        """
        if selected_date is None:
            selected_date = datetime.now()

        record = self.get_by_user(user_telegram_id)

        if record is None:
            # Crear nuevo registro
            record = SelectedService(
                user_telegram_id=user_telegram_id,
                service_id=service_id,
                selected_date=selected_date,
                reminder=0,
            )
            self.add(record)
        else:
            # Actualizar registro existente
            record.service_id = service_id
            record.selected_date = selected_date
            record.reminder = 0  # Reiniciar contador de recordatorios

        self.commit()
        return record

    # ------------------------------------------------------------------
    # Eliminación
    # ------------------------------------------------------------------

    def delete_by_user(self, user_telegram_id: int) -> bool:
        """
        Elimina el registro de servicio seleccionado de un usuario.

        Se llama después de que la compra se completa exitosamente,
        o cuando la selección expira por inactividad.

        Args:
            user_telegram_id: ID de Telegram del usuario.

        Returns:
            True si se eliminó un registro, False si no existía.
        """
        record = self.get_by_user(user_telegram_id)
        if record is not None:
            self.delete(record)
            self.commit()
            return True
        return False

    # ------------------------------------------------------------------
    # Recordatorios
    # ------------------------------------------------------------------

    def increment_reminder(self, user_telegram_id: int) -> bool:
        """
        Incrementa en 1 el contador de recordatorios enviados al usuario.

        Usa una sentencia UPDATE atómica para evitar race conditions
        en entornos concurrentes.

        Args:
            user_telegram_id: ID de Telegram del usuario.

        Returns:
            True si se incrementó el reminder, False si el usuario no
            tenía un servicio seleccionado.
        """
        # Verificar que el registro existe antes de actualizar
        record = self.get_by_user(user_telegram_id)
        if record is None:
            return False

        # UPDATE atómico: incrementa reminder en 1
        self._session.execute(
            update(SelectedService)
            .where(SelectedService.user_telegram_id == user_telegram_id)
            .values(reminder=SelectedService.reminder + 1)
        )
        self.commit()
        return True

    # ------------------------------------------------------------------
    # Verificación de tiempo
    # ------------------------------------------------------------------

    def is_service_selected_recently(
        self,
        user_telegram_id: int,
        max_minutes: int = 10,
    ) -> bool:
        """
        Verifica si el usuario seleccionó un servicio en los últimos N minutos.

        Útil para:
        - Evitar duplicados en el flujo de selección.
        - Validar que la selección aún es válida al procesar un pago.
        - Prevenir spam de selecciones repetidas.

        Args:
            user_telegram_id: ID de Telegram del usuario.
            max_minutes: Ventana de tiempo en minutos (default: 10).

        Returns:
            True si la selección fue hecha dentro del tiempo máximo.
            False si no hay selección o ya expiró la ventana.
        """
        record = self.get_by_user(user_telegram_id)
        if record is None:
            return False

        cutoff = datetime.now() - timedelta(minutes=max_minutes)
        return record.selected_date >= cutoff

    def get_service_name_if_recent(
        self,
        user_telegram_id: int,
        max_minutes: int = 10,
    ) -> str | None:
        """
        Obtiene el nombre del servicio seleccionado si fue seleccionado
        recientemente (dentro de la ventana de tiempo).

        Este método replica la lógica de `funciones_servicio_seleccionado`
        con stage='consulta' del código original.

        Args:
            user_telegram_id: ID de Telegram del usuario.
            max_minutes: Ventana máxima en minutos (default: 10).

        Returns:
            Nombre del servicio si la selección es reciente,
            None si no hay selección o ya expiró.
        """
        record = self.get_by_user(user_telegram_id)
        if record is None:
            return None

        cutoff = datetime.now() - timedelta(minutes=max_minutes)
        if record.selected_date >= cutoff:
            # La selección está vigente: obtener el nombre del servicio
            from models.service import Service

            service = (
                self._session.query(Service)
                .filter_by(service_id=record.service_id)
                .first()
            )
            return service.name if service else None

        return None
