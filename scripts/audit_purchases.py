"""
Script para auditar purchases del último mes buscando casos inválidos.

Casos a buscar:
1. Montos que no corresponden a precios válidos (125, 175, 225 para VIP)
2. Service_id que no coincide con el monto (ej: monto VIP pero service_id Stake)
3. Montos muy bajos o inválidos (< 10 soles)
"""

import sys
from pathlib import Path

# Agregar el directorio del proyecto al sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Cargar explícitamente el archivo .env.production para conectar a producción
from dotenv import load_dotenv

env_file = project_root / ".env.production"
load_dotenv(env_file)

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from config.settings import settings
from core.database import SessionLocal
from models.purchase import Purchase
from models.user import User


def audit_purchases():
    """Audita purchases del último mes buscando casos inválidos."""

    db: Session = SessionLocal()

    try:
        print(f"{'='*70}")
        print("AUDITORÍA DE PURCHASES - ÚLTIMO MES")
        print(f"{'='*70}")
        print(f"Entorno: {settings.ENVIRONMENT}")
        print(f"Database: {settings.DB_HOST}")
        print(f"{'='*70}\n")

        # Calcular fecha de hace 1 mes
        one_month_ago = datetime.now() - timedelta(days=30)

        # Precios válidos para VIP
        valid_vip_prices = [125.0, 175.0, 225.0]

        # Buscar todos los purchases del último mes
        purchases = db.query(Purchase).filter(
            Purchase.purchase_date >= one_month_ago
        ).order_by(Purchase.purchase_date.desc()).all()

        print(f"📊 Total purchases en el último mes: {len(purchases)}\n")

        # Casos sospechosos
        invalid_amounts = []
        service_mismatch = []
        very_low_amounts = []

        for purchase in purchases:
            # Caso 1: Montos muy bajos (< 10 soles)
            if purchase.price < 10.0:
                very_low_amounts.append(purchase)

            # Caso 2: Montos que no corresponden a precios válidos
            is_valid_vip = purchase.price in valid_vip_prices
            is_vip_service = purchase.service_id == 2
            is_stake_service = purchase.service_id == 1

            # Si es service VIP pero monto no es válido
            if is_vip_service and not is_valid_vip:
                invalid_amounts.append(purchase)

            # Si el monto corresponde a VIP pero el service es Stake
            if is_valid_vip and is_stake_service:
                service_mismatch.append(purchase)

        # Reportar resultados
        print("🔍 CASOS SOSPECHOSOS ENCONTRADOS:\n")

        if very_low_amounts:
            print(f"⚠️  MONTOS MUY BAJOS (< 10 soles): {len(very_low_amounts)}")
            print(f"{'-'*70}")
            for p in very_low_amounts:
                user = db.query(User).filter(User.telegram_id == p.user_telegram_id).first()
                user_name = user.telegram_name if user else "N/A"
                print(f"   - ID: {p.purchase_id} | User: {p.user_telegram_id} ({user_name}) | "
                      f"Price: S/ {p.price} | Service: {p.service_id} | Date: {p.purchase_date}")
            print()

        if invalid_amounts:
            print(f"⚠️  VIP CON MONTO INVÁLIDO: {len(invalid_amounts)}")
            print(f"{'-'*70}")
            for p in invalid_amounts:
                user = db.query(User).filter(User.telegram_id == p.user_telegram_id).first()
                user_name = user.telegram_name if user else "N/A"
                print(f"   - ID: {p.purchase_id} | User: {p.user_telegram_id} ({user_name}) | "
                      f"Price: S/ {p.price} | Service: {p.service_id} | Date: {p.purchase_date}")
            print()

        if service_mismatch:
            print(f"⚠️  MONTO VIP PERO SERVICE STAKE: {len(service_mismatch)}")
            print(f"{'-'*70}")
            for p in service_mismatch:
                user = db.query(User).filter(User.telegram_id == p.user_telegram_id).first()
                user_name = user.telegram_name if user else "N/A"
                print(f"   - ID: {p.purchase_id} | User: {p.user_telegram_id} ({user_name}) | "
                      f"Price: S/ {p.price} | Service: {p.service_id} | Date: {p.purchase_date}")
            print()

        if not very_low_amounts and not invalid_amounts and not service_mismatch:
            print("✅ No se encontraron casos sospechosos.")

        # Resumen
        total_suspicious = len(very_low_amounts) + len(invalid_amounts) + len(service_mismatch)
        print(f"\n{'='*70}")
        print("📋 RESUMEN:")
        print(f"   - Total purchases: {len(purchases)}")
        print(f"   - Casos sospechosos: {total_suspicious}")
        print(f"   - Montos muy bajos: {len(very_low_amounts)}")
        print(f"   - VIP con monto inválido: {len(invalid_amounts)}")
        print(f"   - Monto VIP pero service Stake: {len(service_mismatch)}")
        print(f"{'='*70}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    audit_purchases()
