"""
Text Parsers for Payment Receipts - Magic Chatbot v2
=====================================================
Extractores de texto para procesar comprobantes de pago de Yape, Plin,
transferencias bancarias, etc. Diseñados para trabajar con texto crudo
proveniente de Google Cloud Vision OCR o mensajes directos de Telegram.

Uso:
    from utils.text_parser import extract_amount, extract_date, clean_text

    monto = extract_amount("¡Yapeaste! S/ 25.00 a Juan Perez")
    fecha = extract_date("Compra del 05/07/2024 a las 14:30")
    texto_limpio = clean_text("Hola\nMundo  5/ 100")
"""

import re
import unicodedata
from datetime import datetime

# ---------------------------------------------------------------------------
# Constantes: Palabras clave que preceden a montos según plataforma
# ---------------------------------------------------------------------------

KEYWORDS_BEFORE_AMOUNT: dict = {
    "YAPE": "¡Yapeaste!",
    "YAPE_ALT": "Yapeaste",
    "PLIN": "Enviaste",
    "INTERBANK": "enviado",
    "BCP": "transferencia",
    "BANCO": "Transferiste",
}

# Montos máximos y mínimos razonables para filtrar falsos positivos
MAX_REASONABLE_AMOUNT: float = 10000.0
MIN_REASONABLE_AMOUNT: float = 1.0


# ============================================================================
# Limpieza de texto
# ============================================================================


def clean_text(text: str) -> str:
    """
    Limpia y normaliza texto de comprobantes de pago.

    Realiza las siguientes transformaciones:
    - Reemplaza saltos de línea por espacios.
    - Corrige errores de OCR: '5/' -> 'S/', '$/' -> 'S/'.
    - Normaliza caracteres Unicode (tildes, eñes, etc.) vía NFKD.
    - Colapsa múltiples espacios en uno solo.
    - Elimina espacios al inicio y final.

    Args:
        text: Texto crudo del comprobante (puede venir de OCR o mensaje).

    Returns:
        Texto limpio y normalizado.

    Example:
        >>> clean_text("Hola\\nMundo  5/ 100")
        'Hola Mundo S/ 100'
    """
    if not text:
        return ""

    # Normalizar unicode (NFKD descompone caracteres compuestos)
    text = unicodedata.normalize("NFKD", text)

    # Reemplazar saltos de línea
    text = text.replace("\n", " ")
    text = text.replace("\r", " ")

    # Corregir confusión de OCR: '5/' se lee como 'S/' en muchas fuentes
    text = text.replace("5/", "S/")
    text = text.replace("$/", "S/")

    # Colapsar espacios múltiples
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# ============================================================================
# Extracción de montos
# ============================================================================


def extract_amount(text: str) -> float | None:
    """
    Extrae un monto monetario desde el texto de un comprobante de pago.

    Estrategia de extracción (en orden de prioridad):
    1. Busca palabras clave de billeteras digitales (Yape, Plin, etc.)
       y extrae el monto que aparece después de ellas.
    2. Busca el patrón 'S/' seguido de un número (soles peruanos).
    3. Como fallback, busca cualquier número flotante razonable en el texto.

    Args:
        text: Texto del comprobante (crudo o pre-limpiado). Se limpia
              automáticamente si es necesario.

    Returns:
        Monto como float si se encontró y es razonable, None en caso contrario.

    Example:
        >>> extract_amount("¡Yapeaste! S/ 25.00 a Juan Perez")
        25.0
        >>> extract_amount("Enviaste S/ 100.50 por Plin")
        100.5
        >>> extract_amount("Hola mundo")
        None
    """
    if not text:
        return None

    text = clean_text(text)

    # --- Estrategia 1: Buscar después de palabras clave ---
    for keyword in KEYWORDS_BEFORE_AMOUNT.values():
        if keyword.lower() in text.lower():
            # Buscar el primer monto que aparece después de la palabra clave
            pattern = rf"{re.escape(keyword)}.*?([Ss]/?\s*\d+(?:[\.,]\d{{1,2}})?)"
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                amount_str = match.group(1)
                # Limpiar el símbolo S/ y espacios
                amount_str = re.sub(r"[Ss]/?\s*", "", amount_str)
                amount_str = amount_str.replace(",", ".")
                try:
                    amount = float(amount_str)
                    if MIN_REASONABLE_AMOUNT <= amount < MAX_REASONABLE_AMOUNT:
                        return amount
                except ValueError:
                    continue

    # --- Estrategia 2: Buscar patrón S/ seguido de número ---
    sol_pattern = r"[Ss]/?\s*(\d+(?:[\.,]\d{1,2})?)"
    matches = re.findall(sol_pattern, text)
    for amount_str in matches:
        amount_str_clean = amount_str.replace(",", ".")
        try:
            amount = float(amount_str_clean)
            if MIN_REASONABLE_AMOUNT < amount < MAX_REASONABLE_AMOUNT:
                return amount
        except ValueError:
            continue

    # --- Estrategia 3: Fallback - cualquier número flotante razonable ---
    numbers = re.findall(r"[-+]?\d+\.\d{2}|\d+", text)
    for num_str in numbers:
        try:
            amount = float(num_str)
            # Solo montos que parezcan precios (entre 1 y 10000 soles)
            if 1.0 <= amount < MAX_REASONABLE_AMOUNT:
                return amount
        except ValueError:
            continue

    return None


# ============================================================================
# Extracción de fechas
# ============================================================================


def extract_date(text: str) -> str | None:
    """
    Extrae una fecha desde el texto de un comprobante y la retorna
    en formato 'dd/mm/yyyy'.

    Soporta múltiples formatos de entrada:
    - 05 jul. 2024
    - 05/07/2024
    - 05 julio 2024
    - 2024-07-05
    - 05-Jul-2024
    - 05 Jul 2024
    - 05-07-2024

    Args:
        text: Texto del comprobante (crudo o pre-limpiado).

    Returns:
        Fecha en formato 'dd/mm/yyyy' (ej: '05/07/2024'), o None si no se encontró
        ninguna fecha reconocible.

    Example:
        >>> extract_date("Compra del 05/07/2024 a las 14:30")
        '05/07/2024'
        >>> extract_date("Fecha: 05 jul. 2024")
        '05/07/2024'
    """
    if not text:
        return None

    text = clean_text(text)

    # Patrones de fecha con sus respectivos formatos de parsing
    date_patterns: list = [
        (r"\b(\d{1,2}\s+[a-z]{3}\.\s+\d{4})\b", ["%d %b. %Y"]),     # 05 jul. 2024
        (r"\b(\d{1,2}/\d{1,2}/\d{4})\b", ["%d/%m/%Y"]),               # 05/07/2024
        (r"\b(\d{1,2}\s+[a-z]{3,9}\s+\d{4})\b", ["%d %B %Y", "%d %b %Y"]),  # 05 julio 2024
        (r"\b(\d{4}-\d{1,2}-\d{1,2})\b", ["%Y-%m-%d"]),               # 2024-07-05
        (r"\b(\d{1,2}-[a-z]{3}-\d{4})\b", ["%d-%b-%Y"]),              # 05-Jul-2024
        (r"\b(\d{1,2}\s+[a-z]{3}\s+\d{4})\b", ["%d %b %Y"]),          # 05 Jul 2024
        (r"\b(\d{1,2}-\d{1,2}-\d{4})\b", ["%d-%m-%Y"]),               # 05-07-2024
    ]

    for pattern, formats in date_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            extracted_date: str = matches[0]
            for fmt in formats:
                try:
                    date_obj = datetime.strptime(extracted_date, fmt)
                    return date_obj.strftime("%d/%m/%Y")
                except ValueError:
                    continue

    return None
