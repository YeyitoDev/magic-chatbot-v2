"""
Google Cloud Vision Service - Magic Chatbot v2
===============================================
Servicio para detección de texto en imágenes usando Google Cloud Vision API.

Encapsula la inicialización del cliente de Vision y proporciona métodos
para extraer texto de comprobantes de pago (Yape, Plin, transferencias).

Principios:
- Single Responsibility: solo se encarga de la interacción con Vision API.
- Encapsulación: el cliente de Vision se inicializa una vez y se reutiliza.
- Configuración externa: la ruta de credenciales viene de settings.

Uso:
    from services.google_vision import GoogleVisionService

    vision = GoogleVisionService()
    texto = vision.detect_text("images/comprobante.jpg")
    # texto: "¡Yapeaste! S/ 150.00 a Jose Gonzalez"
"""

import logging

from google.cloud import vision

from config.settings import settings

logger = logging.getLogger(__name__)


class GoogleVisionService:
    """
    Servicio wrapper para Google Cloud Vision API.

    Proporciona funcionalidad de detección de texto (OCR) en imágenes,
    utilizado principalmente para extraer montos y fechas de comprobantes
    de pago enviados por los usuarios.

    Attributes:
        _client (vision.ImageAnnotatorClient): Cliente autenticado de Vision API.
        _credentials_path (str): Ruta al archivo JSON de credenciales.
    """

    def __init__(self, credentials_path: str | None = None) -> None:
        """
        Inicializa el cliente de Google Cloud Vision.

        Args:
            credentials_path: Ruta al archivo JSON de credenciales de servicio.
                             Si es None, se usa el valor de settings.GOOGLE_CREDENTIALS_PATH.

        Raises:
            FileNotFoundError: Si el archivo de credenciales no existe.
            Exception: Si hay error al inicializar el cliente de Vision.
        """
        self._credentials_path = credentials_path or settings.GOOGLE_CREDENTIALS_PATH

        try:
            self._client = vision.ImageAnnotatorClient.from_service_account_json(
                self._credentials_path
            )
            logger.info(
                "Cliente de Google Cloud Vision inicializado correctamente."
            )
        except FileNotFoundError:
            logger.error(
                f"Archivo de credenciales no encontrado: {self._credentials_path}"
            )
            raise
        except Exception as e:
            logger.error(
                f"Error al inicializar Vision API client: {e}"
            )
            raise

    # ------------------------------------------------------------------
    # Detección de texto
    # ------------------------------------------------------------------

    def detect_text(self, image_path: str) -> str:
        """
        Detecta y extrae texto de una imagen usando Google Cloud Vision OCR.

        Abre la imagen desde el sistema de archivos, la envía a Vision API
        y retorna el texto detectado.

        Args:
            image_path: Ruta local al archivo de imagen (JPEG, PNG, etc.).

        Returns:
            Texto completo detectado en la imagen.

        Raises:
            FileNotFoundError: Si el archivo de imagen no existe.
            Exception: Si la API de Vision retorna un error.

        Example:
            >>> vision = GoogleVisionService()
            >>> texto = vision.detect_text("images/trans_12345.jpeg")
            >>> print(texto)
            '¡Yapeaste! S/ 150.00\\n15/01/2025 14:30\\nA Jose Gonzalez'
        """
        logger.info(f"Iniciando detección de texto en: {image_path}")

        # Leer la imagen desde el sistema de archivos
        try:
            with open(image_path, 'rb') as image_file:
                content = image_file.read()
        except FileNotFoundError:
            logger.error(f"Archivo de imagen no encontrado: {image_path}")
            raise
        except OSError as e:
            logger.error(f"Error al leer archivo de imagen {image_path}: {e}")
            raise

        # Construir la imagen para Vision API
        image = vision.Image(content=content)

        # Ejecutar detección de texto
        try:
            response = self._client.text_detection(image=image)
        except Exception as e:
            logger.error(f"Error al llamar a Vision API: {e}")
            raise Exception(f"Error en la API de Google Vision: {str(e)}") from e

        # Verificar errores en la respuesta
        if response.error.message:
            error_msg = response.error.message
            logger.error(f"Vision API retornó error: {error_msg}")
            raise Exception(
                f"Error durante la detección de texto: {error_msg}"
            )

        # Extraer el texto detectado (text_annotations[0] contiene todo el texto)
        if not response.text_annotations:
            logger.warning(
                f"No se detectó texto en la imagen: {image_path}"
            )
            return ""

        detected_text = response.text_annotations[0].description

        logger.info(
            f"Texto detectado exitosamente ({len(detected_text)} caracteres): "
            f"{detected_text[:100]}..."
        )

        return detected_text

    # ------------------------------------------------------------------
    # Métodos adicionales de utilidad
    # ------------------------------------------------------------------

    def detect_text_from_bytes(self, image_bytes: bytes) -> str:
        """
        Detecta texto desde bytes de imagen (sin leer del disco).

        Útil cuando la imagen se recibe directamente de Telegram
        y no se desea guardarla en disco antes de procesarla.

        Args:
            image_bytes: Contenido binario de la imagen.

        Returns:
            Texto detectado en la imagen.

        Raises:
            Exception: Si Vision API retorna un error.

        Example:
            >>> photo = await update.message.photo[-1].get_file()
            >>> image_bytes = await photo.download_as_bytearray()
            >>> texto = vision.detect_text_from_bytes(image_bytes)
        """
        logger.info("Iniciando detección de texto desde bytes de imagen.")

        image = vision.Image(content=image_bytes)

        try:
            response = self._client.text_detection(image=image)
        except Exception as e:
            logger.error(f"Error al llamar a Vision API desde bytes: {e}")
            raise

        if response.error.message:
            raise Exception(
                f"Error durante la detección de texto: {response.error.message}"
            )

        if not response.text_annotations:
            logger.warning("No se detectó texto en los bytes de imagen.")
            return ""

        detected_text = response.text_annotations[0].description

        logger.info(f"Texto detectado desde bytes: {detected_text[:100]}...")
        return detected_text

    def is_available(self) -> bool:
        """
        Verifica que el servicio de Vision API esté disponible.

        Realiza una verificación simple de que el cliente está correctamente
        inicializado y el archivo de credenciales existe.

        Returns:
            True si el servicio está listo para usar.
        """
        import os

        if not os.path.exists(self._credentials_path):
            logger.error(
                f"Credenciales no encontradas en: {self._credentials_path}"
            )
            return False

        if self._client is None:
            logger.error("Cliente de Vision API no inicializado.")
            return False

        return True


# ---------------------------------------------------------------------------
# Instancia por defecto (singleton a nivel módulo, lazy)
# ---------------------------------------------------------------------------

_vision_service_instance: GoogleVisionService | None = None


def get_vision_service() -> GoogleVisionService:
    """
    Obtiene la instancia singleton del servicio de Google Vision.

    La primera llamada inicializa el servicio. Las llamadas subsecuentes
    retornan la misma instancia.

    Returns:
        Instancia de GoogleVisionService lista para usar.

    Raises:
        FileNotFoundError: Si el archivo de credenciales no existe.
        Exception: Si hay error al inicializar el cliente.

    Example:
        from services.google_vision import get_vision_service

        vision = get_vision_service()
        texto = vision.detect_text("comprobante.jpg")
    """
    global _vision_service_instance
    if _vision_service_instance is None:
        _vision_service_instance = GoogleVisionService()
    return _vision_service_instance

