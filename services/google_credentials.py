"""
Google Credentials Manager - Magic Chatbot v2
==============================================
Maneja las credenciales de Google Cloud de forma flexible:
- Desarrollo: archivo JSON local (GOOGLE_CREDENTIALS_PATH)
- Producción: variable de entorno GOOGLE_CREDENTIALS_JSON con el JSON completo
- CI/CD: GitHub Secret → variable de entorno

Uso:
    from services.google_credentials import get_google_credentials

    creds = get_google_credentials()
    # creds es un diccionario con el contenido del JSON de service account
"""

import json
import logging
import os

logger = logging.getLogger(__name__)


def get_google_credentials() -> dict:
    from config.settings import settings

    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")

    # Helper: try to parse, repairing newlines if needed
    def try_parse(raw: str) -> dict | None:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        # Repair: fix literal newlines in private key
        try:
            import re
            fixed = re.sub(r'(?<="private_key": ")(.+?)(?=",)',
                          lambda m: m.group(1).replace('\n', '\\n'),
                          raw, flags=re.DOTALL)
            return json.loads(fixed)
        except Exception:
            pass
        # Try base64
        try:
            import base64
            return json.loads(base64.b64decode(raw).decode("utf-8"))
        except Exception:
            pass
        return None

    # 1. Try env var
    if creds_json:
        creds = try_parse(creds_json)
        if creds:
            # Save repaired version to file for next time
            try:
                os.makedirs("credentials", exist_ok=True)
                with open("credentials/google.json", "w") as f:
                    json.dump(creds, f)
            except Exception:
                pass
            logger.info("Google credentials loaded from GOOGLE_CREDENTIALS_JSON env var")
            return creds
        logger.warning("GOOGLE_CREDENTIALS_JSON has invalid JSON. Trying file...")

    # 2. Try GOOGLE_CREDENTIALS_PATH file
    creds_path = settings.GOOGLE_CREDENTIALS_PATH
    if creds_path and os.path.exists(creds_path):
        try:
            with open(creds_path) as f:
                creds = json.load(f)
            logger.info(f"Google credentials loaded from file: {creds_path}")
            return creds
        except Exception:
            pass

    # 3. Try default file
    default_path = "./credentials/google.json"
    if os.path.exists(default_path):
        try:
            with open(default_path) as f:
                creds = json.load(f)
            logger.info(f"Google credentials loaded from default file: {default_path}")
            return creds
        except Exception:
            pass

    raise FileNotFoundError(
        "Google credentials not found. Set GOOGLE_CREDENTIALS_JSON env var."
    )


def get_credentials_json_string() -> str:
    """
    Returns the credentials as a JSON string (useful for subprocess/threading).
    """
    return json.dumps(get_google_credentials())
