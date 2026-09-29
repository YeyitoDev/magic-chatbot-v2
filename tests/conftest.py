"""
Shared Fixtures for Tests - Magic Chatbot v2
==============================================
Fixtures de pytest compartidas para todos los tests del proyecto.

Proporciona:
- Configuración de base de datos en memoria (SQLite) para tests.
- Contenedor de dependencias mock.
- Repositorios pre-inicializados con datos de prueba.
- Servicios con dependencias mock.
- Cliente de Telegram mock.

Uso en tests:
    def test_user_creation(db_session, user_repo):
        user = user_repo.create(telegram_id=12345, telegram_name="Test User")
        assert user.telegram_id == 12345
"""

import os
import sys
from collections.abc import Generator
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# Fijar el entorno ANTES de importar la app: config.settings llama a
# load_dotenv(), que no sobrescribe variables ya definidas. Así un .env local
# con credenciales reales nunca se usa durante los tests.
os.environ.update({
    "ENVIRONMENT": "testing",
    "DB_ENGINE": "mysql+pymysql",
    "DB_USER": "test",
    "DB_PASSWORD": "test",
    "DB_HOST": "localhost",
    "DB_NAME": "test_db",
    "TELEGRAM_BOT_TOKEN": "test_token_12345",
    "TELEGRAM_VIP_GROUP_ID": "-1000000000001",
    "TELEGRAM_VALIDATOR_IDS": "100000001,100000002",
    "ADMIN_NOTIFY_IDS": "",
    "PROTECTED_USER_IDS": "",
})

# Asegurar que el directorio raíz v2_refactor/ esté en el PYTHONPATH
# para que los imports relativos funcionen correctamente en tests.
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def engine():
    """
    Crea un engine de SQLAlchemy con SQLite en memoria para tests.

    Scope: session - se crea una sola vez para toda la suite de tests.
    """
    test_engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    return test_engine


@pytest.fixture(scope="session")
def tables(engine):
    """
    Crea todas las tablas en la base de datos de test.

    Scope: session - se ejecuta una vez al inicio de la suite.
    """
    from models.base import Base

    Base.metadata.create_all(bind=engine)
    yield
    # Teardown: eliminar todas las tablas al finalizar la suite
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(engine, tables) -> Generator[Session, None, None]:
    """
    Proporciona una sesión de base de datos aislada por test.

    Cada test recibe su propia sesión con rollback automático al finalizar,
    garantizando que los tests no interfieran entre sí.

    Scope: function - se ejecuta para cada test individual.
    """
    # SQLite :memory: comparte una única conexión (SingletonThreadPool), por
    # lo que los commit() de servicios/repositorios persisten. Para aislar
    # cada test, se reinicia el esquema (drop + create) al iniciar.
    from models.base import Base

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Repository fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def user_repo(db_session):
    """
    Proporciona un UserRepository con la sesión de test.
    """
    from repositories.user_repo import UserRepository

    return UserRepository(db_session)


@pytest.fixture(scope="function")
def service_repo(db_session):
    """
    Proporciona un ServiceRepository con la sesión de test.
    """
    from repositories.service_repo import ServiceRepository

    return ServiceRepository(db_session)


@pytest.fixture(scope="function")
def purchase_repo(db_session):
    """
    Proporciona un PurchaseRepository con la sesión de test.
    """
    from repositories.purchase_repo import PurchaseRepository

    return PurchaseRepository(db_session)


@pytest.fixture(scope="function")
def subscription_repo(db_session):
    """
    Proporciona un SubscriptionRepository con la sesión de test.
    """
    from repositories.subscription_repo import SubscriptionRepository

    return SubscriptionRepository(db_session)


@pytest.fixture(scope="function")
def selected_service_repo(db_session):
    """
    Proporciona un SelectedServiceRepository con la sesión de test.
    """
    from repositories.selected_service_repo import SelectedServiceRepository

    return SelectedServiceRepository(db_session)


# ---------------------------------------------------------------------------
# Model fixtures (datos de prueba pre-cargados)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def sample_user(db_session, user_repo):
    """
    Crea un usuario de prueba en la base de datos.

    Returns:
        User con telegram_id=777777777, telegram_name="Fixture User".
    """
    from models.user import User

    user = User(telegram_id=777777777, telegram_name="Fixture User")
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture(scope="function")
def sample_service(db_session, service_repo):
    """
    Crea servicios de prueba (Stake y Grupo VIP) con sus precios.

    Returns:
        Diccionario con {"stake": Service, "vip": Service}.
    """
    from models.service import Service, ServicePrice

    # Servicio: Stake
    stake = Service(
        name="Stake",
        description="Stake de máxima seguridad",
        is_subscription=False,
    )
    db_session.add(stake)
    db_session.flush()

    stake_price = ServicePrice(
        service_id=stake.service_id,
        price=50.0,
        discount=0.0,
        duration_months=0,
    )
    db_session.add(stake_price)

    # Servicio: Grupo VIP
    vip = Service(
        name="Grupo VIP",
        description="Grupo VIP de pronósticos",
        is_subscription=True,
    )
    db_session.add(vip)
    db_session.flush()

    # Precios VIP
    prices = [
        ServicePrice(service_id=vip.service_id, price=100.0, discount=10.0, duration_months=1),
        ServicePrice(service_id=vip.service_id, price=150.0, discount=10.0, duration_months=2),
        ServicePrice(service_id=vip.service_id, price=200.0, discount=10.0, duration_months=3),
    ]
    for p in prices:
        db_session.add(p)

    db_session.commit()

    return {"stake": stake, "vip": vip}


@pytest.fixture(scope="function")
def sample_subscription(db_session, sample_user, sample_service):
    """
    Crea una suscripción de prueba activa.

    Returns:
        Subscription activa para el usuario de prueba en Grupo VIP.
    """
    from models.subscription import Subscription

    today = date.today()
    sub = Subscription(
        user_telegram_id=sample_user.telegram_id,
        service_id=sample_service["vip"].service_id,
        start_date=today,
        end_date=today + timedelta(days=30),
    )
    db_session.add(sub)
    db_session.commit()
    return sub


@pytest.fixture(scope="function")
def sample_purchase(db_session, sample_user, sample_service):
    """
    Crea una compra de prueba.

    Returns:
        Purchase para el usuario de prueba en Grupo VIP por S/ 90.
    """
    from models.purchase import Purchase

    purchase = Purchase(
        user_telegram_id=sample_user.telegram_id,
        service_id=sample_service["vip"].service_id,
        purchase_date=datetime.now(),
        price=90.0,
        from_channel="telegram",
    )
    db_session.add(purchase)
    db_session.commit()
    return purchase


# ---------------------------------------------------------------------------
# Service fixtures (con repos mock)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def user_service(user_repo):
    """
    Proporciona un UserService con repositorio real en BD de test.
    """
    from services.user_service import UserService

    return UserService(user_repo)


@pytest.fixture(scope="function")
def subscription_service(user_repo, service_repo, purchase_repo, subscription_repo):
    """
    Proporciona un SubscriptionService con repositorios reales en BD de test.
    """
    from services.subscription_service import SubscriptionService

    return SubscriptionService(
        user_repo=user_repo,
        service_repo=service_repo,
        purchase_repo=purchase_repo,
        subscription_repo=subscription_repo,
    )


@pytest.fixture(scope="function")
def payment_service(user_repo, purchase_repo, subscription_service):
    """
    Proporciona un PaymentService con dependencias reales en BD de test.
    """
    from services.payment_service import PaymentService

    return PaymentService(
        purchase_repo=purchase_repo,
        subscription_service=subscription_service,
        user_repo=user_repo,
    )


# ---------------------------------------------------------------------------
# Mock fixtures (para tests unitarios sin BD)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def mock_user_repo(mocker):
    """
    Proporciona un UserRepository mockeado.
    """
    from repositories.user_repo import UserRepository

    mock = mocker.MagicMock(spec=UserRepository)
    return mock


@pytest.fixture(scope="function")
def mock_bot(mocker):
    """
    Proporciona un mock del bot de Telegram (para tests de handlers).
    """
    return mocker.MagicMock()


@pytest.fixture(scope="function")
def mock_update(mocker):
    """
    Proporciona un mock de Update de python-telegram-bot.
    """
    update = mocker.MagicMock()
    update.message.from_user.id = 123456789
    update.message.from_user.first_name = "Test User"
    update.message.chat.id = 123456789
    update.message.chat.type = "private"
    update.effective_user.id = 123456789
    update.effective_chat.id = 123456789
    return update


@pytest.fixture(scope="function")
def mock_context(mocker):
    """
    Proporciona un mock de ContextTypes.DEFAULT_TYPE.
    """
    context = mocker.MagicMock()
    context.bot.send_message = mocker.AsyncMock()
    context.bot.send_photo = mocker.AsyncMock()
    context.bot.send_video = mocker.AsyncMock()
    return context


# ---------------------------------------------------------------------------
# Environment fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function", autouse=True)
def mock_settings_env(monkeypatch):
    """
    Configura variables de entorno para tests (automático para todos los tests).

    Esto evita que los tests dependan de un archivo .env real.
    """
    monkeypatch.setenv("ENVIRONMENT", "testing")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test_token_12345")
    monkeypatch.setenv("TELEGRAM_VALIDATOR_IDS", "100000001,100000002")
    monkeypatch.setenv("TELEGRAM_VIP_GROUP_ID", "-1000000000001")
    monkeypatch.setenv("DB_ENGINE", "mysql+pymysql")
    monkeypatch.setenv("DB_USER", "test")
    monkeypatch.setenv("DB_PASSWORD", "test")
    monkeypatch.setenv("DB_HOST", "localhost")
    monkeypatch.setenv("DB_NAME", "test_db")
    monkeypatch.setenv("TIMEZONE", "America/Lima")
    monkeypatch.setenv("ENABLE_JOBS", "false")
    monkeypatch.setenv("FLASK_SECRET_KEY", "test-secret")
    monkeypatch.setenv("API_KEY", "test-api-key-123")
