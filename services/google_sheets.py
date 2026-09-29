"""
Google Sheets Service - Magic Chatbot v2
========================================
Servicio de integración con Google Sheets API usando gspread y googleapiclient.

Encapsula todas las operaciones con Google Sheets:
- Autenticación con cuenta de servicio.
- Lectura y escritura de datos en hojas de cálculo.
- Registro de nuevos usuarios.
- Búsqueda de datos de transferencias WhatsApp (WSP).
- Actualización de estados de revisión de pago.

Principios:
- Single Responsibility: solo interacción con Google Sheets API.
- Encapsulación: el cliente gspread se inicializa una vez y se reutiliza.
- Configuración externa: credenciales y IDs vienen de settings.

Hojas utilizadas (basadas en el código original):
- Suscripciones_vip_activas: Suscripciones VIP vigentes.
- Suscripciones_vip_historico: Histórico de suscripciones VIP.
- Usuarios_registrados: Registro de nuevos usuarios.
- usuarios_registrados_wsp: Registro de usuarios vía WhatsApp.

Uso:
    from services.google_sheets import GoogleSheetsService

    sheets = GoogleSheetsService()
    values = sheets.fetch_data("Usuarios_registrados")
    sheets.register_new_user([user_id, nombre, fecha_registro])
"""

import logging
from typing import Any

import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build

from config.settings import settings
from services.google_credentials import get_google_credentials

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Nombres de hojas (deben coincidir con las hojas reales del spreadsheet)
SHEET_SUBS_VIP_ACTIVAS = "Suscripciones_vip_activas"
SHEET_SUBS_VIP_HISTORICO = "Suscripciones_vip_historico"
SHEET_USUARIOS_REGISTRADOS = "Usuarios_registrados"
SHEET_WSP_USUARIOS_REGISTRADOS = "usuarios_registrados_wsp"

# ID del spreadsheet que contiene los links de grupos de Telegram
SHEET_GRUPOS_TELEGRAM_ID = "13IvH0Y_ROBaMGsIrMESIvlkLr_6q7_w1qjcC5Vdeoz4"


class GoogleSheetsService:
    """
    Servicio wrapper para Google Sheets API.

    Proporciona métodos de alto nivel para interactuar con las hojas de cálculo
    utilizadas por el bot: registro de usuarios, gestión de suscripciones,
    y búsqueda de datos de transferencias WhatsApp.

    Attributes:
        _spreadsheet_id (str): ID del spreadsheet principal.
        _wsp_spreadsheet_id (str): ID del spreadsheet de WhatsApp.
        _client (gspread.Client): Cliente de gspread autenticado.
        _service (googleapiclient.discovery.Resource): Servicio de Sheets API v4.
    """

    def __init__(
        self,
        credentials_path: str | None = None,
        spreadsheet_id: str | None = None,
        wsp_spreadsheet_id: str | None = None,
    ) -> None:
        """
        Inicializa el cliente de Google Sheets.

        Args:
            credentials_path: Ruta al JSON de credenciales (opcional,
                              para backward compatibility). Si no se proporciona,
                              se usa get_google_credentials().
            spreadsheet_id: ID del spreadsheet principal. Default: settings.
            wsp_spreadsheet_id: ID del spreadsheet de WhatsApp. Default: settings.

        Raises:
            FileNotFoundError: Si las credenciales no se encuentran.
            Exception: Si hay error al autenticar con Google.
        """
        self._spreadsheet_id = spreadsheet_id or settings.GOOGLE_SHEETS_ID
        self._wsp_spreadsheet_id = (
            wsp_spreadsheet_id or settings.GOOGLE_WSP_SPREADSHEET_ID
        )

        # Autenticar cuenta de servicio
        try:
            if credentials_path:
                creds = service_account.Credentials.from_service_account_file(
                    credentials_path,
                    scopes=SCOPES,
                )
                logger.info(
                    "Google Sheets credentials loaded from explicit path."
                )
            else:
                creds_info = get_google_credentials()
                creds = service_account.Credentials.from_service_account_info(
                    creds_info,
                    scopes=SCOPES,
                )
                logger.info(
                    "Google Sheets credentials loaded from get_google_credentials()."
                )
        except FileNotFoundError:
            logger.error("Google credentials not found for Sheets API.")
            raise
        except Exception as e:
            logger.error(f"Error loading Google credentials: {e}")
            raise

        # Cliente gspread (más simple para operaciones comunes)
        self._client = gspread.authorize(creds)

        # Servicio googleapiclient (para operaciones avanzadas)
        self._service = build("sheets", "v4", credentials=creds)

        logger.info("GoogleSheetsService inicializado correctamente.")

    # ------------------------------------------------------------------
    # Operaciones básicas de lectura/escritura
    # ------------------------------------------------------------------

    def fetch_data(
        self,
        sheet_name: str,
        spreadsheet_id: str | None = None,
        range_spec: str = "A:F",
    ) -> list[list[str]]:
        """
        Obtiene los valores de una hoja de cálculo.

        Args:
            sheet_name: Nombre de la hoja dentro del spreadsheet.
            spreadsheet_id: ID del spreadsheet (default: el principal).
            range_spec: Rango de columnas a obtener (ej: "A:F").

        Returns:
            Lista de filas, cada fila es una lista de strings con los valores
            de cada celda.

        Example:
            >>> values = sheets.fetch_data("Usuarios_registrados")
            >>> headers = values[0]  # Primera fila = encabezados
            >>> data = values[1:]    # Resto = datos
        """
        sid = spreadsheet_id or self._spreadsheet_id
        if not sid:
            logger.error("No se especificó spreadsheet_id.")
            return []

        range_name = f"{sheet_name}!{range_spec}"

        try:
            result = (
                self._service.spreadsheets()
                .values()
                .get(spreadsheetId=sid, range=range_name)
                .execute()
            )
            values = result.get("values", [])
            logger.debug(
                f"fetch_data: {len(values)} filas obtenidas de '{sheet_name}'"
            )
            return values
        except Exception as e:
            logger.error(f"Error al leer datos de '{sheet_name}': {e}")
            return []

    def insert_data(
        self,
        sheet_name: str,
        row_data: list[Any],
        spreadsheet_id: str | None = None,
    ) -> bool:
        """
        Inserta una nueva fila al final de una hoja de cálculo.

        Args:
            sheet_name: Nombre de la hoja.
            row_data: Lista de valores para la nueva fila.
            spreadsheet_id: ID del spreadsheet (default: el principal).

        Returns:
            True si se insertó correctamente, False si hubo error.

        Example:
            >>> sheets.insert_data("Usuarios_registrados", [user_id, nombre, fecha])
        """
        sid = spreadsheet_id or self._spreadsheet_id
        if not sid:
            logger.error("No se especificó spreadsheet_id.")
            return False

        # Obtener la siguiente fila disponible
        existing = self.fetch_data(sheet_name, spreadsheet_id=sid)
        next_row = len(existing) + 1

        range_name = f"{sheet_name}!A{next_row}"

        body = {"values": [row_data]}

        try:
            result = (
                self._service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=sid,
                    range=range_name,
                    valueInputOption="RAW",
                    body=body,
                )
                .execute()
            )
            updated_cells = result.get("updates", {}).get("updatedCells", 0)
            logger.info(
                f"Fila insertada en '{sheet_name}': {updated_cells} celdas actualizadas."
            )
            return True
        except Exception as e:
            logger.error(f"Error al insertar datos en '{sheet_name}': {e}")
            return False

    def update_cell(
        self,
        sheet_name: str,
        row: int,
        col: int,
        value: Any,
        spreadsheet_id: str | None = None,
    ) -> bool:
        """
        Actualiza una celda específica en una hoja de cálculo.

        Args:
            sheet_name: Nombre de la hoja.
            row: Número de fila (1-indexado).
            col: Número de columna (1-indexado).
            value: Valor a escribir en la celda.
            spreadsheet_id: ID del spreadsheet.

        Returns:
            True si se actualizó correctamente.
        """
        sid = spreadsheet_id or self._spreadsheet_id
        if not sid:
            return False

        try:
            sheet = self._client.open_by_key(sid).worksheet(sheet_name)
            sheet.update_cell(row, col, str(value))
            logger.debug(f"Celda ({row},{col}) actualizada en '{sheet_name}'.")
            return True
        except Exception as e:
            logger.error(f"Error al actualizar celda en '{sheet_name}': {e}")
            return False

    def get_all_records(
        self,
        sheet_name: str,
        spreadsheet_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Obtiene todos los registros de una hoja como lista de diccionarios.

        La primera fila se usa como encabezados (keys de los dicts).

        Args:
            sheet_name: Nombre de la hoja.
            spreadsheet_id: ID del spreadsheet.

        Returns:
            Lista de diccionarios, uno por fila de datos.

        Example:
            >>> records = sheets.get_all_records("usuarios_registrados_wsp")
            >>> for r in records:
            ...     print(r['ID'], r['YAPEO CAPTURA'])
        """
        sid = spreadsheet_id or self._spreadsheet_id
        if not sid:
            return []

        try:
            sheet = self._client.open_by_key(sid).worksheet(sheet_name)
            records = sheet.get_all_records()
            logger.debug(f"get_all_records: {len(records)} de '{sheet_name}'")
            return records
        except Exception as e:
            logger.error(f"Error al obtener registros de '{sheet_name}': {e}")
            return []

    # ------------------------------------------------------------------
    # Registro de usuarios
    # ------------------------------------------------------------------

    def register_new_user(
        self, user_data: list[Any]
    ) -> bool:
        """
        Registra un nuevo usuario en la hoja de usuarios registrados.

        Args:
            user_data: Lista con los datos del usuario:
                       [telegram_id, nombre, fecha_registro].

        Returns:
            True si se registró correctamente.
        """
        return self.insert_data(SHEET_USUARIOS_REGISTRADOS, user_data)

    def register_vip_subscription(
        self, subscription_data: list[Any]
    ) -> bool:
        """
        Registra una suscripción VIP en la hoja de histórico.

        Args:
            subscription_data: Datos de la suscripción.

        Returns:
            True si se registró correctamente.
        """
        return self.insert_data(SHEET_SUBS_VIP_HISTORICO, subscription_data)

    # ------------------------------------------------------------------
    # Operaciones con datos de WhatsApp (WSP)
    # ------------------------------------------------------------------

    def get_wsp_transfer_data(
        self, wsp_id: int, telegram_id: int
    ) -> tuple:
        """
        Busca los datos de transferencia de un usuario de WhatsApp.

        Dado un wsp_id (ID de WhatsApp), busca en la hoja de usuarios
        registrados por WhatsApp y retorna la URL de la captura Yape/Plin
        y el tipo de servicio seleccionado.

        También actualiza el telegram_id en la hoja para vincular
        la cuenta de WhatsApp con la de Telegram.

        Args:
            wsp_id: ID del usuario en WhatsApp (número).
            telegram_id: ID de Telegram del usuario para vincular.

        Returns:
            Tupla (url_yapeo, tipo_servicio) donde:
            - url_yapeo: URL de la imagen de la transferencia.
            - tipo_servicio: "grupo_vip" o "stake_maxima_seguridad".
            - Si no se encuentra el wsp_id, retorna (None, None).

        Example:
            >>> url, tipo = sheets.get_wsp_transfer_data(123456789, 987654321)
            >>> print(url)
            'https://manybot-files.s3...'
            >>> print(tipo)
            'grupo_vip'
        """
        wsp_id = int(wsp_id)
        telegram_id = int(telegram_id)

        if not self._wsp_spreadsheet_id:
            logger.error("GOOGLE_WSP_SPREADSHEET_ID no configurado.")
            return None, None

        try:
            sheet = self._client.open_by_key(self._wsp_spreadsheet_id).worksheet(
                SHEET_WSP_USUARIOS_REGISTRADOS
            )
            records = sheet.get_all_records()

            for idx, record in enumerate(records):
                if record.get("ID") == wsp_id:
                    # Actualizar telegram_id en la hoja (columna 6)
                    fila = idx + 2  # +2 porque: 1-indexado + 1 fila de headers
                    sheet.update_cell(fila, 6, telegram_id)
                    logger.info(
                        f"telegram_id={telegram_id} vinculado a wsp_id={wsp_id}"
                    )

                    # Determinar tipo de servicio
                    tipo_servicio = ""
                    etiqueta = record.get("SERVICIO ETIQETA", "")
                    if etiqueta == "REVISIÓN VIP":
                        tipo_servicio = "grupo_vip"
                    elif etiqueta == "REVISIÓN STAKE":
                        tipo_servicio = "stake_maxima_seguridad"

                    url_yapeo = record.get("YAPEO CAPTURA")
                    return url_yapeo, tipo_servicio

            logger.warning(f"wsp_id={wsp_id} no encontrado en la hoja WSP.")
            return None, None

        except Exception as e:
            logger.error(f"Error al buscar datos WSP para wsp_id={wsp_id}: {e}")
            return None, None

    def get_wsp_transfer_url(
        self, wsp_id: int, telegram_id: int
    ) -> str | None:
        """
        Versión simplificada: solo retorna la URL de la transferencia.
        (Compatible con la función original wsp_obtener_url_yapeo_por_id)

        Args:
            wsp_id: ID de WhatsApp del usuario.
            telegram_id: ID de Telegram del usuario.

        Returns:
            URL de la imagen de transferencia o None.
        """
        url, _ = self.get_wsp_transfer_data(wsp_id, telegram_id)
        return url

    def update_wsp_payment_review_status(
        self, telegram_id: int
    ) -> bool:
        """
        Actualiza la etiqueta de revisión de pago a TRUE para un usuario
        de WhatsApp.

        Busca al usuario por su telegram_id en la hoja de WhatsApp
        y marca la columna 'ETIQUETA DE REVISIÓN DE PAGO' como TRUE.

        Args:
            telegram_id: ID de Telegram del usuario.

        Returns:
            True si se encontró y actualizó, False si no.
        """
        telegram_id = int(telegram_id)

        if not self._wsp_spreadsheet_id:
            logger.error("GOOGLE_WSP_SPREADSHEET_ID no configurado.")
            return False

        try:
            sheet = self._client.open_by_key(self._wsp_spreadsheet_id).worksheet(
                SHEET_WSP_USUARIOS_REGISTRADOS
            )
            records = sheet.get_all_records()

            for idx, record in enumerate(records):
                if record.get("TELEGRAM_ID") == telegram_id:
                    fila = idx + 2
                    sheet.update_cell(fila, 4, "TRUE")
                    logger.info(
                        f"Etiqueta de revisión actualizada para telegram_id={telegram_id}"
                    )
                    return True

            logger.warning(
                f"telegram_id={telegram_id} no encontrado en hoja WSP."
            )
            return False

        except Exception as e:
            logger.error(
                f"Error al actualizar revisión WSP para telegram_id={telegram_id}: {e}"
            )
            return False

    # ------------------------------------------------------------------
    # Links de grupos de Telegram
    # ------------------------------------------------------------------

    def get_service_group_id(self, tipo_servicio: str) -> str | None:
        """
        Obtiene el ID del grupo de Telegram correspondiente a un tipo de servicio.

        Busca en el spreadsheet de identificadores de grupos de Telegram
        el ID del grupo para el servicio especificado.

        Args:
            tipo_servicio: Nombre del tipo de servicio (ej: "Stake").

        Returns:
            ID del grupo de Telegram como string, o None si no se encuentra.

        Example:
            >>> group_id = sheets.get_service_group_id("Stake")
            >>> print(group_id)
            '-1001234567890'
        """
        try:
            range_name = f"{tipo_servicio}!A:D"
            result = (
                self._service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=SHEET_GRUPOS_TELEGRAM_ID,
                    range=range_name,
                )
                .execute()
            )
            values = result.get("values", [])
            if values and values[0]:
                group_id = values[0][0]
                logger.debug(f"Group ID para '{tipo_servicio}': {group_id}")
                return group_id
            return None
        except Exception as e:
            logger.error(
                f"Error al obtener group ID para '{tipo_servicio}': {e}"
            )
            return None

    def get_next_available_row(
        self,
        sheet_name: str,
        spreadsheet_id: str | None = None,
    ) -> int:
        """
        Obtiene el número de la siguiente fila disponible en una hoja.

        Args:
            sheet_name: Nombre de la hoja.
            spreadsheet_id: ID del spreadsheet.

        Returns:
            Número de la siguiente fila disponible (1-indexado).
        """
        values = self.fetch_data(sheet_name, spreadsheet_id=spreadsheet_id)
        return len(values) + 1

    def query_rows_by_column(
        self,
        sheet_name: str,
        column_index: int,
        query_value: Any,
        spreadsheet_id: str | None = None,
    ) -> list[list[str]]:
        """
        Busca filas donde una columna específica coincida con un valor.

        Args:
            sheet_name: Nombre de la hoja.
            column_index: Índice de la columna (0-indexado).
            query_value: Valor a buscar en esa columna.
            spreadsheet_id: ID del spreadsheet.

        Returns:
            Lista de filas que coinciden con el criterio.
        """
        values = self.fetch_data(sheet_name, spreadsheet_id=spreadsheet_id)
        if not values:
            return []

        # La primera fila son headers
        data = values[1:]
        query_str = str(query_value)
        return [
            row for row in data
            if len(row) > column_index and row[column_index] == query_str
        ]

    # ------------------------------------------------------------------
    # Verificación
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """
        Verifica que el servicio de Google Sheets esté disponible.

        Returns:
            True si el cliente está correctamente inicializado.
        """
        if self._client is None:
            logger.error("Cliente gspread no inicializado.")
            return False

        return True


# ---------------------------------------------------------------------------
# Instancia por defecto
# ---------------------------------------------------------------------------

_sheets_service_instance: GoogleSheetsService | None = None


def get_sheets_service() -> GoogleSheetsService:
    """
    Obtiene la instancia singleton del servicio de Google Sheets.

    Returns:
        Instancia de GoogleSheetsService lista para usar.

    Raises:
        FileNotFoundError: Si las credenciales no existen.
        Exception: Si hay error al inicializar.
    """
    global _sheets_service_instance
    if _sheets_service_instance is None:
        _sheets_service_instance = GoogleSheetsService()
    return _sheets_service_instance
