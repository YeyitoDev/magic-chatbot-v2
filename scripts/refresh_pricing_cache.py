"""
Script para refrescar el caché de precios desde la base de datos.

Esto fuerza a PricingService a recargar los precios desde la BD
y actualizar el archivo pricing_cache.json.
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

from config.settings import settings
from core.database import SessionLocal
from repositories.service_repo import ServiceRepository
from services.pricing_service import get_pricing_service


def refresh_cache():
    """Refresca el caché de precios desde la base de datos."""

    print(f"{'='*70}")
    print("REFRESCANDO CACHÉ DE PRECIOS")
    print(f"{'='*70}")
    print(f"Entorno: {settings.ENVIRONMENT}")
    print(f"Database: {settings.DB_HOST}")
    print(f"{'='*70}\n")

    # Crear sesión y repositorio
    db = SessionLocal()
    service_repo = ServiceRepository(db)

    try:
        # Obtener instancia de PricingService
        pricing_service = get_pricing_service(service_repo)

        # Mostrar estado actual del caché
        cache_age = pricing_service.get_cache_age_seconds()
        print(f"📊 Edad actual del caché: {cache_age:.0f} segundos ({cache_age/3600:.1f} horas)")

        # Forzar refresh
        print("\n🔄 Forzando refresh del caché...")
        pricing_service.refresh_cache()

        # Mostrar nuevo estado
        new_cache_age = pricing_service.get_cache_age_seconds()
        print(f"✅ Caché refrescado: {new_cache_age:.0f} segundos")

        # Mostrar precios cacheados
        print("\n📋 PRECIOS CACHEADOS:\n")
        all_prices = pricing_service.get_all_prices()

        for p in all_prices:
            service_name = "VIP" if p.service_id == 2 else "Stake"
            print(f"   ID: {p.service_price_id} | {service_name} | "
                  f"Base: S/ {p.price} | Desc: S/ {p.discount} | "
                  f"Efectivo: S/ {p.price - p.discount} | "
                  f"Duración: {p.duration_months} {'mes' if p.duration_months == 1 else 'meses' if p.duration_months > 1 else 'único'}")

        print(f"\n{'='*70}")
        print("✅ Caché refrescado exitosamente")
        print(f"{'='*70}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    refresh_cache()
