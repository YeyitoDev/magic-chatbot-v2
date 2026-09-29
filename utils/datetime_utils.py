"""
Date/Time Utilities - Perú Timezone (America/Lima)
====================================================
Utilidades para manejo de fechas y horas en la zona horaria de Perú.

Proporciona funciones para obtener la fecha/hora actual en Lima,
formatear fechas en español, parsear fechas en múltiples formatos,
y verificar rangos de fechas.

Toda la lógica de zona horaria está centralizada aquí para evitar
dispersión de pytz.timezone('America/Lima') en el código.

Uso:
    from utils.datetime_utils import get_lima_time, format_date_spanish

    ahora = get_lima_time()
    fecha_bonita = format_date_spanish(ahora)
    # "Lunes 15 de enero del 2025 a las 14:30"
"""

from datetime import date, datetime, timedelta

import pytz

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

LIMA_TZ = pytz.timezone("America/Lima")

MONTHS_SPANISH: dict[int, str] = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}

DAYS_SPANISH: dict[int, str] = {
    0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves",
    4: "Viernes", 5: "Sábado", 6: "Domingo",
}


# ---------------------------------------------------------------------------
# Obtención de fecha/hora actual en Lima
# ---------------------------------------------------------------------------

def get_lima_time() -> datetime:
    """
    Obtiene la fecha y hora actual en la zona horaria de Perú (America/Lima).

    Returns:
        Objeto datetime con timezone America/Lima.

    Example:
        >>> ahora = get_lima_time()
        >>> print(ahora.isoformat())
        2025-01-15T14:30:25-05:00
    """
    utc_now = datetime.now(pytz.utc)
    return utc_now.astimezone(LIMA_TZ)


def today_lima() -> date:
    """
    Fecha actual en Lima.

    Los servidores (Fly.io, GitHub Actions, PythonAnywhere) corren en UTC:
    ``date.today()`` adelanta el día a partir de las 19:00 hora de Perú.
    Toda comparación de vencimientos debe usar esta función.
    """
    return get_lima_time().date()


def now_lima_naive() -> datetime:
    """
    Hora actual de Lima sin tzinfo.

    Las columnas DATETIME de MySQL no guardan zona horaria; los valores se
    almacenan como hora local de Lima. Usar esto al comparar contra ellas.
    """
    return get_lima_time().replace(tzinfo=None)


def get_lima_time_formatted() -> dict[str, object]:
    """
    Retorna la fecha/hora actual de Perú en múltiples formatos.

    Útil cuando se necesita la misma fecha en distintos formatos
    para base de datos, Google Sheets, mensajes, etc.

    Returns:
        Diccionario con las siguientes claves:
        - ddmmyyyy: str (ej: "15012025")
        - dd/mm/yyyy: str (ej: "15/01/2025")
        - yyyy-mm-dd: str (ej: "2025-01-15")
        - fecha_completa: str (ej: "15/01/2025 14:30:25")
        - fecha_formateada: str (ej: "15/01/2025 14:30")
        - datetime_obj: datetime (objeto datetime con timezone America/Lima)

    Example:
        >>> formats = get_lima_time_formatted()
        >>> print(formats["ddmmyyyy"])
        15012025
    """
    ahora = get_lima_time()
    return {
        "ddmmyyyy": ahora.strftime("%d%m%Y"),
        "dd/mm/yyyy": ahora.strftime("%d/%m/%Y"),
        "yyyy-mm-dd": ahora.strftime("%Y-%m-%d"),
        "fecha_completa": ahora.strftime("%d/%m/%Y %H:%M:%S"),
        "fecha_formateada": ahora.strftime("%d/%m/%Y %H:%M"),
        "datetime_obj": ahora,
    }


def get_lima_time_iso() -> str:
    """
    Retorna la fecha/hora actual en Lima en formato ISO 8601.

    Returns:
        String ISO 8601 con timezone (ej: "2025-01-15T14:30:25-05:00").
    """
    return get_lima_time().isoformat()


# ---------------------------------------------------------------------------
# Formateo en español
# ---------------------------------------------------------------------------

def format_date_spanish(dt: datetime) -> str:
    """
    Formatea una fecha en español con formato legible y completo.

    Args:
        dt: Objeto datetime a formatear (puede ser naive o con timezone).

    Returns:
        Cadena formateada como "Lunes 15 de enero del 2025 a las 14:30".

    Example:
        >>> from datetime import datetime
        >>> dt = datetime(2025, 1, 15, 14, 30)
        >>> print(format_date_spanish(dt))
        Miércoles 15 de enero del 2025 a las 14:30
    """
    day_name = DAYS_SPANISH.get(dt.weekday(), "")
    month_name = MONTHS_SPANISH.get(dt.month, "")
    return (
        f"{day_name} {dt.day} de {month_name} del {dt.year} "
        f"a las {dt.strftime('%H:%M')}"
    )


def format_date_short_spanish(dt: datetime) -> str:
    """
    Formatea una fecha en español en formato corto.

    Args:
        dt: Objeto datetime a formatear.

    Returns:
        Cadena como "15 de enero de 2025".

    Example:
        >>> dt = datetime(2025, 1, 15)
        >>> print(format_date_short_spanish(dt))
        15 de enero de 2025
    """
    month_name = MONTHS_SPANISH.get(dt.month, "")
    return f"{dt.day} de {month_name} de {dt.year}"


# ---------------------------------------------------------------------------
# Parsing de fechas
# ---------------------------------------------------------------------------

def parse_purchase_date(date_str: str) -> datetime | None:
    """
    Parsea una fecha en formato 'ddmmyyyy' o 'dd/mm/yyyy' a un objeto
    datetime con timezone Lima.

    Args:
        date_str: String de fecha en formato 'ddmmyyyy' (ej: '15012025')
                  o 'dd/mm/yyyy' (ej: '15/01/2025').

    Returns:
        Objeto datetime con timezone America/Lima, o None si el parsing falla.

    Example:
        >>> dt = parse_purchase_date("15012025")
        >>> print(dt.strftime("%Y-%m-%d"))
        2025-01-15
        >>> dt2 = parse_purchase_date("15/01/2025")
        >>> print(dt2.strftime("%Y-%m-%d"))
        2025-01-15
    """
    if not date_str:
        return None

    formats = ["%d%m%Y", "%d/%m/%Y"]
    for fmt in formats:
        try:
            naive_dt = datetime.strptime(date_str.strip(), fmt)
            return LIMA_TZ.localize(naive_dt)
        except ValueError:
            continue

    return None


def parse_date_flexible(date_str: str) -> datetime | None:
    """
    Parsea una fecha en múltiples formatos comunes y retorna datetime con
    timezone Lima.

    Formatos soportados (probados en orden):
    - ddmmyyyy (15012025)
    - dd/mm/yyyy (15/01/2025)
    - yyyy-mm-dd (2025-01-15)
    - dd-mm-yyyy (15-01-2025)
    - yyyy/mm/dd (2025/01/15)

    Args:
        date_str: String de fecha en cualquiera de los formatos soportados.

    Returns:
        Objeto datetime con timezone America/Lima, o None si no se pudo parsear.

    Example:
        >>> dt = parse_date_flexible("2025-01-15")
        >>> print(dt.strftime("%d%m%Y"))
        15012025
    """
    if not date_str:
        return None

    formats = [
        "%d%m%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%Y/%m/%d",
    ]

    for fmt in formats:
        try:
            naive_dt = datetime.strptime(date_str.strip(), fmt)
            return LIMA_TZ.localize(naive_dt)
        except ValueError:
            continue

    return None


def parse_date_from_text(text: str) -> datetime | None:
    """
    Extrae y parsea una fecha desde texto usando los patrones comunes
    en comprobantes de pago peruanos.

    Busca formatos como:
    - 05 jul. 2024
    - 05/07/2024
    - 05 julio 2024
    - 2024-07-05
    - 05-Jul-2024
    - 05 Jul 2024

    Args:
        text: Texto del comprobante de pago.

    Returns:
        Datetime con timezone Lima, o None si no se encontró fecha.
    """
    import re

    if not text:
        return None

    # Mapeo de meses abreviados en español a números
    months_map = {
        "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
        "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
        "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5,
        "junio": 6, "julio": 7, "agosto": 8, "septiembre": 9,
        "octubre": 10, "noviembre": 11, "diciembre": 12,
    }

    patterns = [
        # 05 jul. 2024
        (r"\b(\d{1,2})\s+([a-z]{3})\.\s+(\d{4})\b", lambda m: datetime(
            int(m.group(3)), months_map.get(m.group(2).lower(), 1),
            int(m.group(1))
        )),
        # 05/07/2024
        (r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", lambda m: datetime(
            int(m.group(3)), int(m.group(2)), int(m.group(1))
        )),
        # 05 julio 2024
        (r"\b(\d{1,2})\s+([a-z]{3,9})\s+(\d{4})\b", lambda m: datetime(
            int(m.group(3)), months_map.get(m.group(2).lower(), 1),
            int(m.group(1))
        )),
        # 2024-07-05
        (r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", lambda m: datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3))
        )),
    ]

    for pattern, parser in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                naive_dt = parser(match)
                return LIMA_TZ.localize(naive_dt)
            except (ValueError, KeyError):
                continue

    return None


# ---------------------------------------------------------------------------
# Operaciones con fechas
# ---------------------------------------------------------------------------

def is_date_in_range(
    date_to_check: datetime,
    start_date: datetime,
    end_date: datetime,
) -> bool:
    """
    Verifica si una fecha está dentro de un rango [start_date, end_date].

    Args:
        date_to_check: Fecha a verificar.
        start_date: Inicio del rango (inclusivo).
        end_date: Fin del rango (inclusivo).

    Returns:
        True si date_to_check está en el rango.

    Example:
        >>> from datetime import datetime
        >>> check = datetime(2025, 1, 15)
        >>> start = datetime(2025, 1, 1)
        >>> end = datetime(2025, 1, 31)
        >>> is_date_in_range(check, start, end)
        True
    """
    return start_date <= date_to_check <= end_date


def is_expired(end_date: datetime) -> bool:
    """
    Verifica si una fecha ya expiró (es anterior a ahora en Lima).

    Args:
        end_date: Fecha de vencimiento a verificar.

    Returns:
        True si la fecha ya pasó (expirada).
    """
    now = get_lima_time()
    return end_date < now


def days_until(date_to_check: datetime) -> int:
    """
    Calcula los días que faltan hasta (o desde) una fecha.

    Args:
        date_to_check: Fecha a comparar con hoy en Lima.

    Returns:
        Días restantes. Positivo si falta, negativo si ya pasó.

    Example:
        >>> future = get_lima_time() + timedelta(days=5)
        >>> days_until(future)
        5
    """
    now = get_lima_time()
    delta = date_to_check - now
    return delta.days


def add_days_to_lima_date(days: int) -> datetime:
    """
    Suma N días a la fecha actual en Lima y retorna el resultado.

    Args:
        days: Número de días a agregar (puede ser negativo).

    Returns:
        Nueva fecha en timezone Lima.

    Example:
        >>> next_week = add_days_to_lima_date(7)
        >>> print(next_week.strftime("%d/%m/%Y"))
    """
    now = get_lima_time()
    return now + timedelta(days=days)


def get_start_of_day_lima() -> datetime:
    """
    Obtiene el inicio del día actual en Lima (00:00:00).

    Returns:
        Datetime con hora 00:00:00 en timezone Lima.

    Example:
        >>> start = get_start_of_day_lima()
        >>> print(start.strftime("%Y-%m-%d %H:%M:%S"))
        2025-01-15 00:00:00
    """
    now = get_lima_time()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def get_end_of_day_lima() -> datetime:
    """
    Obtiene el fin del día actual en Lima (23:59:59.999999).

    Returns:
        Datetime con hora 23:59:59.999999 en timezone Lima.
    """
    now = get_lima_time()
    return now.replace(hour=23, minute=59, second=59, microsecond=999999)
