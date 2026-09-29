#!/usr/bin/env python3
"""
Script para crear manualmente usuario, compra y suscripción
"""
import sys

sys.path.append('.')

from datetime import datetime

from core.database import SessionLocal
from repositories.purchase_repo import PurchaseRepository
from repositories.subscription_repo import SubscriptionRepository
from repositories.user_repo import UserRepository


def create_manual_purchase(
    telegram_id: int,
    telegram_name: str,
    amount: float,
    purchase_date: str,
    service_type: str,
    months: int = 3
):
    session = SessionLocal()

    try:
        user_repo = UserRepository(session)
        purchase_repo = PurchaseRepository(session)
        sub_repo = SubscriptionRepository(session)

        # 1. Registrar usuario
        user = user_repo.get_by_telegram_id(telegram_id)
        if not user:
            user = user_repo.create(
                telegram_id=telegram_id,
                telegram_name=telegram_name,
            )
            print(f"✅ Usuario creado: {user.telegram_name} (Telegram ID: {user.telegram_id})")
        else:
            print(f"ℹ️ Usuario ya existe: {user.telegram_name} (Telegram ID: {user.telegram_id})")

        # 2. Determinar service_id (1=Stake, 2=VIP)
        service_id = 2 if service_type == "Grupo VIP" else 1

        # 3. Crear compra
        purchase = purchase_repo.create_purchase(
            user_telegram_id=user.telegram_id,
            service_id=service_id,
            price=amount,
            from_channel="telegram",
            purchase_date=datetime.strptime(purchase_date, "%Y-%m-%d"),
            commit=False,
        )
        print(f"✅ Compra creada: S/ {amount:.2f} el {purchase_date}")

        # 4. Crear suscripción desde la compra
        duration_days = 30 * months
        subscription = sub_repo.create_from_purchase(purchase, duration_days)
        print(f"✅ Suscripción creada: {service_type} ({months} meses)")
        print(f"   - Inicio: {subscription.start_date}")
        print(f"   - Fin: {subscription.end_date}")
        print(f"   - Estado: {'Activa' if subscription.is_active else 'Inactiva'}")

        session.commit()
        print("\n✅ Proceso completado exitosamente")

    except Exception as e:
        session.rollback()
        print(f"❌ Error: {e}")
        raise
    finally:
        session.close()

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Uso: python scripts/create_manual_purchase.py <telegram_id> <nombre> <monto> <fecha> [meses]")
        print("Ejemplo: python scripts/create_manual_purchase.py 123456789 'Usuario' 225 2026-06-12 3")
        sys.exit(1)

    telegram_id = int(sys.argv[1])
    telegram_name = sys.argv[2]
    amount = float(sys.argv[3])
    purchase_date = sys.argv[4]
    months = int(sys.argv[5]) if len(sys.argv) > 5 else 3

    # S/ 225 corresponde a VIP 3 meses
    service_type = "Grupo VIP" if amount == 225 else "Stake"

    create_manual_purchase(telegram_id, telegram_name, amount, purchase_date, service_type, months)
