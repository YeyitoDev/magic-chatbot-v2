"""
Media Service - File ID based (zero storage) with local fallback
=================================================================
Uses Telegram file_id for all images/videos. No local files needed.

How it works:
1. Upload media once → get file_id from Telegram
2. Store file_id in media_config.json
3. Send using file_id → no files on disk, no LFS, no Docker issues
4. Fallback: if file_id fails (e.g. different bot token), use local files

To update a file_id: just edit media_config.json

Usage:
    from services.media_service import MediaService
    media = MediaService()
    await media.send_photo(context, chat_id, "stake_pricing", caption="...")
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

MEDIA_CONFIG_PATH = "media_config.json"
LOCAL_MEDIA_DIR = "imagenes_promocionales"

# Fallback mapping for local files when file_ids don't work (e.g. different bot token)
LOCAL_PHOTO_MAP = {
    "stake_maximo": "stake_maximo.png",
    "grupo_vip_1": "grupo_vip_1.jpg",
    "grupo_vip_2": "grupo_vip_2.jpg",
    "betsafe_logo": "betsafe_logo.jpeg",
    "stake_pricing": "stake_logo.jpeg",
    "vip_pricing": "vip_3.jpeg",
    "magic_logo": "magic_logo.jpeg",
}

LOCAL_VIDEO_MAP = {
    "grupo_vip_explicacion": "recordatorio_video.mp4",
    "stake_explicacion": "recordatorio_video.mp4",
}


class MediaService:
    """Sends media using Telegram file_id, with local file fallback."""

    def __init__(self):
        self._config = self._load_config()

    def _load_config(self) -> dict:
        if os.path.exists(MEDIA_CONFIG_PATH):
            with open(MEDIA_CONFIG_PATH) as f:
                return json.load(f)
        return {"photos": {}, "videos": {}, "updated_at": None}

    def _get_file_id(self, name: str, media_type: str = "photos") -> str | None:
        return self._config.get(media_type, {}).get(name)

    def _find_local_file(self, name: str, media_type: str = "photos") -> str | None:
        """Find a local media file as fallback when file_id doesn't work."""
        media_map = LOCAL_PHOTO_MAP if media_type == "photos" else LOCAL_VIDEO_MAP
        filename = media_map.get(name)
        if filename:
            path = os.path.join(LOCAL_MEDIA_DIR, filename)
            if os.path.exists(path):
                return path

        # Try to find any file matching the name
        if os.path.exists(LOCAL_MEDIA_DIR):
            for ext in (".png", ".jpg", ".jpeg", ".mp4"):
                candidate = os.path.join(LOCAL_MEDIA_DIR, name + ext)
                if os.path.exists(candidate):
                    return candidate
        return None

    async def send_photo(self, context, chat_id: str, name: str, caption: str = "", parse_mode: str = "HTML") -> bool:
        """Send a photo by file_id, falling back to local file if needed."""
        file_id = self._get_file_id(name, "photos")

        # Try file_id first
        if file_id:
            try:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=file_id,
                    caption=caption,
                    parse_mode=parse_mode,
                )
                return True
            except Exception as e:
                logger.warning(f"File ID failed for '{name}', trying local file: {e}")

        # Fallback to local file
        local_path = self._find_local_file(name, "photos")
        if local_path:
            try:
                with open(local_path, "rb") as f:
                    await context.bot.send_photo(
                        chat_id=chat_id,
                        photo=f,
                        caption=caption,
                        parse_mode=parse_mode,
                    )
                logger.info(f"Sent local photo '{name}' from {local_path}")
                return True
            except Exception as e:
                logger.error(f"Failed to send local photo '{name}': {e}")
        else:
            logger.error(f"No file_id or local file found for photo '{name}'")
        return False

    async def send_video(self, context, chat_id: str, name: str, caption: str = "", parse_mode: str = "HTML") -> bool:
        """Send a video by file_id, falling back to local file if needed."""
        file_id = self._get_file_id(name, "videos")

        # Try file_id first
        if file_id:
            try:
                await context.bot.send_video(
                    chat_id=chat_id,
                    video=file_id,
                    caption=caption,
                    parse_mode=parse_mode,
                )
                return True
            except Exception as e:
                logger.warning(f"File ID failed for video '{name}', trying local file: {e}")

        # Fallback to local file
        local_path = self._find_local_file(name, "videos")
        if local_path:
            try:
                with open(local_path, "rb") as f:
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=f,
                        caption=caption,
                        parse_mode=parse_mode,
                    )
                logger.info(f"Sent local video '{name}' from {local_path}")
                return True
            except Exception as e:
                logger.error(f"Failed to send local video '{name}': {e}")
        else:
            logger.error(f"No file_id or local file found for video '{name}'")
        return False

    def get_file_ids_status(self) -> dict:
        """Returns which file_ids are configured."""
        return {
            "photos_configured": list(self._config.get("photos", {}).keys()),
            "videos_configured": list(self._config.get("videos", {}).keys()),
            "total_photos": len(self._config.get("photos", {})),
            "total_videos": len(self._config.get("videos", {})),
        }


# Global instance
media_service = MediaService()
