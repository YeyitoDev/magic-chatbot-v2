"""
Generador de StringSession de Telethon - Magic Chatbot v2
=========================================================
Script interactivo de un solo uso para iniciar sesión en tu cuenta de Telegram
(usuario, no bot) y obtener un ``StringSession`` reutilizable.

El string resultante se guarda como secreto ``TELETHON_SESSION`` y permite que
los jobs de reconciliación (Telethon) corran de forma desatendida en CI sin
necesidad del login interactivo por SMS cada vez.

Requisitos (vienen de https://my.telegram.org → API development tools):
    export TELETHON_API_ID=...
    export TELETHON_API_HASH=...
    export TELETHON_PHONE=+51XXXXXXXXX   # opcional; si no, lo pide por consola

Uso:
    python scripts/generate_telethon_session.py

Telegram enviará un código a tu app de Telegram; ingrésalo cuando se solicite.
Si tienes verificación en dos pasos, también pedirá tu contraseña.

⚠ El StringSession da acceso completo a tu cuenta de Telegram. Trátalo como una
contraseña: guárdalo solo como secreto, nunca lo comitees ni lo compartas.
"""

import os
import sys


def main() -> int:
    try:
        from telethon.sessions import StringSession
        from telethon.sync import TelegramClient
    except ImportError:
        print("Telethon no está instalado. Ejecuta: pip install telethon")
        return 1

    api_id_raw = os.getenv("TELETHON_API_ID", "").strip()
    api_hash = os.getenv("TELETHON_API_HASH", "").strip()
    phone = os.getenv("TELETHON_PHONE", "").strip()

    if not api_id_raw or not api_hash:
        print("Faltan TELETHON_API_ID y/o TELETHON_API_HASH en el entorno.")
        print("Obténlos en https://my.telegram.org → API development tools.")
        return 1

    api_id = int(api_id_raw)

    print("Conectando a Telegram para generar el StringSession...")
    with TelegramClient(StringSession(), api_id, api_hash) as client:
        if phone:
            client.start(phone=phone)
        else:
            client.start()
        session_string = client.session.save()

    print("\n" + "=" * 60)
    print("✅ StringSession generado. Guárdalo como secreto TELETHON_SESSION:")
    print("=" * 60)
    print(session_string)
    print("=" * 60)
    print("\nNO lo comitees ni lo compartas: da acceso total a tu cuenta.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
