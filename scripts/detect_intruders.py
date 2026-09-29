#!/usr/bin/env python3
"""
Detector de intrusos en Grupo VIP
=================================
Obtiene los miembros actuales del grupo VIP vía Telethon y los compara
con la base de datos para detectar usuarios que están en el grupo pero:
1. No están registrados en tabla users
2. No tienen compras registradas
3. No tienen suscripción activa

Requiere credenciales de Telethon:
  - TELETHON_API_ID
  - TELETHON_API_HASH
  - TELETHON_SESSION (string session)

Uso:
    .venv/bin/python scripts/detect_intruders.py
"""

import asyncio
import os
import sys
import time
from collections import defaultdict
from datetime import date

import pymysql
import requests
from dotenv import load_dotenv

load_dotenv()  # Carga .env del directorio actual (funciona local y en CI)

# ── Configuración ──────────────────────────────────────────────────
VIP_GROUP_ID = os.getenv("TELEGRAM_VIP_GROUP_ID", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

# Modo eliminación: si es "true", banea a los intrusos del grupo.
# Por defecto False (solo reporta) para evitar expulsiones accidentales.
REMOVE_INTRUDERS = os.getenv("REMOVE_INTRUDERS", "false").strip().lower() == "true"

# ── IDs SIEMPRE protegidos (nunca eliminar) ────────────────────────
# Admins/bots (PROTECTED_USER_IDS), destinatarios de avisos (ADMIN_NOTIFY_IDS)
# y validadores: la misma lista que usa jobs/subscription_cleanup.py.
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

TELETHON_API_ID = os.getenv("TELETHON_API_ID", "").strip()
TELETHON_API_HASH = os.getenv("TELETHON_API_HASH", "").strip()
TELETHON_SESSION = os.getenv("TELETHON_SESSION", "").strip()


# ── Paso 1: Obtener miembros del grupo VIP vía Telethon ────────────
async def get_vip_members():
    try:
        from telethon import TelegramClient
    except ImportError:
        print("❌ Telethon no instalado. Ejecuta: .venv/bin/pip install telethon")
        sys.exit(1)

    if not TELETHON_API_ID or not TELETHON_API_HASH:
        print("❌ Faltan TELETHON_API_ID y/o TELETHON_API_HASH en el entorno.")
        print("   Obténlos en https://my.telegram.org → API development tools.")
        sys.exit(1)

    api_id = int(TELETHON_API_ID)
    api_hash = TELETHON_API_HASH

    # Usar StringSession si está disponible, sino crear sesión nueva
    from telethon.sessions import StringSession

    client = TelegramClient(
        StringSession(TELETHON_SESSION) if TELETHON_SESSION else StringSession(),
        api_id, api_hash
    )

    from telethon.tl.types import (
        ChannelParticipantAdmin,
        ChannelParticipantCreator,
    )

    members = []
    async with client:
        print(f"🔍 Obteniendo miembros del grupo {VIP_GROUP_ID}...")
        try:
            async for participant in client.iter_participants(int(VIP_GROUP_ID)):
                is_admin = isinstance(
                    getattr(participant, "participant", None),
                    (ChannelParticipantAdmin, ChannelParticipantCreator),
                )
                members.append({
                    "user_telegram_id": str(participant.id),
                    "username": participant.username or "",
                    "first_name": participant.first_name or "",
                    "last_name": participant.last_name or "",
                    "is_bot": participant.bot,
                    "is_admin": is_admin,
                })
        except Exception as e:
            print(f"❌ Error al obtener miembros: {e}")
            sys.exit(1)

    print(f"✅ Miembros obtenidos: {len(members)}")
    return members


# ── Paso 2: Cargar datos de BD ────────────────────────────────────
def load_db_data():
    conn = pymysql.connect(**DB_CONFIG)
    cur = conn.cursor(pymysql.cursors.DictCursor)

    # Usuarios registrados
    cur.execute("SELECT telegram_id, telegram_name FROM users")
    registered_users = {r["telegram_id"]: r for r in cur.fetchall()}

    # Compras (solo VIP)
    cur.execute("""
        SELECT p.user_telegram_id, p.price, p.purchase_date, s.name as service_name
        FROM purchases p
        JOIN services s ON p.service_id = s.service_id
        WHERE s.name = 'grupo_vip'
        ORDER BY p.purchase_date DESC
    """)
    vip_purchases = defaultdict(list)
    for r in cur.fetchall():
        vip_purchases[r["user_telegram_id"]].append(r)

    # Suscripciones activas VIP
    cur.execute("""
        SELECT s.user_telegram_id, s.start_date, s.end_date, s.is_active
        FROM subscriptions s
        JOIN services sv ON s.service_id = sv.service_id
        WHERE sv.name = 'grupo_vip' AND s.is_active = 1 AND s.end_date >= %s
    """, (date.today(),))
    active_subs = {r["user_telegram_id"]: r for r in cur.fetchall()}

    # Suscripciones vencidas VIP
    cur.execute("""
        SELECT s.user_telegram_id, s.start_date, s.end_date
        FROM subscriptions s
        JOIN services sv ON s.service_id = sv.service_id
        WHERE sv.name = 'grupo_vip' AND s.end_date < %s
    """, (date.today(),))
    expired_subs = defaultdict(list)
    for r in cur.fetchall():
        expired_subs[r["user_telegram_id"]].append(r)

    conn.close()
    return registered_users, vip_purchases, active_subs, expired_subs


# ── Paso 3: Clasificar miembros ────────────────────────────────────
def classify_members(members, registered_users, vip_purchases, active_subs, expired_subs):
    categories = {
        "admin_bot": [],
        "active_subscription": [],
        "expired_subscription": [],
        "has_purchase_no_sub": [],
        "registered_no_purchase": [],
        "not_registered_no_purchase": [],  # INTRUSOS
    }

    for m in members:
        uid = int(m["user_telegram_id"])

        # Saltar bots, admins del grupo e IDs siempre protegidos.
        # Estos NUNCA se clasifican como intrusos ni se eliminan.
        if m["is_bot"] or m.get("is_admin") or uid in PROTECTED_IDS:
            categories["admin_bot"].append(m)
            continue

        # ¿Tiene sub activa?
        if uid in active_subs:
            categories["active_subscription"].append(m)
            continue

        # ¿Tiene sub vencida?
        if uid in expired_subs:
            m["expired_info"] = expired_subs[uid]
            categories["expired_subscription"].append(m)
            continue

        # ¿Tiene compra VIP pero sin sub?
        if uid in vip_purchases:
            m["purchases"] = vip_purchases[uid]
            categories["has_purchase_no_sub"].append(m)
            continue

        # ¿Registrado pero sin compra VIP?
        if uid in registered_users:
            m["user_info"] = registered_users[uid]
            categories["registered_no_purchase"].append(m)
            continue

        # No registrado, no compra → INTRUSO
        categories["not_registered_no_purchase"].append(m)

    return categories


# ── Paso 4: Reporte ────────────────────────────────────────────────
def print_report(categories):
    print("\n" + "=" * 70)
    print("REPORTE DE MIEMBROS DEL GRUPO VIP")
    print("=" * 70)

    total = sum(len(v) for v in categories.values())
    print(f"Total miembros analizados: {total}\n")

    # 1. Admins / Bots
    print(f"🤖 Bots/Admins: {len(categories['admin_bot'])}")

    # 2. Con sub activa
    print(f"✅ Con suscripción activa: {len(categories['active_subscription'])}")

    # 3. Sub vencida → candidatos a expulsión
    print(f"\n🗑️  Suscripción VENCIDA ({len(categories['expired_subscription'])}):")
    print("   (Estos deben ser expulsados por el cleanup job)")
    for m in categories["expired_subscription"][:20]:
        exp = m["expired_info"][0]
        print(f"   {m['user_telegram_id']} ({m['first_name']}) – venció: {exp['end_date']}")
    if len(categories["expired_subscription"]) > 20:
        print(f"   ... y {len(categories['expired_subscription']) - 20} más")

    # 4. Compra VIP pero sin sub → error de procesamiento
    print(f"\n🚨 Compra VIP pero SIN suscripción ({len(categories['has_purchase_no_sub'])}):")
    print("   (Compraron VIP pero la suscripción nunca se creó – revisar manualmente)")
    for m in categories["has_purchase_no_sub"]:
        last = m["purchases"][0]
        print(f"   {m['user_telegram_id']} ({m['first_name']}) – "
              f"última compra: S/ {last['price']:.2f} el {last['purchase_date']}")

    # 5. Registrado pero sin compra VIP
    print(f"\n⚠️  Registrado en BD pero sin compra VIP ({len(categories['registered_no_purchase'])}):")
    print("   (Podrían haber entrado por otro medio o tener solo compras Stake)")
    for m in categories["registered_no_purchase"][:10]:
        print(f"   {m['user_telegram_id']} ({m['first_name']})")
    if len(categories["registered_no_purchase"]) > 10:
        print(f"   ... y {len(categories['registered_no_purchase']) - 10} más")

    # 6. INTRUSOS
    print(f"\n🚨🚨 INTRUSOS – No registrados, sin compra ({len(categories['not_registered_no_purchase'])}):")
    print("   (Estos usuarios NO deberían estar en el grupo)")
    for m in categories["not_registered_no_purchase"]:
        print(f"   {m['user_telegram_id']} – @{m['username']} – {m['first_name']} {m['last_name']}")

    # Resumen
    print("\n" + "=" * 70)
    print("RESUMEN EJECUTIVO")
    print("=" * 70)
    print(f"Total miembros:          {total}")
    print(f"✅ Legítimos (sub activa): {len(categories['active_subscription'])}")
    print(f"🗑️  Expirados (eliminar):   {len(categories['expired_subscription'])}")
    print(f"🚨 Compra sin sub (fix):   {len(categories['has_purchase_no_sub'])}")
    print(f"⚠️  Sin compra VIP:         {len(categories['registered_no_purchase']) + len(categories['not_registered_no_purchase'])}")
    print(f"🚨🚨 INTRUSOS confirmados:  {len(categories['not_registered_no_purchase'])}")

    return categories["not_registered_no_purchase"]


# ── Paso 5: Eliminar (expulsar) intrusos ───────────────────────────
def kick_intruder(user_id: int) -> bool:
    """
    Expulsa a un usuario del grupo VIP permitiéndole re-unirse.

    Flujo: banChatMember (kick) → unbanChatMember (only_if_banned=True).
    Esto lo saca del grupo pero NO lo deja baneado, así puede volver a
    unirse con un enlace de invitación si más adelante corresponde.
    Retorna True si el kick fue exitoso.
    """
    kick_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/banChatMember"
    unban_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/unbanChatMember"
    try:
        resp = requests.post(
            kick_url,
            data={"chat_id": VIP_GROUP_ID, "user_id": user_id},
            timeout=30,
        )
        if not resp.json().get("ok"):
            return False
        # Desbanear inmediatamente para permitir re-unirse en el futuro.
        requests.post(
            unban_url,
            data={
                "chat_id": VIP_GROUP_ID,
                "user_id": user_id,
                "only_if_banned": True,
            },
            timeout=30,
        )
        return True
    except Exception as e:
        print(f"   ✗ Error al expulsar {user_id}: {e}")
        return False


def remove_intruders(intruders):
    """
    Expulsa (kick + unban) a la lista de intrusos, respetando SIEMPRE los
    IDs protegidos (admins/bots/creador/validadores) como salvaguarda.

    Returns:
        Número de intrusos expulsados exitosamente.
    """
    if not TELEGRAM_BOT_TOKEN:
        print("\n❌ TELEGRAM_BOT_TOKEN no configurado; no se puede eliminar.")
        return 0

    print("\n" + "=" * 70)
    print(f"🚫 EXPULSANDO {len(intruders)} INTRUSOS (kick, pueden re-unirse)")
    print("=" * 70)

    removed = 0
    skipped = 0
    for m in intruders:
        uid = int(m["user_telegram_id"])

        # Salvaguarda: nunca expulsar IDs protegidos.
        if uid in PROTECTED_IDS or m.get("is_admin") or m.get("is_bot"):
            print(f"   🛡️  Protegido, se omite: {uid} ({m['first_name']})")
            skipped += 1
            continue

        if kick_intruder(uid):
            print(f"   ✓ Expulsado {uid} – @{m['username']} – {m['first_name']}")
            removed += 1
        else:
            print(f"   ✗ No se pudo expulsar {uid} ({m['first_name']})")

        time.sleep(0.5)  # Evitar rate limit de la API de Telegram

    print("\n" + "=" * 70)
    print(f"✅ Intrusos expulsados: {removed} | 🛡️ Protegidos omitidos: {skipped}")
    print("=" * 70)
    return removed


# ── Main ───────────────────────────────────────────────────────────
async def main():
    print("=" * 70)
    print("DETECTOR DE INTRUSOS – Grupo VIP")
    print("=" * 70)

    # Verificar credenciales
    if not TELETHON_API_ID or not TELETHON_API_HASH:
        print("\n❌ CREDENCIALES DE TELETHON NO CONFIGURADAS")
        print("\nPara usar este script necesitas:")
        print("  1. TELETHON_API_ID      (de my.telegram.org)")
        print("  2. TELETHON_API_HASH    (de my.telegram.org)")
        print("  3. TELETHON_SESSION     (string session, opcional)")
        print("\nOpciones:")
        print("  a) Configurar en .env.local y ejecutar: source .env.local && python script.py")
        print("  b) Pasar como variables de entorno:")
        print("     TELETHON_API_ID=12345 TELETHON_API_HASH=abc... python script.py")
        print("  c) Ejecutar desde GitHub Actions (ya tiene los secrets)")
        sys.exit(1)

    # 1. Miembros de Telegram
    members = await get_vip_members()

    # 2. Datos de BD
    print("\n🔍 Cargando datos de la base de datos...")
    registered, purchases, active, expired = load_db_data()
    print(f"   Usuarios registrados: {len(registered)}")
    print(f"   Compras VIP: {sum(len(v) for v in purchases.values())}")
    print(f"   Subs activas VIP: {len(active)}")
    print(f"   Subs vencidas VIP: {sum(len(v) for v in expired.values())}")

    # 3. Clasificar
    categories = classify_members(members, registered, purchases, active, expired)

    # 4. Reporte
    intruders = print_report(categories)

    # 5. Exportar lista de intrusos
    if intruders:
        output_path = "/tmp/intruders_list.txt"
        with open(output_path, "w") as f:
            f.write("user_telegram_id,username,first_name,last_name\n")
            for m in intruders:
                f.write(f"{m['user_telegram_id']},{m['username']},{m['first_name']},{m['last_name']}\n")
        print(f"\n📄 Lista de intrusos guardada en: {output_path}")

    # 6. Eliminar intrusos (solo si REMOVE_INTRUDERS=true)
    if intruders and REMOVE_INTRUDERS:
        remove_intruders(intruders)
    elif intruders:
        print(
            "\nℹ️  Modo solo lectura (REMOVE_INTRUDERS=false). "
            "Para eliminar, ejecuta con REMOVE_INTRUDERS=true."
        )

    return intruders


if __name__ == "__main__":
    intruders = asyncio.run(main())
