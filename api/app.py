"""
Flask API Application - Magic Chatbot v2
=========================================
Aplicación Flask para endpoints REST que permiten la integración
con plataformas externas (WhatsApp, formularios web, etc.).

Endpoints:
- GET  /health               → Health check.
- GET  /hello                → Endpoint de prueba.
- POST /api/v1/register_payment → Registro de pago desde plataforma externa.
- GET  /api/v1/payment/<id>  → Consulta de estado de un pago registrado.

Principios:
- Factory Pattern: create_app() construye la app con sus dependencias.
- Blueprints: las rutas están modularizadas en routes.py.
- Configuración externa: todas las variables desde settings.
- CORS: configurable vía ALLOWED_HOSTS y CORS_ORIGINS en settings.

Basado en el archivo original api_magic.py, refactorizado siguiendo
Clean Code y 12-Factor App.

Uso:
    from api.app import create_app

    app = create_app()
    app.run(host="0.0.0.0", port=5000)

    # O con el contenedor de dependencias:
    from core.container import container
    app = create_app(container=container)
"""

import logging

from flask import Flask, jsonify, request

from config.settings import settings

logger = logging.getLogger(__name__)


def create_app(container=None) -> Flask:
    """
    Factory function que crea y configura la aplicación Flask.

    Args:
        container: Contenedor de dependencias (opcional). Si no se proporciona,
                   se crea una instancia nueva desde core.container.

    Returns:
        Instancia de Flask completamente configurada.
    """
    app = Flask(__name__)

    # ------------------------------------------------------------------
    # Configuración básica
    # ------------------------------------------------------------------
    app.config["SECRET_KEY"] = settings.FLASK_SECRET_KEY
    app.config["DEBUG"] = settings.DEBUG
    app.config["ENV"] = settings.ENVIRONMENT

    # ------------------------------------------------------------------
    # Registrar rutas
    # ------------------------------------------------------------------
    from api.routes import register_routes
    register_routes(app, container)

    # ------------------------------------------------------------------
    # Middleware de errores globales
    # ------------------------------------------------------------------
    _register_error_handlers(app)

    # ------------------------------------------------------------------
    # CORS (opcional, si se necesita en el futuro)
    # ------------------------------------------------------------------
    @app.after_request
    def add_cors_headers(response):
        """Agrega headers CORS a todas las respuestas."""
        origins = settings.CORS_ORIGINS if hasattr(settings, "CORS_ORIGINS") else ["*"]
        origin = request.headers.get("Origin", "")

        if "*" in origins or origin in origins:
            response.headers["Access-Control-Allow-Origin"] = origin or "*"
            response.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, Authorization, X-API-Key"
            )
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, PUT, DELETE, OPTIONS"
            )
            response.headers["Access-Control-Max-Age"] = "3600"

        return response

    logger.info(
        f"Flask app creada: environment={settings.ENVIRONMENT}, "
        f"debug={settings.DEBUG}"
    )

    return app


def _register_error_handlers(app: Flask) -> None:
    """
    Registra handlers globales de errores HTTP.

    Args:
        app: Instancia de Flask.
    """

    @app.errorhandler(400)
    def bad_request(error):
        """Error 400 - Bad Request."""
        return jsonify({
            "error": "Bad Request",
            "message": str(error.description) if error.description else "Solicitud inválida.",
        }), 400

    @app.errorhandler(401)
    def unauthorized(error):
        """Error 401 - Unauthorized."""
        return jsonify({
            "error": "Unauthorized",
            "message": "API Key inválida o no proporcionada.",
        }), 401

    @app.errorhandler(404)
    def not_found(error):
        """Error 404 - Not Found."""
        return jsonify({
            "error": "Not Found",
            "message": "El recurso solicitado no existe.",
        }), 404

    @app.errorhandler(405)
    def method_not_allowed(error):
        """Error 405 - Method Not Allowed."""
        return jsonify({
            "error": "Method Not Allowed",
            "message": "Método HTTP no permitido para este endpoint.",
        }), 405

    @app.errorhandler(500)
    def internal_error(error):
        """Error 500 - Internal Server Error."""
        logger.error(
            f"Internal Server Error: {error}",
            exc_info=True,
        )
        return jsonify({
            "error": "Internal Server Error",
            "message": "Ocurrió un error interno en el servidor.",
        }), 500


def validate_api_key(request) -> bool:
    """
    Valida que la API Key proporcionada en el request sea correcta.

    Busca la API Key en:
    1. Header X-API-Key.
    2. Header Authorization: Bearer <token>.
    3. Query parameter ?api_key=<token>.

    Args:
        request: Objeto request de Flask.

    Returns:
        True si la API Key es válida, False en caso contrario.
    """
    api_key = settings.API_KEY

    # Si no se configuró API_KEY, se permite el acceso sin autenticación
    if not api_key:
        logger.debug("API_KEY no configurada. Acceso público permitido.")
        return True

    # Buscar en headers
    provided_key = (
        request.headers.get("X-API-Key")
        or request.headers.get("Authorization", "").replace("Bearer ", "")
        or request.args.get("api_key")
    )

    is_valid = provided_key == api_key

    if not is_valid:
        logger.warning(
            f"Intento de acceso con API Key inválida desde {request.remote_addr}"
        )

    return is_valid


# ---------------------------------------------------------------------------
# Punto de entrada directo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    """
    Ejecuta la aplicación Flask en modo standalone.

    Uso:
        python -m api.app
    """
    import sys

    # Configurar logging
    logging.basicConfig(
        level=getattr(logging, settings.LOG_LEVEL, "INFO"),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    logger.info("Iniciando servidor Flask en modo standalone...")
    logger.info(f"Host: {settings.FLASK_HOST}:{settings.FLASK_PORT}")
    logger.info(f"Environment: {settings.ENVIRONMENT}")

    # Crear y ejecutar la app
    app = create_app()

    try:
        app.run(
            host=settings.FLASK_HOST,
            port=settings.FLASK_PORT,
            debug=settings.DEBUG,
        )
    except KeyboardInterrupt:
        logger.info("Servidor Flask detenido por el usuario.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error al iniciar servidor Flask: {e}", exc_info=True)
        sys.exit(1)
