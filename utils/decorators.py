"""
Utility Decorators - Magic Chatbot v2
======================================
Decoradores reutilizables para logging, reintentos, manejo de sesiones
de base de datos, medición de tiempo de ejecución, y manejo de errores.

Principios:
- DRY: Los patrones repetitivos (logging, retry, transacciones) se extraen aquí.
- Composición: Los decoradores se pueden combinar (@retry + @log_execution).
- Type-safe: Usan TypeVar para preservar los type hints de la función decorada.

Decoradores incluidos:
- retry: Reintenta una función ante excepciones con exponential backoff.
- log_execution: Registra entrada, salida y tiempo de ejecución.
- db_session: Inyecta una sesión de SQLAlchemy y maneja commit/rollback/close.
- db_session_async: Versión asíncrona de db_session.
- handle_errors: Captura excepciones, las loguea y retorna un valor por defecto.

Uso:
    from utils.decorators import retry, log_execution, db_session

    @retry(max_attempts=3, delay=2.0, exceptions=(ConnectionError,))
    def conectar_api():
        ...

    @log_execution
    def procesar_pago(user_id, monto):
        ...

    @db_session
    def crear_usuario(session, telegram_id, nombre):
        user = User(telegram_id=telegram_id, telegram_name=nombre)
        session.add(user)
        # commit y close son automáticos
"""

import asyncio
import functools
import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

# ---------------------------------------------------------------------------
# Type Variables
# ---------------------------------------------------------------------------

F = TypeVar("F", bound=Callable[..., Any])

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

logger: logging.Logger = logging.getLogger(__name__)


# ============================================================================
# Retry Decorator
# ============================================================================

def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    on_retry: Callable[[Exception, int], None] | None = None,
) -> Callable[[F], F]:
    """
    Decorador que reintenta una función cuando ocurre una excepción.

    Usa exponential backoff: el delay se multiplica por `backoff` tras
    cada intento fallido. Ej: delay=1, backoff=2 → esperas: 1s, 2s, 4s...

    Args:
        max_attempts: Número máximo de intentos (incluyendo el original).
        delay: Tiempo de espera inicial entre intentos (segundos).
        backoff: Factor multiplicador del delay tras cada fallo.
        exceptions: Tupla de excepciones que disparan un reintento.
        on_retry: Callback opcional llamado en cada reintento:
                  on_retry(exception, attempt_number).

    Returns:
        Decorador configurado.

    Example:
        >>> @retry(max_attempts=3, delay=2.0, exceptions=(ConnectionError,))
        ... def conectar_api():
        ...     raise ConnectionError("Sin conexión")
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_delay = delay
            last_exception: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_attempts:
                        logger.error(
                            f"'{func.__name__}' falló después de {max_attempts} "
                            f"intentos. Último error: {e}"
                        )
                        raise

                    logger.warning(
                        f"'{func.__name__}' intento {attempt}/{max_attempts} "
                        f"falló: {e}. Reintentando en {current_delay:.1f}s..."
                    )

                    if on_retry:
                        on_retry(e, attempt)

                    time.sleep(current_delay)
                    current_delay *= backoff

            # Este punto no debería alcanzarse, pero por seguridad:
            if last_exception:
                raise last_exception

        return wrapper  # type: ignore[return-value]
    return decorator


# ============================================================================
# Async Retry Decorator
# ============================================================================

def retry_async(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
    on_retry: Callable[[Exception, int], None] | None = None,
) -> Callable[[F], F]:
    """
    Versión asíncrona del decorador retry para corrutinas.

    Args:
        max_attempts: Número máximo de intentos.
        delay: Tiempo de espera inicial (segundos).
        backoff: Factor multiplicador del delay.
        exceptions: Excepciones que disparan reintento.
        on_retry: Callback opcional en cada reintento.

    Returns:
        Decorador asíncrono configurado.

    Example:
        >>> @retry_async(max_attempts=3, exceptions=(ConnectionError,))
        ... async def fetch_data():
        ...     raise ConnectionError("Timeout")
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_delay = delay
            last_exception: Exception | None = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_attempts:
                        logger.error(
                            f"'{func.__name__}' falló después de {max_attempts} "
                            f"intentos. Último error: {e}"
                        )
                        raise

                    logger.warning(
                        f"'{func.__name__}' intento {attempt}/{max_attempts} "
                        f"falló: {e}. Reintentando en {current_delay:.1f}s..."
                    )

                    if on_retry:
                        on_retry(e, attempt)

                    await asyncio.sleep(current_delay)
                    current_delay *= backoff

            if last_exception:
                raise last_exception

        return wrapper  # type: ignore[return-value]
    return decorator


# ============================================================================
# Log Execution Decorator
# ============================================================================

def log_execution(
    log_level: int = logging.DEBUG,
    log_args: bool = True,
    log_result: bool = False,
) -> Callable[[F], F]:
    """
    Decorador que registra la entrada, salida y tiempo de ejecución de una función.

    Args:
        log_level: Nivel de logging para los mensajes (DEBUG, INFO, etc.).
        log_args: Si True, registra los argumentos de la función.
        log_result: Si True, registra el valor de retorno (¡cuidado con datos sensibles!).

    Returns:
        Decorador configurado.

    Example:
        >>> @log_execution(log_level=logging.INFO)
        ... def procesar_pago(user_id, monto):
        ...     return True

        → procesar_pago(123, 50)
        ← procesar_pago → True (0.0023s)
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            func_logger = logging.getLogger(func.__module__)

            # Construir mensaje de entrada
            if log_args:
                args_repr = [repr(a) for a in args]
                kwargs_repr = [f"{k}={v!r}" for k, v in kwargs.items()]
                signature = ", ".join(args_repr + kwargs_repr)
                func_logger.log(
                    log_level,
                    f"→ {func.__name__}({signature})",
                )
            else:
                func_logger.log(log_level, f"→ {func.__name__}()")

            # Ejecutar y medir tiempo
            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                elapsed = time.perf_counter() - start_time

                if log_result:
                    func_logger.log(
                        log_level,
                        f"← {func.__name__} → {result!r} ({elapsed:.4f}s)",
                    )
                else:
                    func_logger.log(
                        log_level,
                        f"← {func.__name__} ({elapsed:.4f}s)",
                    )
                return result
            except Exception as e:
                elapsed = time.perf_counter() - start_time
                func_logger.error(
                    f"✗ {func.__name__} lanzó {type(e).__name__}: {e} "
                    f"({elapsed:.4f}s)"
                )
                raise

        return wrapper  # type: ignore[return-value]
    return decorator


# ============================================================================
# Async Log Execution Decorator
# ============================================================================

def log_execution_async(
    log_level: int = logging.DEBUG,
    log_args: bool = True,
    log_result: bool = False,
) -> Callable[[F], F]:
    """
    Versión asíncrona del decorador log_execution para corrutinas.

    Args:
        log_level: Nivel de logging.
        log_args: Si True, registra argumentos.
        log_result: Si True, registra valor de retorno.

    Returns:
        Decorador asíncrono configurado.
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            func_logger = logging.getLogger(func.__module__)

            if log_args:
                args_repr = [repr(a) for a in args]
                kwargs_repr = [f"{k}={v!r}" for k, v in kwargs.items()]
                signature = ", ".join(args_repr + kwargs_repr)
                func_logger.log(log_level, f"→ {func.__name__}({signature})")
            else:
                func_logger.log(log_level, f"→ {func.__name__}()")

            start_time = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
                elapsed = time.perf_counter() - start_time

                if log_result:
                    func_logger.log(
                        log_level,
                        f"← {func.__name__} → {result!r} ({elapsed:.4f}s)",
                    )
                else:
                    func_logger.log(
                        log_level,
                        f"← {func.__name__} ({elapsed:.4f}s)",
                    )
                return result
            except Exception as e:
                elapsed = time.perf_counter() - start_time
                func_logger.error(
                    f"✗ {func.__name__} lanzó {type(e).__name__}: {e} "
                    f"({elapsed:.4f}s)"
                )
                raise

        return wrapper  # type: ignore[return-value]
    return decorator


# ============================================================================
# DB Session Decorator (Síncrono)
# ============================================================================

def db_session[F: Callable[..., Any]](func: F) -> F:
    """
    Decorador que inyecta una sesión de SQLAlchemy como primer argumento
    y maneja automáticamente commit/rollback/close.

    La función decorada debe recibir `session` como primer argumento.
    Si la función retorna normalmente → commit.
    Si la función lanza una excepción → rollback.
    En cualquier caso → session.close().

    Uso:
        >>> @db_session
        ... def crear_usuario(session, telegram_id, nombre):
        ...     user = User(telegram_id=telegram_id, telegram_name=nombre)
        ...     session.add(user)
        ...     # commit, rollback y close son automáticos

    Nota:
        Importa SessionLocal de core.database. Asegúrate de que el módulo
        database esté correctamente configurado antes de usar este decorador.
    """
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        # Importación tardía para evitar circular imports
        from core.database import SessionLocal

        session = SessionLocal()
        try:
            result = func(session, *args, **kwargs)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return wrapper  # type: ignore[return-value]


# ============================================================================
# DB Session Decorator (Asíncrono)
# ============================================================================

def db_session_async[F: Callable[..., Any]](func: F) -> F:
    """
    Versión asíncrona del decorador db_session.

    La función decorada debe ser una corrutina que reciba `session`
    como primer argumento.

    Uso:
        >>> @db_session_async
        ... async def crear_usuario(session, telegram_id, nombre):
        ...     user = User(telegram_id=telegram_id, telegram_name=nombre)
        ...     session.add(user)
    """
    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        from core.database import SessionLocal

        session = SessionLocal()
        try:
            result = await func(session, *args, **kwargs)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return wrapper  # type: ignore[return-value]


# ============================================================================
# Handle Errors Decorator
# ============================================================================

def handle_errors(
    default_return: Any = None,
    reraise: bool = False,
    log_level: int = logging.ERROR,
) -> Callable[[F], F]:
    """
    Decorador que captura cualquier excepción, la loguea y retorna
    un valor por defecto (o relanza la excepción si reraise=True).

    Útil para funciones donde un fallo no debe interrumpir el flujo
    principal, como envío de notificaciones o tareas secundarias.

    Args:
        default_return: Valor a retornar en caso de excepción.
        reraise: Si True, relanza la excepción después de loguearla.
        log_level: Nivel de logging para la excepción.

    Returns:
        Decorador configurado.

    Example:
        >>> @handle_errors(default_return={"success": False})
        ... def enviar_notificacion(user_id, mensaje):
        ...     raise ConnectionError("Sin conexión")

        >>> result = enviar_notificacion(123, "Hola")
        >>> print(result)
        {'success': False}
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                logger.log(
                    log_level,
                    f"Error en '{func.__name__}': {type(e).__name__}: {e}",
                    exc_info=True,
                )
                if reraise:
                    raise
                return default_return

        return wrapper  # type: ignore[return-value]
    return decorator


# ============================================================================
# Handle Errors Async Decorator
# ============================================================================

def handle_errors_async(
    default_return: Any = None,
    reraise: bool = False,
    log_level: int = logging.ERROR,
) -> Callable[[F], F]:
    """
    Versión asíncrona del decorador handle_errors.

    Args:
        default_return: Valor a retornar en caso de excepción.
        reraise: Si True, relanza la excepción después de loguearla.
        log_level: Nivel de logging.

    Returns:
        Decorador asíncrono configurado.
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                logger.log(
                    log_level,
                    f"Error en '{func.__name__}': {type(e).__name__}: {e}",
                    exc_info=True,
                )
                if reraise:
                    raise
                return default_return

        return wrapper  # type: ignore[return-value]
    return decorator


# ============================================================================
# Timeout Decorator
# ============================================================================

def timeout(seconds: float) -> Callable[[F], F]:
    """
    Decorador que limita el tiempo de ejecución de una función.

    Si la función tarda más de `seconds` segundos, lanza TimeoutError.
    Usa signal.alarm internamente (solo funciona en UNIX).

    Args:
        seconds: Tiempo máximo de ejecución en segundos.

    Returns:
        Decorador configurado.

    Raises:
        TimeoutError: Si la función excede el tiempo límite.

    Note:
        No funciona en Windows. Para entornos cross-platform, considerar
        concurrent.futures.ThreadPoolExecutor con timeout.

    Example:
        >>> @timeout(5.0)
        ... def tarea_larga():
        ...     time.sleep(10)
        ...     return "hecho"
        ...
        >>> tarea_larga()  # TimeoutError después de 5 segundos
    """
    import signal

    def _timeout_handler(signum, frame):
        raise TimeoutError(
            f"La función excedió el tiempo límite de {seconds} segundos."
        )

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Guardar el handler anterior
            old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(int(seconds))

            try:
                result = func(*args, **kwargs)
            finally:
                # Restaurar handler y desactivar alarma
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)

            return result

        return wrapper  # type: ignore[return-value]
    return decorator
