"""
Service Repository - Magic Chatbot v2
======================================
Repositorio para operaciones de acceso a datos de las entidades
Service y ServicePrice.

Operaciones:
- Búsqueda de servicios por ID, nombre.
- Búsqueda de precios por monto exacto o con descuento.
- Listado de todos los servicios.
"""


from sqlalchemy import or_

from models.service import Service, ServicePrice
from repositories.base import BaseRepository


class ServiceRepository(BaseRepository):
    """
    Repositorio con operaciones específicas para servicios y sus precios.

    Encapsula consultas a las tablas `services` y `service_prices`.
    """

    # ------------------------------------------------------------------
    # Service: Búsqueda
    # ------------------------------------------------------------------

    def get_by_id(self, service_id: int) -> Service | None:
        """
        Busca un servicio por su ID único.

        Args:
            service_id: ID del servicio.

        Returns:
            Service si se encuentra, None en caso contrario.
        """
        return (
            self._session.query(Service)
            .filter_by(service_id=service_id)
            .first()
        )

    def get_by_name(self, name: str) -> Service | None:
        """
        Busca un servicio por su nombre exacto.

        Args:
            name: Nombre del servicio (ej: "Stake", "Grupo VIP").

        Returns:
            Service si se encuentra, None si no existe.
        """
        return (
            self._session.query(Service)
            .filter_by(name=name)
            .first()
        )

    def get_all_services(self) -> list[Service]:
        """
        Obtiene todos los servicios registrados.

        Returns:
            Lista de todos los servicios disponibles.
        """
        return self._session.query(Service).all()

    # ------------------------------------------------------------------
    # ServicePrice: Búsqueda
    # ------------------------------------------------------------------

    def get_price_by_amount(self, amount: float) -> ServicePrice | None:
        """
        Busca un precio de servicio que coincida con el monto pagado.

        Estrategia:
        1. Busca coincidencia exacta con el precio base (price == amount).
        2. Busca coincidencia con precio después del descuento
           (price - discount == amount).

        Esto permite manejar promociones donde el precio efectivo es
        menor al precio base.

        Args:
            amount: Monto pagado por el usuario.

        Returns:
            ServicePrice si hay coincidencia, None si el monto no
            corresponde a ningún servicio conocido.
        """
        return (
            self._session.query(ServicePrice)
            .filter(
                or_(
                    ServicePrice.price == amount,
                    (ServicePrice.price - ServicePrice.discount) == amount,
                )
            )
            .first()
        )

    def get_prices_for_service(self, service_id: int) -> list[ServicePrice]:
        """
        Obtiene todos los precios asociados a un servicio.

        Args:
            service_id: ID del servicio.

        Returns:
            Lista de ServicePrice para ese servicio.
        """
        return (
            self._session.query(ServicePrice)
            .filter_by(service_id=service_id)
            .all()
        )

    # ------------------------------------------------------------------
    # Consultas compuestas
    # ------------------------------------------------------------------

    def get_service_name(self, service_id: int) -> str | None:
        """
        Obtiene el nombre de un servicio dado su ID.

        Args:
            service_id: ID del servicio.

        Returns:
            Nombre del servicio o None si no existe.
        """
        service = self.get_by_id(service_id)
        return service.name if service else None

    def get_service_by_price(self, amount: float) -> Service | None:
        """
        Determina a qué servicio corresponde un monto pagado.

        Busca en ServicePrice por el monto y retorna el Service asociado.

        Args:
            amount: Monto pagado.

        Returns:
            Service correspondiente al monto, o None si no coincide
            con ningún precio registrado.
        """
        service_price = self.get_price_by_amount(amount)
        if service_price:
            return service_price.service
        return None
