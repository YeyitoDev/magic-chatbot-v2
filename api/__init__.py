"""
API Module - Magic Chatbot v2
==============================
Módulo de API REST usando Flask para integraciones externas.

Expone endpoints para:
- Registro de pagos desde plataformas externas (WhatsApp, web, etc.).
- Health check para monitoreo.
- Webhook de Telegram (modo producción en PythonAnywhere).

Principios:
- Factory Pattern: create_app() construye la aplicación Flask.
- Blueprint: las rutas se organizan en Blueprints para modularidad.
- Stateless: la API no mantiene estado; cada request es independiente.

Uso:
    from api.app import create_app

    app = create_app()
    app.run(host="0.0.0.0", port=5000)
"""

from .app import create_app

__all__ = ["create_app"]
