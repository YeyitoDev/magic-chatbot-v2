"""
Dynamic Pricing Service - Magic Chatbot v2
===========================================
Servicio centralizado para consulta de precios desde la base de datos
con caché en JSON para evitar consultas repetitivas a la BD.

Principios:
- Single Source of Truth: la tabla service_prices es la única fuente.
- Caché inteligente: carga inicial desde BD → JSON, se refresca cada 24h.
- Generación dinámica: mensajes de precios y teclados se arman desde los datos.
- Fail-safe: si la BD falla, usa el caché JSON.

Flujo:
1. Al iniciar → carga precios desde BD → guarda en pricing_cache.json
2. En cada consulta → sirve desde RAM (caché en memoria)
3. Cada 24h → refresca desde BD
4. Si BD falla → usa caché JSON como fallback

Para agregar un nuevo plan solo se necesita:
    INSERT INTO service_prices (service_id, price, discount, duration_months)
    VALUES (2, 350, 20, 6);

Uso:
    from services.pricing_service import PricingService

    pricing = PricingService(service_repo)
    plan = pricing.match_price(amount=90)  # → ServicePrice(duration_months=1)
    mensaje = pricing.generate_pricing_message(service_id=2)
    teclado = pricing.generate_confirmation_keyboard(user_id=123, amount=100)
"""

import json
import logging
import os
import threading
from datetime import datetime
from typing import Any

from models.service import ServicePrice

logger = logging.getLogger(__name__)

# Ruta absoluta anclada a la raíz del proyecto (v2_refactor/), independiente
# del directorio de trabajo desde el que se ejecute el bot.
CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "pricing_cache.json",
)
CACHE_TTL_SECONDS = 86400  # 24 horas (1 día)


class PricingService:
    """
    Servicio de precios dinámico con caché en dos niveles (RAM + JSON).

    Attributes:
        _service_repo: Repositorio de servicios para consultar la BD.
        _cache: Lista de ServicePrice en memoria (nivel 1).
        _cache_updated_at: Timestamp de última actualización.
        _lock: Thread lock para thread-safety.
    """

    def __init__(self, service_repo) -> None:
        self._service_repo = service_repo
        self._cache: list[ServicePrice] = []
        self._cache_updated_at: datetime | None = None
        self._lock = threading.Lock()

        # Cargar caché al iniciar
        self._load_cache()
        logger.info(f"PricingService inicializado: {len(self._cache)} precios cacheados.")

    # ------------------------------------------------------------------
    # Carga de caché (RAM + JSON fallback)
    # ------------------------------------------------------------------

    def _load_cache(self) -> None:
        """Carga precios desde BD, con fallback a JSON si la BD no responde."""
        try:
            prices = self._fetch_from_db()
            if prices:
                self._save_to_json(prices)
                with self._lock:
                    self._cache = prices
                    self._cache_updated_at = datetime.now()
                logger.debug(f"Caché actualizado desde BD: {len(prices)} precios.")
                return
        except Exception as e:
            logger.warning(f"No se pudo cargar precios desde BD: {e}")

        # Fallback: cargar desde JSON
        prices = self._load_from_json()
        if prices:
            with self._lock:
                self._cache = prices
                self._cache_updated_at = datetime.now()
            logger.warning(f"Caché cargado desde JSON (fallback): {len(prices)} precios.")
        else:
            logger.error("No se encontraron precios en BD ni en caché JSON.")

    def _fetch_from_db(self) -> list[ServicePrice]:
        """Obtiene todos los ServicePrice desde la BD."""
        return self._service_repo._session.query(ServicePrice).all()

    def _save_to_json(self, prices: list[ServicePrice]) -> None:
        """Guarda los precios en el archivo JSON de caché."""
        data = {
            "updated_at": datetime.now().isoformat(),
            "prices": [
                {
                    "service_price_id": p.service_price_id,
                    "service_id": p.service_id,
                    "price": p.price,
                    "discount": p.discount,
                    "duration_months": p.duration_months,
                }
                for p in prices
            ],
        }
        try:
            with open(CACHE_FILE, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"No se pudo guardar caché JSON: {e}")

    def _load_from_json(self) -> list[ServicePrice]:
        """Carga precios desde el archivo JSON de caché."""
        if not os.path.exists(CACHE_FILE):
            return []
        try:
            with open(CACHE_FILE) as f:
                data = json.load(f)
            return [
                ServicePrice(
                    service_price_id=p["service_price_id"],
                    service_id=p["service_id"],
                    price=p["price"],
                    discount=p["discount"],
                    duration_months=p["duration_months"],
                )
                for p in data.get("prices", [])
            ]
        except Exception as e:
            logger.warning(f"No se pudo cargar caché JSON: {e}")
            return []

    # ------------------------------------------------------------------
    # Refresh automático del caché
    # ------------------------------------------------------------------

    def _should_refresh(self) -> bool:
        """Verifica si el caché necesita refrescarse (TTL expirado)."""
        if self._cache_updated_at is None:
            return True
        elapsed = (datetime.now() - self._cache_updated_at).total_seconds()
        return elapsed >= CACHE_TTL_SECONDS

    def refresh_cache(self) -> None:
        """Fuerza un refresco del caché desde BD."""
        self._load_cache()

    def get_cache_age_seconds(self) -> float:
        """Retorna la antigüedad del caché en segundos."""
        if self._cache_updated_at is None:
            return float("inf")
        return (datetime.now() - self._cache_updated_at).total_seconds()

    # ------------------------------------------------------------------
    # Consultas de precios
    # ------------------------------------------------------------------

    def get_all_prices(self) -> list[ServicePrice]:
        """Obtiene todos los precios (con auto-refresh si TTL expiró)."""
        if self._should_refresh():
            self._load_cache()
        with self._lock:
            return list(self._cache)

    @staticmethod
    def _payment_accounts_html() -> str:
        """Bloque de datos de pago, desde variables de entorno PAYMENT_*."""
        from config.settings import settings

        fields = [
            ("Titular", settings.PAYMENT_HOLDER_NAME),
            ("Yape/Plin", settings.PAYMENT_YAPE_PLIN),
            ("BCP", settings.PAYMENT_BCP_ACCOUNT),
            ("SCOTIA", settings.PAYMENT_SCOTIABANK_ACCOUNT),
        ]
        lines = [f"• <b>{label}:</b> {value}" for label, value in fields if value]
        if not lines:
            return "<b>📲 DATOS DE PAGO:</b> solicítalos a @magic_peru."
        return "<b>📲 DATOS DE PAGO:</b>\n" + "\n".join(lines)

    def get_prices_for_service(self, service_id: int) -> list[ServicePrice]:
        """Obtiene los precios de un servicio específico."""
        all_prices = self.get_all_prices()
        return [p for p in all_prices if p.service_id == service_id]

    def match_price(self, amount: float) -> ServicePrice | None:
        """
        Encuentra el plan que corresponde a un monto pagado usando rangos.

        Lógica de rangos:
        - Cada precio define un rango [price - discount, price]
        - Si el monto cae dentro de este rango, matchea con ese plan
        - Esto permite que usuarios paguen precios con o sin descuento

        Ejemplo VIP 1 mes:
        - Precio base: 125, Descuento: 25
        - Rango: [100, 125]
        - Si usuario paga 100, 110, 120, o 125 → matchea con VIP 1 mes

        Args:
            amount: Monto pagado por el usuario.

        Returns:
            ServicePrice que coincide, o None si no se encuentra.
        """
        all_prices = self.get_all_prices()

        # Búsqueda por rango: amount debe estar entre [price - discount, price]
        for p in all_prices:
            min_price = p.price - p.discount
            max_price = p.price
            if min_price <= amount <= max_price:
                return p

        return None

    def match_price_exact(self, amount: float) -> ServicePrice | None:
        """
        Encuentra el plan cuyo precio coincide EXACTAMENTE con el monto.

        A diferencia de `match_price`, no aplica tolerancia: el monto debe
        ser igual al precio o al precio efectivo (price - discount). Se usa
        para validar que un pago corresponde a un precio definido.

        Args:
            amount: Monto pagado por el usuario.

        Returns:
            ServicePrice que coincide exactamente, o None.
        """
        for p in self.get_all_prices():
            if p.price == amount or (p.price - p.discount) == amount:
                return p
        return None

    def get_service_type(self, amount: float) -> str | None:
        """
        Determina el tipo de servicio según el monto:
        - > 50 → grupo_vip
        - <= 50 → stake

        Args:
            amount: Monto pagado.

        Returns:
            "stake" o "grupo_vip", o None si no es válido.
        """
        plan = self.match_price(amount)
        if plan is None:
            return None
        # service_id 1 = Stake, 2 = Grupo VIP
        return "grupo_vip" if plan.service_id == 2 else "stake"

    # ------------------------------------------------------------------
    # Generación dinámica de mensajes y teclados
    # ------------------------------------------------------------------

    def generate_pricing_message(self, service_id: int) -> str:
        """
        Genera el mensaje de precios dinámicamente desde los datos cacheados.

        Args:
            service_id: ID del servicio (1=Stake, 2=Grupo VIP).

        Returns:
            Mensaje formateado en HTML con precios y cuentas bancarias.
        """
        prices = sorted(
            self.get_prices_for_service(service_id),
            key=lambda p: p.price,
        )

        if not prices:
            return "<b>Precios no disponibles.</b> Contacta a @magic_peru."

        cuentas = self._payment_accounts_html()

        if service_id == 1:  # Stake
            stake_price = int(prices[0].price)
            return (
                "<b>✅ STAKE MÁXIMA SEGURIDAD ✅</b>\n\n"
                "• El stake de máxima seguridad consta de una fija con una probabilidad "
                "de victoria mayor al 96% en el partido indicado.\n\n"
                "• Nosotros estamos entrando con S/. 20,000 a esta jugada "
                "<b>GARANTIZADA DE VICTORIA</b>.\n\n"
                f"<b>💰 EL COSTO DEL STAKE ES DE S/. {stake_price} 💰</b>\n\n"
                f"{cuentas}\n\n"
                "<b>🔥 Realiza tu depósito y envíalo a este chat 🔥</b>"
            )
        else:  # Grupo VIP
            lines = [
                "<b>📈 GRUPO VIP ESTADÍSTICO 📈</b>\n\n"
                "• El único VIP del mundo con un sistema estadístico que nos permite "
                "obtener las jugadas con la mayor probabilidad de acierto.\n\n"
                "• Recibe de 3 a 4 jugadas diarias.\n\n"
                "<b>🌟 BENEFICIOS:</b>\n"
                "• ✅ Asesores personalizados 24/7\n"
                "• ✅ Jugadas revisadas por algoritmos y expertos\n"
                "• ✅ Manejamos Bank\n\n"
                "<b>💰 COSTO MEMBRESÍAS VIP:</b>"
            ]

            for p in prices:
                months = p.duration_months
                price = int(p.price)
                lines.append(f"• ⚪ S/. {price} - {months} {'MES' if months == 1 else 'MESES'}")

            lines.append("")
            lines.append(cuentas)
            lines.append("")
            lines.append(
                "<b>🔥 Realiza tu depósito, envíamelo a este chat y listo estás dentro 🔥</b>"
            )

            return "\n".join(lines)

    def generate_confirmation_keyboard(
        self, user_id: int, amount: float = 0, source: str = "telegram"
    ) -> Any:
        """
        Genera el teclado de confirmación manual dinámicamente.

        Args:
            user_id: ID del usuario.
            amount: Monto detectado (opcional).
            source: Canal de origen.

        Returns:
            InlineKeyboardMarkup con botones generados desde los precios.
        """
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        keyboard = []

        # Precios de Stake (service_id=1)
        stake_prices = self.get_prices_for_service(1)
        for p in stake_prices:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"🎯 STAKE (S/ {int(p.price)})",
                        callback_data=f"buttom_validar_monto:select:{user_id}:{int(p.price)}",
                    )
                ]
            )

        # Precios de VIP (service_id=2)
        vip_prices = sorted(self.get_prices_for_service(2), key=lambda p: p.duration_months)
        for p in vip_prices:
            months = p.duration_months
            vip_price = int(p.price)
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"💎 VIP {months} {'Mes' if months == 1 else 'Meses'} (S/ {vip_price})",
                        callback_data=f"buttom_validar_monto:select:{user_id}:{vip_price}",
                    )
                ]
            )

        return InlineKeyboardMarkup(keyboard)

    def get_vip_threshold(self) -> float:
        """Retorna el umbral que separa Stake de VIP (precio máximo de Stake)."""
        stake_prices = self.get_prices_for_service(1)
        if stake_prices:
            return max(p.price for p in stake_prices)
        return 50.0  # default


# Singleton global
_pricing_service: PricingService | None = None


def get_pricing_service(service_repo=None) -> PricingService:
    """Obtiene la instancia singleton de PricingService."""
    global _pricing_service
    if _pricing_service is None and service_repo is not None:
        _pricing_service = PricingService(service_repo)
    return _pricing_service
