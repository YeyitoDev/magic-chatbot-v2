# Flujo Conversacional Original - Magic Chatbot

> **Proyecto:** `magic-chatbot`  
> **Archivos fuente:** `main_donGato_2025.py` (handlers), `functions/mensajes_rapidos.py` (message templates)  
> **Fecha de extracción:** 2025-07-10

---

## Índice de Flujos

1. [Flujo Principal - Telegram](#1-flujo-principal---telegram)
2. [Flujo de Preguntas Frecuentes](#2-flujo-de-preguntas-frecuentes)
3. [Flujo de Validación de Pago (Business User)](#3-flujo-de-validación-de-pago-business-user)
4. [Flujo de Monto No Reconocido](#4-flujo-de-monto-no-reconocido)
5. [Flujo de Venta Duplicada](#5-flujo-de-venta-duplicada)
6. [Flujo WhatsApp](#6-flujo-whatsapp)
7. [Mensajes Promocionales](#7-mensajes-promocionales)
8. [Mensajes de Recordatorio](#8-mensajes-de-recordatorio)
9. [Mensajes de Registro Betsafe](#9-mensajes-de-registro-betsafe)
10. [Mensajes de Invitación a Grupo](#10-mensajes-de-invitación-a-grupo)

---

## 1. Flujo Principal - Telegram

### 1.1 Entrada: `/start` o primer mensaje de texto del usuario

**Handler:** `start()` en `main_donGato_2025.py:182`  
**También llamado desde:** `echo()` en `main_donGato_2025.py:1248` (cuando el usuario escribe cualquier keyword como 'vip', 'stake', etc.)

**Función de mensaje:** `mensaje_inicial_don_gato(update, context)` en `mensajes_rapidos.py:141`

**Mensaje 1 (principal con botones):**
```
¡Hola, mi gato! 🔥

Soy <b>Don Gato</b>, el Bot Asistente Virtual de <b>Magic Apuestas</b> 🐱.

¿Deseas más información sobre nuestros servicios?

¡Haz clic en la opción que prefieras! 👇
```

**Botones:**
- `STAKE MAXIMA SEGURIDAD` → callback: `consulta_tipo_servicio:stake`
- `GRUPO VIP` → callback: `consulta_tipo_servicio:grupo_vip`
- `PREGUNTAS FRECUENTES` → callback: `consulta_tipo_servicio:preguntas_frecuentes`

**Mensaje 2 (recordatorio, enviado inmediatamente después):**
```
<strong>OJO SI HAS REALIZADO TU PAGO SIMPLEMENTE ENVÍAMELO ACÁ</strong> 📲
```
*Parse mode: HTML*

---

### 1.2 Selección de Servicio: "STAKE MAXIMA SEGURIDAD" o "GRUPO VIP"

**Handler:** `button()` en `main_donGato_2025.py:382` → `context_button == 'consulta_tipo_servicio'` → `action ∈ {stake, grupo_vip}`

**Función de mensaje:** `mensaje_inforamacion_tipo_servicio(user_id, tipo_servicio, context)` en `mensajes_rapidos.py:403`

#### 1.2a Si `tipo_servicio == 'stake'`:

**Imagen:** `./imagenes_promocionales/stake_3.jpeg`

**Caption:**
```html
<b>✅ STAKE MÁXIMA SEGURIDAD ✅</b>

• El stake de máxima seguridad consta de una fija con una probabilidad de victoria mayor al 96% en el partido indicado.

• Nosotros estamos entrando con S/. 20,000 a esta jugada <b>GARANTIZADA DE VICTORIA</b>.

<b>💰 EL COSTO DEL STAKE ES DE S/. 50 💰</b>

<b>📲 DATOS DE PAGO:</b>
• <b>Titular:</b> <PAYMENT_HOLDER_NAME>
• <b>Yape/Plin:</b> <PAYMENT_YAPE_PLIN>
• <b>BCP:</b> <PAYMENT_BCP_ACCOUNT>
• <b>SCOTIA:</b> <PAYMENT_SCOTIABANK_ACCOUNT>

<b>🔥 Realiza tu depósito y envíalo a este chat 🔥</b>
```

#### 1.2b Si `tipo_servicio == 'grupo_vip'`:

**Imagen:** `./imagenes_promocionales/vip_3.jpeg`

**Caption:**
```html
<b>📈 GRUPO VIP ESTADÍSTICO 📈</b>

• El único VIP del mundo con un sistema estadístico que nos permite obtener las jugadas con la mayor probabilidad de acierto.

• Recibe de 3 a 4 jugadas diarias.

<b>🌟 BENEFICIOS:</b>
• ✅ Asesores personalizados 24/7
• ✅ Jugadas revisadas por algoritmos y expertos
• ✅ Manejamos Bank

<b>💰 COSTO MEMBRESÍAS VIP:</b>
• ⚪ S/. 125 - 1 MES
• ⚪ S/. 175 - 2 MESES
• ⚪ S/. 225 - 3 MESES

<b>📲 DATOS DE PAGO:</b>
• <b>Titular:</b> <PAYMENT_HOLDER_NAME>
• <b>Yape/Plin:</b> <PAYMENT_YAPE_PLIN>
• <b>BCP:</b> <PAYMENT_BCP_ACCOUNT>
• <b>SCOTIA:</b> <PAYMENT_SCOTIABANK_ACCOUNT>

<b>🔥 Realiza tu depósito, envíamelo a este chat y listo estás dentro 🔥</b>
```

**Mensaje adicional (ambos servicios):**
```
OJO SI HAS REALIZADO TU PAGO SIMPLEMENTE ENVÍAMELO ACÁ 📲
```
*Sin parse mode HTML*

**Acción DB:** `sql.post_servicio_seleccionado(telegram_id=user_id, service_name=action)` — guarda el servicio que el usuario seleccionó.

---

### 1.3 Usuario envía captura de pago (imagen)

**Handler:** `handle_image_button_reply()` en `main_donGato_2025.py:234`

**Mensaje al usuario (confirmación de recepción):**
```
Recibi tu voucher de pago, en un minuto procedere a validar tu pago ✅
```

**Mensaje al usuario (soporte):**
```
Para cualquier duda, consulta o si necesitas resolver un problema contáctate con @magic_peru 📲
```

**Mensaje al Business User (validadores):**
```html
<b>💰 NUEVO PAGO RECIBIDO</b>
👤 <b>Usuario:</b> <a href="tg://user?id={user_id}">{user_telegram_name}</a>
🆔 <b>ID:</b> <code>{user_id}</code>
💵 <b>Monto:</b> S/ {monto_extraido_captura}
📅 <b>Fecha:</b> {fecha_extraido_captura or 'No detectada'}
```

**Botones para el Business User:**
- `PAGO VALIDADO ✅` → callback: `validar_monto:valid:{user_id}:{monto}`
- `PAGO NO VALIDADO ❌` → callback: `validar_monto:not_valid:{user_id}:{monto}`
- `VALIDAR MONTO DE PAGO 🔵` → callback: `validar_monto:monto_no_reconocido:{user_id}:{monto}`

---

## 2. Flujo de Preguntas Frecuentes

### 2.1 Click en "PREGUNTAS FRECUENTES"

**Handler:** `button()` en `main_donGato_2025.py:386` → `tipo_servicio == 'preguntas_frecuentes'`

**Función de mensaje:** `preguntas_frecuentes(update, context)` en `mensajes_rapidos.py:189`

**Mensaje:**
```
Selecciona el servicio que deseas consultar
```

**Botones:**
- `STAKE MAXIMA SEGURIDAD` → callback: `preguntas_frecuentes:stake`
- `GRUPO VIP` → callback: `preguntas_frecuentes:grupo_vip`

---

### 2.2 Click en servicio específico de FAQ

**Handler:** `button()` en `main_donGato_2025.py:399` → `context_button == 'preguntas_frecuentes'`

**Función de mensaje:** `respuesta_preguntas_frecuentes(update, context, servicio)` en `mensajes_rapidos.py:214`

#### 2.2a Si `servicio == 'stake'`:

**Video:** `./videos_promocionales/STAKE_MAXIMA_SEGURIDAD_EXPLICACION.mp4`

**Caption:**
```html
<b>¿Qué es el Stake Máximo?</b> 🔥

👉 Acá te lo explico.

<b>Aprieta el botón y adquiere tu stake</b>
```

#### 2.2b Si `servicio == 'grupo_vip'`:

**Video:** `./videos_promocionales/GRUPO_VIP_EXPLICACION.mp4`

**Caption:**
```html
<b>¿Qué es el Grupo VIP?</b> 🔥

👉 Acá te lo explico.

<b>Aprieta el botón y adquiere tu suscripción VIP</b>
```

**Botones (ambos servicios):**
- `COMPRAR {SERVICIO}` → callback: `consulta_tipo_servicio:{servicio}`
- `VOLVER A PREGUNTAS` → callback: `consulta_tipo_servicio:preguntas_frecuentes`

---

## 3. Flujo de Validación de Pago (Business User)

**Handler:** `button()` en `main_donGato_2025.py:510` → `context_button == 'validar_monto'`

### 3.1 Pago Validado (`action == 'valid'`)

**Se envía al usuario comprador (orden de mensajes):**

1. **Mensaje de registro Betsafe:** `mensaje_registro_betsafe()` (ver sección 9)
2. **Mensaje de invitación al grupo:** `mensaje_invitacion_grupo()` (ver sección 10)

**Acciones:**
- `sql.adquirir_servicio()` — registra la compra en BD
- `sql.delete_servicio_seleccionado()` — limpia selección
- Elimina la imagen de captura del disco
- Actualiza estado del pedido a `FINISHED`

### 3.2 Pago NO Validado (`action == 'not_valid'`)

**Mensaje al usuario comprador:**
```
Tu pago ha sido rechazado ❌❌❌ Verifica si realmente has hecho la transferencia a alguna de nuestras cuentas y envialo denuevo a este chat.
Si tienes otro problema comunicate con @magic_peru2 📲
```

**Acciones:**
- Actualiza estado del pedido a `NOT VALID`
- Elimina la imagen de captura del disco

### 3.3 Monto No Reconocido (`action == 'monto_no_reconocido'`)

→ Ver [Flujo de Monto No Reconocido](#4-flujo-de-monto-no-reconocido)

---

## 4. Flujo de Monto No Reconocido

### 4.1 Canal Telegram

**Handler:** `button()` en `main_donGato_2025.py:779` → `action == 'monto_no_reconocido'` y `canal_procedencia == 'telegram'`

**Mensaje al Business User (con imagen de la transferencia):**
```html
🔍 <b>CONFIRMACIÓN DE PAGO</b>

👤 <a href="tg://user?id={user_id}">{nombre_usuario}</a>
💵 <b>Monto:</b> S/ {monto_extraido_captura}

<b>✏️ Editar:</b> <code>/vm {user_id} {message_id} [monto] [fecha]</code>
<b>💡 Ej:</b> <code>/vm {user_id} {message_id} 125 {fecha_correcta}</code>

<i>Seleccione el servicio:</i>
```

**Botones:**
- `🎯 STAKE (S/ 50)` → callback: `buttom_validar_monto:valid:{user_id}:50`
- `💎 1 mes` → callback: `buttom_validar_monto:valid:{user_id}:125`
- `💎 2 meses` → callback: `buttom_validar_monto:valid:{user_id}:175`
- `💎 3 meses` → callback: `buttom_validar_monto:valid:{user_id}:225`
- `❌ CANCELAR` → callback: `buttom_validar_monto:cancel:{user_id}`

### 4.2 Botón de servicio rápido (`buttom_validar_monto:valid`)

**Handler:** `button()` en `main_donGato_2025.py:842`

Mismo flujo que validación normal (sección 3.1): envía `mensaje_registro_betsafe()` + `mensaje_invitacion_grupo()`.

### 4.3 Botón Cancelar (`buttom_validar_monto:cancel`)

**Handler:** `button()` en `main_donGato_2025.py:842` → `action == 'cancel'`

**Mensaje al usuario comprador:**
```
Tu pago ha sido rechazado ❌❌❌ Verifica si realmente has hecho la transferencia a alguna de nuestras cuentas y envialo denuevo a este chat.
Si tienes otro problema comunicate con @magic_peru2 📲
```

### 4.4 Canal WhatsApp

**Mensaje al Business User:**
```
Ingrese el monto correcto para el usuario {nombre_usuario}.
El monto que se encontró fue de S/ {monto_extraido_captura}.
Responda con el formato:
```
```
/vm {user_id} {message_id} wsp [monto_correcto]
```

### 4.5 Comando `/vm` (Validación Manual de Monto)

**Handler:** `validar_monto()` en `main_donGato_2025.py:908`  
**Activación:** El business user escribe `/vm {user_id} {message_id} {monto} [{fecha}]`  
**También se activa por:** `echo()` cuando detecta `/vm` en el mensaje

**Formato esperado:**
```
/vm {user_id} {message_id} {monto_correcto} [fecha_correcta] [wsp]
```

**Si la compra es exitosa:** mismo flujo que validación normal → `mensaje_registro_betsafe()` + `mensaje_invitacion_grupo()`.

---

## 5. Flujo de Venta Duplicada

**Se activa en:** `handle_image_button_reply()` y `button()` → `validar_monto` cuando `sql.get_recent_purchases()` retorna datos (el usuario ya compró en las últimas 24h).

### 5.1 Mensaje al usuario comprador

**Función:** `restriccion_por_duplicado_venta()` en `mensajes_rapidos.py:488`

**Mensaje:**
```html
<strong>🐾 ¡Mi gato!</strong>

<strong>Has adquirido el servicio:</strong> {tipo_servicio}

<strong>Fecha de compra:</strong> {purchase_date}

<strong>Monto:</strong> {monto_extraido_captura} soles

<strong>Revisa nuestro chat, ahí encontrarás el enlace.</strong>

<strong>De todas formas, también te lo dejo aquí ⬇️</strong>
```

**Botón:**
- `✅ INGRESA AL GRUPO ACÁ ✅` → URL: `{invite_link}`

### 5.2 Mensaje al Business User

**Función:** `restriccion_por_duplicado_venta_busines_user()` en `mensajes_rapidos.py:512`

**Mensaje:**
```html
<strong>⚠️ Validación de compra duplicada detectada</strong>

<strong>El usuario con ID:</strong> {user_id}

<strong>Ya adquirió previamente el servicio:</strong> {tipo_servicio}

<strong>Fecha de compra:</strong> {purchase_date}

<strong>Monto pagado:</strong> {monto_extraido_captura} soles

<strong>Enlace de acceso al grupo asociado:</strong> {invite_link}
```

---

## 6. Flujo WhatsApp

### 6.1 Inicio desde WhatsApp

**Handler:** `registro_usuario_wsp()` en `main_donGato_2025.py:1145`

**Mensaje de confirmación al usuario:**
```html
<strong>Recibi tu voucher de pago, en un minuto procedere a validar tu pago ✅</strong>
```

### 6.2 Selección de servicio (WhatsApp)

**Función:** `mensaje_wsp_inicial_directo()` en `mensajes_rapidos.py:467`

**Mensaje:**
```
Hola mi gato 🔮, Por favor selecciona el servicio que desees validar
```

**Botones:**
- `STAKE MAXIMA SEGURIDAD` → callback: `servicio_seleccionado_wsp:stake`
- `GRUPO VIP` → callback: `servicio_seleccionado_wsp:grupo_vip`

### 6.3 Solicitud de captura (WhatsApp)

**Función:** `mensaje_wsp_envio_captura()` en `mensajes_rapidos.py:481`

**Mensaje:**
```
Ya casi... ahora envíame una captura de tu pago a este chat! 📸🔥
```

---

## 7. Mensajes Promocionales

### 7.1 Promo Bono 1

**Función:** `mensaje_promo_bono_1()` en `mensajes_rapidos.py:261`

**Mensaje:**
```html
<b>¡TE REGALO 70 LUCAS MI KING!</b>
Regístrate con el link exclusivo, haz tu primer depósito de mínimo S/.40 y listo tendrás 70 soles gratis.
Mira este video con el paso a paso de cómo llevarte los S/. 70 gratis ⬆️
```

**Botón:**
- `OBTÉN TUS 70 SOLES GRATIS` → URL: `https://bit.ly/promobetsafemagic`

### 7.2 Promo Bono 2

**Función:** `mensaje_promo_bono_2()` en `mensajes_rapidos.py:285`

**Mensaje:**
```html
<b>REGALO 70 LUCAS A TODOS!!</b>
<b>ULTIMO LLAMADO GENTE!!!!!</b>
Regístrate con el link exclusivo, haz tu primer depósito de minimo S/.40 y listo tendrás 70
soles gratis.
Mira este video con el paso a paso de cómo llevarte los S/. 70 gratis ⬆️��
```

**Botón:**
- `OBTÉN TUS 70 SOLES GRATIS` → URL: `https://bit.ly/promobetsafemagic`

---

## 8. Mensajes de Recordatorio

### 8.1 Recordatorio de Venta (usuario no ha enviado pago)

**Función:** `mensaje_recordatorio_venta()` en `mensajes_rapidos.py:319`

**Mensaje:**
```
Hermano todavía no nos llega tu pago te quedó alguna duda si ese el caso escríbeme @magic_peru 📲
                En toda caso si quieres info de los servicios dale click aca ⤵️
```

**Botones:**
- `STAKE MAXIMA SEGURIDAD` → callback: `consulta_tipo_servicio:stake`
- `GRUPO VIP` → callback: `consulta_tipo_servicio:grupo_vip`

**También notifica al canal de recordatorio** (`CHATBOT_RECORDATORIO_ID = -100YYYYYYYYYY`):
```
Se envio mensaje recodatario a {user_id}
```

### 8.2 Comando Recordatorio (para el chatbot de recordatorios)

**Función:** `comando_recordatorio_chatbot_flujo_regular()` en `mensajes_rapidos.py:336`

**Mensaje (enviado al canal recordatorio):**
```
/mensaje_recordatorio {user_id}
```

### 8.3 Recordatorio de Compra de Servicio

**Función:** `mensaje_recordatorio_compra_servicio()` en `mensajes_rapidos.py:377`

**Mensaje:**
```
Hola mi gato, para ingresar al {service_name} solo tienes que enviar el screenshot de tu pago y listo ✅
```
*Nota: `service_name` tiene underscores removidos y se muestra en mayúsculas.*

### 8.4 Consulta de Información de Tipo de Servicio

**Función:** `mensaje_consulta_informacion_tipo_servicio()` en `mensajes_rapidos.py:388`

**Mensaje:**
```
Mi gato, Has click sobre el servicio que desees conocer
Si tienes una duda puntual porfavor contacta al siguiente usuario, ojo no responderemos preguntas básicas. @magic_peru 🔮
```

**Botones:**
- `STAKE MAXIMA SEGURIDAD` → callback: `consulta_tipo_servicio:stake`
- `GRUPO VIP` → callback: `consulta_tipo_servicio:grupo_vip`

---

## 9. Mensajes de Registro Betsafe

**Función:** `mensaje_registro_betsafe()` en `mensajes_rapidos.py:347`

**Se envía después de una compra validada exitosamente.** Es parte de la secuencia de confirmación de compra.

**Imagen:** `./imagenes_promocionales/betsafe_logo.jpeg`

**Caption:**
```
INFORMACION ULTRA IMPORTANTE 🆘🆘🆘
Todas nuestras apuestas estadisticas son realizadas en Betsafe debido a que es la unica casa en el mundo que nos da las mejores opciones estadisticas en todas las ligas de futbol. Solo juego aca y no tengo segunda opcion para las personas que apuestan en otras casas por favor registrate en esta casa y usa el link de abajo para que tu cuenta jamas sea bloqueada o limitada.
LINK EXCLUSIVO DE BETSAFE ⤵️
https://bit.ly/promobetsafemagic
```

---

## 10. Mensajes de Invitación a Grupo

**Función:** `mensaje_invitacion_grupo()` en `mensajes_rapidos.py:356`

**Se envía después de `mensaje_registro_betsafe()`.** Es el último paso de la confirmación de compra.

### 10.1 Para Stake

**Imagen:** `./imagenes_promocionales/stake_logo.jpeg`

**Caption:**
```
Únete al siguiente ENLACE para tener acceso al STAKE MAXIMO ⬇️
```

**Botón:**
- `✅ INGRESA AL STAKE ACÁ ✅` → URL: `{invite_link}`

### 10.2 Para Grupo VIP

**Imagen:** `./imagenes_promocionales/magic_logo.jpeg`

**Caption:**
```
Únete al siguiente ENLACE para tener acceso al GRUPO VIP ⬇️
```

**Botón:**
- `✅ INGRESA AL VIP ACÁ ✅` → URL: `{invite_link}`

---

## 11. Mensajes de Información de Servicio (antiguo - parcialmente en desuso)

### 11.1 `mensaje_inicial_completo()`

**Función:** `mensaje_inicial_completo()` en `mensajes_rapidos.py:78`

**Mensaje:**
```
Hola mi gato 🔮
Bienvenido a Magic Apuestas

Deseas información sobre nuestros servicios:
```

**Botones:**
- `STAKE MAXIMA SEGURIDAD` → callback: `consulta_tipo_servicio:stake`
- `GRUPO VIP` → callback: `consulta_tipo_servicio:grupo_vip`
- `CONSULTA PUNTUAL` → callback: `consulta_tipo_servicio:consulta_puntual`

### 11.2 `mensaje_inicial_directo_captura()`

**Función:** `mensaje_inicial_directo_captura()` en `mensajes_rapidos.py:99`

**Mensaje:**
```html
<strong>Hola 🔮 ¿qué servicio deseas validar?</strong>
```

**Botones:**
- `STAKE MAXIMA SEGURIDAD` → callback: `consulta_tipo_servicio:stake`
- `GRUPO VIP` → callback: `consulta_tipo_servicio:grupo_vip`

### 11.3 `mensaje_inicial_directo_texto()`

**Función:** `mensaje_inicial_directo_texto()` en `mensajes_rapidos.py:114`

**Mensaje 1:**
```html
<strong>Hola 🔮 ¿qué servicio deseas?</strong>
```

**Mensaje 2:**
```html
<strong>OJO SI HAS REALIZADO TU PAGO SIMPLEMENTE ENVÍAMELO ACÁ</strong> 📲
```

**Botones:**
- `STAKE MAXIMA SEGURIDAD` → callback: `consulta_tipo_servicio:stake`
- `GRUPO VIP` → callback: `consulta_tipo_servicio:grupo_vip`

### 11.4 Info de Servicio inline (antiguo `informacion_servicio`)

**Handler:** `button()` en `main_donGato_2025.py:363` → `context_button == 'informacion_servicio'`

#### Stake:
```
El stake de máxima seguridad consta de una apuesta con una probabilidad de acierto mayor al 96% en el partido indicado. Nosotros estamos entrando con S/. 20,000 a esta jugada. GARANTIZADA DE VICTORIA.
```
**Imagen:** `./imagenes_promocionales/stake_maximo.png`

#### Grupo VIP:
```
En el grupo VIP recibirás diariamente entre 3 a 4 pronósticos estadísticos con la probabilidad más alta de ganar. En este grupo solo realizamos apuestas 100% estadísticas seleccionadas por nuestros analistas donde también tendrás asesoría directa por ellos para colocar las jugadas
```
**Imágenes:** `./imagenes_promocionales/grupo_vip_1.jpg` y `./imagenes_promocionales/grupo_vip_2.jpg`

---

## 12. Mensaje de Cambio de Bot

**Función:** `aviso_informe_pasar_nueva_cuenta()` en `mensajes_rapidos.py:312`

**Mensaje:**
```
Hermano utiliza nuestro nuevo bot aquí @elmagopagos_bot 🔮
```

---

## 13. Mensajes de "No Compra" (cuando el usuario rechaza comprar)

**Handler:** `button()` en `main_donGato_2025.py:488` → `context_button == 'comprar_servicio'` → `respuesta_compra_user == 'no'`

**Mensaje:**
```
Seguro la proxima te animas mi gato, te recomiendo seguir jugando las apuestas gratis que enviamos por el grupo y te regalo un bono de S/. 40 en la mejor casa de apuestas del mundo
```

**Imagen:** `./imagenes_promocionales/betsafe_logo.jpeg`

**Botón:**
- `REGRESAR A MENU PRINCIPAL ✅` → callback: `regresar_menu_principal:si`

---

## 14. Mensaje de Agradecimiento (WhatsApp - en desuso parcial)

**Handler:** `registro_usuario_wsp()` en `main_donGato_2025.py:1225`

**Mensaje:**
```
Gracias mi gato. Este el enlace para unirte al grupo Stake: {invite_link}
```

---

## Resumen del Orden de Ejecución (Happy Path)

```
Usuario Nuevo → /start
  └─ mensaje_inicial_don_gato()           # Bienvenida + botones de servicio + recordatorio de pago
  
Usuario clickea "STAKE MAXIMA SEGURIDAD"
  └─ button() → consulta_tipo_servicio:stake
      └─ mensaje_inforamacion_tipo_servicio(stake)  # Imagen + precios + datos de pago
      └─ "OJO SI HAS REALIZADO TU PAGO..."          # Recordatorio

Usuario envía captura de pago
  └─ handle_image_button_reply()
      └─ "Recibi tu voucher de pago..."             # Al usuario
      └─ "Para cualquier duda..."                   # Al usuario
      └─ Foto + datos al business user              # A validadores

Business User clickea "PAGO VALIDADO ✅"
  └─ button() → validar_monto:valid
      └─ sql.adquirir_servicio()                    # Registro en BD
      └─ mensaje_registro_betsafe()                 # Info Betsafe
      └─ mensaje_invitacion_grupo()                 # Link de acceso al grupo
```

---

## Notas Importantes

1. **Parse Mode:** La mayoría de mensajes usan `ParseMode.HTML`. Algunos mensajes antiguos no usan parse mode.
2. **Canales de procedencia:** `telegram` (default) y `wsp` (WhatsApp). El flujo varía ligeramente según el canal.
3. **Imágenes:** Las imágenes promocionales están en `./imagenes_promocionales/`. Las capturas de usuario en `./images/trans_{user_id}.jpeg`.
4. **Videos:** Los videos explicativos están en `./videos_promocionales/`.
5. **Datos de pago:** hoy se configuran con las variables `PAYMENT_*` (ver README).
6. **Contactos de soporte:** Se alterna entre `@magic_peru` y `@magic_peru2`.
