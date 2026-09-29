# Knowledge Base - Magic Chatbot v2
## Problemas conocidos y soluciones

> Documento vivo: cada vez que aparece un bug nuevo en producción, registrarlo aquí con síntoma, causa raíz, diagnóstico y solución. Esto evita tener que redescubrir la causa en futuras incidencias.

---

## Índice

1. [BD: PendingRollbackError (sesión compartida)](#1-bd-pendingrollBACKERror-sesión-compartida)
2. [BD: NoneType has no attribute 'chat'](#2-bdg-nonetype-has-no-attribute-chat)
3. [Telegram: Query is too old (callback expirado)](#3-telegram-query-is-too-old-callback-expirado)
4. [Telegram: createChatInviteLink 400 Bad Request](#4-telegram-createchatinvitelink-400-bad-request)
5. [Config: GEMINI_API_KEY no configurada](#5-config-gemini_api_key-no-configurada)
6. [Config: AWS credenciales faltantes (DynamoDB)](#6-config-aws-credenciales-faltantes-dynamodb)
7. [Job: Usuarios "no registrados en BD" eliminados](#7-job-usuarios-no-registrados-en-bd-eliminados)
8. [Seguridad: Credenciales sensibles en el repo](#8-seguridad-credenciales-sensibles-en-el-repo)

---

## 1. BD: PendingRollbackError (sesión compartida)

**Síntoma:**
- El usuario recibe el mensaje genérico: *"❌ Lo siento, ocurrió un error inesperado..."*
- Logs: `sqlalchemy.exc.PendingRollbackError: Can't reconnect until invalid transaction is rolled back.`
- El error afecta en cascada: una vez que falla una query, **todas las siguientes fallan** hasta reiniciar el bot.
- La foto del comprobante puede llegar al validador (usa API de Telegram), pero la validación posterior falla.

**Causa raíz:**
El contenedor IoC (`core/container.py`) registra `db_session` como **singleton**: se crea **una sola sesión de SQLAlchemy** que comparten todos los repositorios durante toda la vida de la app.

Cuando una consulta falla (ej: RDS cierra la conexión por inactividad, timeout de red, etc.), SQLAlchemy deja la sesión en estado "transacción inválida". Como la misma sesión se reutiliza para siempre y **nunca se hace rollback**, todas las operaciones posteriores fallan con `PendingRollbackError`.

Muchas operaciones **capturan el error internamente sin hacer rollback** (ej: `Error al registrar usuario...`, `Error al registrar interacción...`), lo que deja la sesión sucia para la siguiente petición.

**Diagnóstico:**
```bash
flyctl logs -a magic-services --no-tail 2>&1 | grep -iE "PendingRollbackError|rollback|Can't reconnect"
```

**Solución:**
1. **Hook de pre-procesamiento** (`main.py:274-301`): `TypeHandler` en `group=-1` que ejecuta `session.rollback()` al inicio de **cada update** (antes de cualquier otro handler). Esto rompe la cascada entre mensajes.
2. El engine ya tenía `pool_pre_ping=True` y `pool_recycle=280`, pero eso solo detecta conexiones muertas — no limpia transacciones inválidas.

**Código aplicado:**
```python
# main.py - Hook de saneamiento de sesión de BD (group=-1)
async def _ensure_clean_db_session(update, context):
    try:
        if container.is_registered("db_session"):
            session = container.resolve("db_session")
            session.rollback()  # Limpia cualquier transacción inválida
    except Exception:
        from core.database import engine
        engine.dispose()  # Último recurso: reciclar pool

app.add_handler(TypeHandler(Update, _ensure_clean_db_session), group=-1)
```

**Lección aprendida:**
Con sesiones compartidas (singleton), cada petición que puede fallar debe dejar la sesión limpia. `pool_pre_ping` detecta conexiones muertas pero no limpia transacciones en estado inválido. El `rollback()` preventivo antes de cada update es la defensa más robusta.

---

## 2. BD: NoneType has no attribute 'chat'

**Síntoma:**
- Error en logs: `'NoneType' object has no attribute 'chat'`
- Sucede en el handler `echo` (`handlers/messages.py`) cuando el usuario **edita** un mensaje de texto.
- Telegram envía `update.edited_message` y `update.message` queda en `None`.

**Causa raíz:**
El `MessageHandler` (filters.TEXT & ~filters.COMMAND) procesa tanto mensajes normales como **mensajes editados** por defecto. El código accede a `update.message.chat.type` sin verificar que `update.message` exista.

```python
# ANTES (vulnerable):
chat_type = update.message.chat.type  # CRASH si update.message es None
```

**Diagnóstico:**
```bash
flyctl logs -a magic-services --no-tail 2>&1 | grep -iE "NoneType.*chat|AttributeError"
```

**Solución:**
Guard clause al inicio del handler:

```python
# handlers/messages.py:137-142
if not update.message or not update.message.from_user:
    logger.debug("echo: update sin message/from_user, ignorando.")
    return

chat_type = update.message.chat.type
user_id = int(update.message.from_user.id)
```

**Lección aprendida:**
Siempre verificar que `update.message` exista antes de acceder a atributos. Telegram envía updates de tipos variados (edited_message, channel_post, etc.) y el MessageHandler los captura todos.

**Mismo patrón en callbacks:** `query.message` puede ser `None` para botones de mensajes >48h. Protegido en `_handle_payment_validation`:
```python
message_id = query.message.message_id if query.message else None
```

---

## 3. Telegram: Query is too old (callback expirado)

**Síntoma:**
- Error en logs: `telegram.error.BadRequest: Query is too old and response timeout expired or query id is invalid`
- El error handler global le envía al usuario el mensaje genérico de error por hacer clic en un botón viejo.

**Causa raíz:**
Cuando el bot está lento o reiniciando, los callbacks de botones quedan en cola. Telegram da ~15 segundos para responder a un callback con `query.answer()`. Si se procesa pasado ese tiempo, `query.answer()` lanza excepción.

**Diagnóstico:**
```bash
flyctl logs -a magic-services --no-tail 2>&1 | grep -iE "Query is too old"
```

**Solución:**
Hacer `query.answer()` defensivo — capturar el error sin escalar al handler global:

```python
# handlers/callbacks.py:139-142
try:
    await query.answer()
except Exception as e:
    logger.warning(f"No se pudo responder el callback (probablemente expirado): {e}")
```

**Lección aprendida:**
`query.answer()` debe ser siempre defensivo. Un callback expirado no es un error real — solo significa que el usuario hizo clic en un botón viejo mientras el bot estaba lento.

---

## 4. Telegram: createChatInviteLink 400 Bad Request

**Síntoma:**
- Error en logs: `Error HTTP en createChatInviteLink: 400 Client Error: Bad Request for url: https://api.telegram.org/bot<TOKEN>/createChatInviteLink`
- Los validadores no pueden generar links de invitación VIP para nuevos compradores.
- El sistema cae al fallback del bot principal (puede funcionar o no, dependiendo de permisos).

**Causa raíz:**
El bot configurado en `TELEGRAM_BOT_TOKEN_LINKS` (bot de links) **no es admin del grupo VIP** (`-100XXXXXXXXXX`). Telegram responde `"chat not found"` cuando el bot no está en el chat.

**Diagnóstico:**
```bash
# Verificar si el bot es admin del grupo
curl -s "https://api.telegram.org/bot<TOKEN>/getChatMember?chat_id=-100XXXXXXXXXX&user_id=<BOT_ID>" | python3 -m json.tool
# Si dice "chat not found" → el bot no está en el grupo
```

**Solución:**
Actualizar el secret `TELEGRAM_BOT_TOKEN_LINKS` en producción al token del bot que **SÍ es admin** del grupo VIP.

```bash
# Bot correcto en producción: <BOT_ID> (@elmagopagos_bot)
# Verificado: es administrator con can_invite_users=True
flyctl secrets set TELEGRAM_BOT_TOKEN_LINKS="<token_correcto>" -a magic-services
```

**Lección aprendida:**
`createChatInviteLink` requiere que el bot sea admin del grupo con permiso `can_invite_users`. Cuando cambia el token de producción (ej: de un bot de desarrollo al bot productivo), verificar explícitamente que el bot esté en el grupo VIP como admin.

---

## 5. Config: GEMINI_API_KEY no configurada

**Síntoma:**
- Log: `Gemini Vision no detectó precio: GEMINI_API_KEY no configurada, usando fallback OCR`
- Los montos extraídos de comprobantes son imprecisos (ej: `S/ 1.57` en vez de `S/ 50.00`)
- La validación de compra se complica o falla.

**Causa raíz:**
La variable de entorno `GEMINI_API_KEY` no está configurada en producción (Fly.io). Sin ella, el sistema cae al fallback OCR (Google Vision) que es menos preciso con comprobantes de pago.

**Diagnóstico:**
```bash
flyctl secrets list -a magic-services | grep GEMINI
# Si no aparece → no está configurada
```

**Solución:**
```bash
flyctl secrets set GEMINI_API_KEY="<tu_api_key>" -a magic-services
```

**Lección aprendida:**
La extracción de montos usa un pipeline híbrido: Gemini Vision (IA) primero, OCR fallback. Sin Gemini, la precisión baja drásticamente. Configurar siempre `GEMINI_API_KEY` en producción.

---

## 6. Config: AWS credenciales faltantes (DynamoDB)

**Síntoma:**
- Log: `No se pudo registrar usuario XXXXX en DynamoDB: Unable to locate credentials`
- El pipeline de promociones no funciona (no registra usuarios nuevos en DynamoDB).
- El job de promociones (`promotion_batch.py`) falla silenciosamente.

**Causa raíz:**
Faltan `AWS_ACCESS_KEY_ID` y `AWS_SECRET_ACCESS_KEY` en los secrets de Fly.io. Solo está `AWS_REGION`. El servicio `PromotionService` necesita credenciales AWS para escribir en DynamoDB.

**Diagnóstico:**
```bash
flyctl secrets list -a magic-services | grep -iE "AWS|DYNAMO"
# Si solo aparece AWS_REGION → faltan las credenciales
```

**Solución:**
```bash
flyctl secrets set AWS_ACCESS_KEY_ID="<key>" AWS_SECRET_ACCESS_KEY="<secret>" -a magic-services
```

**Lección aprendida:**
`AWS_REGION` sola no basta. DynamoDB (usado por PromotionService) requiere `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY`. Sin ellos, el pipeline de promociones está inactivo.

---

## 7. Job: Usuarios "no registrados en BD" eliminados

**Síntoma:**
- Usuarios que están en el grupo VIP pero no tienen registro en la BD son expulsados por el job de limpieza.
- Algunos de estos usuarios **sí compraron** pero la validación falló (error transitorio, bug, etc.) y nunca se registró su suscripción.
- Se necesita validar manualmente antes de expulsar.

**Causa raíz:**
El `SubscriptionCleanupJob` marca `eliminar = True` por defecto para todos los usuarios de Telegram, y luego solo cambia a `False` si encuentran una suscripción activa. Usuarios sin suscripción en BD ("no registrados") quedaban marcados para eliminación.

**Solución aplicada:**
1. `_build_comparison` (`subscription_cleanup.py:778`): `eliminar = False` por defecto para "Usuario no registrado en BD".
2. `_classify_users` (`subscription_cleanup.py:844-850`): excluye SIEMPRE a "no registrados en BD" de `to_remove`, sin importar el flag `validate_special_clients`.

```python
# Fuente: eliminar = False para no registrados
mensaje = "Usuario no registrado en BD"
eliminar = False  # NUNCA eliminar automáticamente

# Clasificación: excluir SIEMPRE de to_remove
to_remove = comparison_df[
    (comparison_df["eliminar_suscripcion"]) &
    (comparison_df["mensaje"] != "Usuario no registrado en BD")
].copy()
```

**Lección aprendida:**
Los usuarios "no registrados en BD" pueden ser compradores cuya validación falló por algún error transitorio. Nunca eliminarlos automáticamente — requieren revisión manual por soporte para determinar si son legítimos o intrusos.

---

## 8. Seguridad: Credenciales sensibles en el repo

**Síntoma:**
- Archivo `credentials/magic-chatbottelegram-948350ae1b51.json` (clave privada de Google Service Account) está en el repo.
- Si el repo es público o se comparte, la clave privada queda expuesta.

**Causa raíz:**
Las credenciales de Google se guardan localmente en `credentials/` y no están adecuadamente protegidas.

**Diagnóstico:**
```bash
git ls-files credentials/ | head
grep -nE "credentials|\.json|\.env" .gitignore
```

**Solución:**
1. **Rotar la clave privada inmediatamente** en Google Cloud Console:
   - Ir a IAM & Admin → Service Accounts → `<service-account>@<project>.iam.gserviceaccount.com`
   - Keys → Add Key → Create new key → JSON
   - Eliminar la clave anterior (`948350ae1b51`)
2. Guardar el nuevo JSON como secreto en Fly (NO en el repo):
   ```bash
   flyctl secrets set GOOGLE_CREDENTIALS_JSON="$(cat nuevo-archivo.json)" -a magic-services
   ```
   Nota: `startup.py` lee `GOOGLE_CREDENTIALS_JSON` del environment y escribe `credentials/google.json` al arrancar.
3. Agregar `credentials/*.json` al `.gitignore` (excepto templates/ficticios).
4. Para entornos locales, usar `.env` (que sí está en `.gitignore`).

**Lección aprendida:**
Nunca commitear claves privadas de servicio al repo. Usar variables de entorno (Fly secrets) y que el startup script las escriba al filesystem si es necesario.

---

## Checklist de deploy a producción

Antes de cada deploy, verificar:

- [ ] `TELEGRAM_BOT_TOKEN_LINKS` apunta al bot admin del grupo VIP (`<BOT_ID>`)
- [ ] `GEMINI_API_KEY` configurada (para precisión en extracción de montos)
- [ ] `AWS_ACCESS_KEY_ID` + `AWS_SECRET_ACCESS_KEY` configuradas (DynamoDB/Promotions)
- [ ] No hay credenciales sensibles commiteadas en el repo
- [ ] `.gitignore` incluye `credentials/*.json`, `.env`

## Comandos útiles para diagnóstico

```bash
# Ver logs recientes
flyctl logs -a magic-services --no-tail 2>&1 | tail -50

# Filtrar errores
flyctl logs -a magic-services --no-tail 2>&1 | grep -iE "ERROR|Exception|Traceback|Failed"

# Verificar secrets
flyctl secrets list -a magic-services

# Verificar estado del bot
curl -s https://magic-services.fly.dev/ | head

# Re-deploy manual
flyctl deploy -a magic-services
```
