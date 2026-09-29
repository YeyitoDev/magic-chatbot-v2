"""
API Routes - Magic Chatbot v2
==============================
Definición de los endpoints REST de la API Flask.

Endpoints:
- GET  /health                          → Health check
- GET  /hello                           → Hello world
- POST /api/v1/register_service_payment → Registrar pago externo
- POST /api/v1/payments/validate        → Validar pago manualmente
- GET  /api/v1/stats                    → Estadísticas básicas

Principios:
- Thin routes: validan input, delegan lógica a servicios.
- JSON responses con códigos HTTP apropiados.
- Autenticación vía API Key para endpoints protegidos.
- Rate limiting básico para prevenir abuso.

Basado en: api_magic.py (líneas 1-89)
"""

import logging
from collections.abc import Callable
from datetime import datetime
from functools import wraps

import pandas as pd
from flask import Blueprint, current_app, jsonify, request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------

api_bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

# Ruta del CSV para pagos externos (igual que el código original)
SERVICES_PAYMENTS_CSV_PATH = "./csv/service_payments_api.csv"
CSV_COLUMNS = [
    "id", "from_channel", "name", "date", "amount", "service", "claimed"
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def require_api_key(func: Callable) -> Callable:
    """
    Decorador que verifica la presencia de una API Key válida en la request.

    La API Key debe enviarse en el header `X-API-Key` o como query param `api_key`.
    Si no se configura API_KEY en settings, la autenticación se omite (dev mode).

    Usage:
        @require_api_key
        def protected_endpoint():
            ...

    Returns:
        401 JSON si la API Key es inválida o falta.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            from config.settings import settings

            api_key = settings.API_KEY
            # Si no se configuró API Key, permitir acceso en desarrollo
            if not api_key:
                return func(*args, **kwargs)

            # Obtener key del request
            provided_key = (
                request.headers.get("X-API-Key")
                or request.args.get("api_key")
                or request.form.get("api_key")
            )

            if not provided_key:
                return jsonify({
                    "error": "Falta API Key",
                    "message": "Incluye X-API-Key en el header o api_key como query param.",
                }), 401

            if provided_key != api_key:
                return jsonify({
                    "error": "API Key inválida",
                    "message": "La clave proporcionada no es correcta.",
                }), 401

            return func(*args, **kwargs)

        except ImportError:
            # Si settings no está disponible, permitir acceso
            return func(*args, **kwargs)

    return wrapper


def validate_payment_inputs(data: dict) -> tuple:
    """
    Valida que todos los campos requeridos estén presentes en la request.

    Args:
        data: Diccionario con los datos del pago.

    Returns:
        Tupla (is_valid: bool, error_message: str | None).
    """
    required_fields = ["id", "from_channel", "name", "date", "amount", "service"]

    for field in required_fields:
        if not data.get(field):
            return False, f"El campo '{field}' es requerido."

    # Validar que amount sea numérico
    try:
        float(data["amount"])
    except (ValueError, TypeError):
        return False, "El campo 'amount' debe ser un número."

    # Validar formato de fecha
    try:
        datetime.strptime(data["date"], "%Y-%m-%d")
    except (ValueError, TypeError):
        return False, "El campo 'date' debe tener formato YYYY-MM-DD."

    return True, None


def load_csv_data(filepath: str) -> pd.DataFrame:
    """
    Carga datos desde un archivo CSV. Si no existe, crea un DataFrame vacío.

    Args:
        filepath: Ruta al archivo CSV.

    Returns:
        DataFrame con los datos del CSV.
    """
    import os

    if os.path.exists(filepath):
        return pd.read_csv(filepath)
    else:
        # Crear directorio si no existe
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        df = pd.DataFrame(columns=CSV_COLUMNS)
        df.to_csv(filepath, index=False)
        return df


def save_csv_data(filepath: str, df: pd.DataFrame) -> None:
    """
    Guarda un DataFrame en un archivo CSV.

    Args:
        filepath: Ruta de destino.
        df: DataFrame a guardar.
    """
    df.to_csv(filepath, index=False)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@api_bp.route("/health", methods=["GET"])
def health_check():
    """
    Health check del servicio.

    Retorna información del estado del API, incluyendo timestamp UTC.

    Returns:
        JSON con status "ok", timestamp, y version.
    """
    try:
        from config.settings import settings

        return jsonify({
            "status": "ok",
            "service": "Magic Chatbot API",
            "version": settings.PROJECT_VERSION,
            "environment": settings.ENVIRONMENT,
            "timestamp": datetime.utcnow().isoformat(),
        }), 200
    except ImportError:
        return jsonify({
            "status": "ok",
            "service": "Magic Chatbot API",
            "timestamp": datetime.utcnow().isoformat(),
        }), 200


@api_bp.route("/hello", methods=["GET"])
def hello():
    """
    Endpoint simple de prueba.

    Returns:
        JSON con respuesta de hello.
    """
    return jsonify({"response": "hello", "timestamp": datetime.utcnow().isoformat()})


# ---------------------------------------------------------------------------
# Registro de pagos desde plataforma externa
# ---------------------------------------------------------------------------

@api_bp.route("/register_service_payment", methods=["POST"])
@require_api_key
def register_service_payment():
    """
    Registra un pago proveniente de una plataforma externa (WhatsApp, web, etc.).

    Request Body (JSON):
        {
            "id": "unique_id_123",
            "from_channel": "whatsapp",
            "name": "Juan Perez",
            "date": "2025-01-15",
            "amount": 150.00,
            "service": "grupo_vip"
        }

    Returns:
        200: {"message": "Data saved successfully."}
        400: {"error": "mensaje de error"} si falta algún campo.
        401: Si falta la API Key o es inválida.
        500: Error interno del servidor.

    Note:
        Este endpoint guarda los datos en un CSV, igual que el código original.
        El CSV es luego procesado por el comando /valid del bot de Telegram.
    """
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({
            "error": "No se recibieron datos JSON o el Content-Type no es application/json."
        }), 400

    # Validar campos
    is_valid, error_msg = validate_payment_inputs(data)
    if not is_valid:
        return jsonify({"error": error_msg}), 400

    # Extraer datos
    user_id = data["id"]
    from_channel = data["from_channel"]
    name = data["name"]
    date_str = data["date"]
    amount = float(data["amount"])
    service = data["service"]

    try:
        parsed_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return jsonify({
            "error": "Formato de fecha inválido. Use YYYY-MM-DD."
        }), 400

    # Cargar CSV existente o crear uno nuevo

    filepath = SERVICES_PAYMENTS_CSV_PATH
    df = load_csv_data(filepath)

    # Crear nuevo registro
    new_record = pd.DataFrame([{
        "id": user_id,
        "from_channel": from_channel,
        "name": name,
        "date": str(parsed_date),
        "amount": amount,
        "service": service,
        "claimed": False,
    }])

    # Concatenar y guardar
    updated_df = pd.concat([df, new_record], ignore_index=True)
    save_csv_data(filepath, updated_df)

    logger.info(
        f"API: Pago registrado - id={user_id}, amount={amount}, "
        f"service={service}, channel={from_channel}"
    )

    return jsonify({
        "message": "Data saved successfully.",
        "id": user_id,
        "service": service,
        "amount": amount,
    }), 200


# ---------------------------------------------------------------------------
# Validación de pago manual (para integraciones)
# ---------------------------------------------------------------------------

@api_bp.route("/payments/validate", methods=["POST"])
@require_api_key
def validate_payment():
    """
    Valida un pago manualmente a través de la API.

    Request Body (JSON):
        {
            "telegram_id": 123456789,
            "amount": 150.00,
            "from_channel": "whatsapp",
            "purchase_date": "2025-01-15"
        }

    Returns:
        200: {"success": true, "message": "Compra registrada...", "service_type": "grupo_vip"}
        400: Error de validación.
        500: Error interno.

    Note:
        Este endpoint requiere que el contenedor de dependencias esté
        inicializado en la aplicación Flask (app.container).
    """
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "No se recibieron datos JSON."}), 400

    # Validar campos requeridos
    telegram_id = data.get("telegram_id")
    amount = data.get("amount")

    if not telegram_id or amount is None:
        return jsonify({
            "error": "Los campos 'telegram_id' y 'amount' son requeridos."
        }), 400

    try:
        telegram_id = int(telegram_id)
        amount = float(amount)
    except (ValueError, TypeError):
        return jsonify({
            "error": "'telegram_id' debe ser entero y 'amount' debe ser numérico."
        }), 400

    from_channel = data.get("from_channel", "api")
    purchase_date = data.get("purchase_date")

    # Obtener servicios del contenedor de Flask
    container = getattr(current_app, "container", None)
    if container is None:
        return jsonify({
            "error": "Servicios no disponibles",
            "message": "El contenedor de dependencias no está inicializado en la app Flask."
        }), 500

    try:
        payment_service = container.resolve("payment_service")
    except KeyError:
        return jsonify({
            "error": "PaymentService no disponible."
        }), 500

    # Validar y procesar el pago
    result = payment_service.validate_payment(
        telegram_id=telegram_id,
        amount=amount,
        from_channel=from_channel,
        purchase_date=purchase_date,
    )

    if result.success:
        return jsonify({
            "success": True,
            "message": result.message,
            "service_type": result.service_type,
            "service_id": getattr(result.purchase_result, "service_id", None),
        }), 200
    else:
        return jsonify({
            "success": False,
            "error": result.message,
            "is_duplicate": result.is_duplicate,
            "details": result.errors,
        }), 422  # Unprocessable Entity


# ---------------------------------------------------------------------------
# Estadísticas
# ---------------------------------------------------------------------------

@api_bp.route("/stats", methods=["GET"])
@require_api_key
def get_stats():
    """
    Obtiene estadísticas básicas del sistema.

    Returns:
        JSON con estadísticas: suscripciones activas, expiradas,
        usuarios registrados, pagos recientes, etc.
    """
    container = getattr(current_app, "container", None)
    if container is None:
        return jsonify({"error": "Servicios no disponibles."}), 500

    try:
        subscription_service = container.resolve("subscription_service")
        container.resolve("user_repository")
        container.resolve("purchase_repository")

        active_subs = subscription_service.get_active_subscriptions()
        expired_subs = subscription_service.get_expired_subscriptions()

        # Contar usuarios (requiere acceso a la sesión)
        from core.database import SessionLocal
        from models.user import User

        session = SessionLocal()
        try:
            total_users = session.query(User).count()
        finally:
            session.close()

        stats = {
            "active_subscriptions": len(active_subs),
            "expired_subscriptions": len(expired_subs),
            "total_users": total_users,
            "generated_at": datetime.utcnow().isoformat(),
        }

        return jsonify(stats), 200

    except KeyError as e:
        return jsonify({"error": f"Servicio no disponible: {e}"}), 500
    except Exception as e:
        logger.error(f"Error al obtener estadísticas: {e}", exc_info=True)
        return jsonify({"error": "Error interno al obtener estadísticas."}), 500


# ---------------------------------------------------------------------------
# Endpoint para el webhook de Telegram (polling alternativo)
# ---------------------------------------------------------------------------

@api_bp.route("/telegram/webhook", methods=["POST"])
def telegram_webhook():
    """
    Webhook de Telegram para recibir updates (modo webhook en PythonAnywhere).

    En modo polling, este endpoint no se usa. En modo webhook, Telegram
    envía POST requests a este endpoint con cada update.

    Returns:
        200 OK si el update se procesa correctamente.
        500 si hay error.

    Note:
        Este endpoint asume que la aplicación de Telegram está almacenada
        en current_app.telegram_app (se asigna en la factory de Flask).
    """
    telegram_app = getattr(current_app, "telegram_app", None)

    if telegram_app is None:
        logger.error("Telegram app no configurada en la aplicación Flask.")
        return jsonify({
            "error": "Telegram app not configured",
            "message": "El bot no está inicializado en modo webhook."
        }), 500

    try:
        data = request.get_json(force=True)
        if data is None:
            return jsonify({"error": "No se recibieron datos."}), 400

        # Pasar el update a python-telegram-bot
        import asyncio

        from telegram import Update

        update = Update.de_json(data, telegram_app.bot)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(
            telegram_app.process_update(update)
        )
        loop.close()

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        logger.error(f"Error procesando webhook de Telegram: {e}", exc_info=True)
        return jsonify({
            "error": "Error procesando update",
            "message": str(e),
        }), 500


# ---------------------------------------------------------------------------
# Registro de rutas en la app (función helper)
# ---------------------------------------------------------------------------

def register_routes(app) -> None:
    """
    Registra el blueprint de API en una aplicación Flask.

    Args:
        app: Instancia de Flask.

    Example:
        from flask import Flask
        from api.routes import register_routes

        app = Flask(__name__)
        register_routes(app)
    """
    app.register_blueprint(api_bp)
    logger.info("Rutas de API registradas en la aplicación Flask.")
