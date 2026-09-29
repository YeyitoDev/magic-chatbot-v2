"""
Seed test data for subscription cleanup testing.
Creates users with various subscription states:
- Active subs (should NOT be removed)
- Expired subs (should be removed in 'eliminar' mode)
- Users without subs (should be flagged as special clients)
"""

import sys

sys.path.insert(0, '.')

from datetime import date, timedelta

from core.database import SessionLocal
from models.purchase import Purchase
from models.service import Service
from models.subscription import Subscription
from models.user import User

session = SessionLocal()

# Clean existing test data
session.query(Subscription).filter(
    Subscription.user_telegram_id.in_([111111, 222222, 333333, 444444, 555555])
).delete()
session.query(Purchase).filter(
    Purchase.user_telegram_id.in_([111111, 222222, 333333, 444444, 555555])
).delete()
session.query(User).filter(
    User.telegram_id.in_([111111, 222222, 333333, 444444, 555555])
).delete()
session.commit()

# Get services
vip = session.query(Service).filter_by(name="Grupo VIP").first()
if not vip:
    vip = Service(name="Grupo VIP", description="VIP", is_subscription=True)
    session.add(vip)
    session.flush()

stake = session.query(Service).filter_by(name="Stake").first()
if not stake:
    stake = Service(name="Stake", description="Stake", is_subscription=False)
    session.add(stake)
    session.flush()

today = date.today()

# ===== TEST DATA =====

# 1. User with ACTIVE subscription (should survive)
u1 = User(telegram_id=111111, telegram_name="Test Activo VIP")
session.add(u1)
sub1 = Subscription(user_telegram_id=111111, service_id=vip.service_id,
                    start_date=today - timedelta(days=15),
                    end_date=today + timedelta(days=15))
session.add(sub1)
print("✅ 111111 - Suscripción ACTIVA (30 días, vence en 15 días)")

# 2. User with EXPIRED subscription (should be removed)
u2 = User(telegram_id=222222, telegram_name="Test Expirado VIP")
session.add(u2)
sub2 = Subscription(user_telegram_id=222222, service_id=vip.service_id,
                    start_date=today - timedelta(days=45),
                    end_date=today - timedelta(days=15))
session.add(sub2)
print("❌ 222222 - Suscripción EXPIRADA (venció hace 15 días)")

# 3. User EXPIRED 60 days ago (should be removed)
u3 = User(telegram_id=333333, telegram_name="Test Muy Expirado")
session.add(u3)
sub3 = Subscription(user_telegram_id=333333, service_id=vip.service_id,
                    start_date=today - timedelta(days=90),
                    end_date=today - timedelta(days=60))
session.add(sub3)
print("❌ 333333 - Suscripción muy EXPIRADA (venció hace 60 días)")

# 4. User WITHOUT subscription (special client - not in DB)
# This user exists in the Telegram group but not in our DB
# We don't insert a User record - it simulates a user in the group without DB record
print("⚠️ 444444 - Sin registro en BD (cliente especial)")

# 5. User with Stake (one-time purchase, no subscription)
u5 = User(telegram_id=555555, telegram_name="Test Stake User")
session.add(u5)
p5 = Purchase(user_telegram_id=555555, service_id=stake.service_id,
              purchase_date=today - timedelta(days=30),
              price=50.0, from_channel="telegram")
session.add(p5)
print("ℹ️ 555555 - Usuario Stake (compra única, sin suscripción)")

session.commit()
session.close()

print("\n📊 Datos de prueba insertados:")
print("  111111 = Activo (NO eliminar)")
print("  222222 = Expirado (ELIMINAR)")
print("  333333 = Muy expirado (ELIMINAR)")
print("  444444 = No registrado (CLIENTE ESPECIAL)")
print("  555555 = Stake (según lógica)")
print("\nEjecutá: python -m jobs.subscription_cleanup validar")
