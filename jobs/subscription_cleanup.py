"""
Subscription Cleanup Job - Magic Chatbot v2
===========================================
Job programado que sincroniza los miembros del grupo VIP de Telegram
con la base de datos y elimina a los usuarios con suscripciones vencidas.

Este job replica la lógica del archivo original `getMembersTelethon.py`,
refactorizada siguiendo principios SOLID:
- Single Responsibility: solo se encarga de la limpieza de suscripciones.
- Dependency Inversion: recibe servicios por constructor.
- Configurable: modo de ejecución (validar/eliminar) vía settings.

Flujo del job:
1. Obtener miembros actuales del grupo de Telegram (via Telethon).
2. Obtener miembros con suscripción activa desde la base de datos.
3. Cruzar ambas listas para identificar:
   - Usuarios con suscripción vencida → candidatos a eliminación.
   - Usuarios sin registro en BD → "clientes especiales" para revisión.
4. En modo "validar": solo generar reportes (JSON/CSV en output/).
5. En modo "eliminar": enviar mensaje de vencimiento + kick del grupo.
6. Generar logs detallados y resumen de ejecución.

Uso:
    from jobs.subscription_cleanup import SubscriptionCleanupJob

    job = SubscriptionCleanupJob(telegram_api, subscription_service, user_service)
    await job.run(mode="eliminar")
"""

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from config.settings import settings
from utils.datetime_utils import today_lima

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

OUTPUT_DIR = "output"
DEFAULT_MODE = "validar"  # Modo seguro por defecto: solo reporta, no elimina
VIP_SERVICE_ID = 2
DEFAULT_PLAN_DAYS = 30
REPAIR_LOOKBACK_DAYS = 120

EXPIRED_MESSAGE = (
    "¡Hola, mi gato! 👋\n\n"
    "Me comunico contigo porque *tu suscripción al Grupo VIP ha expirado*.\n\n"
    "Para seguir disfrutando de todos los pronósticos y beneficios, "
    "*renueva tu suscripción* enviándonos un mensaje a @magic_peru 🔮 📲\n\n"
    "💬 ¿Hubo algún problema con tu pago o crees que esto es un error? "
    "Avísanos y lo revisamos de inmediato.\n\n"
    "¡Gracias por tu preferencia! ✨"
)


class SubscriptionCleanupJob:
    """
    Job de limpieza de suscripciones vencidas.

    Sincroniza los miembros del grupo VIP de Telegram con la base de datos,
    identifica suscripciones expiradas y ejecuta la eliminación de usuarios
    según el modo configurado.

    Attributes:
        telegram_api: TelegramAPIService para interactuar con la API de Telegram.
        subscription_service: SubscriptionService para consultas de suscripciones.
        user_service: UserService para consultas de usuarios.
        purchase_repo: PurchaseRepository para consultas de compras.
        settings: Configuración centralizada.
    """

    def __init__(
        self,
        telegram_api,
        subscription_service,
        user_service,
        purchase_repo=None,
        container=None,
    ) -> None:
        """
        Inicializa el job de limpieza.

        Args:
            telegram_api: Servicio de API de Telegram.
            subscription_service: Servicio de suscripciones.
            user_service: Servicio de usuarios.
            purchase_repo: Repositorio de compras (opcional).
            container: Contenedor de dependencias (opcional).
        """
        self.telegram_api = telegram_api
        self.subscription_service = subscription_service
        self.user_service = user_service
        self.purchase_repo = purchase_repo
        self.container = container

        # Parámetros desde settings
        self.vip_group_id = int(settings.TELEGRAM_VIP_GROUP_ID or "0")
        self.validator_ids = settings.TELEGRAM_VALIDATOR_IDS

    # ------------------------------------------------------------------
    # DB-only mode (no Telegram API needed)
    # ------------------------------------------------------------------

    def run_db_only(self, mode: str = "validar") -> dict:
        """
        Limpieza basada solo en la BD (no requiere Telethon).

        Es idempotente: ejecutarla varias veces el mismo día no vuelve a
        expulsar ni a avisar a nadie.

        1. Reparación: crea la suscripción de compras VIP recientes que no la
           tienen, solo si el periodo pagado sigue vigente. En modo "validar"
           solo se cuentan (no se escribe nada en la BD).
        2. Vencidos: usuarios cuya suscripción activa venció y que no tienen
           otra vigente. En modo "eliminar" se expulsan del grupo y su fila se
           desactiva (``is_active=False``), sin borrarla.

        Returns:
            Dict con stats: total, active, expired, removed, repaired, kick_failed.
        """
        import json
        from datetime import datetime

        from sqlalchemy import distinct, func, text

        from core.database import SessionLocal as MakeSession
        from models.subscription import Subscription
        from models.user import User

        session = MakeSession()
        # Keep connection alive during long operations (MySQL-specific; ignore
        # if the backend doesn't support SET SESSION so cleanup never crashes).
        try:
            session.execute(text("SET SESSION wait_timeout=28800"))
            session.execute(text("SET SESSION interactive_timeout=28800"))
        except Exception as e:  # noqa: BLE001
            logger.debug(f"SET SESSION no soportado por el backend: {e}")
            session.rollback()

        today = today_lima()
        protected_ids = self._protected_user_ids()
        stats = {
            "total": 0,
            "active": 0,
            "expired": 0,
            "special": 0,
            "removed": 0,
            "repaired": 0,
            "kick_failed": 0,
        }

        try:
            # ---- PASO 1: REPAIR ----
            stats["repaired"] = self._repair_missing_subscriptions(
                session, today, protected_ids, apply=(mode == "eliminar")
            )

            # ---- PASO 2: Clasificar POR USUARIO (no por fila) ----
            stats["total"] = session.query(
                func.count(distinct(Subscription.user_telegram_id))
            ).scalar() or 0

            # Solo suscripciones VIP: la limpieza expulsa del grupo VIP.
            vip_active = (Subscription.service_id == VIP_SERVICE_ID, Subscription.is_active)
            valid_ids = {
                uid
                for (uid,) in session.query(Subscription.user_telegram_id)
                .filter(*vip_active, Subscription.end_date >= today)
                .distinct()
            }
            stale_subs = (
                session.query(Subscription)
                .filter(*vip_active, Subscription.end_date < today)
                .order_by(Subscription.end_date)
                .all()
            )

            # Un usuario solo está vencido si NO tiene otra suscripción vigente.
            expired_by_user: dict[int, list] = {}
            for sub in stale_subs:
                uid = sub.user_telegram_id
                if uid in valid_ids or uid in protected_ids:
                    continue
                expired_by_user.setdefault(uid, []).append(sub)

            stats["active"] = len(valid_ids)
            stats["expired"] = len(expired_by_user)
            print(
                f"🛡️ Protegidos {len(protected_ids)} IDs. "
                f"Vigentes: {stats['active']}. Vencidos: {stats['expired']}"
            )

            names = {}
            if expired_by_user:
                names = {
                    u.telegram_id: u.telegram_name
                    for u in session.query(User).filter(
                        User.telegram_id.in_(list(expired_by_user))
                    )
                }
            expired_snapshot = [
                {
                    "user_id": uid,
                    "end_date": str(max(s.end_date for s in subs)),
                    "name": names.get(uid),
                }
                for uid, subs in expired_by_user.items()
            ]

            if mode == "eliminar" and expired_by_user:
                # Defensa adicional: nunca expulsar a administradores reales del
                # grupo, aunque falten en PROTECTED_USER_IDS. Si no se pueden
                # consultar, esta ejecución no expulsa a nadie.
                group_admins = self._group_admin_ids()
                if group_admins is None:
                    print("⛔ No se pudieron obtener los admins del grupo: no se expulsa a nadie.")
                    mode = "validar"
                else:
                    for uid in group_admins & set(expired_by_user):
                        expired_by_user.pop(uid)

            if mode == "eliminar":
                # Filas vencidas de usuarios que tienen otra vigente: solo se
                # desactivan, sin expulsar ni avisar.
                for sub in stale_subs:
                    if sub.user_telegram_id in valid_ids:
                        sub.is_active = False
                session.commit()

                self._remove_expired_users(session, expired_by_user, stats)

            # ---- Reporte ----
            output_dir = os.path.join(OUTPUT_DIR, today.strftime("%Y-%m-%d"))
            os.makedirs(output_dir, exist_ok=True)
            hora = datetime.now().strftime("%H%M%S")

            report = {
                "date": str(today),
                "mode": mode,
                "stats": stats,
                "expired_users": expired_snapshot,
            }
            with open(os.path.join(output_dir, f"resumen_{hora}.json"), "w") as f:
                json.dump(report, f, indent=2)

            # El workflow de GitHub Actions parsea estas líneas.
            with open(os.path.join(output_dir, f"resumen_{hora}.txt"), "w") as f:
                f.write("DB-ONLY CLEANUP REPORT\n")
                f.write(f"Date: {today}\n")
                f.write(f"Mode: {mode}\n")
                f.write(f"Total Users with Subs: {stats['total']}\n")
                f.write(f"Active Subscriptions: {stats['active']}\n")
                f.write(f"Expired Subscriptions: {stats['expired']}\n")
                f.write(f"Removed: {stats['removed']}\n")

            print("DB-Only Cleanup Complete:")
            for key in ("total", "active", "expired", "removed", "repaired", "kick_failed"):
                print(f"  {key}: {stats[key]}")

        finally:
            session.close()

        header = (
            "📊 *Reporte de Limpieza (Solo lectura)*"
            if mode == "validar"
            else "🚨 *PROCESO DE ELIMINACIÓN* 🚨"
        )
        self._notify_admins(
            f"─────────────────\n"
            f"{header}\n"
            f"─────────────────\n\n"
            f"📅 Fecha: {today}\n\n"
            f"📊 *Estadísticas de la BD*\n"
            f"├ 🔧 Reparados: {stats['repaired']}\n"
            f"├ 👥 Total en BD: {stats['total']}\n"
            f"├ ✅ Vigentes: {stats['active']}\n"
            f"├ ❌ Vencidos: {stats['expired']}\n"
            f"├ 🚫 Eliminados: {stats['removed']}\n"
            f"└ ⚠️ Expulsiones fallidas: {stats['kick_failed']}\n\n"
            f"─────────────────"
        )
        return stats

    def _repair_missing_subscriptions(
        self, session, today, protected_ids: set[int], apply: bool
    ) -> int:
        """
        Crea la suscripción de compradores VIP recientes que no tienen ninguna.

        Solo se crea si el periodo pagado (fecha de compra + duración del plan)
        sigue vigente. Antes se recreaba siempre con 30 días, aunque ya hubiera
        vencido, y la siguiente ejecución volvía a expulsar y avisar al mismo
        usuario (ciclo borrar → reparar → borrar).
        """
        from datetime import timedelta

        from models.purchase import Purchase
        from models.subscription import Subscription

        purchased_ids = {
            uid
            for (uid,) in session.query(Purchase.user_telegram_id)
            .filter(
                Purchase.service_id == VIP_SERVICE_ID,
                Purchase.status == "active",
                Purchase.purchase_date >= today - timedelta(days=REPAIR_LOOKBACK_DAYS),
            )
            .distinct()
        }
        subscribed_ids = {
            uid
            for (uid,) in session.query(Subscription.user_telegram_id)
            .filter(Subscription.service_id == VIP_SERVICE_ID)
            .distinct()
        }
        missing_ids = purchased_ids - subscribed_ids - protected_ids
        if not missing_ids:
            print("\n✅ Todos los compradores VIP ya tienen suscripción")
            return 0

        repaired = 0
        for uid in missing_ids:
            latest = (
                session.query(Purchase)
                .filter(
                    Purchase.user_telegram_id == uid,
                    Purchase.service_id == VIP_SERVICE_ID,
                    Purchase.status == "active",
                )
                .order_by(Purchase.purchase_date.desc())
                .first()
            )
            if latest is None:
                continue
            paid_on = (
                latest.purchase_date.date()
                if hasattr(latest.purchase_date, "date")
                else latest.purchase_date
            )
            end_date = paid_on + timedelta(days=self._plan_duration_days(latest.price))
            if end_date < today:
                continue  # El periodo pagado ya venció: nada que reparar.
            repaired += 1
            if not apply:
                print(f"  • Se repararía {uid} (vence {end_date})")
                continue
            session.add(
                Subscription(
                    user_telegram_id=uid,
                    service_id=VIP_SERVICE_ID,
                    start_date=paid_on,
                    end_date=end_date,
                    is_active=True,
                )
            )
            print(f"  ✓ Suscripción reparada para {uid} (vence {end_date})")

        if apply:
            session.commit()
        print(f"\n🔧 Reparadas {repaired} de {len(missing_ids)} compras VIP sin suscripción")
        return repaired

    def _remove_expired_users(self, session, expired_by_user: dict, stats: dict) -> None:
        """
        Expulsa a los usuarios vencidos y desactiva sus suscripciones.

        La fila se desactiva solo si la expulsión funcionó, y se confirma por
        usuario: si el job se interrumpe, nadie es expulsado ni avisado dos veces.
        Si la expulsión falla, la fila sigue activa y se reintenta mañana.
        """
        from services.telegram_api import TelegramAPIService

        api = TelegramAPIService()
        batch_limit = settings.CLEANUP_BATCH_LIMIT
        users = list(expired_by_user.items())
        to_process = users[:batch_limit] if batch_limit > 0 else users
        pending = len(users) - len(to_process)
        print(
            f"\n🚮 Procesando {len(to_process)} de {len(users)} "
            f"vencidos (límite={batch_limit or '∞'}, pendientes={pending})"
        )

        for uid, subs in to_process:
            user_id = int(uid)
            try:
                result = api.remove_user_allow_rejoin(chat_id=self.vip_group_id, user_id=user_id)
                kicked = bool(result.get("kick_success"))
            except Exception as e:  # noqa: BLE001
                print(f"  ✗ Error kick {user_id}: {e}")
                kicked = False

            if not kicked:
                stats["kick_failed"] += 1
                continue

            for sub in subs:
                sub.is_active = False
            session.commit()
            stats["removed"] += 1
            print(f"  ✓ Expulsado y desactivado {user_id}")

            # Bots cannot DM users who never started a chat, so 400s are
            # expected here; suppress the error logs to avoid spam.
            try:
                api.send_message(
                    chat_id=user_id,
                    text=EXPIRED_MESSAGE,
                    parse_mode="Markdown",
                    log_errors=False,
                )
            except Exception:  # noqa: BLE001
                pass

        if pending > 0:
            print(f"⏭️ Quedan {pending} vencidos para la próxima ejecución")

    def _plan_duration_days(self, price: float) -> int:
        """Duración del plan VIP pagado; 30 días si no se puede determinar."""
        getter = getattr(self.subscription_service, "get_plan_duration_days", None)
        if getter is not None:
            try:
                days = getter(price)
                if days:
                    return days
            except Exception as e:  # noqa: BLE001
                logger.warning(f"No se pudo determinar la duración para S/ {price}: {e}")
        return DEFAULT_PLAN_DAYS

    def _group_admin_ids(self) -> set[int] | None:
        """IDs de los administradores del grupo VIP, o None si falla la consulta."""
        try:
            admins = self.telegram_api.get_chat_administrators(self.vip_group_id)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"No se pudieron obtener administradores: {e}")
            return None
        if not admins:
            return None
        return {int(a["user"]["id"]) for a in admins if a.get("user", {}).get("id")}

    @staticmethod
    def _protected_user_ids() -> set[int]:
        """Admins, validadores y bots que la limpieza nunca expulsa."""
        return (
            set(settings.PROTECTED_USER_IDS)
            | set(settings.ADMIN_NOTIFY_IDS)
            | set(settings.get_validator_ids_as_int())
        )

    def _notify_admins(self, text: str) -> None:
        """Envía un resumen a los admins configurados en ADMIN_NOTIFY_IDS."""
        if not settings.ADMIN_NOTIFY_IDS:
            return
        try:
            from services.telegram_api import TelegramAPIService

            api = TelegramAPIService()
            for admin_id in settings.ADMIN_NOTIFY_IDS:
                api.send_message(chat_id=admin_id, text=text, parse_mode="Markdown")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"No se pudo notificar a los admins: {e}")

    # ------------------------------------------------------------------
    # Método principal
    # ------------------------------------------------------------------

    async def run(
        self,
        mode: str = DEFAULT_MODE,
        validate_special_clients: bool = True,
    ) -> dict[str, Any]:
        """
        Ejecuta el proceso completo de limpieza de suscripciones.

        Args:
            mode: Modo de ejecución:
                  "validar" - Solo genera reportes, no elimina usuarios.
                  "eliminar" - Ejecuta validación + eliminación completa.
            validate_special_clients: Si True, guarda clientes no registrados
                  para revisión manual por soporte. Si False, los elimina
                  automáticamente.

        Returns:
            Diccionario con estadísticas de la ejecución:
            - total_members: Miembros en el grupo de Telegram.
            - admins: Número de administradores.
            - active_subs: Suscripciones activas encontradas.
            - expired_subs: Suscripciones vencidas.
            - special_clients: Clientes sin registro en BD.
            - removed: Usuarios eliminados (si mode="eliminar").
            - errors: Lista de errores encontrados.
        """
        now = datetime.now()
        fecha_ejecucion = now.strftime("%Y-%m-%d")
        hora_ejecucion = now.strftime("%H:%M:%S")
        hora_archivo = now.strftime("%H%M%S")

        output_dir = os.path.join(OUTPUT_DIR, fecha_ejecucion)
        os.makedirs(output_dir, exist_ok=True)

        logger.info(
            f"Iniciando limpieza de suscripciones: mode={mode}, "
            f"fecha={fecha_ejecucion}, hora={hora_ejecucion}"
        )

        stats = {
            "total_members": 0,
            "admins": 0,
            "active_subs": 0,
            "expired_subs": 0,
            "special_clients": 0,
            "removed": 0,
            "errors": [],
        }

        try:
            # ---- Paso 1: Obtener administradores del grupo ----
            admins = await self._get_group_admins()
            if not admins and mode == "eliminar":
                logger.error(
                    "No se pudieron obtener los administradores del grupo: "
                    "esta ejecución no expulsa a nadie (modo validar)."
                )
                stats["errors"].append("admins_unavailable")
                mode = "validar"
            admin_ids = [str(a["user_id"]) for a in admins]
            # Sumar IDs protegidos por configuración (bots, validadores, admins)
            extra_ids = {str(uid) for uid in self._protected_user_ids()}
            admin_ids = list(set(admin_ids) | extra_ids)
            stats["admins"] = len(admin_ids)
            logger.info(f"Administradores obtenidos: {len(admin_ids)}")

            # ---- Paso 2: Obtener miembros actuales del grupo desde Telethon ----
            telegram_members = await self._get_telegram_members()
            if telegram_members.empty:
                logger.warning("No se obtuvieron miembros de Telegram (Telethon).")
                stats["errors"].append("telethon_no_members")
                return stats

            stats["total_members"] = len(telegram_members)
            logger.info(f"Miembros en Telegram: {len(telegram_members)}")

            # ---- Paso 3: Obtener suscripciones activas desde BD ----
            active_subs = self.subscription_service.get_active_subscriptions()

            # ---- Paso 4: Cruzar miembros vs suscripciones ----
            comparison_df = self._build_comparison(
                telegram_members, active_subs, admin_ids
            )

            # ---- Paso 5: Clasificar usuarios ----
            special_clients, to_remove = self._classify_users(
                comparison_df, validate_special_clients
            )

            # Stats basados SOLO en miembros del grupo (coherentes con reconcile report)
            stats["active_subs"] = len(
                comparison_df[comparison_df["mensaje"] == "suscripción activa"]
            )
            stats["expired_subs"] = len(
                comparison_df[comparison_df["mensaje"] == "suscripción vencida"]
            )
            stats["special_clients"] = len(
                comparison_df[comparison_df["mensaje"] == "Usuario no registrado en BD"]
            )

            logger.info(
                f"Clasificación: {len(special_clients)} clientes especiales, "
                f"{len(to_remove)} suscripciones vencidas"
            )

            # ---- Paso 6: Guardar reportes ----
            if not special_clients.empty:
                self._save_special_clients_report(
                    special_clients, output_dir, hora_archivo
                )

            if not to_remove.empty:
                self._save_prevalidation_report(to_remove, output_dir, hora_archivo)

            # ---- Paso 7: Ejecutar eliminación (solo en modo "eliminar") ----
            if mode == "eliminar" and not to_remove.empty:
                removed_count = await self._execute_removal(
                    to_remove, comparison_df, output_dir, hora_archivo
                )
                stats["removed"] = removed_count

            # ---- Paso 8: Guardar resumen general ----
            self._save_summary_report(
                stats, comparison_df, output_dir, hora_archivo,
                fecha_ejecucion, hora_ejecucion
            )

            # ---- Paso 8b: Generar Excel unificado de contabilidad ----
            excel_path = os.path.join(output_dir, f"limpieza_{fecha_ejecucion}.xlsx")
            with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
                # 1. Resumen
                resumen_df = pd.DataFrame({
                    "Metric": ["Fecha", "Total en grupo", "Activos", "Expirados",
                               "Sin registro BD", "Eliminados", "Admins protegidos"],
                    "Value": [fecha_ejecucion, stats["total_members"],
                              stats["active_subs"], stats["expired_subs"],
                              stats["special_clients"], stats["removed"],
                              stats["admins"]],
                })
                resumen_df.to_excel(writer, sheet_name="Resumen", index=False)

                # 2. Activos (en grupo + suscripción vigente)
                activos_df = comparison_df[
                    comparison_df["mensaje"] == "suscripción activa"
                ][["user_telegram_id", "username", "first_name",
                   "end_date", "servicio", "fecha_final_suscripcion"]].copy()
                activos_df.to_excel(writer, sheet_name="Activos", index=False)

                # 3. Expirados (en grupo + vencida)
                expirados_df = comparison_df[
                    comparison_df["mensaje"] == "suscripción vencida"
                ][["user_telegram_id", "username", "first_name",
                   "end_date", "servicio"]].copy()
                expirados_df.to_excel(writer, sheet_name="Expirados", index=False)

                # 4. Sin registro
                sin_reg_df = comparison_df[
                    comparison_df["mensaje"] == "Usuario no registrado en BD"
                ][["user_telegram_id", "username", "first_name"]].copy()
                sin_reg_df.to_excel(writer, sheet_name="SinRegistro", index=False)

            logger.info(f"Excel unificado generado: {excel_path}")

            logger.info(
                f"Limpieza completada: modo={mode}, "
                f"removed={stats['removed']}, errors={len(stats['errors'])}"
            )

        except Exception as e:
            error_msg = f"Error general en limpieza de suscripciones: {e}"
            logger.error(error_msg, exc_info=True)
            stats["errors"].append(error_msg)

        # ---- Notify admin of cleanup results ----
        try:
            header = (
                "📊 *Reporte de Limpieza (Solo lectura)*"
                if mode == "validar"
                else "🚨 *PROCESO DE ELIMINACIÓN* 🚨"
            )
            summary = (
                f"─────────────────\n"
                f"{header}\n"
                f"─────────────────\n\n"
                f"📅 Fecha: {fecha_ejecucion}\n"
                f"🕐 Hora: {hora_ejecucion}\n\n"
                f"📊 *Estadísticas del Grupo*\n"
                f"├ 👥 Total en grupo: {stats.get('total_members', 0)}\n"
                f"├ ✅ Activos en grupo: {stats.get('active_subs', 0)}\n"
                f"├ ❌ Expirados en grupo: {stats.get('expired_subs', 0)}\n"
                f"├ 🆕 Sin registro BD: {stats.get('special_clients', 0)}\n"
                f"└ 🚫 Eliminados: {stats.get('removed', 0)}\n\n"
                f"─────────────────"
            )
            for admin_id in settings.ADMIN_NOTIFY_IDS:
                self.telegram_api.send_message(
                    chat_id=admin_id, text=summary, parse_mode="Markdown"
                )
        except Exception as e:
            logger.warning(f"No se pudo notificar al admin: {e}")

        return stats

    # ------------------------------------------------------------------
    # Paso 1: Obtener administradores
    # ------------------------------------------------------------------

    async def _get_group_admins(self) -> list[dict[str, Any]]:
        """
        Obtiene la lista de administradores del grupo VIP de Telegram.

        Returns:
            Lista de diccionarios con info de cada administrador.
        """
        try:
            admins = self.telegram_api.get_chat_administrators(self.vip_group_id)
            admin_list = []
            for admin in admins:
                user = admin.get("user", {})
                admin_list.append({
                    "user_id": user.get("id"),
                    "username": user.get("username", ""),
                    "first_name": user.get("first_name", ""),
                    "status": admin.get("status", ""),
                    "is_admin": True,
                })
            return admin_list
        except Exception as e:
            logger.error(f"Error al obtener administradores: {e}")
            return []

    # ------------------------------------------------------------------
    # Paso 2: Obtener miembros desde Telethon
    # ------------------------------------------------------------------

    async def _get_telegram_members(self) -> pd.DataFrame:
        """
        Obtiene los miembros actuales del grupo VIP usando Telethon.

        Returns:
            DataFrame con columnas: user_telegram_id, username, first_name,
            is_bot, joined_date (ISO 8601 si está disponible).
        """
        try:
            from telethon.sessions import StringSession
            from telethon.sync import TelegramClient
            from telethon.tl.functions.channels import GetParticipantsRequest
            from telethon.tl.types import ChannelParticipantsSearch

            api_id_raw = (os.getenv("TELETHON_API_ID") or "").strip()
            api_hash = (os.getenv("TELETHON_API_HASH") or "").strip()

            if not api_id_raw or not api_hash:
                logger.error(
                    "TELETHON_API_ID y/o TELETHON_API_HASH vacíos o ausentes. "
                    "No se pueden obtener miembros de Telegram."
                )
                return pd.DataFrame()

            try:
                api_id = int(api_id_raw)
            except ValueError:
                logger.error(f"TELETHON_API_ID no es un número válido: {api_id_raw!r}")
                return pd.DataFrame()

            # Prefer a StringSession from env (works unattended in CI); fall
            # back to the local file session for interactive/local runs.
            session_str = (os.getenv("TELETHON_SESSION") or "").strip()
            session: Any = (
                StringSession(session_str) if session_str else "my_user_session"
            )

            members_list = []

            async with TelegramClient(session, api_id, api_hash) as client:
                if not await client.is_user_authorized():
                    logger.error(
                        "Cliente Telethon no autorizado. Ejecuta la autenticación manual."
                    )
                    return pd.DataFrame()

                group_entity = await client.get_entity(self.vip_group_id)
                offset = 0
                limit = 200

                while True:
                    participants = await client(GetParticipantsRequest(
                        channel=group_entity,
                        filter=ChannelParticipantsSearch(''),
                        offset=offset,
                        limit=limit,
                        hash=0,
                    ))

                    if not participants.users:
                        break

                    # Build a map of user_id -> joined_date from participant metadata
                    # Telegram API returns 'date' as Unix timestamp (int), not 'joined_date'
                    joined_dates: dict[int, str] = {}
                    for p in participants.participants:
                        uid = getattr(p, "user_id", None)
                        jd = getattr(p, "date", None)
                        if uid and jd:
                            try:
                                joined_dates[uid] = datetime.fromtimestamp(
                                    int(jd), tz=UTC
                                ).isoformat()
                            except (ValueError, TypeError):
                                joined_dates[uid] = str(jd)

                    for user in participants.users:
                        members_list.append({
                            "user_telegram_id": user.id,
                            "username": getattr(user, 'username', ''),
                            "first_name": getattr(user, 'first_name', ''),
                            "is_bot": bool(getattr(user, 'bot', False)),
                            "joined_date": joined_dates.get(user.id, ""),
                        })

                    offset += len(participants.users)

                    if len(participants.users) < limit:
                        break

                # Conteo REAL de participantes del grupo (dato público, no
                # depende de visibilidad de la lista de miembros).
                real_count = 0
                try:
                    from telethon.tl.functions.channels import (
                        GetFullChannelRequest,
                    )
                    full = await client(GetFullChannelRequest(channel=group_entity))
                    real_count = full.full_chat.participants_count or 0
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"No se pudo obtener participants_count: {e}")

            # GUARD anti-fetch-parcial: si enumeramos muchos menos miembros que
            # el total real, la cuenta de Telethon probablemente perdió el rol
            # de admin (Telegram solo muestra la lista completa a admins) y solo
            # vemos a los administradores. Devolvemos un DataFrame VACÍO para que
            # run() aborte SIN eliminar a nadie sobre datos incompletos.
            if real_count and len(members_list) < max(int(real_count * 0.5), 20):
                logger.error(
                    f"Fetch PARCIAL de miembros: {len(members_list)} de "
                    f"{real_count} reales. La cuenta de Telethon probablemente NO "
                    f"es administrador del grupo. Abortando limpieza para evitar "
                    f"actuar sobre datos incompletos."
                )
                return pd.DataFrame()

            logger.info(
                f"Telethon: {len(members_list)} miembros obtenidos del grupo "
                f"(real={real_count})."
            )
            return pd.DataFrame(members_list)

        except ImportError:
            logger.error("Telethon no está instalado. No se pueden obtener miembros.")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"Error en Telethon al obtener miembros: {e}", exc_info=True)
            return pd.DataFrame()

    # ------------------------------------------------------------------
    # Paso 4: Construir tabla de comparación
    # ------------------------------------------------------------------

    def _build_comparison(
        self,
        telegram_members: pd.DataFrame,
        active_subs: list[Any],
        admin_ids: list[str],
    ) -> pd.DataFrame:
        """
        Cruza los miembros de Telegram con las suscripciones activas
        para construir una tabla de comparación.

        Args:
            telegram_members: DataFrame con miembros del grupo.
            active_subs: Lista de Subscription activas.
            admin_ids: Lista de IDs de administradores (serán omitidos).

        Returns:
            DataFrame con columnas:
            - user_telegram_id
            - username
            - first_name
            - end_date
            - mensaje (estado: activa, vencida, no registrado)
            - eliminar_suscripcion (bool)
            - servicio
            - fecha_compra
            - fecha_final_suscripcion
        """
        results = []

        for _, member in telegram_members.iterrows():
            user_id = str(member["user_telegram_id"])

            # Omitir administradores
            if user_id in admin_ids:
                continue

            end_date = None
            mensaje = "Usuario no registrado en BD"
            # NUNCA eliminar usuarios no registrados en BD automáticamente.
            # Estos usuarios deben ser validados manualmente por soporte para
            # determinar si realmente no compraron o tuvieron una dificultad
            # en la validación de compra (ej: comprobante enviado pero no
            # procesado por error transitorio).
            eliminar = False
            servicio = ""
            fecha_compra = ""
            fecha_final = ""

            # Verificar suscripción activa en BD
            user_subs = [
                s for s in active_subs
                if str(s.user_telegram_id) == user_id and s.service_id == VIP_SERVICE_ID
            ]

            if user_subs:
                # Tomar la suscripción con end_date más lejano
                latest_sub = max(user_subs, key=lambda s: s.end_date)
                end_date = latest_sub.end_date
                servicio = "grupo_vip" if latest_sub.service_id == 2 else "stake"

                if end_date >= today_lima():
                    mensaje = "suscripción activa"
                    eliminar = False
                else:
                    mensaje = "suscripción vencida"
                    eliminar = True

            results.append({
                "user_telegram_id": user_id,
                "username": member.get("username", ""),
                "first_name": member.get("first_name", ""),
                "end_date": end_date or "",
                "mensaje": mensaje,
                "eliminar_suscripcion": eliminar,
                "servicio": servicio,
                "fecha_compra": fecha_compra,
                "fecha_final_suscripcion": fecha_final,
            })

        comparison = pd.DataFrame(results)
        logger.info(f"Comparación construida: {len(comparison)} usuarios evaluados.")
        return comparison

    # ------------------------------------------------------------------
    # Paso 5: Clasificar usuarios
    # ------------------------------------------------------------------

    def _classify_users(
        self,
        comparison_df: pd.DataFrame,
        validate_special_clients: bool,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Clasifica los usuarios en:
        - Clientes especiales (no registrados en BD).
        - Usuarios a eliminar (suscripción vencida confirmada).

        Args:
            comparison_df: DataFrame de comparación.
            validate_special_clients: Si True, separa clientes especiales.

        Returns:
            Tupla (special_clients_df, to_remove_df).
        """
        # Clientes especiales: no registrados en BD
        special_clients = comparison_df[
            comparison_df["mensaje"] == "Usuario no registrado en BD"
        ].copy()

        # Usuarios "no registrados en BD" se excluyen SIEMPRE de la
        # eliminación, sin importar el flag validate_special_clients.
        # Estos usuarios requieren validación manual por soporte.
        to_remove = comparison_df[
            (comparison_df["eliminar_suscripcion"]) &
            (comparison_df["mensaje"] != "Usuario no registrado en BD")
        ].copy()

        return special_clients, to_remove

    # ------------------------------------------------------------------
    # Paso 7: Ejecutar eliminación
    # ------------------------------------------------------------------

    async def _execute_removal(
        self,
        to_remove: pd.DataFrame,
        comparison_df: pd.DataFrame,
        output_dir: str,
        hora_archivo: str,
    ) -> int:
        """
        Ejecuta la eliminación de usuarios con suscripción vencida.

        Para cada usuario:
        1. Lo expulsa del grupo (kick + unban para permitir rejoin).
        2. Si la expulsión funcionó, desactiva su suscripción y le avisa.

        Args:
            to_remove: DataFrame con usuarios a eliminar.
            comparison_df: DataFrame completo de comparación.
            output_dir: Directorio para guardar logs.
            hora_archivo: Timestamp para nombres de archivo.

        Returns:
            Número de usuarios eliminados exitosamente.
        """
        removed_count = 0
        removed_users = []

        logger.info(f"Iniciando eliminación de {len(to_remove)} usuarios...")

        for _, row in to_remove.iterrows():
            user_id = str(row["user_telegram_id"])
            mensaje_eliminacion = ""

            try:
                # 1. Expulsar del grupo (kick + unban para permitir re-unirse).
                #    Si falla, no se desactiva ni se avisa: se reintenta mañana.
                try:
                    result = self.telegram_api.remove_user_allow_rejoin(
                        chat_id=self.vip_group_id,
                        user_id=int(user_id),
                    )
                    kicked = bool(result.get("kick_success"))
                except Exception as e:  # noqa: BLE001
                    logger.error(f"Error al expulsar a {user_id}: {e}")
                    kicked = False
                    result = {"kick_result": str(e)}

                if not kicked:
                    logger.warning(
                        f"No se pudo expulsar a {user_id}: {result.get('kick_result')}"
                    )
                    continue

                # 2. Desactivar sus suscripciones VIP (no se borran).
                try:
                    from core.database import SessionLocal
                    from models.subscription import Subscription

                    session = SessionLocal()
                    try:
                        session.query(Subscription).filter_by(
                            user_telegram_id=int(user_id),
                            service_id=VIP_SERVICE_ID,
                            is_active=True,
                        ).update({"is_active": False})
                        session.commit()
                    finally:
                        session.close()
                    mensaje_eliminacion = "Expulsado; suscripción desactivada"
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"Error al desactivar suscripción de {user_id}: {e}")
                    mensaje_eliminacion = f"Expulsado; error al desactivar: {e}"

                # 3. Avisar al usuario (puede fallar si nunca escribió al bot).
                try:
                    self.telegram_api.send_message(
                        chat_id=int(user_id),
                        text=EXPIRED_MESSAGE,
                        parse_mode="Markdown",
                        log_errors=False,
                    )
                except Exception as e:  # noqa: BLE001
                    mensaje_eliminacion += f" | sin aviso: {e}"

                # Registrar usuario eliminado
                removed_users.append({
                    "user_telegram_id": user_id,
                    "username": row.get("username", ""),
                    "first_name": row.get("first_name", ""),
                    "servicio": row.get("servicio", ""),
                    "razon_eliminacion": row.get("mensaje", ""),
                    "estado_eliminacion": mensaje_eliminacion,
                    "timestamp_eliminacion": datetime.now().isoformat(),
                })

                removed_count += 1

                # Guardar en línea (para no perder datos si el proceso se interrumpe)
                self._save_removed_user_inline(
                    removed_users[-1], output_dir, hora_archivo
                )

            except Exception as e:
                logger.error(
                    f"Error al procesar eliminación de user={user_id}: {e}",
                    exc_info=True,
                )

        # Guardar CSV de eliminaciones
        if removed_users:
            df_removed = pd.DataFrame(removed_users)
            csv_path = os.path.join(output_dir, f"eliminaciones_{hora_archivo}.csv")
            df_removed.to_csv(csv_path, index=False)
            logger.info(f"CSV de eliminaciones guardado: {csv_path}")

        logger.info(f"Eliminación completada: {removed_count} usuarios eliminados.")
        return removed_count

    # ------------------------------------------------------------------
    # Reportes
    # ------------------------------------------------------------------

    def _save_special_clients_report(
        self,
        special_clients: pd.DataFrame,
        output_dir: str,
        hora_archivo: str,
    ) -> None:
        """Guarda el reporte de clientes especiales para revisión manual."""
        filepath = os.path.join(
            output_dir, f"clientes_especiales_validacion_{hora_archivo}.json"
        )

        data = {
            "fecha_ejecucion": datetime.now().strftime("%Y-%m-%d"),
            "hora_ejecucion": datetime.now().strftime("%H:%M:%S"),
            "total_clientes_especiales": len(special_clients),
            "nota": "Clientes no registrados en BD - Requieren validación por soporte",
            "estado_validacion": "PENDIENTE",
            "usuarios": [],
        }

        for _, row in special_clients.iterrows():
            data["usuarios"].append({
                "user_telegram_id": str(row["user_telegram_id"]),
                "username": row.get("username", ""),
                "first_name": row.get("first_name", ""),
                "estado": row.get("mensaje", ""),
                "accion_recomendada": "Contactar por soporte - Validar si es cliente legítimo",
                "timestamp_identificacion": datetime.now().isoformat(),
            })

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Reporte de clientes especiales guardado: {filepath}")

    def _save_prevalidation_report(
        self,
        to_remove: pd.DataFrame,
        output_dir: str,
        hora_archivo: str,
    ) -> None:
        """Guarda el reporte de pre-validación de usuarios a eliminar."""
        filepath = os.path.join(output_dir, f"prevalidacion_{hora_archivo}.json")

        data = {
            "fecha_ejecucion": datetime.now().strftime("%Y-%m-%d"),
            "hora_ejecucion": datetime.now().strftime("%H:%M:%S"),
            "total_usuarios_a_eliminar": len(to_remove),
            "nota": "Usuarios con suscripción vencida comprobada",
            "usuarios": [],
        }

        for _, row in to_remove.iterrows():
            data["usuarios"].append({
                "user_telegram_id": str(row["user_telegram_id"]),
                "username": row.get("username", ""),
                "first_name": row.get("first_name", ""),
                "servicio": row.get("servicio", ""),
                "razon": row.get("mensaje", ""),
            })

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info(f"Reporte de pre-validación guardado: {filepath}")

    def _save_summary_report(
        self,
        stats: dict[str, Any],
        comparison_df: pd.DataFrame,
        output_dir: str,
        hora_archivo: str,
        fecha_ejecucion: str,
        hora_ejecucion: str,
    ) -> None:
        """Guarda el reporte resumen de la ejecución."""
        # Guardar JSON
        json_path = os.path.join(output_dir, f"log_ejecucion_{hora_archivo}.json")
        log_data = {
            "fecha_ejecucion": fecha_ejecucion,
            "hora_ejecucion": hora_ejecucion,
            "resumen_general": stats,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)

        # Guardar TXT
        txt_path = os.path.join(output_dir, f"resumen_{hora_archivo}.txt")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write("RESUMEN DE EJECUCIÓN - LIMPIEZA DE SUSCRIPCIONES\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"📅 Fecha: {fecha_ejecucion}\n")
            f.write(f"Hora: {hora_ejecucion}\n\n")
            f.write("ESTADÍSTICAS GENERALES:\n")
            f.write("-" * 60 + "\n")
            for key, value in stats.items():
                f.write(f"{key}: {value}\n")

        logger.info(f"Reportes guardados: {json_path}, {txt_path}")

    def _save_removed_user_inline(
        self,
        user_data: dict[str, Any],
        output_dir: str,
        hora_archivo: str,
    ) -> None:
        """
        Guarda un usuario eliminado en el archivo JSON en tiempo real.
        Evita pérdida de datos si el proceso se interrumpe a mitad.
        """
        filepath = os.path.join(output_dir, f"usuarios_eliminados_{hora_archivo}.json")

        if os.path.exists(filepath):
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = {
                "fecha_ejecucion": datetime.now().strftime("%Y-%m-%d"),
                "hora_ejecucion": datetime.now().strftime("%H:%M:%S"),
                "total_eliminados": 0,
                "resumen_tipos": {
                    "suscripcion_expirada": 0,
                    "sin_compra_registrada": 0,
                    "no_registrado_bd": 0,
                },
                "usuarios": [],
            }

        data["usuarios"].append(user_data)
        data["total_eliminados"] = len(data["usuarios"])

        # Actualizar contadores por tipo
        tipo = user_data.get("tipo_usuario", "desconocido")
        if tipo in data["resumen_tipos"]:
            data["resumen_tipos"][tipo] += 1

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
