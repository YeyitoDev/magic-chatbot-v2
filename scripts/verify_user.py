#!/usr/bin/env python3
"""
Script para verificar usuario, compra y suscripción
"""
import sys

sys.path.append('.')

from datetime import datetime

from core.database import SessionLocal
from repositories.purchase_repo import PurchaseRepository
from repositories.subscription_repo import SubscriptionRepository
from repositories.user_repo import UserRepository


def verify_user(telegram_id: int):
    session = SessionLocal()

    try:
        user_repo = UserRepository(session)
        sub_repo = SubscriptionRepository(session)
        purchase_repo = PurchaseRepository(session)

        # 1. Verificar usuario
        user = user_repo.get_by_telegram_id(telegram_id)
        if not user:
            print(f"❌ Usuario {telegram_id} NO encontrado en la base de datos")
            return

        print("✅ Usuario encontrado:")
        print(f"   - Telegram ID: {user.telegram_id}")
        print(f"   - Nombre: {user.telegram_name}")
        print()

        # 2. Verificar compras
        purchases = purchase_repo.get_by_user_id(user.telegram_id)
        if not purchases:
            print("❌ No hay compras registradas para este usuario")
            return

        print(f"📋 Compras registradas ({len(purchases)}):")
        for purchase in purchases:
            print(f"   - ID: {purchase.purchase_id}")
            print(f"   - Monto: S/ {purchase.price:.2f}")
            print(f"   - Fecha: {purchase.purchase_date}")
            print(f"   - Canal: {purchase.from_channel}")
            print(f"   - Servicio ID: {purchase.service_id}")
            print()

        # 3. Verificar suscripciones
        subscriptions = sub_repo.get_active_sub(user.telegram_id)
        if not subscriptions:
            print("❌ No hay suscripciones activas para este usuario")
            return

        print(f"📋 Suscripciones ({len(subscriptions)}):")
        for sub in subscriptions:
            print(f"   - Servicio ID: {sub.service_id}")
            print(f"   - Estado: {'Activa' if sub.is_active else 'Inactiva'}")
            print(f"   - Inicio: {sub.start_date}")
            print(f"   - Fin: {sub.end_date}")
            print()

        # 4. Buscar compra específica del 12-06-2026 por 225
        target_date = datetime(2026, 6, 12).date()
        target_amount = 225.0

        found_purchase = None
        for purchase in purchases:
            purchase_date = purchase.purchase_date.date() if hasattr(purchase.purchase_date, 'date') else purchase.purchase_date
            if purchase_date == target_date and abs(purchase.price - target_amount) < 0.01:
                found_purchase = purchase
                break

        if found_purchase:
            print("✅ Compra del 12-06-2026 por S/ 225 encontrada:")
            print(f"   - ID pago: {found_purchase.purchase_id}")
            print(f"   - Servicio ID: {found_purchase.service_id}")
        else:
            print("❌ No se encontró compra del 12-06-2026 por S/ 225")

    finally:
        session.close()

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python scripts/verify_user.py <telegram_id>")
        sys.exit(1)

    telegram_id = int(sys.argv[1])
    verify_user(telegram_id)
