"""
Register Telegram file_ids for all media.
Run this ONCE to upload images/videos and save their file_ids.

Usage:
    cd v2_refactor && python scripts/register_file_ids.py
"""

import asyncio
import json
import os
import sys

# Allow running from any directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from telegram.ext import ApplicationBuilder

from config.settings import settings

TOKEN = settings.TELEGRAM_BOT_TOKEN
CHANNEL_ID = os.getenv("MEDIA_CHANNEL_ID", "@magic_media_storage")

MEDIA_FILES = {
    "photos": {
        "stake_pricing": "./imagenes_promocionales/stake_3.jpeg",
        "vip_pricing": "./imagenes_promocionales/vip_3.jpeg",
        "stake_maximo": "./imagenes_promocionales/stake_maximo.png",
        "grupo_vip_1": "./imagenes_promocionales/grupo_vip_1.jpg",
        "grupo_vip_2": "./imagenes_promocionales/grupo_vip_2.jpg",
        "betsafe_logo": "./imagenes_promocionales/betsafe_logo.jpeg",
    },
    "videos": {
        "grupo_vip_explicacion": "./videos_promocionales/GRUPO_VIP_EXPLICACION.mp4",
        "stake_explicacion": "./videos_promocionales/STAKE_MAXIMA_SEGURIDAD_EXPLICACION.mp4",
    },
}


async def main():
    app = ApplicationBuilder().token(TOKEN).build()
    config = {"photos": {}, "videos": {}, "updated_at": None}

    for media_type, files in MEDIA_FILES.items():
        for name, path in files.items():
            if not os.path.exists(path):
                print(f"❌ {name}: file not found at {path}")
                continue

            print(f"📤 Uploading {name} from {path}...")
            try:
                if media_type == "photos":
                    msg = await app.bot.send_photo(
                        chat_id=CHANNEL_ID,
                        photo=open(path, "rb"),
                    )
                    file_id = msg.photo[-1].file_id
                else:
                    msg = await app.bot.send_video(
                        chat_id=CHANNEL_ID,
                        video=open(path, "rb"),
                    )
                    file_id = msg.video.file_id

                config[media_type][name] = file_id
                print(f"  ✅ file_id: {file_id[:30]}...")
            except Exception as e:
                print(f"  ❌ Failed: {e}")

    with open("media_config.json", "w") as f:
        json.dump(config, f, indent=2)

    print(f"\n✅ Registered {len(config['photos'])} photos and {len(config['videos'])} videos")
    await app.shutdown()


asyncio.run(main())
