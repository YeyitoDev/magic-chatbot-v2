#!/usr/bin/env python3
"""
Validación de usuarios "sin registro BD" reportados por cleanup job.
==================================================================
Recibe IDs de Telegram de usuarios sospechosos y verifica:
1. Si están registrados en tabla users
2. Si tienen compras registradas
3. Si tienen suscripciones (activas o vencidas)
4. Si tienen alguna compra VIP (grupo_vip) sin sub activa

Uso:
    .venv/bin/python scripts/validate_special_users.py 12345 67890 11111 ...

O interactivo (sin args):
    .venv/bin/python scripts/validate_special_users.py
    # Luego pegar los IDs separados por espacio o coma
"""

import os
import sys
from datetime import date

import pymysql
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "charset": "utf8mb4",
}


def validate_user(conn, telegram_id: int) -> dict:
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        # 1. ¿Registrado en users?
        cur.execute("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
        user = cur.fetchone()

        # 2. Compras
        cur.execute(
            """SELECT p.*, s.name as service_name
               FROM purchases p
               JOIN services s ON p.service_id = s.service_id
               WHERE p.user_telegram_id = %s
               ORDER BY p.purchase_date DESC""",
            (telegram_id,),
        )
        purchases = cur.fetchall()

        # 3. Suscripciones
        cur.execute(
            "SELECT * FROM subscriptions WHERE user_telegram_id = %s ORDER BY end_date DESC",
            (telegram_id,),
        )
        subscriptions = cur.fetchall()

    # Clasificar
    vip_purchases = [p for p in purchases if p["service_name"] == "grupo_vip"]
    stake_purchases = [p for p in purchases if p["service_name"] == "stake"]

    active_subs = [s for s in subscriptions if s["is_active"] and s["end_date"] >= date.today()]
    expired_subs = [s for s in subscriptions if s["end_date"] < date.today()]

    return {
        "telegram_id": telegram_id,
        "registered": user is not None,
        "user_name": user["telegram_name"] if user else None,
        "total_purchases": len(purchases),
        "vip_purchases": vip_purchases,
        "stake_purchases": stake_purchases,
        "active_subs": active_subs,
        "expired_subs": expired_subs,
        "all_subs": subscriptions,
    }


def print_result(r: dict):
    uid = r["telegram_id"]
    name = r["user_name"] or "—sin nombre—"
    print(f"\n{'='*70}")
    print(f"👤 User {uid} – {name}")
    print(f"{'='*70}")

    if not r["registered"]:
        print("   ❌ NO registrado en tabla 'users'")
    else:
        print("   ✅ Registrado en BD")

    if not r["total_purchases"]:
        print("   ❌ Sin compras registradas")
    else:
        print(f"   📦 Compras totales: {r['total_purchases']}")
        if r["vip_purchases"]:
            print(f"      → VIP: {len(r['vip_purchases'])}")
            for p in r["vip_purchases"][:3]:
                print(f"         S/ {p['price']:.2f} | {p['purchase_date']} | {p['from_channel']}")
        if r["stake_purchases"]:
            print(f"      → Stake: {len(r['stake_purchases'])}")

    if r["active_subs"]:
        print(f"   ✅ Suscripciones activas: {len(r['active_subs'])}")
        for s in r["active_subs"]:
            print(f"      → servicio {s['service_id']} | {s['start_date']} → {s['end_date']}")
    elif r["expired_subs"]:
        print(f"   🗑️  Suscripciones vencidas: {len(r['expired_subs'])}")
        for s in r["expired_subs"][:3]:
            print(f"      → servicio {s['service_id']} | {s['start_date']} → {s['end_date']}")
    else:
        print("   ❌ Sin suscripciones")

    # Diagnóstico final
    if not r["registered"] and not r["total_purchases"]:
        print("   🚨 DIAGNÓSTICO: Usuario en el grupo pero NUNCA compró. Posible intruso.")
    elif r["vip_purchases"] and not r["active_subs"]:
        print("   🚨 DIAGNÓSTICO: Compró VIP pero NO tiene suscripción activa. Requiere recreación.")
    elif r["stake_purchases"] and not r["all_subs"]:
        print("   ℹ️  DIAGNÓSTICO: Solo compró Stake (pago único, no requiere suscripción). Normal.")
    elif r["active_subs"]:
        print("   ✅ DIAGNÓSTICO: Todo en orden. Tiene suscripción activa.")
    else:
        print("   ⚠️  DIAGNÓSTICO: Sin compras ni suscripción. Requiere investigación.")


def main():
    if len(sys.argv) > 1:
        # Args: python script.py 123 456 789
        ids_raw = sys.argv[1:]
    else:
        # Interactivo
        raw = input("Pega los IDs de Telegram separados por espacio o coma:\n> ").strip()
        ids_raw = raw.replace(",", " ").split()

    ids = []
    for s in ids_raw:
        try:
            ids.append(int(s.strip()))
        except ValueError:
            print(f"Ignorando valor no numérico: {s!r}")

    if not ids:
        print("No se proporcionaron IDs válidos.")
        sys.exit(1)

    conn = pymysql.connect(**DB_CONFIG)
    print(f"\nValidando {len(ids)} usuario(s) contra la BD de producción...")

    for uid in ids:
        result = validate_user(conn, uid)
        print_result(result)

    conn.close()
    print(f"\n{'='*70}")
    print("Validación completa.")
    print("=" * 70)


if __name__ == "__main__":
    main()
