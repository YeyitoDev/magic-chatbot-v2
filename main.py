"""
Magic Chatbot v2 - Main Entry Point
=====================================
Punto de entrada principal de la aplicación refactorizada.

Soporta dos modos de ejecución:
1. Modo Polling (desarrollo local):
   El bot consulta continuamente a Telegram por nuevos mensajes.
   Ideal para desarrollo y testing.

2. Modo Webhook (producción - PythonAnywhere):
   Telegram envía updates a un endpoint HTTP.
   Más eficiente y recomendado para producción en PythonAnywhere.

También puede ejecutar jobs programados en modo standalone:
   python main.py --jobs-only    (solo jobs, sin bot)
   python main.py --all           (bot + jobs en hilos separados)

Uso:
    # Desarrollo local (polling)
    python main.py

    # Producción (webhook + jobs)
    python main.py --mode webhook

    # Solo jobs programados
    python main.py --jobs-only

    # Ejecutar job de limpieza de suscripciones
    python main.py --cleanup

    # Ejecutar pipeline de promociones
    python main.py --promotions

Environment:
    Todas las credenciales se leen de variables de entorno (.env).
    Copia .env.example a .env y completa los valores antes de ejecutar.

Autor: Magic Chatbot v2 Team
"""

import argparse
import asyncio
import logging
import os
import sys
import threading

# ---------------------------------------------------------------------------
# Configuración temprana de logging
# ---------------------------------------------------------------------------
from utils.logger import configure_root_logger, init_logging

init_logging()
configure_root_logger()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Banner de inicio
# ---------------------------------------------------------------------------

def print_banner() -> None:
    """Imprime el banner ASCII de inicio del bot."""
    banner = """
    ╔══════════════════════════════════════════════╗
    ║          MAGIC CHATBOT v2.0 🔮               ║
    ║  Sistema de Gestión de Suscripciones VIP     ║
    ║  y Validación de Pagos vía Telegram          ║
    ╚══════════════════════════════════════════════╝
    """
    print(banner)


# ---------------------------------------------------------------------------
# Inicialización del sistema
# ---------------------------------------------------------------------------

def initialize_system():
    """
    Inicializa los componentes CORE del sistema:
    1. Valida variables de entorno requeridas.
    2. Crea tablas en la base de datos (si no existen).
    3. Inicializa el contenedor de dependencias con todos los servicios.
    4. Configura directorios necesarios (images, output, logs, csv).

    Returns:
        El contenedor de dependencias inicializado.

    Raises:
        SystemExit: Si faltan variables de entorno críticas.
    """
    from config.settings import settings
    from core.container import container
    from core.database import init_db

    # ------------------------------------------------------------------
    # Paso 1: Validar variables de entorno
    # ------------------------------------------------------------------
    logger.info("Validando variables de entorno...")
    try:
        settings.validate(raise_exception=True)
        logger.info("✅ Variables de entorno OK.")
    except ValueError as e:
        logger.critical(f"❌ Error de configuración: {e}")
        sys.exit(1)

    logger.info(f"Environment: {settings.ENVIRONMENT}")
    logger.info(f"Debug: {settings.DEBUG}")
    logger.info(f"Timezone: {settings.TIMEZONE}")

    # ------------------------------------------------------------------
    # Paso 2: Crear directorios necesarios
    # ------------------------------------------------------------------
    directories = [
        "./images",          # Comprobantes de pago
        "./output",          # Reportes de jobs
        "./logs",            # Archivos de log
        "./csv",             # Datos CSV de API externa
        "./estados",         # Estados de validación (legacy compat)
    ]
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
    logger.info(f"✅ Directorios de trabajo creados: {', '.join(directories)}")

    # ------------------------------------------------------------------
    # Paso 3: Inicializar base de datos
    # ------------------------------------------------------------------
    try:
        logger.info("Inicializando base de datos...")
        init_db()
        logger.info("✅ Base de datos inicializada (tablas creadas si no existían).")

        from core.database import engine
        from core.schema import missing_columns

        pending = missing_columns(engine)
        if pending:
            logger.critical(
                f"❌ Faltan columnas en la BD: {', '.join(pending)}. "
                f"Aplica las migraciones de migrations/ antes de iniciar el bot."
            )
            sys.exit(1)
    except Exception as e:
        logger.error(f"⚠️  No se pudo inicializar la BD: {e}")
        if settings.is_production():
            logger.critical("❌ Error crítico de BD en producción. Abortando.")
            sys.exit(1)
        else:
            logger.warning("Continuando sin BD inicializada (modo desarrollo).")

    # ------------------------------------------------------------------
    # Paso 4: Inicializar contenedor de dependencias
    # ------------------------------------------------------------------
    logger.info("Inicializando contenedor de dependencias...")
    try:
        container.initialize_defaults()
        logger.info("✅ Contenedor IoC inicializado.")
        services = container.list_services()
        logger.info(f"   Servicios registrados: {len(services)}")
        for name, svc_type in sorted(services.items()):
            logger.debug(f"     • {name}: {svc_type}")
    except Exception as e:
        logger.error(f"❌ Error al inicializar contenedor: {e}", exc_info=True)
        sys.exit(1)

    logger.info("🚀 Sistema inicializado correctamente.")
    return container


# ---------------------------------------------------------------------------
# Construcción de la aplicación de Telegram
# ---------------------------------------------------------------------------

def build_telegram_app(container):
    """
    Construye y configura la Application de python-telegram-bot.

    Registra todos los handlers (comandos, mensajes, callbacks, errores)
    conectándolos con los servicios del contenedor IoC.

    Args:
        container: Contenedor de dependencias inicializado.

    Returns:
        Application de python-telegram-bot lista para ejecutar.
    """
    from telegram import Update
    from telegram.ext import (
        ApplicationBuilder,
        CallbackQueryHandler,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        TypeHandler,
        filters,
    )

    from config.settings import settings

    logger.info("Construyendo aplicación de Telegram...")

    # ------------------------------------------------------------------
    # Resolver servicios necesarios
    # ------------------------------------------------------------------
    user_service = container.resolve("user_service")
    subscription_service = container.resolve("subscription_service")
    payment_service = container.resolve("payment_service")

    # Servicios opcionales - Sheets first (repara creds de Google para Vision)
    sheets_service = None
    try:
        sheets_service = container.resolve("google_sheets_service")
    except (KeyError, FileNotFoundError, Exception):
        try:
            from services.google_sheets import GoogleSheetsService
            sheets_service = GoogleSheetsService()
        except (FileNotFoundError, Exception) as e:
            logger.warning(f"Sheets service no disponible: {e}")

    vision_service = None
    try:
        vision_service = container.resolve("vision_service")
    except (KeyError, FileNotFoundError, Exception):
        try:
            from services.google_vision import GoogleVisionService
            vision_service = GoogleVisionService()
        except (FileNotFoundError, Exception) as e:
            logger.warning(f"Vision service no disponible: {e}")

    promotion_service = None
    try:
        promotion_service = container.resolve("promotion_service")
    except KeyError:
        try:
            from services.promotion_service import PromotionService
            promotion_service = PromotionService()
        except Exception as e:
            logger.warning(f"Promotion service no disponible: {e}")

    # ------------------------------------------------------------------
    # Crear handlers
    # ------------------------------------------------------------------
    from handlers.callbacks import CallbackHandlers
    from handlers.commands import CommandHandlers
    from handlers.errors import ErrorHandler
    from handlers.messages import MessageHandlers

    command_handlers = CommandHandlers(
        user_service=user_service,
        subscription_service=subscription_service,
        payment_service=payment_service,
        vision_service=vision_service,
        sheets_service=sheets_service,
        promotion_service=promotion_service,
    )

    message_handlers = MessageHandlers(
        user_service=user_service,
        payment_service=payment_service,
        vision_service=vision_service,
        gemini_vision_service=container.resolve("gemini_vision_service"),
        promotion_service=promotion_service,
        container=container,
    )

    callback_handlers = CallbackHandlers(
        user_service=user_service,
        subscription_service=subscription_service,
        payment_service=payment_service,
        vision_service=vision_service,
        sheets_service=sheets_service,
        promotion_service=promotion_service,
    )

    # ------------------------------------------------------------------
    # Construir Application
    # ------------------------------------------------------------------
    app = (
        ApplicationBuilder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .build()
    )

    # ------------------------------------------------------------------
    # Hook de saneamiento de sesión de BD (group=-1, corre antes que todo)
    # ------------------------------------------------------------------
    # Garantiza que la sesión compartida de SQLAlchemy esté limpia al inicio
    # de CADA update. Esto evita el efecto cascada de PendingRollbackError
    # cuando una operación previa dejó la sesión en estado inválido
    # (especialmente cuando el error fue capturado internamente sin rollback).
    async def _ensure_clean_db_session(
        update: object, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        try:
            if container.is_registered("db_session"):
                session = container.resolve("db_session")
                # rollback() limpia cualquier transacción inválida pendiente.
                # Si la conexión está muerta, pool_pre_ping la reemplaza en la
                # próxima query. Es un no-op si la sesión ya está limpia.
                session.rollback()
        except Exception as e:
            logger.warning(f"No se pudo sanear la sesión de BD antes del update: {e}")
            # Como último recurso, reciclar el pool de conexiones.
            try:
                from core.database import engine
                engine.dispose()
            except Exception:
                pass

    app.add_handler(TypeHandler(Update, _ensure_clean_db_session), group=-1)
    logger.info("✅ Hook de saneamiento de sesión de BD registrado (group=-1).")

    # ------------------------------------------------------------------
    # Registrar handlers de comandos
    # ------------------------------------------------------------------
    app.add_handler(CommandHandler("start", command_handlers.start))
    app.add_handler(CommandHandler("vm", command_handlers.validar_monto))
    app.add_handler(CommandHandler("wsp", command_handlers.registro_usuario_wsp))
    app.add_handler(CommandHandler("valid", command_handlers.register_user_from_api))
    app.add_handler(CommandHandler("id", command_handlers.validador_business_user_id))
    app.add_handler(
        CommandHandler("mensaje_recordatorio", command_handlers.envio_mensaje_recordatorio)
    )
    app.add_handler(CommandHandler("servicio_id", command_handlers.servicio_id))
    app.add_handler(CommandHandler("generar_link", command_handlers.generar_link_servicio))
    app.add_handler(CommandHandler("link", command_handlers.generar_link_servicio))
    app.add_handler(CommandHandler("version", command_handlers.version))
    app.add_handler(CommandHandler("delete", command_handlers.delete_purchase))
    app.add_handler(CommandHandler("help", command_handlers.start))  # help redirige a start

    logger.info("✅ Handlers de comandos registrados: /start, /vm, /wsp, /valid, /id, /delete, /version, /help")

    # ------------------------------------------------------------------
    # Registrar handlers de callbacks (botones inline)
    # ------------------------------------------------------------------
    app.add_handler(
        CallbackQueryHandler(callback_handlers.handle_button)
    )
    logger.info("✅ Handler de callbacks registrado.")

    # ------------------------------------------------------------------
    # Registrar handlers de mensajes
    # ------------------------------------------------------------------
    # Texto que NO son comandos
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_handlers.echo)
    )
    # Imágenes (comprobantes de pago)
    app.add_handler(
        MessageHandler(filters.PHOTO, message_handlers.handle_image)
    )
    logger.info("✅ Handlers de mensajes registrados (texto + imágenes).")

    # ------------------------------------------------------------------
    # Registrar handler global de errores
    # ------------------------------------------------------------------
    ErrorHandler.register(app)
    logger.info("✅ Handler global de errores registrado.")

    logger.info("🏗️  Aplicación de Telegram construida exitosamente.")
    return app


# ============================================================================
# Modos de ejecución
# ============================================================================

def run_polling(app) -> None:
    """
    Ejecuta el bot en modo polling (desarrollo local).

    El bot consulta continuamente a Telegram por nuevos updates.
    Ideal para desarrollo, pero menos eficiente que webhook.

    Args:
        app: Application de python-telegram-bot.
    """

    logger.info("🤖 Iniciando bot en modo POLLING...")
    logger.info("   Presiona Ctrl+C para detener.")

    try:
        app.run_polling(
            poll_interval=1.0,
            timeout=30,
            drop_pending_updates=True,  # Eliminar webhook y limpiar updates pendientes
            allowed_updates=["message", "callback_query"],
        )
    except KeyboardInterrupt:
        logger.info("🛑 Bot detenido por el usuario (Ctrl+C).")
    except Exception as e:
        logger.critical(f"❌ Error fatal en polling: {e}", exc_info=True)
        raise


async def setup_webhook(app, webhook_url: str) -> None:
    """
    Configura el webhook de Telegram para recibir updates vía HTTP POST.

    Args:
        app: Application de python-telegram-bot.
        webhook_url: URL completa del webhook (ej: https://tudominio.com/webhook).
    """
    logger.info(f"🌐 Configurando webhook en: {webhook_url}")

    await app.bot.set_webhook(
        url=webhook_url,
        drop_pending_updates=True,
        max_connections=40,
    )

    webhook_info = await app.bot.get_webhook_info()
    logger.info(f"   Webhook info: {webhook_info}")

    if webhook_info.url != webhook_url:
        logger.critical("❌ El webhook no se configuró correctamente.")
        raise RuntimeError("Webhook setup failed")
    else:
        logger.info("✅ Webhook configurado correctamente.")


async def remove_webhook(app) -> None:
    """
    Elimina el webhook de Telegram (útil al cambiar de webhook a polling).
    """
    logger.info("🗑️  Eliminando webhook...")
    await app.bot.delete_webhook(drop_pending_updates=True)
    logger.info("✅ Webhook eliminado.")


def run_jobs(container) -> None:
    """
    Ejecuta el scheduler de jobs programados.
    Se ejecuta en un hilo separado cuando se usa --all.
    """
    from jobs.scheduler import JobScheduler, register_shutdown_handlers

    logger.info("🕐 Iniciando scheduler de jobs programados...")

    scheduler = JobScheduler(container)
    register_shutdown_handlers(scheduler)
    scheduler.start()

    logger.info("✅ Scheduler de jobs iniciado.")


def run_cleanup_job(container) -> None:
    """
    Ejecuta el job de limpieza de suscripciones una sola vez.
    Activado con: python main.py --cleanup
    """
    from jobs.subscription_cleanup import SubscriptionCleanupJob
    from services.telegram_api import TelegramAPIService

    logger.info("🧹 Ejecutando job de limpieza de suscripciones...")

    telegram_api = TelegramAPIService()
    subscription_service = container.resolve("subscription_service")
    user_service = container.resolve("user_service")

    job = SubscriptionCleanupJob(
        telegram_api=telegram_api,
        subscription_service=subscription_service,
        user_service=user_service,
    )

    import asyncio
    result = asyncio.run(job.run(mode="validar"))
    logger.info(f"✅ Limpieza completada: {result}")


def run_promotion_job(container) -> None:
    """
    Ejecuta el job de pipeline de promociones una sola vez.
    Activado con: python main.py --promotions
    """
    from jobs.promotion_batch import PromotionBatchJob

    logger.info("📢 Ejecutando pipeline de promociones...")

    job = PromotionBatchJob()
    results = job.run()

    sent = sum(1 for r in results if r.get("action") == "promo_sent")
    finalized = sum(1 for r in results if r.get("action") == "finalized")
    logger.info(f"✅ Pipeline completado: {sent} enviadas, {finalized} finalizados.")


# ============================================================================
# Punto de entrada principal
# ============================================================================

def main():
    """
    Punto de entrada principal. Despacha según los argumentos de línea
    de comandos al modo de ejecución correspondiente.
    """
    parser = argparse.ArgumentParser(
        description="Magic Chatbot v2 - Telegram Bot para gestión de suscripciones VIP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python main.py                     # Modo polling (desarrollo)
  python main.py --mode webhook      # Modo webhook (producción)
  python main.py --all               # Bot + jobs en paralelo
  python main.py --jobs-only         # Solo jobs (sin bot)
  python main.py --cleanup           # Ejecuta limpieza de suscripciones
  python main.py --promotions        # Ejecuta pipeline de promociones
        """,
    )

    parser.add_argument(
        "--mode",
        choices=["polling", "webhook"],
        default="polling",
        help="Modo de ejecución del bot. Default: polling.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Ejecutar bot + jobs programados en paralelo.",
    )
    parser.add_argument(
        "--jobs-only",
        action="store_true",
        help="Ejecutar SOLO los jobs programados (sin bot).",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Ejecutar job de limpieza de suscripciones una vez y salir.",
    )
    parser.add_argument(
        "--promotions",
        action="store_true",
        help="Ejecutar pipeline de promociones una vez y salir.",
    )
    parser.add_argument(
        "--remove-webhook",
        action="store_true",
        help="Eliminar webhook y salir (útil para cambiar a polling).",
    )

    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Mostrar banner
    # ------------------------------------------------------------------
    print_banner()

    # ------------------------------------------------------------------
    # Inicializar sistema
    # ------------------------------------------------------------------
    container = initialize_system()
    from config.settings import settings

    # ------------------------------------------------------------------
    # Startup logging
    # ------------------------------------------------------------------
    init_logging()
    configure_root_logger()
    logger.info(f"Magic Chatbot v2 starting - env={settings.ENVIRONMENT} - pid={os.getpid()}")

    # ------------------------------------------------------------------
    # Modo: Eliminar webhook
    # ------------------------------------------------------------------
    if args.remove_webhook:
        app = build_telegram_app(container)
        asyncio.run(remove_webhook(app))
        logger.info("✅ Webhook eliminado. Ahora puedes iniciar en modo polling.")
        return

    # ------------------------------------------------------------------
    # Modo: Solo jobs programados
    # ------------------------------------------------------------------
    if args.jobs_only:
        logger.info("📋 Modo: SOLO JOBS PROGRAMADOS")
        run_jobs(container)
        # Mantener vivo el proceso (los jobs corren en background)
        try:
            while True:
                import time
                time.sleep(60)
        except KeyboardInterrupt:
            logger.info("🛑 Jobs detenidos por el usuario.")
        return

    # ------------------------------------------------------------------
    # Modo: Ejecutar job de limpieza y salir
    # ------------------------------------------------------------------
    if args.cleanup:
        run_cleanup_job(container)
        return

    # ------------------------------------------------------------------
    # Modo: Ejecutar pipeline de promociones y salir
    # ------------------------------------------------------------------
    if args.promotions:
        run_promotion_job(container)
        return

    # ------------------------------------------------------------------
    # Modo: Bot + Jobs en paralelo
    # ------------------------------------------------------------------
    if args.all:
        logger.info("🤖 Modo: BOT + JOBS EN PARALELO")

        # Iniciar jobs en un thread separado
        jobs_thread = threading.Thread(
            target=run_jobs,
            args=(container,),
            daemon=True,
            name="job-scheduler",
        )
        jobs_thread.start()
        logger.info("   Jobs iniciados en thread separado.")

        # Construir y ejecutar el bot
        app = build_telegram_app(container)

        if args.mode == "webhook":
            webhook_url = settings.TELEGRAM_WEBHOOK_URL
            if not webhook_url:
                logger.error(
                    "❌ TELEGRAM_WEBHOOK_URL no está configurado en .env.\n"
                    "   Configúralo o usa --mode polling."
                )
                sys.exit(1)
            logger.info(f"🌐 Iniciando bot en modo WEBHOOK: {webhook_url}")
            # En webhook, usamos Flask para recibir los updates
            from api.app import create_app as create_flask_app
            flask_app = create_flask_app(container=container)
            flask_app.telegram_app = app
            asyncio.run(setup_webhook(app, webhook_url))
            logger.info(f"Iniciando servidor Flask en {settings.FLASK_HOST}:{settings.FLASK_PORT}")
            flask_app.run(
                host=settings.FLASK_HOST,
                port=settings.FLASK_PORT,
                debug=settings.DEBUG,
            )
        else:
            from health_server import start_health_server
            start_health_server()
            run_polling(app)

        return

    # ------------------------------------------------------------------
    # Modo: Solo Bot (polling o webhook)
    # ------------------------------------------------------------------
    logger.info(f"🤖 Modo: SOLO BOT ({args.mode.upper()})")

    app = build_telegram_app(container)

    if args.mode == "webhook":
        webhook_url = settings.TELEGRAM_WEBHOOK_URL
        if not webhook_url:
            logger.error(
                "❌ TELEGRAM_WEBHOOK_URL no está configurado en .env.\n"
                "   Configúralo o usa --mode polling."
            )
            sys.exit(1)

        logger.info(f"🌐 Iniciando en modo WEBHOOK: {webhook_url}")
        from api.app import create_app as create_flask_app
        flask_app = create_flask_app(container=container)
        flask_app.telegram_app = app
        asyncio.run(setup_webhook(app, webhook_url))
        logger.info(f"Iniciando servidor Flask en {settings.FLASK_HOST}:{settings.FLASK_PORT}")
        flask_app.run(
            host=settings.FLASK_HOST,
            port=settings.FLASK_PORT,
            debug=settings.DEBUG,
        )
    else:
        # Modo polling (default)
        from health_server import start_health_server
        start_health_server()
        run_polling(app)

    logger.info("👋 Magic Chatbot v2 finalizado. ¡Hasta pronto!")


# ============================================================================
# Entry point
# ============================================================================

if __name__ == "__main__":
    """
    Punto de entrada cuando se ejecuta directamente:
        python main.py [argumentos]
    """
    try:
        main()
    except KeyboardInterrupt:
        logger.info("👋 Detenido por el usuario (Ctrl+C).")
        sys.exit(0)
    except Exception as e:
        logger.critical(
            f"❌ Error fatal no controlado: {e}",
            exc_info=True,
        )
        sys.exit(1)
