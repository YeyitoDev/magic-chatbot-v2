"""
Promotion Service - Magic Chatbot v2
=====================================
Pipeline de promociones y spam controlado usando AWS DynamoDB.

Este servicio replica la lógica de `get_users_interactions_status()` del
archivo original `jobMensajesRecordatorios.py`, refactorizada siguiendo
principios SOLID y Clean Code.

Flujo de promociones (basado en el código original):
1. Registrar usuario en DynamoDB con estado 'pendiente' al interactuar con el bot.
2. El job programado escanea DynamoDB buscando usuarios con estado != 'FINALIZADO'.
3. Evalúa timestamps para determinar qué promo enviar:
   - Promo_15_min: se envía a los 0 minutos (inmediata).
   - Promo_24_horas: se envía después de 5 segundos (en el código original).
4. Envía videos promocionales de BetSafe con botones inline.
5. Actualiza el estado en DynamoDB según la promo enviada.
6. Al llegar a la última promo, marca al usuario como 'FINALIZADO'.

Principios:
- Single Responsibility: solo lógica de pipeline de promociones.
- Configuración externa: región y tabla desde settings.
- Stateless + DynamoDB: el estado se mantiene en la nube, no en memoria.

Uso:
    from services.promotion_service import PromotionService

    promo_service = PromotionService(region="us-east-1", table_name="MAGIC-USER-SESSIONS-LOG")
    promo_service.register_user(12345)
    results = promo_service.process_promotion_pipeline()
"""

import logging
import time
from typing import Any

import boto3
from boto3.dynamodb.conditions import Attr
from botocore.exceptions import ClientError

from config.settings import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constantes de promociones (basadas en el código original)
# ---------------------------------------------------------------------------

ESTADO_FINAL = "FINALIZADO"
ESTADO_PENDIENTE = "pendiente"

MENSAJE_BETSAFE_PROMO_1 = (
    "<b>¡TE REGALO 70 LUCAS, MI KING!</b> 👑🔥\n\n"
    "Regístrate con el <b>link exclusivo</b>, haz tu primer depósito de mínimo "
    "<b>S/. 40</b> y listo, tendrás <b>70 soles gratis</b>.\n\n"
    "Mira este video con el paso a paso de cómo llevarte los S/. 70 gratis ⬆️🎥"
)

MENSAJE_BETSAFE_PROMO_2 = (
    "<b>¡REGALO 70 LUCAS A TODOS!</b> 🎉\n\n"
    "<b>¡ÚLTIMO LLAMADO GENTE!</b> 🚨\n\n"
    "Regístrate con el <b>link exclusivo</b>, haz tu primer depósito de mínimo "
    "<b>S/. 40</b> y listo, tendrás <b>70 soles gratis</b>.\n\n"
    "Mira este video con el paso a paso de cómo llevarte los S/. 70 gratis ⬆️🔥"
)

PROMOS_CONFIG = [
    {
        "orden": 1,
        "nombre": "Promo_15_min",
        "video": "BETSAFE_PROMO_1.MP4",
        "mensaje": MENSAJE_BETSAFE_PROMO_1,
        "segundos_despues": 0,
    },
    {
        "orden": 2,
        "nombre": "Promo_24_horas",
        "video": "BETSAFE_PROMO_2.MP4",
        "mensaje": MENSAJE_BETSAFE_PROMO_2,
        "segundos_despues": 5,
    },
]


# ---------------------------------------------------------------------------
# Promotion Service
# ---------------------------------------------------------------------------

class PromotionService:
    """
    Servicio para la gestión del pipeline de promociones vía DynamoDB.

    Maneja el registro de usuarios en la tabla de sesiones de DynamoDB,
    el escaneo periódico de usuarios pendientes y el envío de promociones
    según la configuración de PROMOS_CONFIG.

    Attributes:
        _region_name (str): Región de AWS donde está la tabla DynamoDB.
        _table_name (str): Nombre de la tabla DynamoDB.
        _table: Recurso Table de DynamoDB (boto3).
        _telegram_api: Instancia de TelegramAPIService para enviar mensajes.
    """

    def __init__(
        self,
        region_name: str | None = None,
        table_name: str | None = None,
    ) -> None:
        """
        Inicializa el servicio de promociones con conexión a DynamoDB.

        Args:
            region_name: Región de AWS. Si None, usa settings.AWS_REGION.
            table_name: Nombre de la tabla DynamoDB. Si None, usa settings.AWS_DYNAMODB_TABLE.

        Raises:
            ValueError: Si no se pueden obtener credenciales de AWS.
        """
        self._region_name = region_name or settings.AWS_REGION
        self._table_name = table_name or settings.AWS_DYNAMODB_TABLE

        try:
            dynamodb = boto3.resource('dynamodb', region_name=self._region_name)
            self._table = dynamodb.Table(self._table_name)
            logger.info(
                f"PromotionService inicializado: tabla={self._table_name}, "
                f"region={self._region_name}"
            )
        except Exception as e:
            logger.warning(
                f"No se pudo conectar con DynamoDB: {e}. "
                f"PromotionService operará en modo degradado (sin DynamoDB)."
            )
            self._table = None

        # Lazy import para evitar circular imports
        self._telegram_api = None

    def _is_available(self) -> bool:
        """Verifica si el servicio DynamoDB está disponible."""
        return self._table is not None

    def _mark_unavailable(self) -> None:
        """Marca el servicio como no disponible tras un error de credenciales."""
        if self._table is not None:
            logger.warning(
                "PromotionService marcado como NO DISPONIBLE. "
                "Verifica las credenciales AWS (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)."
            )
            self._table = None

    @property
    def telegram_api(self):
        """Obtiene la instancia de TelegramAPIService (lazy)."""
        if self._telegram_api is None:
            from services.telegram_api import TelegramAPIService
            self._telegram_api = TelegramAPIService()
        return self._telegram_api

    # ------------------------------------------------------------------
    # Registro de usuario
    # ------------------------------------------------------------------

    def register_user(self, user_id: str) -> bool:
        """
        Registra un usuario en la tabla DynamoDB para iniciar el pipeline
        de promociones.

        El usuario se inserta con:
        - userId: ID del usuario en Telegram.
        - timestamp: Timestamp actual en segundos Unix (como string).
        - estado: 'pendiente'.

        Si el usuario ya existe con estado 'pendiente', no se duplica.

        Args:
            user_id: ID de Telegram del usuario (se convierte a string).

        Returns:
            True si se insertó correctamente, False si ya existía o hubo error.

        Example:
            >>> promo_service.register_user("123456789")
            True
        """
        if not self._is_available():
            logger.warning("PromotionService no disponible. register_user omitido.")
            return False
        user_id = str(user_id)
        timestamp_actual = str(time.time())

        # Verificar si ya existe con estado 'pendiente'
        try:
            response = self._table.scan(
                FilterExpression=(
                    Attr('userId').eq(user_id) &
                    Attr('estado').eq(ESTADO_PENDIENTE)
                )
            )
            if response.get('Items'):
                logger.info(
                    f"Usuario {user_id} ya existe con estado '{ESTADO_PENDIENTE}'. "
                    f"No se inserta duplicado."
                )
                return False
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            if error_code in ("InvalidSignatureException", "UnrecognizedClientException",
                              "AccessDeniedException", "ExpiredTokenException"):
                self._mark_unavailable()
            logger.error(f"Error al verificar usuario {user_id}: {e}")
            return False

        # Insertar nuevo registro
        try:
            self._table.put_item(
                Item={
                    'userId': user_id,
                    'timestamp': timestamp_actual,
                    'estado': ESTADO_PENDIENTE,
                }
            )
            logger.info(
                f"Usuario {user_id} registrado en {self._table_name} "
                f"con estado '{ESTADO_PENDIENTE}'."
            )
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            logger.error(
                f"Error al insertar usuario {user_id} en DynamoDB: "
                f"[{error_code}] {e}"
            )
            return False

    # ------------------------------------------------------------------
    # Búsqueda de usuarios
    # ------------------------------------------------------------------

    def get_user_status(self, user_id: str) -> str | None:
        """
        Obtiene el estado actual de un usuario en la tabla DynamoDB.

        Args:
            user_id: ID de Telegram del usuario.

        Returns:
            Estado del usuario ('pendiente', 'Promo_15_min', 'Promo_24_horas',
            'FINALIZADO') o None si no se encuentra.

        Example:
            >>> estado = promo_service.get_user_status("123456789")
            >>> print(estado)
            'Promo_15_min'
        """
        user_id = str(user_id)
        try:
            response = self._table.get_item(
                Key={'userId': user_id}
            )
            item = response.get('Item')
            if item:
                estado = item.get('estado')
                logger.debug(f"Estado del usuario {user_id}: {estado}")
                return estado
            else:
                logger.debug(f"Usuario {user_id} no encontrado en DynamoDB.")
                return None
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            if error_code in ("InvalidSignatureException", "UnrecognizedClientException",
                              "AccessDeniedException", "ExpiredTokenException"):
                self._mark_unavailable()
            logger.error(f"Error al obtener estado de {user_id}: {e}")
            return None

    # ------------------------------------------------------------------
    # Pipeline de promociones (método principal)
    # ------------------------------------------------------------------

    def process_promotion_pipeline(self) -> list[dict[str, Any]]:
        """
        Ejecuta una iteración del pipeline de promociones.

        Escanea la tabla DynamoDB buscando usuarios con estado != 'FINALIZADO',
        evalúa sus timestamps y envía la promoción correspondiente según
        la configuración de PROMOS_CONFIG.

        Flujo para cada usuario:
        1. Determinar qué promo le toca según su estado actual.
        2. Si ya recibió la última promo → marcar como FINALIZADO.
        3. Si le toca la siguiente promo y ya pasó el tiempo requerido →
           enviar promo y actualizar estado.
        4. Si no ha pasado el tiempo → saltar (esperar próxima iteración).

        Returns:
            Lista de diccionarios con los resultados del procesamiento:
            - user_id: ID del usuario procesado.
            - action: Acción tomada ('promo_sent', 'finalized', 'skipped').
            - promo_name: Nombre de la promo enviada (si aplica).
            - error: Mensaje de error (si aplica).

        Example:
            >>> results = promo_service.process_promotion_pipeline()
            >>> for r in results:
            ...     print(f"User {r['user_id']}: {r['action']}")
        """
        logger.info("Iniciando pipeline de promociones...")
        results = []

        # Escanear todos los usuarios con estado != FINALIZADO
        try:
            items = self._scan_users_not_finalized()
        except Exception as e:
            logger.error(f"Error al escanear DynamoDB: {e}")
            return results

        logger.info(f"Usuarios pendientes encontrados: {len(items)}")

        for item in items:
            user_id = item.get('userId')
            estado_actual = item.get('estado', '')
            timestamp_str = item.get('timestamp', '0')
            timestamp = int(float(timestamp_str))
            tiempo_transcurrido = int(time.time()) - timestamp

            logger.debug(
                f"[{user_id}] Estado actual: {estado_actual}, "
                f"Tiempo transcurrido: {tiempo_transcurrido}s"
            )

            # Determinar el orden actual en el pipeline
            orden_actual = self._get_orden_actual(estado_actual)

            # Si ya recibió la última promo → FINALIZADO
            if orden_actual == PROMOS_CONFIG[-1]['orden']:
                self._update_estado(user_id, item.get('timestamp'), ESTADO_FINAL)
                results.append({
                    'user_id': user_id,
                    'action': 'finalized',
                    'promo_name': None,
                })
                logger.info(f"[{user_id}] Última promo entregada → FINALIZADO.")
                continue

            # Buscar la próxima promoción por orden
            siguiente_promo = self._get_siguiente_promo(orden_actual)
            if siguiente_promo is None:
                logger.warning(
                    f"[{user_id}] No se encontró siguiente promo para "
                    f"orden={orden_actual}. Saltando."
                )
                continue

            # Verificar si ya pasó el tiempo requerido
            segundos_despues = siguiente_promo.get('segundos_despues', 0)
            if tiempo_transcurrido >= segundos_despues:
                # Enviar promo
                try:
                    self._enviar_promocion(user_id, siguiente_promo)
                    self._update_estado(
                        user_id,
                        item.get('timestamp'),
                        siguiente_promo['nombre'],
                    )
                    results.append({
                        'user_id': user_id,
                        'action': 'promo_sent',
                        'promo_name': siguiente_promo['nombre'],
                    })
                    logger.info(
                        f"[{user_id}] Promo enviada: {siguiente_promo['nombre']}"
                    )
                except Exception as e:
                    logger.error(
                        f"[{user_id}] Error al enviar promo: {e}"
                    )
                    results.append({
                        'user_id': user_id,
                        'action': 'error',
                        'promo_name': siguiente_promo['nombre'],
                        'error': str(e),
                    })
            else:
                logger.debug(
                    f"[{user_id}] Aún no toca promo '{siguiente_promo['nombre']}'. "
                    f"Faltan {segundos_despues - tiempo_transcurrido}s."
                )

        logger.info(
            f"Pipeline de promociones completado. "
            f"Procesados: {len(items)}, Acciones: {len(results)}"
        )
        return results

    # ------------------------------------------------------------------
    # Métodos auxiliares internos
    # ------------------------------------------------------------------

    def _scan_users_not_finalized(self) -> list[dict[str, Any]]:
        """
        Escanea la tabla DynamoDB y retorna todos los items con
        estado != 'FINALIZADO'.

        Maneja paginación automáticamente usando ExclusiveStartKey.

        Returns:
            Lista de items (diccionarios) de DynamoDB.
        """
        if not self._is_available():
            logger.warning("PromotionService no disponible. _scan_users_not_finalized omitido.")
            return []

        scan_kwargs = {
            'FilterExpression': Attr('estado').ne(ESTADO_FINAL),
        }

        items = []
        start_key = None

        try:
            while True:
                if start_key:
                    scan_kwargs['ExclusiveStartKey'] = start_key

                response = self._table.scan(**scan_kwargs)
                items.extend(response.get('Items', []))
                start_key = response.get('LastEvaluatedKey')

                if not start_key:
                    break
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            if error_code in ("InvalidSignatureException", "UnrecognizedClientException",
                              "AccessDeniedException", "ExpiredTokenException"):
                self._mark_unavailable()
            logger.error(f"Error al escanear usuarios no finalizados: {e}")
            return []

        return items

    def _get_orden_actual(self, estado_actual: str) -> int:
        """
        Determina el orden en el pipeline según el estado actual del usuario.

        Args:
            estado_actual: Estado del usuario en DynamoDB.

        Returns:
            Número de orden (0 si está pendiente, 1 si recibió Promo_15_min, etc.).
        """
        if estado_actual == ESTADO_PENDIENTE:
            return 0
        for promo in PROMOS_CONFIG:
            if promo['nombre'] == estado_actual:
                return promo['orden']
        return 0  # Por defecto, tratar como pendiente

    def _get_siguiente_promo(self, orden_actual: int) -> dict | None:
        """
        Obtiene la siguiente promoción en el pipeline según el orden actual.

        Args:
            orden_actual: Orden de la promo actual (0 = pendiente).

        Returns:
            Diccionario con la configuración de la siguiente promo, o None.
        """
        for promo in PROMOS_CONFIG:
            if promo['orden'] == orden_actual + 1:
                return promo
        return None

    def _enviar_promocion(self, user_id: str, promo: dict) -> None:
        """
        Envía una promoción (video + mensaje) a un usuario por Telegram.

        Args:
            user_id: ID de Telegram del usuario (destino).
            promo: Diccionario con la configuración de la promo a enviar.

        Raises:
            Exception: Si falla el envío del mensaje.
        """
        video_filename = promo.get('video', '')
        mensaje = promo.get('mensaje', '')
        video_path = f"./videos_promocionales/{video_filename}"

        logger.info(
            f"Enviando promo '{promo['nombre']}' a usuario {user_id}: "
            f"video={video_filename}"
        )

        try:
            # Obtener el teclado de Betsafe
            from utils.keyboards import betsafe_video_keyboard
            reply_markup = betsafe_video_keyboard()

            # Enviar video con mensaje y botón
            self.telegram_api.send_video(
                chat_id=int(user_id),
                video=video_path,
                caption=mensaje,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
            logger.info(f"Promo '{promo['nombre']}' enviada exitosamente a {user_id}")
        except FileNotFoundError:
            logger.error(f"Archivo de video no encontrado: {video_path}")
            raise
        except Exception as e:
            logger.error(f"Error al enviar video a {user_id}: {e}")
            raise

    def _update_estado(
        self,
        user_id: str,
        timestamp: str,
        nuevo_estado: str,
    ) -> bool:
        """
        Actualiza el estado de un usuario en la tabla DynamoDB.

        Args:
            user_id: ID del usuario.
            timestamp: Timestamp original del registro (parte de la key).
            nuevo_estado: Nuevo estado a asignar.

        Returns:
            True si se actualizó correctamente, False si hubo error.
        """
        try:
            self._table.update_item(
                Key={
                    'userId': user_id,
                    'timestamp': timestamp,
                },
                UpdateExpression="SET estado = :nuevo_estado",
                ExpressionAttributeValues={
                    ':nuevo_estado': nuevo_estado,
                },
            )
            logger.debug(
                f"Estado de usuario {user_id} actualizado a '{nuevo_estado}'."
            )
            return True
        except ClientError as e:
            logger.error(
                f"Error al actualizar estado de {user_id} "
                f"a '{nuevo_estado}': {e}"
            )
            return False

    def finalize_user(self, user_id: str) -> bool:
        """
        Marca manualmente a un usuario como FINALIZADO en el pipeline.

        Args:
            user_id: ID de Telegram del usuario.

        Returns:
            True si se actualizó correctamente.
        """
        user_id = str(user_id)
        try:
            response = self._table.get_item(Key={'userId': user_id})
            item = response.get('Item')
            if item:
                return self._update_estado(
                    user_id, item.get('timestamp'), ESTADO_FINAL
                )
            else:
                logger.warning(
                    f"No se puede finalizar: usuario {user_id} no encontrado."
                )
                return False
        except ClientError as e:
            logger.error(f"Error al finalizar usuario {user_id}: {e}")
            return False

    # ------------------------------------------------------------------
    # Métodos de utilidad
    # ------------------------------------------------------------------

    def get_pipeline_stats(self) -> dict[str, int]:
        """
        Obtiene estadísticas del pipeline de promociones.

        Returns:
            Diccionario con conteos por estado:
            - pendiente: int
            - Promo_15_min: int
            - Promo_24_horas: int
            - FINALIZADO: int
            - total: int
        """
        stats = {
            'pendiente': 0,
            'Promo_15_min': 0,
            'Promo_24_horas': 0,
            'FINALIZADO': 0,
            'total': 0,
        }

        try:
            # Escanear todos los usuarios
            response = self._table.scan()
            items = response.get('Items', [])

            # Contar por estado
            for item in items:
                estado = item.get('estado', 'desconocido')
                if estado in stats:
                    stats[estado] += 1
                stats['total'] += 1

            # Manejar paginación
            while 'LastEvaluatedKey' in response:
                response = self._table.scan(
                    ExclusiveStartKey=response['LastEvaluatedKey']
                )
                items = response.get('Items', [])
                for item in items:
                    estado = item.get('estado', 'desconocido')
                    if estado in stats:
                        stats[estado] += 1
                    stats['total'] += 1

        except ClientError as e:
            logger.error(f"Error al obtener estadísticas: {e}")

        return stats

    def is_registered(self, user_id: str) -> bool:
        """
        Verifica si un usuario ya está registrado en la tabla DynamoDB.

        Args:
            user_id: ID de Telegram del usuario.

        Returns:
            True si el usuario está registrado (cualquier estado).
        """
        return self.get_user_status(user_id) is not None
