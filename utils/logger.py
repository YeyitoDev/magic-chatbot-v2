"""
Production-Grade Structured Logging - Magic Chatbot v2
=======================================================
Sistema de logging enterprise con:
- JsonFormatter: logs JSON con timestamp, level, logger, message, module, function, line, pid, extra, exception
- TextFormatter: consola con colores ANSI (cyan=DEBUG, green=INFO, yellow=WARNING, red=ERROR, magenta=CRITICAL)
- DailyRotatingFileHandler: rotación diaria a medianoche, archivos con fecha, compresión gzip a archive/YYYY-MM/
- TelegramAlertHandler: alertas CRITICAL a admins vía Telegram (rate-limited: 1 por tipo cada 5 min)
- PaymentLogger: eventos de pago → logs/domain/payment_YYYY-MM-DD.log
- AuditLogger: eventos de auditoría → logs/domain/audit_YYYY-MM-DD.log
- HealthCheck: ping system para Healthchecks.io
- configure_root_logger(): inicializa todo
- init_logging(): crea directorios

Uso:
    from utils.logger import configure_root_logger, init_logging
    init_logging()
    root = configure_root_logger()
"""

import gzip
import json
import logging
import logging.handlers
import os
import shutil
import threading
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone  # noqa: UP017
from pathlib import Path
from typing import Any

import requests

from config.settings import settings

# ============================================================================
# ANSI Colors
# ============================================================================

ANSI_COLORS: dict[str, str] = {
    "DEBUG": "\033[36m",
    "INFO": "\033[32m",
    "WARNING": "\033[33m",
    "ERROR": "\033[31m",
    "CRITICAL": "\033[35m",
    "RESET": "\033[0m",
}

LEVEL_COLOR: dict[int, str] = {
    logging.DEBUG: ANSI_COLORS["DEBUG"],
    logging.INFO: ANSI_COLORS["INFO"],
    logging.WARNING: ANSI_COLORS["WARNING"],
    logging.ERROR: ANSI_COLORS["ERROR"],
    logging.CRITICAL: ANSI_COLORS["CRITICAL"],
}

# ============================================================================
# JsonFormatter
# ============================================================================

class JsonFormatter(logging.Formatter):
    """Formateador JSON estructurado."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),  # noqa: UP017
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "pid": os.getpid(),
        }
        if hasattr(record, "extra_fields") and record.extra_fields:
            if isinstance(record.extra_fields, dict):
                log_entry["extra"] = record.extra_fields
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])
            log_entry["exception_type"] = type(record.exc_info[1]).__name__
        if record.stack_info:
            log_entry["stack_info"] = record.stack_info
        return json.dumps(log_entry, ensure_ascii=False, default=str)


# ============================================================================
# TextFormatter (ANSI Colors)
# ============================================================================

class TextFormatter(logging.Formatter):
    """Formateador de texto con colores ANSI para consola."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s | %(levelname)-5s | %(name)-20s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        color = LEVEL_COLOR.get(record.levelno, "")
        reset = ANSI_COLORS["RESET"]
        formatted = super().format(record)
        if not color:
            return formatted
        if record.levelno >= logging.ERROR:
            return f"{color}{formatted}{reset}"
        formatted = formatted.replace(
            f" {record.levelname:<7} ",
            f" {color}{record.levelname:<7}{reset} ",
            1,
        )
        return formatted


# ============================================================================
# DailyRotatingFileHandler
# ============================================================================

class DailyRotatingFileHandler(logging.Handler):
    """Handler con rotación diaria a medianoche y archivado gzip mensual."""

    def __init__(
        self,
        filename_pattern: str,
        backup_count: int = 30,
        encoding: str = "utf-8",
    ) -> None:
        super().__init__()
        self.filename_pattern = filename_pattern
        self.backup_count = backup_count
        self.encoding = encoding
        self._current_date: str | None = None
        self._file = None
        self._lock = threading.Lock()
        log_dir = os.path.dirname(filename_pattern) or "."
        self._archive_dir = os.path.join(log_dir, "archive")
        self._open_file()
        self._scheduler_thread = threading.Thread(
            target=self._rotation_scheduler, daemon=True, name="log-rotator"
        )
        self._scheduler_thread.start()

    def _get_filename(self, date_str: str) -> str:
        return self.filename_pattern.replace("{date}", date_str)

    @staticmethod
    def _get_today_str() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _open_file(self) -> None:
        today = self._get_today_str()
        if self._current_date == today and self._file is not None:
            return
        if self._file:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None
        self._current_date = today
        filename = self._get_filename(today)
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        self._file = open(filename, "a", encoding=self.encoding)

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock:
            if self._current_date != self._get_today_str():
                self._do_rotation()
            if self._file:
                try:
                    msg = self.format(record)
                    self._file.write(msg + "\n")
                    self._file.flush()
                except Exception:
                    self.handleError(record)

    def close(self) -> None:
        with self._lock:
            if self._file:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None
        super().close()

    def _do_rotation(self) -> None:
        if self._file:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None
        self._archive_old_files()
        self._open_file()

    def _archive_old_files(self) -> None:
        cutoff_date = datetime.now() - timedelta(days=self.backup_count)
        log_dir = os.path.dirname(self.filename_pattern)
        if not log_dir or not os.path.isdir(log_dir):
            return
        base = os.path.basename(self.filename_pattern)
        if "{date}" not in base:
            return
        prefix, suffix = base.split("{date}", 1)
        for fname in os.listdir(log_dir):
            fpath = os.path.join(log_dir, fname)
            if not os.path.isfile(fpath):
                continue
            if not (fname.startswith(prefix) and fname.endswith(suffix)):
                continue
            date_part = fname[len(prefix):-len(suffix) or None]
            try:
                file_date = datetime.strptime(date_part, "%Y-%m-%d")
            except ValueError:
                continue
            if file_date >= cutoff_date:
                continue
            archive_month_dir = os.path.join(self._archive_dir, file_date.strftime("%Y-%m"))
            os.makedirs(archive_month_dir, exist_ok=True)
            archive_path = os.path.join(archive_month_dir, fname + ".gz")
            try:
                with open(fpath, "rb") as f_in:
                    with gzip.open(archive_path, "wb") as f_out:
                        shutil.copyfileobj(f_in, f_out)
                os.remove(fpath)
            except OSError:
                pass

    def _rotation_scheduler(self) -> None:
        while True:
            time.sleep(30)
            with self._lock:
                if self._current_date != self._get_today_str():
                    try:
                        self._do_rotation()
                    except Exception:
                        pass


# ============================================================================
# TelegramAlertHandler
# ============================================================================

class TelegramAlertHandler(logging.Handler):
    """Envía alertas CRITICAL a administradores vía Telegram (rate-limited)."""

    def __init__(
        self,
        bot_token: str,
        admin_ids: list[int],
        rate_limit_seconds: int = 300,
    ) -> None:
        super().__init__(level=logging.CRITICAL)
        self.bot_token = bot_token
        self.admin_ids = admin_ids
        self.rate_limit_seconds = rate_limit_seconds
        self._last_alert: dict[str, float] = {}
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < logging.CRITICAL:
            return
        error_type = self._get_error_type(record)
        with self._lock:
            now = time.time()
            last = self._last_alert.get(error_type, 0)
            if now - last < self.rate_limit_seconds:
                return
            self._last_alert[error_type] = now
        message = self._format_alert(record, error_type)
        for admin_id in self.admin_ids:
            self._send_telegram_message(admin_id, message)

    @staticmethod
    def _get_error_type(record: logging.LogRecord) -> str:
        if record.exc_info and record.exc_info[0]:
            return f"{record.name}:{record.exc_info[0].__name__}"
        return f"{record.name}:{record.funcName}:{record.lineno}"

    @staticmethod
    def _format_alert(record: logging.LogRecord, error_type: str) -> str:
        msg = record.getMessage()
        exc_info = ""
        if record.exc_info and record.exc_info[1]:
            exc_info = (
                f"\n\n*Exception:* `{type(record.exc_info[1]).__name__}`\n"
                f"```\n{record.exc_info[1]}\n```"
            )
        return (
            f"🚨 *CRITICAL ALERT* — Magic Chatbot v2\n\n"
            f"*Error Type:* `{error_type}`\n"
            f"*Logger:* `{record.name}`\n"
            f"*Function:* `{record.funcName}:{record.lineno}`\n"
            f"*Module:* `{record.module}`\n"
            f"*PID:* `{os.getpid()}`\n"
            f"*Time (UTC):* `{datetime.now(timezone.utc).isoformat()}`\n\n"  # noqa: UP017
            f"*Message:* {msg}{exc_info}"
        )

    def _send_telegram_message(self, chat_id: int, text: str) -> None:
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
        except Exception:
            pass


# ============================================================================
# PaymentLogger
# ============================================================================

class PaymentLogger:
    """Logger especializado para eventos de pago → logs/domain/payment_YYYY-MM-DD.log"""

    def __init__(self, log_dir: str = "logs/domain") -> None:
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self._logger = logging.getLogger("payment.domain")
        self._logger.propagate = False
        self._logger.setLevel(logging.INFO)
        self._handler = DailyRotatingFileHandler(
            filename_pattern=os.path.join(log_dir, "payment_{date}.log"),
            backup_count=30,
        )
        self._handler.setFormatter(JsonFormatter())
        self._handler.setLevel(logging.INFO)
        if not self._logger.handlers:
            self._logger.addHandler(self._handler)

    def log_payment_received(self, user_id: int, amount: float, channel: str) -> None:
        self._logger.info("PAYMENT_RECEIVED", extra={"extra_fields": {
            "event": "payment_received", "user_id": user_id, "amount": amount, "channel": channel
        }})

    def log_payment_validated(self, user_id: int, validator_id: int, amount: float, service: str) -> None:
        self._logger.info("PAYMENT_VALIDATED", extra={"extra_fields": {
            "event": "payment_validated", "user_id": user_id, "validator_id": validator_id,
            "amount": amount, "service": service
        }})

    def log_payment_rejected(self, user_id: int, validator_id: int, amount: float) -> None:
        self._logger.info("PAYMENT_REJECTED", extra={"extra_fields": {
            "event": "payment_rejected", "user_id": user_id, "validator_id": validator_id,
            "amount": amount
        }})

    def log_duplicate_detected(self, user_id: int, amount: float) -> None:
        self._logger.warning("DUPLICATE_DETECTED", extra={"extra_fields": {
            "event": "duplicate_detected", "user_id": user_id, "amount": amount
        }})


# ============================================================================
# AuditLogger
# ============================================================================

class AuditLogger:
    """Logger especializado para eventos de auditoría → logs/domain/audit_YYYY-MM-DD.log"""

    def __init__(self, log_dir: str = "logs/domain") -> None:
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self._logger = logging.getLogger("audit.domain")
        self._logger.propagate = False
        self._logger.setLevel(logging.INFO)
        self._handler = DailyRotatingFileHandler(
            filename_pattern=os.path.join(log_dir, "audit_{date}.log"),
            backup_count=30,
        )
        self._handler.setFormatter(JsonFormatter())
        self._handler.setLevel(logging.INFO)
        if not self._logger.handlers:
            self._logger.addHandler(self._handler)

    def log_user_kicked(self, admin_id: int, user_id: int, reason: str) -> None:
        self._logger.info("USER_KICKED", extra={"extra_fields": {
            "event": "user_kicked", "admin_id": admin_id, "user_id": user_id, "reason": reason
        }})

    def log_user_unbanned(self, admin_id: int, user_id: int) -> None:
        self._logger.info("USER_UNBANNED", extra={"extra_fields": {
            "event": "user_unbanned", "admin_id": admin_id, "user_id": user_id
        }})

    def log_subscription_expired(self, user_id: int, end_date: str) -> None:
        self._logger.info("SUBSCRIPTION_EXPIRED", extra={"extra_fields": {
            "event": "subscription_expired", "user_id": user_id, "end_date": end_date
        }})

    def log_subscription_created(self, user_id: int, service: str, duration_days: int) -> None:
        self._logger.info("SUBSCRIPTION_CREATED", extra={"extra_fields": {
            "event": "subscription_created", "user_id": user_id, "service": service,
            "duration_days": duration_days
        }})


# ============================================================================
# HealthCheck
# ============================================================================

class HealthCheck:
    """Ping system para Healthchecks.io o similar."""

    def __init__(self, ping_url: str | None = None) -> None:
        self._ping_url = ping_url

    def configure(self, ping_url: str) -> None:
        self._ping_url = ping_url

    def ping(self, success: bool = True) -> None:
        if not self._ping_url:
            return
        try:
            url = self._ping_url if success else f"{self._ping_url}/fail"
            requests.get(url, timeout=10)
        except Exception:
            pass

    def ping_on_success(self, func: Callable) -> Callable:
        import functools
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                result = func(*args, **kwargs)
                self.ping(success=True)
                return result
            except Exception:
                self.ping(success=False)
                raise
        return wrapper


# ============================================================================
# Inicialización
# ============================================================================

def init_logging() -> None:
    """Crea los directorios necesarios para el sistema de logging."""
    dirs = ["logs", "logs/domain", "logs/archive"]
    for d in dirs:
        os.makedirs(d, exist_ok=True)


def configure_root_logger() -> logging.Logger:
    """Configura el logger raíz con todos los handlers."""
    root_logger = logging.getLogger()  # The actual root logger
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))
    if root_logger.handlers:
        return root_logger

    # Console (testing only)
    if settings.is_testing():
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(TextFormatter())
        console_handler.setLevel(logging.DEBUG if settings.DEBUG else logging.INFO)
        root_logger.addHandler(console_handler)

    # App log file (INFO+)
    app_handler = DailyRotatingFileHandler(
        filename_pattern=os.path.join(settings.LOG_FILE_PATH, "app_{date}.log"),
        backup_count=30,
    )
    app_handler.setFormatter(JsonFormatter())
    app_handler.setLevel(logging.INFO)
    root_logger.addHandler(app_handler)

    # Error log file (ERROR+)
    error_handler = DailyRotatingFileHandler(
        filename_pattern=os.path.join(settings.LOG_FILE_PATH, "error_{date}.log"),
        backup_count=30,
    )
    error_handler.setFormatter(JsonFormatter())
    error_handler.setLevel(logging.ERROR)
    root_logger.addHandler(error_handler)

    # Telegram alerts (CRITICAL+, production only)
    if settings.is_production() and settings.TELEGRAM_BOT_TOKEN:
        try:
            admin_ids = settings.get_validator_ids_as_int()
            telegram_handler = TelegramAlertHandler(
                bot_token=settings.TELEGRAM_BOT_TOKEN,
                admin_ids=admin_ids,
                rate_limit_seconds=300,
            )
            telegram_handler.setFormatter(JsonFormatter())
            root_logger.addHandler(telegram_handler)
            root_logger.info("TelegramAlertHandler configurado exitosamente.")
        except Exception as e:
            logging.warning(f"No se pudo configurar TelegramAlertHandler: {e}")

    root_logger.propagate = False

    # Silence noisy third-party loggers
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.orm").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("botocore").setLevel(logging.WARNING)

    return root_logger


# ============================================================================
# Legacy Compatibility
# ============================================================================

def setup_logger(
    name: str,
    log_level: str = "INFO",
    log_format: str = "text",
    log_file_path: str | None = None,
    max_file_size: int = 10 * 1024 * 1024,
    backup_count: int = 10,
    console_output: bool = True,
) -> logging.Logger:
    """Configura un logger individual (compatibilidad legacy)."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    if logger.handlers:
        return logger
    formatter = JsonFormatter() if log_format.lower() == "json" else TextFormatter()
    if log_file_path:
        try:
            log_dir = Path(log_file_path).parent
            log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                filename=log_file_path, maxBytes=max_file_size, backupCount=backup_count,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logger.level)
            logger.addHandler(file_handler)
        except (OSError, PermissionError) as e:
            fallback = logging.StreamHandler()
            fallback.setFormatter(TextFormatter())
            logger.addHandler(fallback)
            logger.warning(f"No se pudo crear archivo de log: {e}")
    if console_output:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(logger.level)
        logger.addHandler(console_handler)
    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    """Obtiene un logger (compatibilidad legacy - ahora usa el logger raíz)."""
    import warnings
    warnings.warn(
        "get_logger() is deprecated. Use logging.getLogger(__name__) instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    return logging.getLogger(name)


class ContextAdapter(logging.LoggerAdapter):
    """Adaptador que inyecta campos extra automáticamente en todos los logs."""
    def __init__(self, logger: logging.Logger, extra_context: dict) -> None:
        super().__init__(logger, extra_context)
    def process(self, msg: Any, kwargs: dict) -> tuple:
        extra = kwargs.get("extra", {})
        extra["extra_fields"] = self.extra
        kwargs["extra"] = extra
        return msg, kwargs
