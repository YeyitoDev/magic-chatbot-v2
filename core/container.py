"""
Dependency Injection Container - Magic Chatbot v2
==================================================
Contenedor de inversión de control (IoC) ligero sin dependencias externas.
Gestiona el registro y resolución de servicios con soporte para
inicialización perezosa (lazy) mediante factories.

Principios:
- Dependency Inversion Principle (SOLID): Los módulos de alto nivel no
  dependen de implementaciones concretas sino de abstracciones.
- Service Locator Pattern: El contenedor actúa como localizador central.

Uso:
    from core.container import container

    # Registrar una instancia ya creada
    container.register("config", settings)

    # Registrar una factory para inicialización perezosa
    container.register_factory("db_session", lambda: SessionLocal())

    # Resolver un servicio
    db = container.resolve("db_session")
"""

from collections.abc import Callable
from typing import Any


class Container:
    """
    Contenedor de inversión de control (IoC) ligero.

    Mantiene un registro de servicios indexados por nombre. Soporta:
    - Instancias pre-creadas (register).
    - Factories lazy (register_factory): la instancia se crea en la primera
      resolución y se cachea para usos posteriores.

    Attributes:
        _services: Diccionario de instancias de servicios.
        _factories: Diccionario de factories pendientes de inicialización.
    """

    def __init__(self) -> None:
        """Inicializa un contenedor vacío."""
        self._services: dict[str, Any] = {}
        self._factories: dict[str, Callable[[], Any]] = {}

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------

    def register(self, name: str, instance: Any) -> None:
        """
        Registra una instancia de servicio ya creada.

        Args:
            name: Nombre único para identificar el servicio.
            instance: Instancia del servicio a registrar.

        Raises:
            ValueError: Si el nombre ya está registrado (instancia o factory).
        """
        if name in self._services or name in self._factories:
            raise ValueError(
                f"El servicio '{name}' ya está registrado en el contenedor."
            )
        self._services[name] = instance

    def register_factory(self, name: str, factory: Callable[[], Any]) -> None:
        """
        Registra una factory que crea el servicio bajo demanda (lazy init).

        La factory se invoca una sola vez: en la primera llamada a resolve().
        El resultado se cachea y las llamadas subsiguientes retornan la
        misma instancia (patrón Singleton dentro del contenedor).

        Args:
            name: Nombre único para identificar el servicio.
            factory: Función sin argumentos que retorna una instancia.

        Raises:
            ValueError: Si el nombre ya está registrado.
        """
        if name in self._services or name in self._factories:
            raise ValueError(
                f"El servicio o factory '{name}' ya está registrado."
            )
        self._factories[name] = factory

    # ------------------------------------------------------------------
    # Resolución
    # ------------------------------------------------------------------

    def resolve(self, name: str) -> Any:
        """
        Resuelve un servicio por su nombre.

        Si el servicio fue registrado como factory, la invoca en la primera
        resolución, cachea el resultado y elimina la factory del registro.

        Args:
            name: Nombre del servicio a resolver.

        Returns:
            La instancia del servicio registrado.

        Raises:
            KeyError: Si el nombre no está registrado.
        """
        # Verificar instancias ya creadas
        if name in self._services:
            return self._services[name]

        # Verificar factories pendientes
        if name in self._factories:
            instance = self._factories[name]()
            self._services[name] = instance
            del self._factories[name]
            return instance

        raise KeyError(
            f"Servicio '{name}' no encontrado en el contenedor. "
            f"Servicios disponibles: {list(self._services.keys())}"
        )

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------

    def is_registered(self, name: str) -> bool:
        """
        Verifica si un servicio está registrado (instancia o factory).

        Args:
            name: Nombre del servicio a verificar.

        Returns:
            True si el servicio existe en el contenedor.
        """
        return name in self._services or name in self._factories

    def clear(self) -> None:
        """Elimina todos los servicios registrados en el contenedor."""
        self._services.clear()
        self._factories.clear()

    def list_services(self) -> dict[str, str]:
        """
        Lista los servicios registrados con su tipo.

        Returns:
            Diccionario {nombre: tipo}, donde tipo es 'instance' o 'factory'.
        """
        result: dict[str, str] = {}
        for name in self._services:
            result[name] = "instance"
        for name in self._factories:
            result[name] = "factory (lazy)"
        return result

    # ------------------------------------------------------------------
    # Inicialización por defecto del sistema
    # ------------------------------------------------------------------

    def initialize_defaults(self) -> None:
        """
        Inicializa el contenedor con las dependencias por defecto del sistema.

        Registra repositorios, servicios y otros componentes core necesarios
        para el funcionamiento del bot. Debe llamarse durante el arranque de
        la aplicación, después de que la configuración y BD estén listas.

        El orden es importante: primero las dependencias de bajo nivel
        (DB, config) y luego los servicios de alto nivel.
        """
        # ---- Configuración ----
        from config.settings import settings

        self.register("settings", settings)

        # ---- Base de datos ----
        from core.database import SessionLocal

        self.register_factory("db_session", lambda: SessionLocal())

        # ---- Repositorios ----
        from repositories.purchase_repo import PurchaseRepository
        from repositories.selected_service_repo import SelectedServiceRepository
        from repositories.service_repo import ServiceRepository
        from repositories.subscription_repo import SubscriptionRepository
        from repositories.user_repo import UserRepository

        self.register_factory(
            "user_repository",
            lambda: UserRepository(self.resolve("db_session")),
        )
        self.register_factory(
            "service_repository",
            lambda: ServiceRepository(self.resolve("db_session")),
        )
        self.register_factory(
            "purchase_repository",
            lambda: PurchaseRepository(self.resolve("db_session")),
        )
        self.register_factory(
            "subscription_repository",
            lambda: SubscriptionRepository(self.resolve("db_session")),
        )
        self.register_factory(
            "selected_service_repository",
            lambda: SelectedServiceRepository(self.resolve("db_session")),
        )

        # ---- Servicios de dominio (incluye visión: Gemini) ----
        from services.openai_vision import GeminiVisionService
        from services.payment_service import PaymentService
        from services.promotion_service import PromotionService
        from services.reminder_service import ReminderService
        from services.subscription_service import SubscriptionService
        from services.user_service import UserService

        self.register_factory(
            "gemini_vision_service",
            lambda: GeminiVisionService(),
        )

        self.register_factory(
            "user_service",
            lambda: UserService(self.resolve("user_repository")),
        )
        self.register_factory(
            "subscription_service",
            lambda: SubscriptionService(
                self.resolve("user_repository"),
                self.resolve("service_repository"),
                self.resolve("purchase_repository"),
                self.resolve("subscription_repository"),
                self.resolve("pricing_service"),
            ),
        )
        self.register_factory(
            "payment_service",
            lambda: PaymentService(
                self.resolve("purchase_repository"),
                self.resolve("subscription_service"),
                self.resolve("user_repository"),
                self.resolve("pricing_service"),
            ),
        )
        self.register_factory(
            "promotion_service",
            lambda: PromotionService(
                settings.AWS_REGION,
                settings.AWS_DYNAMODB_TABLE,
            ),
        )
        self.register_factory(
            "reminder_service",
            lambda: ReminderService(
                self.resolve("selected_service_repository"),
                self.resolve("subscription_repository"),
            ),
        )

        # ---- Pricing Service (dynamic, DB-driven) ----
        from services.pricing_service import PricingService

        self.register_factory(
            "pricing_service",
            lambda: PricingService(self.resolve("service_repository")),
        )

        # ---- Seed default prices if table is empty ----
        self._seed_default_prices()

    def _seed_default_prices(self) -> None:
        """Inserta los precios por defecto si la tabla service_prices está vacía."""
        try:
            session = self.resolve("db_session")
            # ---- Migración: agregar columna is_active si no existe ----
            from sqlalchemy import text

            from models.service import Service, ServicePrice
            try:
                session.execute(text(
                    "ALTER TABLE subscriptions ADD COLUMN is_active BOOLEAN DEFAULT TRUE"
                ))
                session.commit()
            except Exception:
                session.rollback()
                pass  # Column already exists

            existing = session.query(ServicePrice).count()
            if existing > 0:
                return  # Ya hay precios, no hacer nada

            # Verificar que los servicios existen
            stake = session.query(Service).filter_by(name="Stake").first()
            vip = session.query(Service).filter_by(name="Grupo VIP").first()

            if not stake:
                stake = Service(name="Stake", description="Stake de máxima seguridad", is_subscription=False)
                session.add(stake)
                session.flush()
            if not vip:
                vip = Service(name="Grupo VIP", description="Grupo VIP de pronósticos", is_subscription=True)
                session.add(vip)
                session.flush()

            prices = [
                ServicePrice(service_id=stake.service_id, price=50.0, discount=0.0, duration_months=0),
                ServicePrice(service_id=vip.service_id, price=100.0, discount=0.0, duration_months=1),
                ServicePrice(service_id=vip.service_id, price=150.0, discount=0.0, duration_months=2),
                ServicePrice(service_id=vip.service_id, price=200.0, discount=0.0, duration_months=3),
            ]
            session.add_all(prices)
            session.commit()

            # After seeding, reset discounts to 0 for all existing rows
            session.query(ServicePrice).update({'discount': 0.0})
            session.commit()
            import logging
            logging.getLogger(__name__).info(f"✅ Precios por defecto insertados: {len(prices)} planes.")
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"No se pudieron seedear precios: {e}")
            session.rollback()


# Instancia global del contenedor para toda la aplicación
container = Container()
