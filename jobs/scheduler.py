"""
Job Scheduler - Magic Chatbot v2
=================================
Scheduler central para todos los jobs programados del sistema usando APScheduler.

Gestiona la ejecución periódica de tareas de mantenimiento:
- Recordatorios de compra pendiente (cada N minutos).
- Limpieza de suscripciones expiradas (a una hora específica).
- Pipeline de promociones (periódico).
- Sincronización de miembros Telegram ↔ BD (Telethon-based).

Principios:
- Single Responsibility: solo orquestar la planificación y ejecución.
- Fail-safe: los jobs se ejecutan en threads separados y los errores no
  interrumpen el scheduler.
- Configuración externa: intervalos y horas desde settings.
- Graceful shutdown: detiene todos los jobs al apagar la aplicación.

Dependencias:
- APScheduler (BackgroundScheduler).
- Contenedor IoC para resolver servicios bajo demanda.
- Jobs individuales en módulos separados (subscription_cleanup, promotion_batch).

Uso:
    from jobs.scheduler import JobScheduler

    scheduler = JobScheduler(container)
    scheduler.start()  # Inicia todos los jobs programados

    # Al apagar:
    scheduler.shutdown()
"""

import logging
import signal
import sys
from datetime import datetime
from typing import Any

from apscheduler.events import (
    EVENT_JOB_ERROR,
    EVENT_JOB_EXECUTED,
    EVENT_JOB_MISSED,
    JobExecutionEvent,
)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config.settings import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default intervals
DEFAULT_REMINDER_INTERVAL_MINUTES = 10
DEFAULT_PROMOTION_INTERVAL_MINUTES = 15
DEFAULT_SUBSCRIPTION_CHECK_HOUR = 20  # 8 PM Lima time
DEFAULT_CLEANUP_HOUR = 3              # 3 AM Lima time
DEFAULT_WEBHOOK_GUARD_INTERVAL_MINUTES = 1  # Vigilancia de webhook (seguridad)


# ---------------------------------------------------------------------------
# Job Scheduler
# ---------------------------------------------------------------------------

class JobScheduler:
    """
    Scheduler central para todos los jobs programados del bot.

    Utiliza APScheduler (BackgroundScheduler) para ejecutar jobs en
    threads secundarios sin bloquear el hilo principal del bot.

    Jobs gestionados:
    1. process_reminders: Recordatorios de compra pendiente.
    2. process_promotions: Pipeline de promociones BetSafe (DynamoDB).
    3. check_expired_subscriptions: Limpieza de suscripciones vencidas.
    4. sync_members: Sincronización de miembros Telegram ↔ BD.

    Attributes:
        _container: Contenedor IoC para resolver dependencias.
        _scheduler: Instancia de APScheduler BackgroundScheduler.
        _jobs: Diccionario de jobs registrados {job_id: job_info}.
        _running: Flag que indica si el scheduler está activo.
    """

    def __init__(self, container) -> None:
        """
        Inicializa el scheduler con el contenedor de dependencias.

        Args:
            container: Contenedor IoC con todas las dependencias del sistema.
        """
        self._container = container
        self._scheduler: BackgroundScheduler = BackgroundScheduler(
            timezone=settings.TIMEZONE,
            job_defaults={
                "coalesce": True,           # Si se pierde una ejecución, solo ejecuta la última
                "max_instances": 1,         # Solo una instancia del job a la vez
                "misfire_grace_time": 300,  # 5 minutos de gracia para misfires
            },
        )
        self._jobs: dict[str, dict[str, Any]] = {}
        self._running: bool = False
        # Estado del watchdog de webhook (para evitar alertas repetidas)
        self._last_alerted_webhook_url: str | None = None

        # Registrar listeners de eventos para logging
        self._scheduler.add_listener(
            self._on_job_event,
            EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED,
        )

        logger.info("JobScheduler inicializado (APScheduler BackgroundScheduler).")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Inicia el scheduler y registra todos los jobs programados.

        Si ENABLE_JOBS=False en settings, no se inicia ningún job
        (útil para desarrollo local o debugging).

        Debe llamarse después de que el contenedor IoC esté completamente
        inicializado con todas las dependencias.
        """
        if not settings.ENABLE_JOBS:
            logger.info(
                "Jobs programados DESHABILITADOS (ENABLE_JOBS=false). "
                "Solo se ejecutará el bot."
            )
            return

        logger.info("Iniciando JobScheduler y registrando jobs...")

        # Registrar todos los jobs
        self._register_reminder_job()
        self._register_promotion_job()
        self._register_subscription_check_job()
        self._register_member_sync_job()
        self._register_webhook_guard_job()

        # Iniciar el scheduler
        self._scheduler.start()
        self._running = True

        # Mostrar resumen de jobs registrados
        registered_jobs = self._scheduler.get_jobs()
        logger.info(
            f"JobScheduler iniciado con {len(registered_jobs)} jobs:\n"
            + "\n".join(
                f"  • {job.id}: next={job.next_run_time}"
                for job in registered_jobs
            )
        )

    def shutdown(self, wait: bool = True) -> None:
        """
        Detiene el scheduler y todos los jobs programados.

        Args:
            wait: Si True, espera a que los jobs en ejecución terminen.
        """
        if self._running:
            logger.info("Apagando JobScheduler...")
            self._scheduler.shutdown(wait=wait)
            self._running = False
            logger.info("JobScheduler apagado exitosamente.")
        else:
            logger.debug("JobScheduler no estaba en ejecución.")

    def is_running(self) -> bool:
        """
        Verifica si el scheduler está activo.

        Returns:
            True si los jobs están programados y ejecutándose.
        """
        return self._running and self._scheduler.running

    # ------------------------------------------------------------------
    # Registro de jobs individuales
    # ------------------------------------------------------------------

    def _register_reminder_job(self) -> None:
        """
        Registra el job de recordatorios de compra pendiente.

        Se ejecuta cada JOB_REMINDER_INTERVAL_MINUTES minutos (default: 10).
        Procesa la tabla SelectedService para enviar recordatorios a usuarios
        que seleccionaron un servicio pero no completaron la compra.
        """
        interval = getattr(
            settings, "JOB_REMINDER_INTERVAL_MINUTES", DEFAULT_REMINDER_INTERVAL_MINUTES
        )

        job_id = "reminder_job"
        self._scheduler.add_job(
            func=self._process_reminders_wrapper,
            trigger=IntervalTrigger(minutes=interval),
            id=job_id,
            name="Recordatorios de compra pendiente",
            replace_existing=True,
        )
        self._jobs[job_id] = {
            "interval_minutes": interval,
            "description": "Procesa recordatorios de compra pendiente",
        }
        logger.info(
            f"Job '{job_id}' registrado: cada {interval} minutos."
        )

    def _register_promotion_job(self) -> None:
        """
        Registra el job del pipeline de promociones (BetSafe vía DynamoDB).

        Se ejecuta cada 15 minutos por defecto.
        Escanea la tabla DynamoDB 'MAGIC-USER-SESSIONS-LOG' y envía
        promociones de BetSafe según el estado de cada usuario.
        """
        interval = getattr(
            settings, "JOB_PROMOTION_INTERVAL_MINUTES", DEFAULT_PROMOTION_INTERVAL_MINUTES
        )

        job_id = "promotion_job"
        self._scheduler.add_job(
            func=self._process_promotions_wrapper,
            trigger=IntervalTrigger(minutes=interval),
            id=job_id,
            name="Pipeline de promociones BetSafe",
            replace_existing=True,
        )
        self._jobs[job_id] = {
            "interval_minutes": interval,
            "description": "Procesa pipeline de promociones vía DynamoDB",
        }
        logger.info(
            f"Job '{job_id}' registrado: cada {interval} minutos."
        )

    def _register_subscription_check_job(self) -> None:
        """
        Registra el job de verificación de suscripciones expiradas.

        Se ejecuta una vez al día a la hora configurada en
        JOB_SUBSCRIPTION_CHECK_HOUR (default: 20 = 8 PM hora Lima).

        Este job:
        - Verifica suscripciones vencidas en la BD.
        - Envía mensaje de "suscripción vencida" a los usuarios.
        - Expulsa a los usuarios del grupo VIP (kick + unban).
        - Elimina las suscripciones expiradas de la BD.
        """
        hour = int(getattr(
            settings, "JOB_SUBSCRIPTION_CHECK_HOUR", DEFAULT_SUBSCRIPTION_CHECK_HOUR
        ))

        job_id = "subscription_check_job"
        self._scheduler.add_job(
            func=self._check_expired_subscriptions_wrapper,
            trigger=CronTrigger(hour=hour, minute=0),
            id=job_id,
            name="Verificación de suscripciones expiradas",
            replace_existing=True,
        )
        self._jobs[job_id] = {
            "hour": hour,
            "description": "Verifica y limpia suscripciones expiradas",
        }
        logger.info(
            f"Job '{job_id}' registrado: cada día a las {hour:02d}:00 (hora Lima)."
        )

    def _register_member_sync_job(self) -> None:
        """
        Registra el job de sincronización de miembros Telegram ↔ BD.

        Se ejecuta una vez al día a la hora configurada en
        JOB_CLEANUP_HOUR (default: 3 AM hora Lima).

        Este job ejecuta la lógica de getMembersTelethon para:
        - Obtener todos los miembros del grupo VIP vía Telethon.
        - Comparar con la base de datos.
        - Identificar usuarios con suscripción vencida o sin registro.
        - Generar reportes (JSON, CSV) en output/YYYY-MM-DD/.
        - Si está en modo "eliminar", expulsar usuarios del grupo.
        """
        hour = int(getattr(
            settings, "JOB_CLEANUP_HOUR", DEFAULT_CLEANUP_HOUR
        ))

        job_id = "member_sync_job"
        self._scheduler.add_job(
            func=self._sync_members_wrapper,
            trigger=CronTrigger(hour=hour, minute=0),
            id=job_id,
            name="Sincronización de miembros Telegram ↔ BD",
            replace_existing=True,
        )
        self._jobs[job_id] = {
            "hour": hour,
            "description": "Sincroniza miembros del grupo con BD (Telethon)",
        }
        logger.info(
            f"Job '{job_id}' registrado: cada día a las {hour:02d}:00 (hora Lima)."
        )

    def _register_webhook_guard_job(self) -> None:
        """
        Registra el watchdog de seguridad del webhook.

        El bot opera en modo polling (getUpdates) en producción, por lo que
        NUNCA debe existir un webhook. Si un tercero con el token configura
        un webhook (para interceptar mensajes), este job lo detecta, lo
        elimina inmediatamente y alerta a los validadores.

        Se ejecuta cada JOB_WEBHOOK_GUARD_INTERVAL_MINUTES minutos (default: 1).
        """
        interval = getattr(
            settings,
            "JOB_WEBHOOK_GUARD_INTERVAL_MINUTES",
            DEFAULT_WEBHOOK_GUARD_INTERVAL_MINUTES,
        )

        job_id = "webhook_guard_job"
        self._scheduler.add_job(
            func=self._webhook_guard_wrapper,
            trigger=IntervalTrigger(minutes=interval),
            id=job_id,
            name="Watchdog de seguridad del webhook",
            replace_existing=True,
        )
        self._jobs[job_id] = {
            "interval_minutes": interval,
            "description": "Elimina webhooks no autorizados y alerta",
        }
        logger.info(
            f"Job '{job_id}' registrado: cada {interval} minuto(s)."
        )

    # ------------------------------------------------------------------
    # Wrappers de ejecución (con manejo de errores y logging)
    # ------------------------------------------------------------------

    def _process_reminders_wrapper(self) -> None:
        """
        Wrapper seguro para el job de recordatorios.
        Captura y loguea cualquier excepción sin interrumpir el scheduler.
        """
        logger.info("--- INICIO: Job de recordatorios ---")
        try:
            from jobs.promotion_batch import run_reminder_job

            stats = run_reminder_job(self._container)
            logger.info(
                f"Job de recordatorios completado: "
                f"fase1={stats.get('fase1_enviados', 0)}, "
                f"fase2={stats.get('fase2_enviados', 0)}, "
                f"deleted={stats.get('eliminados', 0)}, "
                f"errors={stats.get('errores', 0)}"
            )
        except Exception as e:
            logger.error(
                f"Error crítico en job de recordatorios: {e}",
                exc_info=True,
            )
        logger.info("--- FIN: Job de recordatorios ---")

    def _process_promotions_wrapper(self) -> None:
        """
        Wrapper seguro para el job de pipeline de promociones.
        """
        logger.info("--- INICIO: Job de promociones ---")
        try:
            from jobs.promotion_batch import run_promotion_pipeline

            stats = run_promotion_pipeline(self._container)
            logger.info(
                f"Job de promociones completado: "
                f"procesados={stats.get('total_procesados', 0)}, "
                f"enviadas={stats.get('promos_enviadas', 0)}, "
                f"errores={stats.get('errores', 0)}"
            )
        except Exception as e:
            logger.error(
                f"Error crítico en job de promociones: {e}",
                exc_info=True,
            )
        logger.info("--- FIN: Job de promociones ---")

    def _check_expired_subscriptions_wrapper(self) -> None:
        """
        Wrapper seguro para el job de verificación de suscripciones expiradas.
        """
        logger.info("--- INICIO: Job de verificación de suscripciones ---")
        try:
            from jobs.subscription_cleanup import SubscriptionCleanupJob
            from services.telegram_api import TelegramAPIService

            telegram_api = TelegramAPIService()
            subscription_service = self._container.resolve("subscription_service")
            user_service = self._container.resolve("user_service")

            job = SubscriptionCleanupJob(
                telegram_api=telegram_api,
                subscription_service=subscription_service,
                user_service=user_service,
                container=self._container,
            )
            stats = job.run_db_only(mode="validar")
            logger.info(
                f"Job de verificación de suscripciones completado: "
                f"total={stats.get('total', 0)}, "
                f"expired={stats.get('expired', 0)}, "
                f"removed={stats.get('removed', 0)}"
            )
        except Exception as e:
            logger.error(
                f"Error crítico en job de suscripciones: {e}",
                exc_info=True,
            )
        logger.info("--- FIN: Job de verificación de suscripciones ---")

    def _sync_members_wrapper(self) -> None:
        """
        Wrapper seguro para el job de sincronización de miembros.
        """
        logger.info("--- INICIO: Job de sincronización de miembros ---")
        try:
            import asyncio

            from jobs.subscription_cleanup import SubscriptionCleanupJob
            from services.telegram_api import TelegramAPIService

            telegram_api = TelegramAPIService()
            subscription_service = self._container.resolve("subscription_service")
            user_service = self._container.resolve("user_service")

            job = SubscriptionCleanupJob(
                telegram_api=telegram_api,
                subscription_service=subscription_service,
                user_service=user_service,
                container=self._container,
            )
            stats = asyncio.run(job.run(mode="validar"))
            logger.info(
                f"Job de sincronización de miembros completado: "
                f"telegram_members={stats.get('total_members', 0)}, "
                f"db_members={stats.get('active_subs', 0)}, "
                f"to_remove={stats.get('expired_subs', 0)}, "
                f"removed={stats.get('removed', 0)}, "
                f"errors={len(stats.get('errors', []))}"
            )
        except Exception as e:
            logger.error(
                f"Error crítico en job de sincronización: {e}",
                exc_info=True,
            )
        logger.info("--- FIN: Job de sincronización de miembros ---")

    def _webhook_guard_wrapper(self) -> None:
        """
        Watchdog de seguridad: detecta y elimina webhooks no autorizados.

        El bot usa polling en producción, así que cualquier webhook activo es
        indicio de que el token está siendo usado por un tercero. Si se
        detecta uno, se elimina y se alerta a los validadores (solo una vez
        por URL para evitar spam).
        """
        try:
            from services.telegram_api import TelegramAPIService

            api = TelegramAPIService()
            info = api.get_webhook_info(log_errors=False)
            url = (info.get("url") or "").strip()

            if not url:
                # Sin webhook: estado correcto. Reiniciar el dedupe de alertas.
                self._last_alerted_webhook_url = None
                return

            # ¡Webhook no autorizado detectado!
            logger.warning(
                f"⚠️ WEBHOOK NO AUTORIZADO detectado: {url}. Eliminando..."
            )
            api.delete_webhook(drop_pending_updates=False, log_errors=True)
            logger.warning("✅ Webhook no autorizado eliminado.")

            # Alertar a los validadores solo si es una URL nueva
            if url != self._last_alerted_webhook_url:
                self._last_alerted_webhook_url = url
                alert = (
                    "🚨 <b>ALERTA DE SEGURIDAD</b>\n\n"
                    "Se detectó y eliminó un <b>webhook no autorizado</b> "
                    "en el bot:\n"
                    f"<code>{url}</code>\n\n"
                    "Esto indica que el token está comprometido. "
                    "Se recomienda rotar el token cuanto antes."
                )
                for vid in settings.TELEGRAM_VALIDATOR_IDS:
                    try:
                        api.send_message(
                            chat_id=int(vid),
                            text=alert,
                            parse_mode="HTML",
                            log_errors=False,
                        )
                    except Exception:
                        pass
        except Exception as e:
            logger.error(
                f"Error en watchdog de webhook: {e}",
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # Eventos del scheduler (logging)
    # ------------------------------------------------------------------

    def _on_job_event(self, event: JobExecutionEvent) -> None:
        """
        Callback para eventos de APScheduler (éxito, error, missed).

        Args:
            event: Evento del scheduler (JobExecutionEvent).
        """
        if event.exception:
            logger.error(
                f"Job '{event.job_id}' FALLÓ: {event.exception}",
                exc_info=event.exception,
            )
        elif event.code == EVENT_JOB_MISSED:
            logger.warning(
                f"Job '{event.job_id}' NO SE EJECUTÓ (misfire) a las "
                f"{event.scheduled_run_time}"
            )
        elif event.code == EVENT_JOB_EXECUTED:
            logger.debug(
                f"Job '{event.job_id}' ejecutado exitosamente. "
                f"Return value: {event.retval}"
            )

    # ------------------------------------------------------------------
    # Métodos de utilidad
    # ------------------------------------------------------------------

    def get_jobs_status(self) -> dict[str, Any]:
        """
        Obtiene el estado actual de todos los jobs registrados.

        Returns:
            Diccionario con {job_id: {next_run, trigger, status}}.
        """
        status = {}
        for job in self._scheduler.get_jobs():
            status[job.id] = {
                "name": job.name,
                "next_run": str(job.next_run_time) if job.next_run_time else None,
                "trigger": str(job.trigger),
                "pending": job.pending,
            }
        return status

    def trigger_job_now(self, job_id: str) -> bool:
        """
        Ejecuta un job específico inmediatamente (para testing/debug).

        Args:
            job_id: ID del job a ejecutar.

        Returns:
            True si el job se encoló para ejecución inmediata.
        """
        job = self._scheduler.get_job(job_id)
        if job:
            logger.info(f"Ejecutando job '{job_id}' manualmente...")
            job.modify(next_run_time=datetime.now())
            return True
        else:
            logger.warning(f"Job '{job_id}' no encontrado.")
            return False

    def pause_job(self, job_id: str) -> None:
        """
        Pausa un job específico.

        Args:
            job_id: ID del job a pausar.
        """
        job = self._scheduler.get_job(job_id)
        if job:
            self._scheduler.pause_job(job_id)
            logger.info(f"Job '{job_id}' pausado.")
        else:
            logger.warning(f"Job '{job_id}' no encontrado.")

    def resume_job(self, job_id: str) -> None:
        """
        Reanuda un job pausado.

        Args:
            job_id: ID del job a reanudar.
        """
        job = self._scheduler.get_job(job_id)
        if job:
            self._scheduler.resume_job(job_id)
            logger.info(f"Job '{job_id}' reanudado.")
        else:
            logger.warning(f"Job '{job_id}' no encontrado.")


# ---------------------------------------------------------------------------
# Helper: registrar señales de shutdown para apagado graceful
# ---------------------------------------------------------------------------

def register_shutdown_handlers(scheduler: JobScheduler) -> None:
    """
    Registra handlers para señales del sistema operativo (SIGINT, SIGTERM)
    que apagan el scheduler de forma graceful.

    Args:
        scheduler: Instancia de JobScheduler a apagar.

    Example:
        scheduler = JobScheduler(container)
        scheduler.start()
        register_shutdown_handlers(scheduler)
    """
    def _shutdown(signum, frame):
        logger.info(f"Recibida señal {signum}. Apagando scheduler...")
        scheduler.shutdown(wait=True)
        logger.info("Scheduler apagado. Saliendo.")
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)
    logger.debug("Handlers de señal SIGINT/SIGTERM registrados.")
