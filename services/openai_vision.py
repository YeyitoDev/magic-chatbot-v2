"""
Gemini Vision Service - Magic Chatbot v2
========================================
Servicio para analizar imágenes de pagos usando Google Gemini Vision API
y extraer automáticamente el monto del pago.

Uso:
    from services.openai_vision import GeminiVisionService

    service = GeminiVisionService()
    price = await service.extract_price_from_image(image_path_or_url)
"""

import base64
import logging
import re
from pathlib import Path

import httpx

from config.settings import settings

logger = logging.getLogger(__name__)


class GeminiVisionService:
    """
    Servicio para analizar imágenes con Google Gemini Vision API.

    Extrae automáticamente el monto de pagos de recibos, capturas
    de pantalla de transferencias, etc.

    Usa Gemini 1.5 Flash (más económico: ~$0.0005/imagen vs ~$0.005/imagen de OpenAI).
    """

    def __init__(self, api_key: str | None = None) -> None:
        """
        Inicializa el servicio de Gemini Vision.

        Args:
            api_key: API key de Google Gemini. Si no se proporciona, usa settings.GEMINI_API_KEY.
        """
        self.api_key = api_key or getattr(settings, "GEMINI_API_KEY", None)
        # Modelo actualizado: gemini-1.5-flash fue descontinuado por Google.
        # Usar variable de entorno GEMINI_MODEL para permitir ajustes futuros.
        self.model = getattr(settings, "GEMINI_MODEL", "gemini-2.5-flash")
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"

    async def extract_price_from_image(
        self,
        image_source: str,
        expected_price: float | None = None,
    ) -> dict:
        """
        Extrae el precio de una imagen usando Gemini Vision.

        Args:
            image_source: Ruta local del archivo o URL de la imagen.
            expected_price: Precio esperado (opcional, para validación).

        Returns:
            Dict con:
            - success: bool
            - price: float (si se detectó)
            - confidence: str (high/medium/low)
            - raw_response: str (respuesta completa del modelo)
            - error: str (si hubo error)
        """
        if not self.api_key:
            return {
                "success": False,
                "error": "GEMINI_API_KEY no configurada",
                "price": None,
                "confidence": "low",
                "raw_response": "",
            }

        try:
            # Obtener la imagen en base64
            image_base64 = await self._image_to_base64(image_source)
            if not image_base64:
                return {
                    "success": False,
                    "error": "No se pudo procesar la imagen",
                    "price": None,
                    "confidence": "low",
                    "raw_response": "",
                }

            # Construir el prompt
            prompt = self._build_extraction_prompt(expected_price)

            # Llamar a la API de Gemini
            response = await self._call_gemini_vision(image_base64, prompt)

            # Extraer el precio de la respuesta
            price, confidence = self._parse_price_from_response(response)

            return {
                "success": True,
                "price": price,
                "confidence": confidence,
                "raw_response": response,
                "error": None,
            }

        except Exception as e:
            logger.error(f"Error al extraer precio con Gemini Vision: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "price": None,
                "confidence": "low",
                "raw_response": "",
            }

    async def _image_to_base64(self, image_source: str) -> str | None:
        """
        Convierte una imagen (ruta local o URL) a base64.

        Args:
            image_source: Ruta local o URL de la imagen.

        Returns:
            String en base64 o None si falla.
        """
        try:
            # Si es una ruta local
            if Path(image_source).exists():
                with open(image_source, "rb") as f:
                    return base64.b64encode(f.read()).decode("utf-8")

            # Si es una URL, descargarla
            async with httpx.AsyncClient() as client:
                response = await client.get(image_source)
                response.raise_for_status()
                return base64.b64encode(response.content).decode("utf-8")

        except Exception as e:
            logger.error(f"Error al convertir imagen a base64: {e}")
            return None

    def _build_extraction_prompt(self, expected_price: float | None) -> str:
        """
        Construye el prompt para extraer el precio.

        Args:
            expected_price: Precio esperado (opcional).

        Returns:
            Prompt optimizado para extracción de precios.
        """
        base_prompt = (
            "Extract the payment amount from this receipt or payment screenshot. "
            "Return ONLY the numeric value, no currency symbols, no text. "
            "If multiple amounts are shown, return the total payment amount. "
            "If no amount is clearly visible, return '0'."
        )

        if expected_price is not None:
            base_prompt += (
                f" The expected amount is {expected_price}. "
                "If the detected amount is different, still return the detected amount."
            )

        return base_prompt

    async def _call_gemini_vision(self, image_base64: str, prompt: str) -> str:
        """
        Llama a la API de Gemini Vision.

        Args:
            image_base64: Imagen en base64.
            prompt: Prompt para el modelo.

        Returns:
            Respuesta del modelo como string.
        """
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt,
                        },
                        {
                            "inline_data": {
                                "mime_type": "image/jpeg",
                                "data": image_base64,
                            },
                        },
                    ],
                }
            ],
            "generationConfig": {
                "maxOutputTokens": 100,
                "temperature": 0.1,
            },
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.api_url, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["candidates"][0]["content"]["parts"][0]["text"]

    def _parse_price_from_response(self, response: str) -> tuple[float | None, str]:
        """
        Extrae el precio numérico de la respuesta del modelo.

        Args:
            response: Respuesta del modelo.

        Returns:
            Tupla (precio, confidence) donde confidence es "high"/"medium"/"low".
        """
        # Buscar números con decimales (ej: 50.00, 50, 50.0)
        price_pattern = r"(\d+\.?\d*)"
        matches = re.findall(price_pattern, response)

        if not matches:
            return None, "low"

        # Tomar el último número (asumir que es el total)
        try:
            price = float(matches[-1])

            # Validar que sea un precio razonable (entre 1 y 10000)
            if 1 <= price <= 10000:
                return price, "high"
            elif 0 < price < 1 or price > 10000:
                return price, "medium"
            else:
                return None, "low"

        except (ValueError, IndexError):
            return None, "low"

    async def validate_payment_image(
        self,
        image_source: str,
        expected_price: float,
        tolerance: float = 0.5,
    ) -> dict:
        """
        Valida si el precio en la imagen coincide con el esperado.

        Args:
            image_source: Ruta local o URL de la imagen.
            expected_price: Precio esperado.
            tolerance: Tolerancia en la misma moneda (ej: 0.5 para 50 soles ±0.5).

        Returns:
            Dict con:
            - valid: bool (si el precio coincide dentro de la tolerancia)
            - detected_price: float (precio detectado)
            - difference: float (diferencia absoluta)
            - confidence: str
        """
        result = await self.extract_price_from_image(image_source, expected_price)

        if not result["success"]:
            return {
                "valid": False,
                "detected_price": None,
                "difference": None,
                "confidence": result["confidence"],
                "error": result["error"],
            }

        detected_price = result["price"]
        if detected_price is None:
            return {
                "valid": False,
                "detected_price": None,
                "difference": None,
                "confidence": "low",
                "error": "No se detectó precio",
            }

        difference = abs(detected_price - expected_price)
        is_valid = difference <= tolerance

        return {
            "valid": is_valid,
            "detected_price": detected_price,
            "difference": difference,
            "confidence": result["confidence"],
            "error": None,
        }
