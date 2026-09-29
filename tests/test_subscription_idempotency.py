"""
Idempotencia de pagos, renovaciones y limpieza de suscripciones.

Cada test corresponde a un defecto encontrado en producción:
- Renovar una suscripción vencida extendía desde la fecha vieja y el cliente
  quedaba con una suscripción ya vencida.
- Validar dos veces el mismo comprobante (doble click, varios validadores)
  registraba dos compras y duplicaba los días.
- Dos validaciones simultáneas podían crear dos filas para el mismo usuario.
- La limpieza expulsaba y avisaba al mismo usuario en ejecuciones sucesivas
  (ciclo borrar → reparar → borrar).
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from utils.datetime_utils import today_lima

BUYER_ID = 700000002
TODAY = today_lima()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def catalog(db_session):
    from models.service import Service, ServicePrice

    db_session.add_all([
        Service(service_id=1, name="Stake", description="Stake", is_subscription=False),
        Service(service_id=2, name="Grupo VIP", description="VIP", is_subscription=True),
    ])
    db_session.flush()
    db_session.add_all([
        ServicePrice(service_id=1, price=50.0, discount=0.0, duration_months=0),
        ServicePrice(service_id=2, price=100.0, discount=10.0, duration_months=1),
        ServicePrice(service_id=2, price=200.0, discount=10.0, duration_months=3),
    ])
    db_session.commit()


@pytest.fixture
def pricing(service_repo, catalog, monkeypatch, tmp_path):
    from services import pricing_service as pricing_module

    monkeypatch.setattr(pricing_module, "CACHE_FILE", str(tmp_path / "pricing_cache.json"))
    return pricing_module.PricingService(service_repo)


@pytest.fixture
def sub_service(user_repo, service_repo, purchase_repo, subscription_repo, pricing):
    from services.subscription_service import SubscriptionService

    return SubscriptionService(
        user_repo, service_repo, purchase_repo, subscription_repo, pricing
    )


@pytest.fixture
def payments(purchase_repo, sub_service, user_repo, pricing):
    from services.payment_service import PaymentService

    return PaymentService(purchase_repo, sub_service, user_repo, pricing)


@pytest.fixture
def buyer(db_session):
    from models.user import User

    db_session.add(User(telegram_id=BUYER_ID, telegram_name="Buyer"))
    db_session.commit()


def add_sub(db_session, user_id=BUYER_ID, *, end_offset, active=True, length=30):
    from models.subscription import Subscription

    end = TODAY + timedelta(days=end_offset)
    sub = Subscription(
        user_telegram_id=user_id,
        service_id=2,
        start_date=end - timedelta(days=length),
        end_date=end,
        is_active=active,
    )
    db_session.add(sub)
    db_session.commit()
    return sub


def subs_of(db_session, user_id=BUYER_ID):
    from models.subscription import Subscription

    db_session.expire_all()
    return db_session.query(Subscription).filter_by(user_telegram_id=user_id).all()


# ---------------------------------------------------------------------------
# Renovación
# ---------------------------------------------------------------------------


class TestRenewal:
    def test_expired_subscription_renews_from_payment_date(self, db_session, payments, buyer):
        add_sub(db_session, end_offset=-40)

        result = payments.validate_payment(telegram_id=BUYER_ID, amount=100.0)

        assert result.success is True
        (sub,) = subs_of(db_session)
        assert sub.start_date == TODAY
        assert sub.end_date == TODAY + timedelta(days=30)

    def test_active_subscription_accumulates_days(self, db_session, payments, buyer):
        add_sub(db_session, end_offset=10)

        payments.validate_payment(telegram_id=BUYER_ID, amount=100.0)

        (sub,) = subs_of(db_session)
        assert sub.end_date == TODAY + timedelta(days=40)

    def test_deactivated_subscription_is_reused_without_leftover_days(
        self, db_session, payments, buyer
    ):
        # Fila desactivada (limpieza o fraude) que aún tenía días por delante.
        add_sub(db_session, end_offset=20, active=False)

        payments.validate_payment(telegram_id=BUYER_ID, amount=100.0)

        (sub,) = subs_of(db_session)
        assert sub.is_active is True
        assert sub.end_date == TODAY + timedelta(days=30)

    def test_backdated_voucher_starts_on_payment_date(self, db_session, payments, buyer):
        add_sub(db_session, end_offset=-40)
        paid_on = TODAY - timedelta(days=2)

        payments.validate_payment(
            telegram_id=BUYER_ID, amount=100.0, purchase_date=paid_on.strftime("%d/%m/%Y")
        )

        (sub,) = subs_of(db_session)
        assert sub.start_date == paid_on
        assert sub.end_date == paid_on + timedelta(days=30)


# ---------------------------------------------------------------------------
# Idempotencia del comprobante
# ---------------------------------------------------------------------------


class TestVoucherIdempotency:
    def test_same_voucher_is_registered_once(self, db_session, payments, buyer):
        from models.purchase import Purchase

        first = payments.validate_payment(
            telegram_id=BUYER_ID, amount=100.0, payment_ref="tg:AQADabc"
        )
        second = payments.validate_payment(
            telegram_id=BUYER_ID, amount=100.0, payment_ref="tg:AQADabc"
        )

        assert first.success is True
        assert second.success is False
        assert second.is_duplicate is True
        assert db_session.query(Purchase).filter_by(user_telegram_id=BUYER_ID).count() == 1
        (sub,) = subs_of(db_session)
        assert sub.end_date == TODAY + timedelta(days=30)

    def test_different_vouchers_both_count(self, db_session, payments, buyer):
        payments.validate_payment(telegram_id=BUYER_ID, amount=100.0, payment_ref="tg:A")
        payments.validate_payment(telegram_id=BUYER_ID, amount=100.0, payment_ref="tg:B")

        (sub,) = subs_of(db_session)
        assert sub.end_date == TODAY + timedelta(days=60)

    def test_voucher_ref_comes_from_photo_unique_id(self):
        from types import SimpleNamespace

        from services.payment_service import voucher_payment_ref

        small = SimpleNamespace(file_unique_id="small")
        large = SimpleNamespace(file_unique_id="large")
        assert voucher_payment_ref(SimpleNamespace(photo=[small, large])) == "tg:large"
        text_reply = SimpleNamespace(photo=[], reply_to_message=SimpleNamespace(photo=[large]))
        assert voucher_payment_ref(text_reply) == "tg:large"
        assert voucher_payment_ref(SimpleNamespace(photo=[], reply_to_message=None)) is None
        assert voucher_payment_ref(None) is None


# ---------------------------------------------------------------------------
# Concurrencia: una sola fila por (usuario, servicio)
# ---------------------------------------------------------------------------


class TestSingleRowPerUser:
    def test_database_rejects_second_row(self, db_session, buyer, catalog):
        add_sub(db_session, end_offset=10)
        with pytest.raises(IntegrityError):
            add_sub(db_session, end_offset=20)
        db_session.rollback()

    def test_concurrent_creation_retries_as_renewal(
        self, db_session, payments, subscription_repo, buyer, monkeypatch
    ):
        # Otra transacción creó la fila entre la lectura y el INSERT: el
        # primer intento no la ve, choca con el UNIQUE y el reintento renueva.
        add_sub(db_session, end_offset=10)
        real_lookup = subscription_repo.get_for_renewal
        calls = {"n": 0}

        def stale_then_real(*args, **kwargs):
            calls["n"] += 1
            return None if calls["n"] == 1 else real_lookup(*args, **kwargs)

        monkeypatch.setattr(subscription_repo, "get_for_renewal", stale_then_real)

        result = payments.validate_payment(telegram_id=BUYER_ID, amount=100.0)

        assert result.success is True
        (sub,) = subs_of(db_session)
        assert sub.end_date == TODAY + timedelta(days=40)


# ---------------------------------------------------------------------------
# Limpieza (run_db_only)
# ---------------------------------------------------------------------------


class FakeTelegramAPI:
    calls: list = []
    kick_ok = True
    admins: list | None = [{"user": {"id": 1}, "status": "creator"}]

    def __init__(self, *args, **kwargs):
        pass

    def remove_user_allow_rejoin(self, chat_id, user_id):
        FakeTelegramAPI.calls.append(("kick", user_id))
        return {"kick_success": FakeTelegramAPI.kick_ok}

    def send_message(self, chat_id, text, **kwargs):
        FakeTelegramAPI.calls.append(("message", chat_id))
        return {"ok": True}

    def get_chat_administrators(self, chat_id):
        return FakeTelegramAPI.admins or []


@pytest.fixture
def cleanup(engine, db_session, sub_service, monkeypatch, tmp_path):
    import core.database
    import services.telegram_api
    from jobs import subscription_cleanup

    FakeTelegramAPI.calls = []
    FakeTelegramAPI.kick_ok = True
    FakeTelegramAPI.admins = [{"user": {"id": 1}, "status": "creator"}]
    monkeypatch.setattr(core.database, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(services.telegram_api, "TelegramAPIService", FakeTelegramAPI)
    monkeypatch.setattr(subscription_cleanup, "OUTPUT_DIR", str(tmp_path))
    return subscription_cleanup.SubscriptionCleanupJob(
        telegram_api=FakeTelegramAPI(), subscription_service=sub_service, user_service=None
    )


def add_vip_purchase(db_session, days_ago, price=100.0, user_id=BUYER_ID):
    from models.purchase import Purchase

    paid = datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time())
    db_session.add(Purchase(
        user_telegram_id=user_id, service_id=2, price=price,
        from_channel="telegram", purchase_date=paid,
    ))
    db_session.commit()


class TestCleanup:
    def test_expired_user_is_kicked_once_across_runs(self, db_session, cleanup, buyer):
        add_vip_purchase(db_session, days_ago=60)
        add_sub(db_session, end_offset=-30)

        for _ in range(4):
            cleanup.run_db_only(mode="eliminar")

        kicks = [c for c in FakeTelegramAPI.calls if c[0] == "kick"]
        messages = [c for c in FakeTelegramAPI.calls if c == ("message", BUYER_ID)]
        assert kicks == [("kick", BUYER_ID)]
        assert len(messages) == 1
        (sub,) = subs_of(db_session)
        assert sub.is_active is False

    def test_repair_skips_paid_period_already_over(self, db_session, cleanup, buyer):
        add_vip_purchase(db_session, days_ago=60)  # 30 días pagados, vencidos

        stats = cleanup.run_db_only(mode="eliminar")

        assert stats["repaired"] == 0
        assert subs_of(db_session) == []
        assert FakeTelegramAPI.calls == []

    def test_repair_uses_plan_duration(self, db_session, cleanup, buyer):
        add_vip_purchase(db_session, days_ago=45, price=200.0)  # plan de 3 meses

        stats = cleanup.run_db_only(mode="eliminar")

        assert stats["repaired"] == 1
        (sub,) = subs_of(db_session)
        assert sub.end_date == TODAY - timedelta(days=45) + timedelta(days=90)
        assert FakeTelegramAPI.calls == []

    def test_validar_mode_writes_nothing(self, db_session, cleanup, buyer):
        add_vip_purchase(db_session, days_ago=5)
        add_sub(db_session, user_id=BUYER_ID, end_offset=-1)

        stats = cleanup.run_db_only(mode="validar")

        assert stats["expired"] == 1
        (sub,) = subs_of(db_session)
        assert sub.is_active is True
        assert FakeTelegramAPI.calls == []

    def test_failed_kick_keeps_subscription_for_retry(self, db_session, cleanup, buyer):
        add_sub(db_session, end_offset=-3)
        FakeTelegramAPI.kick_ok = False

        stats = cleanup.run_db_only(mode="eliminar")

        assert stats["kick_failed"] == 1
        assert ("message", BUYER_ID) not in FakeTelegramAPI.calls
        (sub,) = subs_of(db_session)
        assert sub.is_active is True

    def test_valid_and_protected_users_are_not_kicked(
        self, db_session, cleanup, buyer, monkeypatch
    ):
        from models.user import User

        protected_id = 700000099
        db_session.add(User(telegram_id=protected_id, telegram_name="Admin"))
        db_session.commit()
        add_sub(db_session, end_offset=5)  # vigente
        add_sub(db_session, user_id=protected_id, end_offset=-10)
        monkeypatch.setenv("PROTECTED_USER_IDS", str(protected_id))

        stats = cleanup.run_db_only(mode="eliminar")

        assert stats["removed"] == 0
        assert [c for c in FakeTelegramAPI.calls if c[0] == "kick"] == []

    def test_group_admins_are_never_kicked(self, db_session, cleanup, buyer):
        add_sub(db_session, end_offset=-10)
        FakeTelegramAPI.admins = [{"user": {"id": BUYER_ID}, "status": "administrator"}]

        stats = cleanup.run_db_only(mode="eliminar")

        assert stats["removed"] == 0
        assert FakeTelegramAPI.calls == []

    def test_no_kicks_when_admins_cannot_be_fetched(self, db_session, cleanup, buyer):
        add_sub(db_session, end_offset=-10)
        FakeTelegramAPI.admins = None

        stats = cleanup.run_db_only(mode="eliminar")

        assert stats["removed"] == 0
        assert FakeTelegramAPI.calls == []
        (sub,) = subs_of(db_session)
        assert sub.is_active is True


class TestTelethonRemoval:
    """_execute_removal: ruta usada por la limpieza diaria (miembros vía Telethon)."""

    def _run(self, cleanup, tmp_path):
        import asyncio

        import pandas as pd

        to_remove = pd.DataFrame([{
            "user_telegram_id": str(BUYER_ID), "username": "", "first_name": "",
            "servicio": "grupo_vip", "mensaje": "suscripción vencida",
        }])
        return asyncio.run(cleanup._execute_removal(to_remove, to_remove, str(tmp_path), "000000"))

    def test_failed_kick_does_not_deactivate_or_message(self, db_session, cleanup, buyer, tmp_path):
        add_sub(db_session, end_offset=-5)
        FakeTelegramAPI.kick_ok = False

        removed = self._run(cleanup, tmp_path)

        assert removed == 0
        assert ("message", BUYER_ID) not in FakeTelegramAPI.calls
        (sub,) = subs_of(db_session)
        assert sub.is_active is True

    def test_successful_kick_deactivates_then_messages(self, db_session, cleanup, buyer, tmp_path):
        add_sub(db_session, end_offset=-5)

        removed = self._run(cleanup, tmp_path)

        assert removed == 1
        assert FakeTelegramAPI.calls == [("kick", BUYER_ID), ("message", BUYER_ID)]
        (sub,) = subs_of(db_session)
        assert sub.is_active is False

