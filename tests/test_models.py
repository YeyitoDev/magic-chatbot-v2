"""Tests for SQLAlchemy models."""

from datetime import date


class TestUserModel:
    def test_create_user(self, db_session):
        from models.user import User
        user = User(telegram_id=123456789, telegram_name="Test User")
        db_session.add(user)
        db_session.commit()

        assert user.telegram_id == 123456789
        assert user.telegram_name == "Test User"

    def test_get_user_by_id(self, db_session, user_repo):
        from models.user import User
        user = User(telegram_id=999999, telegram_name="Repo Test")
        db_session.add(user)
        db_session.commit()

        found = user_repo.get_by_telegram_id(999999)
        assert found is not None
        assert found.telegram_name == "Repo Test"


class TestServiceModel:
    def test_create_service(self, db_session):
        from models.service import Service
        service = Service(name="Test Service", description="Test", is_subscription=True)
        db_session.add(service)
        db_session.commit()

        assert service.name == "Test Service"
        assert service.is_subscription is True

    def test_service_price_effective(self, db_session):
        from models.service import Service, ServicePrice
        service = Service(name="Price Test", description="Test", is_subscription=True)
        db_session.add(service)
        db_session.flush()

        price = ServicePrice(service_id=service.service_id, price=100.0, discount=10.0, duration_months=1)
        db_session.add(price)
        db_session.commit()

        assert price.effective_price == 90.0
        assert price.duration_months == 1


class TestSubscriptionModel:
    def test_subscription_is_active(self, db_session):
        from datetime import timedelta

        from models.service import Service
        from models.subscription import Subscription
        from models.user import User

        user = User(telegram_id=888888, telegram_name="Sub Test")
        service = Service(name="VIP Test", description="Test", is_subscription=True)
        db_session.add_all([user, service])
        db_session.flush()

        today = date.today()
        sub = Subscription(
            subscription_id=1,
            user_telegram_id=888888,
            service_id=service.service_id,
            start_date=today,
            end_date=today + timedelta(days=30),
        )
        db_session.add(sub)
        db_session.commit()

        assert sub.is_active is True   # columna: default=True
        assert sub.is_valid is True    # propiedad: end_date >= hoy
        assert sub.days_remaining >= 29

    def test_subscription_expired(self, db_session):
        from datetime import timedelta

        from models.service import Service
        from models.subscription import Subscription
        from models.user import User

        user = User(telegram_id=999888, telegram_name="Expired Test")
        service = Service(name="VIP Expired", description="Test", is_subscription=True)
        db_session.add_all([user, service])
        db_session.flush()

        today = date.today()
        sub = Subscription(
            subscription_id=2,
            user_telegram_id=999888,
            service_id=service.service_id,
            start_date=today - timedelta(days=60),
            end_date=today - timedelta(days=30),
        )
        db_session.add(sub)
        db_session.commit()

        assert sub.is_active is True   # columna: sigue True hasta que se marque inactiva
        assert sub.is_valid is False   # propiedad: end_date < hoy
        assert sub.days_remaining < 0
