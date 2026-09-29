"""
Purchase Repository - Magic Chatbot v2
=======================================
Repositorio para operaciones de acceso a datos de la entidad Purchase.

Operaciones:
- Creación de compras.
- Búsqueda de compras recientes (anti-duplicados, ventana 24h).
- Última compra por usuario para un servicio específico (subquery).

Uso:
    repo = PurchaseRepository(session)
    purchase = repo.create_purchase(
        user_telegram_id=12345,
        service_id=2,
        price=150.0,
        from_channel="telegram",
    )
"""

from datetime import timedelta

from sqlalchemy import desc, func

from models.purchase import Purchase
from repositories.base import BaseRepository
from utils.datetime_utils import get_lima_time, now_lima_naive

# Tolerancia al comparar montos: `price` es FLOAT en MySQL (precisión simple).
PRICE_TOLERANCE = 0.005


class PurchaseRepository(BaseRepository):
    """
    Repositorio con operaciones específicas para la tabla `purchases`.

    Encapsula toda la lógica de consulta y creación de registros de compra.
    """

    # ------------------------------------------------------------------
    # Creación
    # ------------------------------------------------------------------

    def create_purchase(
        self,
        user_telegram_id: int,
        service_id: int,
        price: float,
        from_channel: str,
        purchase_date=None,
        commit: bool = True,
        payment_ref: str | None = None,
    ) -> Purchase:
        """
        Crea y persiste un nuevo registro de compra.

        Args:
            user_telegram_id: ID de Telegram del comprador.
            service_id: ID del servicio adquirido.
            price: Precio pagado por el servicio en el momento de la compra.
            from_channel: Canal de origen (ej: "telegram", "whatsapp", "wsp").
            purchase_date: Fecha de compra. Si es None, se usa la hora actual de Lima.
            commit: Si True (default) confirma de inmediato. Si False, solo hace
                flush (para participar en una transacción mayor controlada por
                el caller, p.ej. compra + suscripción atómicas).
            payment_ref: Clave de idempotencia del comprobante (UNIQUE).

        Returns:
            La instancia Purchase recién creada y persistida.
        """
        purchase = Purchase(
            user_telegram_id=user_telegram_id,
            service_id=service_id,
            price=price,
            from_channel=from_channel,
            purchase_date=purchase_date or get_lima_time(),
            payment_ref=payment_ref,
        )
        self.add(purchase)
        if commit:
            self.commit()
        else:
            self.flush()
        return purchase

    # ------------------------------------------------------------------
    # Búsqueda de duplicados
    # ------------------------------------------------------------------

    def get_by_payment_ref(self, payment_ref: str) -> Purchase | None:
        """Compra registrada con esa clave de comprobante, o None."""
        return (
            self._session.query(Purchase)
            .filter(Purchase.payment_ref == payment_ref)
            .first()
        )

    def get_recent_purchases(
        self,
        user_id: int,
        amount: float,
        hours: int = 24,
    ) -> list[Purchase]:
        """
        Busca compras recientes de un usuario que coincidan con un monto.

        Estrategia anti-duplicados: si un usuario envía la misma captura
        de pago dos veces en menos de `hours` horas, se detecta como
        duplicado y se evita reprocesar.

        Args:
            user_id: ID de Telegram del usuario.
            amount: Monto exacto pagado a buscar.
            hours: Ventana de tiempo hacia atrás en horas (default 24).

        Returns:
            Lista de compras que coinciden (vacía si no hay duplicados).
        """
        cutoff = now_lima_naive() - timedelta(hours=hours)
        return (
            self._session.query(Purchase)
            .filter(
                Purchase.user_telegram_id == user_id,
                Purchase.price.between(amount - PRICE_TOLERANCE, amount + PRICE_TOLERANCE),
                Purchase.purchase_date >= cutoff,
            )
            .order_by(desc(Purchase.purchase_date))
            .all()
        )

    def get_recent_purchases_for_service(
        self,
        user_id: int,
        service_id: int,
        hours: int = 24,
    ) -> list[Purchase]:
        """
        Busca compras recientes de un usuario para un servicio específico.

        A diferencia de `get_recent_purchases` (que filtra por monto exacto),
        esta consulta filtra por `service_id`, independientemente del monto.
        Se usa para aplicar el límite de 1 compra de Stake por día.

        Args:
            user_id: ID de Telegram del usuario.
            service_id: ID del servicio a buscar (1=Stake, 2=Grupo VIP).
            hours: Ventana de tiempo hacia atrás en horas (default 24).

        Returns:
            Lista de compras del servicio en la ventana (vacía si no hay).
        """
        cutoff = now_lima_naive() - timedelta(hours=hours)
        return (
            self._session.query(Purchase)
            .filter(
                Purchase.user_telegram_id == user_id,
                Purchase.service_id == service_id,
                Purchase.purchase_date >= cutoff,
            )
            .order_by(desc(Purchase.purchase_date))
            .all()
        )

    def has_recent_purchase(
        self,
        user_id: int,
        amount: float,
        hours: int = 24,
    ) -> bool:
        """
        Verifica si existe una compra reciente duplicada.

        Versión booleana de get_recent_purchases para uso en condicionales.

        Args:
            user_id: ID de Telegram del usuario.
            amount: Monto exacto pagado.
            hours: Ventana de tiempo en horas (default 24).

        Returns:
            True si ya existe una compra con el mismo monto en la ventana.
        """
        purchases = self.get_recent_purchases(user_id, amount, hours)
        return len(purchases) > 0

    # ------------------------------------------------------------------
    # Consultas agregadas
    # ------------------------------------------------------------------

    def get_all_last_purchases_for_service(
        self, service_id: int
    ) -> list[Purchase]:
        """
        Obtiene la última compra de cada usuario para un servicio dado.

        Útil para el job de limpieza de suscripciones (getMembersTelethon)
        que necesita saber la última compra de cada miembro del grupo VIP.

        Usa una subquery con func.max para obtener el máximo purchase_id
        (equivalente a la última compra) por usuario.

        Args:
            service_id: ID del servicio a consultar.

        Returns:
            Lista de las compras más recientes, una por usuario.
        """
        # Subquery: último purchase_id por usuario para el servicio dado
        subquery = (
            self._session.query(
                Purchase.user_telegram_id,
                func.max(Purchase.purchase_id).label("max_id"),
            )
            .filter(Purchase.service_id == service_id)
            .group_by(Purchase.user_telegram_id)
            .subquery()
        )

        return (
            self._session.query(Purchase)
            .join(
                subquery,
                Purchase.purchase_id == subquery.c.max_id,
            )
            .order_by(desc(Purchase.purchase_date))
            .all()
        )

    # ------------------------------------------------------------------
    # Consultas por usuario
    # ------------------------------------------------------------------

    def get_by_user_id(self, user_telegram_id: int) -> list[Purchase]:
        """
        Obtiene todas las compras de un usuario, ordenadas por fecha descendente.

        Args:
            user_telegram_id: ID de Telegram del usuario.

        Returns:
            Lista de todas las compras del usuario (más recientes primero).
        """
        return (
            self._session.query(Purchase)
            .filter_by(user_telegram_id=user_telegram_id)
            .order_by(desc(Purchase.purchase_date))
            .all()
        )

    def get_last_purchase_by_user(
        self, user_telegram_id: int
    ) -> Purchase | None:
        """
        Obtiene la compra más reciente de un usuario.

        Args:
            user_telegram_id: ID de Telegram del usuario.

        Returns:
            La última compra del usuario, o None si no tiene compras.
        """
        return (
            self._session.query(Purchase)
            .filter_by(user_telegram_id=user_telegram_id)
            .order_by(desc(Purchase.purchase_date))
            .first()
        )

    def get_last_active_purchase_by_user(
        self, user_telegram_id: int
    ) -> Purchase | None:
        """
        Obtiene la compra más reciente con status='active' de un usuario.

        Args:
            user_telegram_id: ID de Telegram del usuario.

        Returns:
            La última compra activa del usuario, o None si no tiene.
        """
        return (
            self._session.query(Purchase)
            .filter(
                Purchase.user_telegram_id == user_telegram_id,
                Purchase.status == "active",
            )
            .order_by(desc(Purchase.purchase_date))
            .first()
        )

    def mark_as_fraud(
        self, purchase_id: int, notes: str = "Marcada como estafa"
    ) -> bool:
        """
        Marca una compra como fraudulenta (status='fraud') y agrega notas.

        No elimina la compra: solo cambia su estado para que no sea
        contabilizada en reportes ni considerada válida.

        Args:
            purchase_id: ID de la compra a marcar como fraude.
            notes: Motivo o nota explicativa.

        Returns:
            True si se actualizó correctamente, False si no se encontró.
        """
        purchase = (
            self._session.query(Purchase)
            .filter_by(purchase_id=purchase_id)
            .first()
        )
        if purchase is None:
            return False
        purchase.status = "fraud"
        purchase.notes = notes
        self.commit()
        return True
