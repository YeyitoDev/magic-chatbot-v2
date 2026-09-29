"""
Promotion & Reminder Batch Job - Magic Chatbot v2
===================================================
Job por lotes que ejecuta dos tareas programadas:

1. **Pipeline de Promociones (DynamoDB):**
   Escanea la tabla DynamoDB de sesiones de usuarios, evalúa timestamps
   y envía promociones de BetSafe según la etapa del pipeline
   (Promo_15_min → Promo_24_horas → FINALIZADO).

2. **Recordatorios de Compra Pendiente:**
   Revisa la tabla `selected_services` de MySQL y envía recordatorios
   a usuarios que seleccionaron un servicio pero no completaron la compra.

Este script reemplaza y unifica la lógica de `jobMensajesRecordatorios.py`
y `jobMain.py` del código legacy, siguiendo principios SOLID.

Ejecución:
    python -m jobs.promotion_batch           # Ejecución única
    python -m jobs.promotion_batch --daemon  # Modo continuo (cada N minutos)

O programado vía APScheduler en scheduler.py o cron en PythonAnywhere.

Autor: Magic Chatbot v2 Team
"""

import argparse
import sys
import time
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Configuración de logging
# ---------------------------------------------------------------------------
from utils.logger import setup_logger

logger = setup_logger(
    "jobs.promotion_batch",
    log_format="text",
    console_output=True,
)


# ---------------------------------------------------------------------------
# Funciones principales del job
# ---------------------------------------------------------------------------

def run_promotion_pipeline(container) -> dict[str, Any]:
    """
    Ejecuta una iteración del pipeline de promociones de BetSafe.

    Flujo:
    1. Obtiene el PromotionService del contenedor.
    2. Escanea DynamoDB por usuarios con estado != 'FINALIZADO'.
    3. Evalúa timestamps y envía la promo correspondiente.
    4. Actualiza estados en DynamoDB.
    5. Retorna estadísticas del procesamiento.

    Args:
        container: Contenedor de dependencias inicializado.

    Returns:
        Diccionario con estadísticas: total_procesados, promos_enviadas, finalizados, errores.
    """
    logger.info("=" * 60)
    logger.info("INICIANDO PIPELINE DE PROMOCIONES (DynamoDB)")
    logger.info("=" * 60)

    stats = {
        "total_procesados": 0,
        "promos_enviadas": 0,
        "finalizados": 0,
        "errores": 0,
        "timestamp": datetime.now().isoformat(),
    }

    try:
        promotion_service = container.resolve("promotion_service")
    except KeyError:
        logger.error(
            "PromotionService no está registrado en el contenedor. "
            "Verifica la inicialización en core/container.py."
        )
        return stats

    if promotion_service is None:
        logger.warning(
            "PromotionService no está disponible. "
            "Verifica las credenciales de AWS y la configuración de DynamoDB."
        )
        return stats

    try:
        results = promotion_service.process_promotion_pipeline()

        for item in results:
            action = item.get("action", "unknown")
            if action == "promo_sent":
                stats["promos_enviadas"] += 1
            elif action == "finalized":
                stats["finalizados"] += 1
            elif action == "error":
                stats["errores"] += 1

        stats["total_procesados"] = len(results)

        # Obtener estadísticas acumuladas del pipeline
        try:
            pipeline_stats = promotion_service.get_pipeline_stats()
            logger.info(
                f"Estadísticas acumuladas del pipeline: "
                f"pendiente={pipeline_stats.get('pendiente', 0)}, "
                f"promo_15min={pipeline_stats.get('Promo_15_min', 0)}, "
                f"promo_24h={pipeline_stats.get('Promo_24_horas', 0)}, "
                f"finalizado={pipeline_stats.get('FINALIZADO', 0)}, "
                f"total={pipeline_stats.get('total', 0)}"
            )
        except Exception as e:
            logger.warning(f"No se pudieron obtener estadísticas acumuladas: {e}")

    except Exception as e:
        logger.error(
            f"Error en el pipeline de promociones: {e}", exc_info=True
        )
        stats["errores"] += 1

    logger.info(
        f"Pipeline de promociones completado: "
        f"total={stats['total_procesados']}, "
        f"enviadas={stats['promos_enviadas']}, "
        f"finalizados={stats['finalizados']}, "
        f"errores={stats['errores']}"
    )

    return stats


def run_reminder_job(container) -> dict[str, Any]:
    """
    Ejecuta una iteración del job de recordatorios de compra pendiente.

    Flujo:
    1. Obtiene el ReminderService del contenedor.
    2. Procesa todos los SelectedService con recordatorios pendientes.
    3. Envía recordatorios fase 1 (foto + precios) o fase 2 (video).
    4. Elimina registros expirados.
    5. Retorna estadísticas del procesamiento.

    Args:
        container: Contenedor de dependencias inicializado.

    Returns:
        Diccionario con estadísticas: total, fase1, fase2, eliminados, errores.
    """
    logger.info("=" * 60)
    logger.info("INICIANDO JOB DE RECORDATORIOS DE COMPRA")
    logger.info("=" * 60)

    stats = {
        "total_procesados": 0,
        "fase1_enviados": 0,
        "fase2_enviados": 0,
        "eliminados": 0,
        "errores": 0,
        "timestamp": datetime.now().isoformat(),
    }

    try:
        reminder_service = container.resolve("reminder_service")
    except KeyError:
        logger.error(
            "ReminderService no está registrado en el contenedor. "
            "Verifica la inicialización en core/container.py."
        )
        return stats

    if reminder_service is None:
        logger.warning("ReminderService no está disponible.")
        return stats

    try:
        result = reminder_service.process_pending_reminders()

        stats["total_procesados"] = result.get("total_processed", 0)
        stats["fase1_enviados"] = result.get("phase1_sent", 0)
        stats["fase2_enviados"] = result.get("phase2_sent", 0)
        stats["eliminados"] = result.get("deleted", 0)
        stats["errores"] = len(result.get("errors", []))

        if result.get("errors"):
            for error in result["errors"]:
                logger.error(f"  Error: {error}")

    except Exception as e:
        logger.error(f"Error en job de recordatorios: {e}", exc_info=True)
        stats["errores"] += 1

    logger.info(
        f"Job de recordatorios completado: "
        f"total={stats['total_procesados']}, "
        f"fase1={stats['fase1_enviados']}, "
        f"fase2={stats['fase2_enviados']}, "
        f"eliminados={stats['eliminados']}, "
        f"errores={stats['errores']}"
    )

    return stats


def run_all_jobs(container) -> dict[str, Any]:
    """
    Ejecuta todos los jobs batch en secuencia.

    Args:
        container: Contenedor de dependencias.

    Returns:
        Diccionario con los resultados individuales de cada job.
    """
    resultados = {}

    # 1. Pipeline de promociones (DynamoDB)
    try:
        resultados["promotion_pipeline"] = run_promotion_pipeline(container)
    except Exception as e:
        logger.error(f"Fallo crítico en promotion_pipeline: {e}")
        resultados["promotion_pipeline"] = {"error": str(e)}

    # 2. Recordatorios de compra pendiente
    try:
        resultados["reminder_job"] = run_reminder_job(container)
    except Exception as e:
        logger.error(f"Fallo crítico en reminder_job: {e}")
        resultados["reminder_job"] = {"error": str(e)}

    return resultados


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """
    Punto de entrada principal del job batch.

    Soporta dos modos:
    - Ejecución única (por defecto): ejecuta todos los jobs una vez y sale.
    - Modo daemon (--daemon): ejecuta los jobs en loop cada N minutos.

    Uso:
        python -m jobs.promotion_batch
        python -m jobs.promotion_batch --daemon
        python -m jobs.promotion_batch --interval 5
    """
    parser = argparse.ArgumentParser(
        description="Magic Chatbot v2 - Promotion & Reminder Batch Job"
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Ejecutar en modo continuo (daemon) en lugar de una sola vez.",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Intervalo en minutos entre ejecuciones en modo daemon (default: 10).",
    )
    parser.add_argument(
        "--skip-promotions",
        action="store_true",
        help="Omitir el pipeline de promociones (DynamoDB).",
    )
    parser.add_argument(
        "--skip-reminders",
        action="store_true",
        help="Omitir los recordatorios de compra pendiente.",
    )
    parser.add_argument(
        "--skip-db-init",
        action="store_true",
        help="No inicializar la base de datos (útil si ya está inicializada).",
    )
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("MAGIC CHATBOT v2 - BATCH JOB")
    logger.info(f"Hora de inicio: {datetime.now().isoformat()}")
    logger.info(f"Modo: {'daemon' if args.daemon else 'único'}")
    if args.daemon:
        logger.info(f"Intervalo: {args.interval} minutos")
    logger.info("=" * 60)

    # Inicializar el contenedor de dependencias
    from core.container import container

    if not args.skip_db_init:
        try:
            logger.info("Inicializando base de datos...")
            from core.database import init_db
            init_db()
            logger.info("Base de datos inicializada correctamente.")
        except Exception as e:
            logger.warning(
                f"No se pudo inicializar la base de datos: {e}. "
                f"Continuando de todas formas..."
            )

    # Inicializar dependencias del contenedor
    try:
        container.initialize_defaults()
        logger.info("Contenedor de dependencias inicializado correctamente.")
        logger.info(
            f"Servicios registrados: {list(container.list_services().keys())}"
        )
    except Exception as e:
        logger.error(
            f"Error al inicializar el contenedor de dependencias: {e}",
            exc_info=True,
        )
        sys.exit(1)

    # Ejecutar jobs
    if args.daemon:
        _run_daemon(
            container=container,
            interval_minutes=args.interval,
            skip_promotions=args.skip_promotions,
            skip_reminders=args.skip_reminders,
        )
    else:
        _run_once(
            container=container,
            skip_promotions=args.skip_promotions,
            skip_reminders=args.skip_reminders,
        )


def _run_once(
    container,
    skip_promotions: bool = False,
    skip_reminders: bool = False,
) -> None:
    """
    Ejecuta todos los jobs una sola vez y termina.

    Args:
        container: Contenedor de dependencias.
        skip_promotions: Si True, omite el pipeline de DynamoDB.
        skip_reminders: Si True, omite los recordatorios de compra.
    """
    logger.info("Modo: EJECUCIÓN ÚNICA")

    if not skip_promotions:
        run_promotion_pipeline(container)
    else:
        logger.info("Pipeline de promociones OMITIDO (--skip-promotions).")

    if not skip_reminders:
        run_reminder_job(container)
    else:
        logger.info("Recordatorios OMITIDOS (--skip-reminders).")

    logger.info("Ejecución completada. Saliendo.")


def _run_daemon(
    container,
    interval_minutes: int = 10,
    skip_promotions: bool = False,
    skip_reminders: bool = False,
) -> None:
    """
    Ejecuta los jobs en un loop infinito, esperando `interval_minutes`
    entre cada iteración.

    Args:
        container: Contenedor de dependencias.
        interval_minutes: Minutos a esperar entre ejecuciones.
        skip_promotions: Si True, omite el pipeline DynamoDB.
        skip_reminders: Si True, omite los recordatorios de compra.
    """
    logger.info(
        f"Modo: DAEMON (intervalo: {interval_minutes} minutos). "
        f"Presiona Ctrl+C para detener."
    )

    iteration = 0

    try:
        while True:
            iteration += 1
            logger.info(
                f"\n{'=' * 60}\n"
                f"ITERACIÓN #{iteration} - {datetime.now().isoformat()}\n"
                f"{'=' * 60}"
            )

            # Ejecutar jobs
            if not skip_promotions:
                run_promotion_pipeline(container)

            if not skip_reminders:
                run_reminder_job(container)

            # Esperar hasta la próxima iteración
            wait_seconds = interval_minutes * 60
            logger.info(
                f"Esperando {interval_minutes} minutos hasta la próxima "
                f"iteración... (Ctrl+C para salir)"
            )

            time.sleep(wait_seconds)

    except KeyboardInterrupt:
        logger.info(
            f"\nDaemon detenido por el usuario después de {iteration} iteraciones."
        )
        logger.info("¡Hasta luego!")

    except Exception as e:
        logger.error(
            f"Error inesperado en el daemon: {e}", exc_info=True
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Ejecución directa
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()
