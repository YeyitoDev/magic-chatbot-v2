# Magic Chatbot v2

Bot de Telegram que vende y administra las suscripciones del **Grupo VIP** y el **Stake** de Magic:
registra usuarios, recibe comprobantes de pago, los envía a validadores, registra la compra,
crea o renueva la suscripción, entrega el link de invitación y expulsa del grupo a quienes vencen.

- Python 3.12 · python-telegram-bot 20+ · SQLAlchemy 2 · MySQL
- OCR de comprobantes con Gemini / Google Vision (opcional)
- Despliegue en Fly.io; jobs programados en GitHub Actions

---

## Arquitectura

```text
handlers/      Telegram: comandos, mensajes (fotos de comprobantes) y botones inline
services/      Lógica de negocio: pagos, suscripciones, precios, Telegram API, OCR, medios
repositories/  Acceso a datos (una clase por tabla, sesión inyectada)
models/        Modelos SQLAlchemy: users, services, service_prices, purchases, subscriptions
core/          Base de datos, contenedor de dependencias y verificación de esquema
jobs/          Limpieza de suscripciones, avisos de vencimiento, recordatorios, reportes
api/           API Flask (health, pagos externos, webhook)
scripts/       Herramientas operativas (diagnóstico, intrusos, file_ids, sesión Telethon)
migrations/    Migraciones SQL manuales
```

Flujo de dependencias: `handlers → services → repositories → models`. `core/container.py`
construye los servicios; los handlers nunca hablan directo con la BD.

| Tabla | Propósito |
|---|---|
| `users` | Usuarios del bot (`telegram_id`) |
| `services` / `service_prices` | Catálogo (Stake, Grupo VIP) y precios por plan (monto, descuento, meses) |
| `purchases` | Cada pago validado; `payment_ref` identifica el comprobante; `status` = `active` / `fraud` |
| `subscriptions` | Una fila por (usuario, servicio) con `start_date`, `end_date`, `is_active` |
| `selected_services` | Servicio en el "carrito" del usuario y recordatorios enviados |

---

## Instalación local

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # completar valores
python main.py         # modo polling
```

Las tablas se crean al iniciar (`init_db()`). Si la BD ya existe, aplica antes las
[migraciones](migrations/README.md): el bot **no arranca** si falta `purchases.payment_ref`.

---

## Configuración

Todo se configura con variables de entorno (`config/settings.py`). Plantilla: [`.env.example`](.env.example).

| Variable | Requerida | Descripción |
|---|---|---|
| `ENVIRONMENT` | — | `testing` (default) o `production` |
| `TELEGRAM_BOT_TOKEN` | Sí | Token del bot |
| `TELEGRAM_BOT_TOKEN_LINKS` | — | Token del bot admin del grupo VIP para crear links de invitación |
| `TELEGRAM_BOT_USERNAME` | — | Username del bot sin `@` |
| `TELEGRAM_VALIDATOR_IDS` | En producción | IDs de validadores separados por coma (reciben los comprobantes) |
| `TELEGRAM_VIP_GROUP_ID` | En producción | ID del grupo VIP (`-100…`) |
| `TELEGRAM_DEFAULT_VIP_LINK` | — | Link de respaldo si no se puede generar uno nuevo |
| `TELEGRAM_ERROR_NOTIFICATION_USER_ID` | — | Chat que recibe alertas de errores |
| `ADMIN_NOTIFY_IDS` | — | IDs que reciben los resúmenes de los jobs (coma) |
| `PROTECTED_USER_IDS` | — | Admins y bots que la limpieza nunca expulsa (coma). Validadores y `ADMIN_NOTIFY_IDS` se protegen solos |
| `PAYMENT_HOLDER_NAME` | — | Titular mostrado junto a los datos de pago |
| `PAYMENT_YAPE_PLIN` / `PAYMENT_BCP_ACCOUNT` / `PAYMENT_SCOTIABANK_ACCOUNT` | Al menos una en producción | Datos de pago que ve el cliente con los precios |
| `DB_ENGINE`, `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` | Sí (salvo engine/port) | Conexión MySQL (`mysql+pymysql`, puerto 3306) |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT` | — | Pool de conexiones |
| `GOOGLE_CREDENTIALS_JSON` / `GOOGLE_CREDENTIALS_PATH` | — | Credenciales de Google (Sheets/Vision). `startup.py` escribe el JSON a disco |
| `GOOGLE_SHEETS_ID`, `GOOGLE_WSP_SPREADSHEET_ID`, `GOOGLE_SHEETS_WORKSHEET_NAME` | — | Hojas de registro de usuarios y pagos por WhatsApp |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | — | OCR de comprobantes con Gemini |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `AWS_DYNAMODB_TABLE` | — | Sesiones de usuario para el pipeline de promociones |
| `TELETHON_API_ID`, `TELETHON_API_HASH`, `TELETHON_SESSION` | Para la limpieza | Cuenta Telethon (admin del grupo) para listar miembros |
| `BETSAFE_PROMO_LINK`, `BETSAFE_BUTTON_TEXT` | — | Enlace y texto de la promoción de BetSafe |
| `FLASK_HOST`, `FLASK_PORT`, `FLASK_SECRET_KEY`, `API_KEY` | — | API Flask |
| `ENABLE_JOBS`, `JOB_*`, `CLEANUP_BATCH_LIMIT`, `TIMEZONE` | — | Scheduler interno; máximo de expulsiones por ejecución (default 150) |
| `LOG_LEVEL`, `LOG_FORMAT`, `LOG_FILE_PATH` | — | Logging (`text` o `json`) |

En producción `settings.validate()` detiene el arranque si falta alguna variable requerida.

---

## Ejecución

```bash
python main.py                  # bot en modo polling
python main.py --mode webhook   # bot vía webhook (requiere TELEGRAM_WEBHOOK_URL)
python main.py --all            # bot + scheduler de jobs
python main.py --jobs-only      # solo scheduler (app magic-services-jobs)
python main.py --cleanup        # limpieza de suscripciones una vez (modo validar)
python main.py --promotions     # pipeline de promociones una vez
python -m jobs.expiry_warnings --days 3
```

### Comandos del bot

| Comando | Quién | Descripción |
|---|---|---|
| `/start`, `/help` | Todos | Registro y menú principal |
| `/id` | Todos | Muestra tu ID de Telegram |
| `/servicio_id` | Todos | Servicio seleccionado actualmente |
| `/valid <codigo>` | Todos | Reclamar una compra registrada desde la API externa |
| `/vm <user_id> [msg_id] <monto> [fecha]` | Validadores | Validar un pago con monto corregido (responder a la foto del comprobante evita registrarlo dos veces) |
| `/wsp <codigo>` | Validadores | Registrar un pago recibido por WhatsApp |
| `/generar_link <servicio> [user_id]`, `/link` | Validadores | Enviar un link de invitación |
| `/mensaje_recordatorio` | Validadores | Enviar el recordatorio con precios |
| `/delete <user_id>` | Validadores | Marcar la última compra como fraude/duplicada y expulsar del VIP |
| `/version` | Todos | Versión del bot |

### Flujo de compra

1. El usuario elige Stake o Grupo VIP y ve precios y datos de pago.
2. Envía la foto del comprobante; el OCR extrae monto y fecha si está disponible.
3. Cada validador recibe la foto con botones: validar, rechazar o corregir monto.
4. Al validar se registra la compra y la suscripción en una sola transacción y el usuario
   recibe su link de invitación.

Mensajes y conversación completos: [docs/flujo-conversacional.md](docs/flujo-conversacional.md),
[docs/messages-reference.md](docs/messages-reference.md).

---

## Idempotencia de pagos y suscripciones

- **Un comprobante, una compra.** La clave del comprobante es el `file_unique_id` de la foto en
  Telegram (igual para todas las copias que reciben los validadores) y se guarda en
  `purchases.payment_ref` con índice `UNIQUE`. Un doble click o un segundo validador sobre la
  misma foto responde "ya fue validado" sin registrar nada.
- **Una fila por usuario y servicio.** `subscriptions` tiene `UNIQUE (user_telegram_id, service_id)`.
  Renovar reutiliza la fila; si dos validaciones chocan, la segunda reintenta como renovación.
- **Renovaciones sin días perdidos.** Si la suscripción sigue activa, se suman días desde su
  `end_date`; si ya venció o fue desactivada, el nuevo periodo empieza en la fecha de pago.
- **Limpieza repetible.** Los jobs desactivan (`is_active = false`) en vez de borrar, expulsan
  solo si el usuario no tiene otra suscripción vigente, nunca tocan a admins del grupo ni a
  `PROTECTED_USER_IDS`, y solo marcan la fila si la expulsión funcionó. Ejecutarlos dos veces
  no vuelve a expulsar ni a avisar a nadie. El modo `validar` no escribe en la BD.
- **Fechas en hora de Lima.** Los vencimientos se comparan con `today_lima()`; los servidores corren en UTC.

---

## Tests y calidad

```bash
pip install pytest pytest-asyncio ruff
pytest          # SQLite en memoria; no usa el .env local
ruff check .
```

`tests/test_subscription_idempotency.py` cubre renovación, idempotencia del comprobante,
concurrencia y limpieza.

---

## Despliegue (Fly.io)

| App | Config | Proceso |
|---|---|---|
| `magic-services` | `fly.toml` | Bot (`python startup.py && python main.py`) |
| `magic-services-jobs` | `fly.jobs.toml` | Scheduler (`python main.py --jobs-only`), opcional |

Los jobs de producción corren en GitHub Actions; desplegar además `fly.jobs.toml` los ejecutaría
dos veces.

Los secretos se cargan con `fly secrets set VAR=valor --app <app>`; `.env` no viaja en la imagen.
Guía paso a paso: [docs/deploy-fly.md](docs/deploy-fly.md). Si el cambio incluye una migración,
aplícala antes de desplegar ([migrations/README.md](migrations/README.md)).

### GitHub Actions

| Workflow | Disparo | Qué hace |
|---|---|---|
| `ci.yml` | push / PR | Lint (ruff) y tests |
| `fly-deploy.yml` | push a `main` | Despliega el bot en Fly.io |
| `cleanup-scheduled.yml` | diario 07:00 Lima | Limpieza de suscripciones vencidas (Telethon + BD) |
| `expiry-warnings.yml` | diario 08:00 Lima | Avisa a quienes vencen pronto |
| `reminders-scheduled.yml` | cada hora | Recordatorios y promociones |
| `detect-intruders.yml` | semanal / manual | Miembros del grupo sin suscripción |
| `reconcile-report.yml`, `inspect-users.yml`, `diag-subs.yml` | manual | Reportes y diagnóstico |
| `generar-reporte-servicios.yml` | manual | Reporte mensual de servicios (Word) |
| `scheduled.yml` | cada 6 h | Health check del bot |

Los workflows operativos solo corren en el repositorio `YeyitoDev/magic-services` y necesitan sus
secretos (`TELEGRAM_*`, `DB_*`, `TELETHON_*`, `GOOGLE_CREDENTIALS_JSON`, `FLY_API_TOKEN`,
`ADMIN_CHAT_ID`, `ADMIN_NOTIFY_IDS`, `PROTECTED_USER_IDS`).

---

## Medios

Las imágenes y videos promocionales no se incluyen en el repositorio público. El bot los envía por
`file_id` de Telegram (`media_config.json`, generado con `scripts/register_file_ids.py`) y, si un
`file_id` falla, busca archivos locales en `imagenes_promocionales/` y `videos_promocionales/`.

---

## Documentación

- [docs/flujo-conversacional.md](docs/flujo-conversacional.md) — flujo de conversación
- [docs/messages-reference.md](docs/messages-reference.md) — textos que envía el bot
- [docs/original-messages.md](docs/original-messages.md) — mensajes del bot original (referencia)
- [docs/knowledge-base.md](docs/knowledge-base.md) — problemas conocidos y soluciones
- [docs/deploy-fly.md](docs/deploy-fly.md) — despliegue en Fly.io
- [docs/git-flow.md](docs/git-flow.md) — ramas y flujo de trabajo
- [migrations/README.md](migrations/README.md) — migraciones de base de datos
