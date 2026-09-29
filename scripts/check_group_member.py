#!/usr/bin/env python3
"""
Script para verificar si un usuario es miembro de un grupo
"""
import sys

sys.path.append('.')

from services.telegram_api import TelegramAPIService


def check_group_member(telegram_id: int, group_id: int):
    api = TelegramAPIService()

    try:
        is_member = api.is_member_in_chat(group_id, telegram_id)

        if is_member:
            print(f"✅ Usuario {telegram_id} ES miembro del grupo {group_id}")
        else:
            print(f"❌ Usuario {telegram_id} NO es miembro del grupo {group_id}")

        # Obtener información detallada del miembro
        member_info = api.get_chat_member(group_id, telegram_id)
        if member_info:
            print("📋 Información del miembro:")
            print(f"   - Status: {member_info.get('status')}")
            print(f"   - User ID: {member_info.get('user', {}).get('id')}")
            print(f"   - Username: {member_info.get('user', {}).get('username')}")
            print(f"   - Nombre: {member_info.get('user', {}).get('first_name')}")

    except Exception as e:
        print(f"❌ Error al verificar miembro: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python scripts/check_group_member.py <telegram_id> <group_id>")
        print("Ejemplo: python scripts/check_group_member.py 123456789 -1001234567890")
        sys.exit(1)

    telegram_id = int(sys.argv[1])
    group_id = int(sys.argv[2])
    check_group_member(telegram_id, group_id)
