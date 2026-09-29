#!/usr/bin/env python3
"""
Diagnóstico READ-ONLY del fetch de miembros vía Telethon.

Compara distintos métodos de obtención de participantes contra el MISMO grupo
para entender por qué el job de limpieza a veces obtiene muy pocos miembros.

Imprime:
  - Autorización de la sesión y datos de la entidad.
  - participants_count real (GetFullChannelRequest).
  - Conteo con ChannelParticipantsSearch('')  ← el que usa el job hoy.
  - Conteo con ChannelParticipantsRecent().
  - Conteo con client.get_participants(aggressive=True).
  - Número de administradores.

Requiere: TELETHON_API_ID, TELETHON_API_HASH, TELETHON_SESSION,
          TELEGRAM_VIP_GROUP_ID.
"""

import asyncio
import os

from dotenv import load_dotenv

load_dotenv()

API_ID = int((os.getenv("TELETHON_API_ID") or "0").strip() or 0)
API_HASH = (os.getenv("TELETHON_API_HASH") or "").strip()
SESSION = (os.getenv("TELETHON_SESSION") or "").strip()
GROUP_ID = int(os.getenv("TELEGRAM_VIP_GROUP_ID", "0"))


async def main():
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.tl.functions.channels import (
        GetFullChannelRequest,
        GetParticipantsRequest,
    )
    from telethon.tl.types import (
        ChannelParticipantsAdmins,
        ChannelParticipantsRecent,
        ChannelParticipantsSearch,
    )

    print("=" * 70)
    print(f"GROUP_ID={GROUP_ID}  API_ID set={bool(API_ID)}  SESSION set={bool(SESSION)}")
    print("=" * 70)

    async with TelegramClient(StringSession(SESSION), API_ID, API_HASH) as client:
        print(f"is_user_authorized: {await client.is_user_authorized()}")
        me = await client.get_me()
        print(f"Sesión como: id={getattr(me, 'id', None)} "
              f"user=@{getattr(me, 'username', None)} bot={getattr(me, 'bot', None)}")

        entity = await client.get_entity(GROUP_ID)
        print(f"Entidad: type={type(entity).__name__} "
              f"title={getattr(entity, 'title', None)!r} "
              f"megagroup={getattr(entity, 'megagroup', None)} "
              f"broadcast={getattr(entity, 'broadcast', None)}")

        # Conteo real del canal
        try:
            full = await client(GetFullChannelRequest(channel=entity))
            print(f"\n[REAL] participants_count = {full.full_chat.participants_count}")
        except Exception as e:
            print(f"\n[REAL] error GetFullChannel: {e}")

        # Método actual del job: ChannelParticipantsSearch('')
        async def count_via_request(flt, label):
            total = 0
            offset = 0
            limit = 200
            pages = 0
            try:
                while True:
                    part = await client(GetParticipantsRequest(
                        channel=entity, filter=flt,
                        offset=offset, limit=limit, hash=0,
                    ))
                    pages += 1
                    if not part.users:
                        break
                    total += len(part.users)
                    offset += len(part.users)
                    if len(part.users) < limit:
                        break
                    if pages > 100:
                        break
                print(f"[{label}] users={total} (páginas={pages})")
            except Exception as e:
                print(f"[{label}] ERROR: {e}")

        print()
        await count_via_request(ChannelParticipantsSearch(''), "SEARCH('')  <-- el del job")
        await count_via_request(ChannelParticipantsRecent(), "RECENT()")
        await count_via_request(ChannelParticipantsAdmins(), "ADMINS()")

        # Confirmar si la cuenta de la sesión es admin
        try:
            admins = await client.get_participants(entity, filter=ChannelParticipantsAdmins())
            admin_ids = [a.id for a in admins]
            print(f"\n[ADMINS detalle] ids={admin_ids}")
            print(f"[ADMINS detalle] la sesión ({me.id}) es admin: {me.id in admin_ids}")
        except Exception as e:
            print(f"[ADMINS detalle] ERROR: {e}")

        # Método de alto nivel de Telethon
        try:
            parts = await client.get_participants(entity, aggressive=True)
            print(f"[get_participants(aggressive=True)] users={len(parts)}")
        except Exception as e:
            print(f"[get_participants(aggressive=True)] ERROR: {e}")

        try:
            parts2 = await client.get_participants(entity)
            print(f"[get_participants()] users={len(parts2)}")
        except Exception as e:
            print(f"[get_participants()] ERROR: {e}")


if __name__ == "__main__":
    asyncio.run(main())
