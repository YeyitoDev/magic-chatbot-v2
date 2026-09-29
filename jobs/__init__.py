"""
Jobs Module - Magic Chatbot v2
===============================
Módulo de tareas programadas y procesos batch.

Contiene:
- scheduler.py: JobScheduler con APScheduler.
- subscription_cleanup.py: SubscriptionCleanupJob (Telethon sync + cleanup).
- promotion_batch.py: Funciones de batch (promotions + reminders).

Uso:
    from jobs.scheduler import JobScheduler
    from jobs.subscription_cleanup import SubscriptionCleanupJob
    from jobs.promotion_batch import run_promotion_pipeline, run_reminder_job
"""

from jobs.expiry_warnings import run_expiry_warnings
from jobs.promotion_batch import run_all_jobs, run_promotion_pipeline, run_reminder_job
from jobs.scheduler import JobScheduler
from jobs.subscription_cleanup import SubscriptionCleanupJob

__all__ = [
    "JobScheduler",
    "SubscriptionCleanupJob",
    "run_promotion_pipeline",
    "run_reminder_job",
    "run_all_jobs",
    "run_expiry_warnings",
]
