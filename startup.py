"""Startup script - writes Google credentials from env var to file."""
import base64
import json
import os

os.makedirs("credentials", exist_ok=True)
d = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")

if d:
    # The secret may be raw JSON, single base64, or even double base64
    # (e.g. the GitHub secret is already base64 and the deploy workflow
    # base64-encodes it again). Decode repeatedly until we obtain valid JSON.
    data = d.strip()
    parsed = None
    for _ in range(4):
        s = data.strip()
        if s.startswith("{"):
            try:
                json.loads(s)
                parsed = s
                break
            except Exception:
                pass
        try:
            data = base64.b64decode(s).decode()
        except Exception:
            break

    if parsed:
        with open("credentials/google.json", "w") as f:
            f.write(parsed)
        print("✅ Google credentials written to credentials/google.json")
    else:
        print(
            "⚠️ Failed to obtain valid JSON from GOOGLE_CREDENTIALS_JSON "
            "after decoding base64 layers. Writing raw value as fallback."
        )
        with open("credentials/google.json", "w") as f:
            f.write(d)
else:
    print("⚠️ GOOGLE_CREDENTIALS_JSON not set - Vision/Sheets will not work")
