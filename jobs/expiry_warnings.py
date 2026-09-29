"""
Expiry Warnings Job - Magic Chatbot v2
=======================================
Job programado que avisa de las suscripciones VIP próximas a vencer.

A diferencia de la versión anterior (script inline en el workflow que solo
imprimía la lista en el log sin enviar nada), este job:

1. Consulta las suscripciones VIP (`service_id == 2`) cuyo `end_date` cae
   entre hoy y hoy + N días.
2. Envía un aviso (best-effort) por DM a cada usuario próximo a vencer.
   Los bots no pueden iniciar conversación con usuarios que nunca le
   escribieron, por lo que esos 400 son esperados y se silencian.
3. Envía SIEMPRE un resumen consolidado a los administradores (entrega fiable).
4. Guarda un reporte JSON/TXT en `output/`.

Ejecución:
    python -m jobs.expiry_warnings              # 3 días por defecto
    python -m jobs.expiry_warnings --days 7
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

from config.settings import settings
from utils.datetime_utils import today_lima
from utils.logger import setup_logger

logger = setup_logger(
    "jobs.expiry_warnings",
    log_format="text",
    console_output=True,
)



def run_expiry_warnings(days: int = 3) -> dict:
    """
    Avisa de las suscripciones VIP que vencen en los próximos ``days`` días.

    Args:
        days: Número de días de antelación para el aviso.

    Returns:
        Dict con estadísticas: ``expiring``, ``notified``, ``failed``.
    """
    from core.database import SessionLocal
    from models.subscription import Subscription
    from services.telegram_api import TelegramAPIService

    api = TelegramAPIService()
    session = SessionLocal()
    today = today_lima()
    deadline = today + timedelta(days=days)

    stats = {"expiring": 0, "notified": 0, "failed": 0}
    expiring_rows: list[dict] = []

    try:
        expiring = (
            session.query(Subscription)
            .filter(
                Subscription.is_active,
                Subscription.end_date >= today,
                Subscription.end_date <= deadline,
                Subscription.service_id == 2,  # VIP only
            )
            .order_by(Subscription.end_date)
            .all()
        )
        stats["expiring"] = len(expiring)
        logger.info(f"⚠ {len(expiring)} suscripciones vencen en {days} días")

        for sub in expiring:
            user_id = int(sub.user_telegram_id)
            days_left = (sub.end_date - today).days
            expiring_rows.append(
                {
                    "user_id": user_id,
                    "end_date": str(sub.end_date),
                    "days_left": days_left,
                }
            )
            logger.info(f"  Usuario {user_id}: vence en {days_left} días ({sub.end_date})")

            # Best-effort DM to the user. Failures (e.g. user never started the
            # bot) are expected; suppress error logs to avoid noise.
            try:
                api.send_message(
                    chat_id=user_id,
                    text=(
                        "⏳ *Tu suscripción VIP está por vencer*\n\n"
                        f"Vence en {days_left} día(s) ({sub.end_date}).\n"
                        "Renová enviando un mensaje a @magic_peru 📲"
                    ),
                    parse_mode="Markdown",
                    log_errors=False,
                )
                stats["notified"] += 1
            except Exception:
                stats["failed"] += 1
    finally:
        session.close()

    # ---- Resumen a administradores (entrega fiable) ----
    summary = (
        f"⚠ *Avisos de Vencimiento*\n"
        f"├ 🗓️ Fecha: {today}\n"
        f"├ ⏰ Ventana: {days} día(s)\n"
        f"├ 📋 Por vencer: {stats['expiring']}\n"
        f"├ ✅ Avisados: {stats['notified']}\n"
        f"└ ⚠ No avisados: {stats['failed']}"
    )
    if expiring_rows:
        lines = "\n".join(
            f"  • {r['user_id']}: {r['days_left']}d ({r['end_date']})"
            for r in expiring_rows[:50]
        )
        summary += f"\n\n{lines}"

    for aid in settings.ADMIN_NOTIFY_IDS:
        try:
            api.send_message(chat_id=aid, text=summary, parse_mode="Markdown")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"No se pudo avisar al admin {aid}: {e}")

    # ---- Guardar reporte ----
    output_dir = os.path.join("output", today.strftime("%Y-%m-%d"))
    os.makedirs(output_dir, exist_ok=True)
    hora = datetime.now().strftime("%H%M%S")
    report = {
        "date": str(today),
        "days": days,
        "stats": stats,
        "expiring_users": expiring_rows,
    }
    with open(os.path.join(output_dir, f"avisos_{hora}.json"), "w") as f:
        json.dump(report, f, indent=2)

    logger.info(
        f"Avisos completados: {stats['expiring']} por vencer, "
        f"{stats['notified']} avisados, {stats['failed']} no avisados"
    )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Magic Chatbot v2 - Avisos de Vencimiento"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=int(os.getenv("EXPIRY_WARNING_DAYS", "3")),
        help="Días de antelación para el aviso (default: 3).",
    )
    args = parser.parse_args()

    try:
        run_expiry_warnings(days=args.days)
        return 0
    except Exception as e:  # noqa: BLE001
        logger.error(f"Error ejecutando avisos de vencimiento: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
