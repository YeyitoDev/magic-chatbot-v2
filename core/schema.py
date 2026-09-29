"""
Verificación de esquema al arrancar.

Las migraciones se aplican manualmente (ver ``migrations/``). Si el código
espera columnas que la BD aún no tiene, el bot fallaría en la primera
consulta con un error poco claro; esta verificación lo detecta al inicio.
"""

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

# Columnas agregadas por migraciones que el código necesita: tabla -> columnas
REQUIRED_COLUMNS: dict[str, set[str]] = {
    "purchases": {"status", "notes", "payment_ref"},
    "subscriptions": {"is_active"},
}


def missing_columns(engine: Engine) -> list[str]:
    """Retorna las columnas requeridas que no existen, como 'tabla.columna'."""
    inspector = inspect(engine)
    missing: list[str] = []
    for table, columns in REQUIRED_COLUMNS.items():
        if not inspector.has_table(table):
            continue  # init_db la crea completa
        existing = {col["name"] for col in inspector.get_columns(table)}
        missing.extend(f"{table}.{col}" for col in sorted(columns - existing))
    return missing
