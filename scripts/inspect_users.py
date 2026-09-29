#!/usr/bin/env python3
"""
Inspector de usuarios específicos – Grupo VIP
=============================================
Para una lista de user_telegram_id, muestra:
  - Datos del usuario (tabla users)
  - TODAS sus compras (cualquier servicio, con estado/precio/fecha/canal)
  - TODAS sus suscripciones (activas y vencidas)
  - Un diagnóstico: ¿tiene compra VIP?, ¿sub VIP activa?, ¿debería estar afuera?

Opcionalmente (CREATE_SUBS=true) REPARA a los usuarios que tienen una compra
VIP válida pero sin suscripción, creando la suscripción a partir de su última
compra VIP (duración según lo pagado; fallback 30 días).

Variables de entorno:
  USER_IDS      Lista de telegram_id separados por coma (obligatorio).
  CREATE_SUBS   "true" para crear suscripciones faltantes (default: false).
  DB_*          Credenciales de la base de datos.

Uso:
  USER_IDS="123,456" .venv/bin/python scripts/inspect_users.py
"""

import os
import time
from datetime import date, timedelta

import pymysql
import requests
from dotenv import load_dotenv

load_dotenv()

USER_IDS = [uid.strip() for uid in os.getenv("USER_IDS", "").split(",") if uid.strip()]
CREATE_SUBS = os.getenv("CREATE_SUBS", "false").strip().lower() == "true"
# Si es true, expulsa (kick + unban) a los usuarios diagnosticados como
# "deberían estar afuera" (sin compra/sub VIP vigente). Salvaguarda extra:
# nunca toca IDs protegidos.
KICK_OUT = os.getenv("KICK_OUT", "false").strip().lower() == "true"
VIP_SERVICE_ID = 2  # grupo_vip

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
VIP_GROUP_ID = os.getenv("TELEGRAM_VIP_GROUP_ID", "")

# IDs SIEMPRE protegidos (admins/bots/validadores). Nunca expulsar.
PROTECTED_IDS: set[int] = set()
for _var in ("PROTECTED_USER_IDS", "ADMIN_NOTIFY_IDS", "TELEGRAM_VALIDATOR_IDS"):
    for _vid in (os.getenv(_var, "") or "").split(","):
        _vid = _vid.strip()
        if _vid.isdigit():
            PROTECTED_IDS.add(int(_vid))

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "charset": "utf8mb4",
    "connect_timeout": 10,
}


def kick_user(user_id: int) -> bool:
    """Expulsa a un usuario permitiéndole re-unirse (ban + unban)."""
    base = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
    try:
        resp = requests.post(
            f"{base}/banChatMember",
            data={"chat_id": VIP_GROUP_ID, "user_id": user_id},
            timeout=30,
        )
        if not resp.json().get("ok"):
            return False
        requests.post(
            f"{base}/unbanChatMember",
            data={"chat_id": VIP_GROUP_ID, "user_id": user_id, "only_if_banned": True},
            timeout=30,
        )
        return True
    except Exception as e:
        print(f"   ✗ Error al expulsar {user_id}: {e}")
        return False


def get_vip_duration_days(cur, price: float) -> int:
    """
    Determina la duración (días) de una suscripción VIP a partir del precio
    pagado, buscando en service_prices el plan cuyo precio coincida.
    Fallback: 30 días si no hay coincidencia.
    """
    try:
        cur.execute(
            """
            SELECT duration_months
            FROM service_prices
            WHERE service_id = %s AND price = %s
            ORDER BY duration_months DESC
            LIMIT 1
            """,
            (VIP_SERVICE_ID, price),
        )
        row = cur.fetchone()
        if row and row.get("duration_months"):
            return int(row["duration_months"]) * 30
    except Exception as e:
        print(f"   (aviso: no se pudo leer service_prices: {e})")
    return 30


def main():
    if not USER_IDS:
        print("❌ No se pasaron USER_IDS.")
        return

    conn = pymysql.connect(**DB_CONFIG)
    cur = conn.cursor(pymysql.cursors.DictCursor)
    today = date.today()

    should_be_out = []
    repaired = []
    legit = []

    for uid in USER_IDS:
        print("=" * 70)
        # Usuario
        cur.execute(
            "SELECT telegram_id, telegram_name FROM users WHERE telegram_id = %s",
            (uid,),
        )
        u = cur.fetchone()
        name = u["telegram_name"] if u else "(NO REGISTRADO)"
        print(f"👤 {uid} – {name}")

        # Compras (todos los servicios)
        cur.execute(
            """
            SELECT p.purchase_id, p.service_id, s.name AS service_name,
                   p.price, p.purchase_date, p.from_channel, p.status
            FROM purchases p
            LEFT JOIN services s ON p.service_id = s.service_id
            WHERE p.user_telegram_id = %s
            ORDER BY p.purchase_date DESC
            """,
            (uid,),
        )
        purchases = cur.fetchall()

        # Suscripciones (todas)
        cur.execute(
            """
            SELECT sub.subscription_id, sub.service_id, s.name AS service_name,
                   sub.start_date, sub.end_date, sub.is_active
            FROM subscriptions sub
            LEFT JOIN services s ON sub.service_id = s.service_id
            WHERE sub.user_telegram_id = %s
            ORDER BY sub.end_date DESC
            """,
            (uid,),
        )
        subs = cur.fetchall()

        print(f"\n   🧾 Compras ({len(purchases)}):")
        if not purchases:
            print("      (ninguna)")
        for p in purchases:
            print(
                f"      #{p['purchase_id']} · {p['service_name']} "
                f"(sid={p['service_id']}) · S/ {p['price']:.2f} · "
                f"{p['purchase_date']} · {p['from_channel']} · {p['status']}"
            )

        print(f"\n   📆 Suscripciones ({len(subs)}):")
        if not subs:
            print("      (ninguna)")
        for s in subs:
            estado = "VIGENTE" if (s["end_date"] and s["end_date"] >= today) else "VENCIDA"
            print(
                f"      #{s['subscription_id']} · {s['service_name']} "
                f"(sid={s['service_id']}) · {s['start_date']} → {s['end_date']} · "
                f"activa={s['is_active']} · {estado}"
            )

        # Análisis VIP
        vip_purchases = [p for p in purchases if p["service_id"] == VIP_SERVICE_ID]
        vip_subs = [s for s in subs if s["service_id"] == VIP_SERVICE_ID]
        active_vip_subs = [
            s for s in vip_subs if s["end_date"] and s["end_date"] >= today and s["is_active"]
        ]

        print("\n   🔎 Diagnóstico:")
        if active_vip_subs:
            print("      ✅ Tiene suscripción VIP VIGENTE → legítimo, se queda.")
            legit.append(uid)
        elif vip_purchases:
            latest = vip_purchases[0]  # más reciente (ORDER BY DESC)
            start = latest["purchase_date"]
            start = start.date() if hasattr(start, "date") else start
            days = get_vip_duration_days(cur, latest["price"])
            end = start + timedelta(days=days)
            vigente = end >= today
            print(
                f"      🔧 Tiene compra VIP (S/ {latest['price']:.2f} el {start}) "
                f"pero SIN sub activa → correspondería sub {start} → {end} "
                f"({'VIGENTE' if vigente else 'YA VENCIDA'})."
            )
            if CREATE_SUBS:
                cur.execute(
                    """
                    INSERT INTO subscriptions
                        (user_telegram_id, service_id, start_date, end_date, is_active)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (uid, VIP_SERVICE_ID, start, end, 1),
                )
                conn.commit()
                print(f"      ✓ Suscripción creada (#{cur.lastrowid}).")
                repaired.append((uid, vigente))
                if not vigente:
                    should_be_out.append(uid)
            else:
                print("      (solo lectura: usa CREATE_SUBS=true para crearla)")
                if not vigente:
                    should_be_out.append(uid)
        else:
            print(
                "      🚨 NO tiene compra VIP ni suscripción VIP → "
                "NO debería estar en el grupo (candidato a expulsión)."
            )
            should_be_out.append(uid)

    conn.close()

    print("\n" + "=" * 70)
    print("RESUMEN")
    print("=" * 70)
    print(f"✅ Legítimos (sub VIP vigente): {len(legit)} → {legit}")
    print(f"🔧 Reparados (sub creada):      {len(repaired)} → {repaired}")
    print(f"🚨 Deberían estar AFUERA:       {len(should_be_out)} → {should_be_out}")

    # Expulsión (solo si KICK_OUT=true)
    if should_be_out and KICK_OUT:
        if not TELEGRAM_BOT_TOKEN:
            print("\n❌ TELEGRAM_BOT_TOKEN no configurado; no se puede expulsar.")
            return
        print("\n" + "=" * 70)
        print(f"🚫 EXPULSANDO {len(should_be_out)} usuarios (kick, pueden re-unirse)")
        print("=" * 70)
        kicked = 0
        for uid in should_be_out:
            if int(uid) in PROTECTED_IDS:
                print(f"   🛡️  Protegido, se omite: {uid}")
                continue
            if kick_user(int(uid)):
                print(f"   ✓ Expulsado {uid}")
                kicked += 1
            else:
                print(f"   ✗ No se pudo expulsar {uid}")
            time.sleep(0.5)
        print(f"\n✅ Expulsados: {kicked}/{len(should_be_out)}")
    elif should_be_out:
        print("\nℹ️  Solo lectura (KICK_OUT=false). Usa KICK_OUT=true para expulsar.")


if __name__ == "__main__":
    main()
