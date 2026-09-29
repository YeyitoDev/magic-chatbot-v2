"""
Tests de reglas de negocio de pagos - Magic Chatbot v2
=======================================================
Cubre las casuísticas:
- Solo se aceptan montos que correspondan a un precio definido (undefined_price).
- Stake y VIP permiten varias compras; el MISMO comprobante (payment_ref)
  nunca se registra dos veces.
- VIP: cada compra renueva/extiende la suscripción.
- get_recent_purchases_for_service (consulta por servicio).
"""

import pytest

BUYER_ID = 700000001


# ---------------------------------------------------------------------------
# Fixtures locales: catálogo de precios + servicios con pricing dinámico
# ---------------------------------------------------------------------------

@pytest.fixture
def catalog(db_session):
    """Crea los servicios Stake (id=1) y Grupo VIP (id=2) con sus precios."""
    from models.service import Service, ServicePrice

    stake = Service(
        service_id=1, name="Stake", description="Stake", is_subscription=False
    )
    vip = Service(
        service_id=2, name="Grupo VIP", description="VIP", is_subscription=True
    )
    db_session.add_all([stake, vip])
    db_session.flush()

    db_session.add_all(
        [
            ServicePrice(service_id=1, price=50.0, discount=0.0, duration_months=0),
            ServicePrice(service_id=2, price=100.0, discount=10.0, duration_months=1),
            ServicePrice(service_id=2, price=150.0, discount=10.0, duration_months=2),
            ServicePrice(service_id=2, price=200.0, discount=10.0, duration_months=3),
        ]
    )
    db_session.commit()
    return {"stake": stake, "vip": vip}


@pytest.fixture
def pricing_service(service_repo, catalog, monkeypatch, tmp_path):
    """PricingService real sobre el catálogo de test (sin tocar el cache real)."""
    from services import pricing_service as pricing_module

    # Evitar sobrescribir el pricing_cache.json del repositorio.
    monkeypatch.setattr(
        pricing_module, "CACHE_FILE", str(tmp_path / "pricing_cache.json")
    )
    return pricing_module.PricingService(service_repo)


@pytest.fixture
def payment_service_dyn(
    user_repo, service_repo, purchase_repo, subscription_repo, pricing_service
):
    """PaymentService con PricingService inyectado (catálogo dinámico)."""
    from services.payment_service import PaymentService
    from services.subscription_service import SubscriptionService

    sub_service = SubscriptionService(
        user_repo=user_repo,
        service_repo=service_repo,
        purchase_repo=purchase_repo,
        subscription_repo=subscription_repo,
        pricing_service=pricing_service,
    )
    return PaymentService(
        purchase_repo=purchase_repo,
        subscription_service=sub_service,
        user_repo=user_repo,
        pricing_service=pricing_service,
    )


@pytest.fixture
def buyer(db_session):
    """Usuario comprador de prueba."""
    from models.user import User

    user = User(telegram_id=BUYER_ID, telegram_name="Buyer")
    db_session.add(user)
    db_session.commit()
    return user


# ---------------------------------------------------------------------------
# Regla: monto debe corresponder a un precio definido
# ---------------------------------------------------------------------------

class TestDefinedPriceRule:
    def test_rejects_undefined_price(self, payment_service_dyn, buyer):
        result = payment_service_dyn.validate_payment(
            telegram_id=buyer.telegram_id, amount=77.0
        )
        assert result.success is False
        assert "undefined_price" in result.errors

    def test_is_defined_price_helper(self, payment_service_dyn):
        assert payment_service_dyn.is_defined_price(50.0) is True   # Stake
        assert payment_service_dyn.is_defined_price(100.0) is True  # VIP 1 mes
        assert payment_service_dyn.is_defined_price(77.0) is False  # no definido

    def test_accepts_stake_defined_price(self, payment_service_dyn, buyer):
        result = payment_service_dyn.validate_payment(
            telegram_id=buyer.telegram_id, amount=50.0
        )
        assert result.success is True
        assert result.service_type == "stake"


# ---------------------------------------------------------------------------
# Regla: Stake máximo 1 por día
# ---------------------------------------------------------------------------

class TestStakeDailyLimit:
    def test_second_stake_allowed_same_voucher_blocked(self, payment_service_dyn, buyer):
        first = payment_service_dyn.validate_payment(
            telegram_id=buyer.telegram_id, amount=50.0, payment_ref="tg:voucher-1"
        )
        other_voucher = payment_service_dyn.validate_payment(
            telegram_id=buyer.telegram_id, amount=50.0, payment_ref="tg:voucher-2"
        )
        same_voucher = payment_service_dyn.validate_payment(
            telegram_id=buyer.telegram_id, amount=50.0, payment_ref="tg:voucher-1"
        )
        assert first.success is True
        assert other_voucher.success is True
        assert same_voucher.success is False
        assert same_voucher.is_duplicate is True
        assert "duplicate_payment_ref" in same_voucher.errors

    def test_check_duplicate_true_after_stake(self, payment_service_dyn, buyer):
        payment_service_dyn.validate_payment(
            telegram_id=buyer.telegram_id, amount=50.0
        )
        assert payment_service_dyn.check_duplicate_payment(buyer.telegram_id, 50.0) is True


# ---------------------------------------------------------------------------
# Regla: VIP ilimitado (renovación de suscripción)
# ---------------------------------------------------------------------------

class TestVipUnlimited:
    def test_multiple_vip_purchases_allowed(self, payment_service_dyn, buyer):
        first = payment_service_dyn.validate_payment(
            telegram_id=buyer.telegram_id, amount=100.0
        )
        second = payment_service_dyn.validate_payment(
            telegram_id=buyer.telegram_id, amount=100.0
        )
        assert first.success is True
        assert second.success is True
        assert second.is_duplicate is False

    def test_vip_never_flagged_duplicate(self, payment_service_dyn, buyer):
        payment_service_dyn.validate_payment(
            telegram_id=buyer.telegram_id, amount=100.0
        )
        assert payment_service_dyn.check_duplicate_payment(buyer.telegram_id, 100.0) is False

    def test_vip_renewal_extends_subscription(
        self, payment_service_dyn, buyer, subscription_repo
    ):
        # Dos compras de 1 mes (30 días) deben acumular 60 días.
        payment_service_dyn.validate_payment(
            telegram_id=buyer.telegram_id, amount=100.0
        )
        payment_service_dyn.validate_payment(
            telegram_id=buyer.telegram_id, amount=100.0
        )
        sub = subscription_repo.get_sub_by_user_and_service(
            user_telegram_id=buyer.telegram_id, service_id=2
        )
        assert sub is not None
        assert (sub.end_date - sub.start_date).days == 60


# ---------------------------------------------------------------------------
# Repositorio: consulta de compras recientes por servicio
# ---------------------------------------------------------------------------

class TestPurchaseRepoByService:
    def test_get_recent_purchases_for_service(self, purchase_repo, buyer, catalog):
        purchase_repo.create_purchase(
            user_telegram_id=buyer.telegram_id,
            service_id=1,
            price=50.0,
            from_channel="telegram",
        )
        stake_recent = purchase_repo.get_recent_purchases_for_service(
            buyer.telegram_id, service_id=1, hours=24
        )
        vip_recent = purchase_repo.get_recent_purchases_for_service(
            buyer.telegram_id, service_id=2, hours=24
        )
        assert len(stake_recent) == 1
        assert vip_recent == []


# ---------------------------------------------------------------------------
# Regla: el monto debe caer en el rango [price - discount, price] de un plan
# ---------------------------------------------------------------------------

class TestStrictPriceValidation:
    def test_amount_outside_plan_ranges_rejected(self, payment_service_dyn, buyer):
        # Rangos VIP: 90–100, 140–150, 190–200. 120 no cae en ninguno.
        assert payment_service_dyn.is_defined_price(120.0) is False
        result = payment_service_dyn.validate_payment(
            telegram_id=buyer.telegram_id, amount=120.0
        )
        assert result.success is False
        assert "undefined_price" in result.errors

    def test_amount_within_discount_range_accepted(self, payment_service_dyn):
        assert payment_service_dyn.is_defined_price(93.0) is True

    def test_effective_price_accepted(self, payment_service_dyn, buyer):
        # El precio efectivo (price - discount = 90) sí es válido.
        assert payment_service_dyn.is_defined_price(90.0) is True
        result = payment_service_dyn.validate_payment(
            telegram_id=buyer.telegram_id, amount=90.0
        )
        assert result.success is True
        assert result.service_type == "grupo_vip"


# ---------------------------------------------------------------------------
# Atomicidad: si falla la suscripción, NO debe quedar compra registrada
# ---------------------------------------------------------------------------

class TestAtomicPurchase:
    def test_subscription_failure_rolls_back_purchase(
        self, payment_service_dyn, buyer, purchase_repo, monkeypatch
    ):
        def _boom(*args, **kwargs):
            raise RuntimeError("fallo simulado al crear suscripción")

        monkeypatch.setattr(
            payment_service_dyn._subscription_service,
            "_create_or_extend_subscription",
            _boom,
        )

        result = payment_service_dyn.validate_payment(
            telegram_id=buyer.telegram_id, amount=100.0
        )

        assert result.success is False
        assert "purchase_transaction_failed" in result.errors

        # La compra NO debe haber quedado registrada (rollback atómico).
        vip_purchases = purchase_repo.get_recent_purchases_for_service(
            buyer.telegram_id, service_id=2, hours=24
        )
        assert vip_purchases == []
