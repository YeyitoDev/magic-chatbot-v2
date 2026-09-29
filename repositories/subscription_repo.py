"""
Subscription Repository - Magic Chatbot v2
===========================================
Repositorio para operaciones de acceso a datos de la entidad Subscription.

Operaciones:
- Búsqueda de suscripciones activas, por usuario, expiradas y próximas a vencer.
- Creación y actualización de suscripciones.
- Eliminación de suscripciones.
- Extensión de fecha de fin basada en compras.

Uso:
    repo = SubscriptionRepository(session)
    active_subs = repo.get_active_subs()
    expired = repo.get_expired_subs()
"""

from datetime import timedelta

from sqlalchemy import and_

from models.purchase import Purchase
from models.subscription import Subscription
from repositories.base import BaseRepository
from utils.datetime_utils import today_lima


class SubscriptionRepository(BaseRepository):
    """
    Repositorio con operaciones específicas para la tabla `subscriptions`.

    Maneja el ciclo de vida completo de las suscripciones: creación,
    extensión, consulta de vigencia y eliminación de suscripciones vencidas.
    """

    # ------------------------------------------------------------------
    # Consultas de suscripciones activas
    # ------------------------------------------------------------------

    def get_active_subs(self) -> list[Subscription]:
        """
        Obtiene todas las suscripciones actualmente activas.

        Una suscripción está activa si is_active == True.

        Returns:
            Lista de suscripciones vigentes.
        """
        return (
            self._session.query(Subscription)
            .filter(Subscription.is_active)
            .all()
        )

    def get_active_sub(
        self, user_telegram_id: int
    ) -> list[Subscription]:
        """
        Obtiene las suscripciones activas de un usuario específico.

        Args:
            user_telegram_id: ID de Telegram del usuario.

        Returns:
            Lista de suscripciones activas del usuario.
        """
        return (
            self._session.query(Subscription)
            .filter(
                and_(
                    Subscription.user_telegram_id == user_telegram_id,
                    Subscription.is_active,
                )
            )
            .all()
        )

    def get_sub_by_user_and_service(
        self, user_telegram_id: int, service_id: int
    ) -> Subscription | None:
        """
        Busca la suscripción activa de un usuario a un servicio específico.

        Retorna la suscripción más reciente (mayor end_date) si hay varias.

        Args:
            user_telegram_id: ID de Telegram del usuario.
            service_id: ID del servicio.

        Returns:
            La suscripción encontrada o None.
        """
        return (
            self._session.query(Subscription)
            .filter(
                and_(
                    Subscription.user_telegram_id == user_telegram_id,
                    Subscription.service_id == service_id,
                    Subscription.is_active,
                )
            )
            .order_by(Subscription.end_date.desc())
            .first()
        )

    def get_for_renewal(
        self, user_telegram_id: int, service_id: int
    ) -> Subscription | None:
        """
        Fila a renovar para (usuario, servicio), activa o no, bloqueada.

        Incluye filas desactivadas (limpieza o fraude) para reutilizarlas en
        vez de crear duplicados. ``FOR UPDATE`` serializa dos validaciones
        simultáneas del mismo usuario y ``populate_existing`` evita trabajar
        con una copia vieja cacheada en la sesión compartida del bot.
        """
        return (
            self._session.query(Subscription)
            .filter(
                Subscription.user_telegram_id == user_telegram_id,
                Subscription.service_id == service_id,
            )
            .order_by(Subscription.is_active.desc(), Subscription.end_date.desc())
            .with_for_update()
            .populate_existing()
            .first()
        )

    # ------------------------------------------------------------------
    # Consultas de suscripciones vencidas / próximas a vencer
    # ------------------------------------------------------------------

    def get_expired_subs(self) -> list[Subscription]:
        """
        Obtiene suscripciones vencidas (end_date < hoy).

        Estas son candidatas para el proceso de limpieza (kick del grupo).

        Returns:
            Lista de suscripciones expiradas.
        """
        return (
            self._session.query(Subscription)
            .filter(Subscription.is_active, Subscription.end_date < today_lima())
            .all()
        )

    def get_expiring_soon(self, days: int = 3) -> list[Subscription]:
        """
        Obtiene suscripciones que vencerán en los próximos N días.

        Útil para enviar avisos de renovación antes del vencimiento.

        Args:
            days: Días de anticipación (default 3).

        Returns:
            Lista de suscripciones próximas a vencer.
        """
        today = today_lima()
        deadline = today + timedelta(days=days)
        return (
            self._session.query(Subscription)
            .filter(
                and_(
                    Subscription.is_active,
                    Subscription.end_date >= today,
                    Subscription.end_date <= deadline,
                )
            )
            .all()
        )

    # ------------------------------------------------------------------
    # Creación y actualización
    # ------------------------------------------------------------------

    def extend_subscription(
        self,
        subscription: Subscription,
        additional_days: int,
        commit: bool = True,
    ) -> Subscription:
        """
        Extiende la fecha de fin de una suscripción por N días.

        Args:
            subscription: Instancia de Subscription a extender.
            additional_days: Número de días a agregar a end_date.
            commit: Si True (default) confirma de inmediato. Si False, deja la
                operación pendiente para una transacción mayor del caller.

        Returns:
            La misma instancia ya actualizada y persistida.
        """
        subscription.extend(additional_days)
        if commit:
            self.commit()
        return subscription

    def apply_payment(
        self,
        user_telegram_id: int,
        service_id: int,
        duration_days: int,
        paid_on,
        commit: bool = True,
    ) -> tuple[Subscription, bool]:
        """
        Crea o renueva la única suscripción de (usuario, servicio).

        Args:
            user_telegram_id: ID de Telegram del usuario.
            service_id: ID del servicio.
            duration_days: Días que otorga el pago.
            paid_on: Fecha del pago (date).
            commit: Si False, solo hace flush para que el caller confirme la
                transacción completa (compra + suscripción).

        Returns:
            Tupla (suscripción, creada). ``creada`` es False si se renovó.

        Raises:
            IntegrityError: si otra transacción creó la fila en paralelo
                (UNIQUE user+service). El caller debe hacer rollback y reintentar.
        """
        subscription = self.get_for_renewal(user_telegram_id, service_id)
        created = subscription is None
        if created:
            subscription = Subscription(
                user_telegram_id=user_telegram_id,
                service_id=service_id,
                start_date=paid_on,
                end_date=paid_on + timedelta(days=duration_days),
                is_active=True,
            )
            self.add(subscription)
        else:
            subscription.renew(duration_days, paid_on)

        self.flush()
        if commit:
            self.commit()
        return subscription, created

    def create_from_purchase(self, purchase: Purchase, duration_days: int) -> Subscription:
        """
        Crea o renueva la suscripción correspondiente a una compra ya registrada.

        Args:
            purchase: Instancia de Purchase con los datos de la compra.
            duration_days: Duración en días de la suscripción.

        Returns:
            La suscripción creada o renovada.
        """
        paid_on = purchase.purchase_date.date() if hasattr(
            purchase.purchase_date, "date"
        ) else purchase.purchase_date
        subscription, _ = self.apply_payment(
            user_telegram_id=purchase.user_telegram_id,
            service_id=purchase.service_id,
            duration_days=duration_days,
            paid_on=paid_on,
        )
        return subscription

    # ------------------------------------------------------------------
    # Eliminación
    # ------------------------------------------------------------------

    def delete_sub(self, subscription: Subscription) -> None:
        """
        Elimina físicamente una suscripción de la base de datos.

        Args:
            subscription: Instancia de Subscription a eliminar.
        """
        self.delete(subscription)
        self.commit()

    def deactivate_expired_subs(self) -> int:
        """
        Desactiva (is_active=False) las suscripciones vencidas.

        No borra filas: así la limpieza es idempotente y una renovación
        posterior reutiliza la misma fila.

        Returns:
            Número de suscripciones desactivadas.
        """
        expired = self.get_expired_subs()
        for sub in expired:
            sub.is_active = False
        if expired:
            self.commit()
        return len(expired)
