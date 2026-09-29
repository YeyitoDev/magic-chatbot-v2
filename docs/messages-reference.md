# Magic Apuestas Bot — Full Message Reference

> Extracted verbatim from `functions/mensajes_rapidos.py`
> Date: 2025-07-10

---

## `mensaje_inicial_don_gato`

**Parse mode:** `HTML`

**Message (primary):**
```
¡Hola, mi gato! 🔥

Soy <b>Don Gato</b>, el Bot Asistente Virtual de <b>Magic Apuestas</b> 🐱.

¿Deseas más información sobre nuestros servicios?

¡Haz clic en la opción que prefieras! 👇
```

**Keyboard (InlineKeyboardMarkup):**
| Button Text | Callback Data |
|---|---|
| STAKE MAXIMA SEGURIDAD | `consulta_tipo_servicio:stake` |
| GRUPO VIP | `consulta_tipo_servicio:grupo_vip` |
| PREGUNTAS FRECUENTES | `consulta_tipo_servicio:preguntas_frecuentes` |

**Message (follow-up, sent immediately after):**
```
<strong>OJO SI HAS REALIZADO TU PAGO SIMPLEMENTE ENVÍAMELO ACÁ</strong> 📲
```
- Parse mode: `HTML`
- Keyboard: none

---

## `mensaje_inforamacion_tipo_servicio`

**Parse mode:** `HTML`

**Variant: `stake`**

Sent as a photo caption (`send_photo`). Image: `./imagenes_promocionales/stake_3.jpeg`

```
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

**Keyboard:** none

---

**Variant: `grupo_vip`**

Sent as a photo caption (`send_photo`). Image: `./imagenes_promocionales/vip_3.jpeg`

```
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

**Keyboard:** none

**Follow-up message (both variants, sent immediately after photo):**
```
OJO SI HAS REALIZADO TU PAGO SIMPLEMENTE ENVÍAMELO ACÁ 📲
```
- Parse mode: none
- Keyboard: none

---

## `preguntas_frecuentes`

**Parse mode:** `HTML`

**Message:**
```
 Selecciona el servicio que deseas consultar 
```

**Keyboard (InlineKeyboardMarkup):**
| Button Text | Callback Data |
|---|---|
| STAKE MAXIMA SEGURIDAD | `preguntas_frecuentes:stake` |
| GRUPO VIP | `preguntas_frecuentes:grupo_vip` |

---

## `respuesta_preguntas_frecuentes`

**Parse mode:** `HTML`

**Variant: `stake`**

Sent as a video caption via `enviar_video_respuesta`. Video: `./videos_promocionales/STAKE_MAXIMA_SEGURIDAD_EXPLICACION.mp4`

```
<b>¿Qué es el Stake Máximo?</b> 🔥

👉 Acá te lo explico.

<b>Aprieta el botón y adquiere tu stake</b>
```

**Keyboard (InlineKeyboardMarkup):**
| Button Text | Callback Data |
|---|---|
| COMPRAR STAKE | `consulta_tipo_servicio:stake` |
| VOLVER A PREGUNTAS | `consulta_tipo_servicio:preguntas_frecuentes` |

---

**Variant: `grupo_vip`**

Sent as a video caption via `enviar_video_respuesta`. Video: `./videos_promocionales/GRUPO_VIP_EXPLICACION.mp4`

```
<b>¿Qué es el Grupo VIP?</b> 🔥

👉 Acá te lo explico.

<b>Aprieta el botón y adquiere tu suscripción VIP</b>
```

**Keyboard (InlineKeyboardMarkup):**
| Button Text | Callback Data |
|---|---|
| COMPRAR GRUPO_VIP | `consulta_tipo_servicio:grupo_vip` |
| VOLVER A PREGUNTAS | `consulta_tipo_servicio:preguntas_frecuentes` |

---

## `mensaje_registro_betsafe`

**Parse mode:** none (not set)

Sent as a photo caption (`send_photo`). Image: `./imagenes_promocionales/betsafe_logo.jpeg`

```
INFORMACION ULTRA IMPORTANTE 🆘🆘🆘
Todas nuestras apuestas estadisticas son realizadas en Betsafe debido a que es la unica casa en el mundo que nos da las mejores opciones estadisticas en todas las ligas de futbol. Solo juego aca y no tengo segunda opcion para las personas que apuestan en otras casas por favor registrate en esta casa y usa el link de abajo para que tu cuenta jamas sea bloqueada o limitada.
LINK EXCLUSIVO DE BETSAFE ⤵️
https://bit.ly/promobetsafemagic
```

**Keyboard:** none

---

## `mensaje_invitacion_grupo`

**Parse mode:** none (not set)

**Variant: `stake`**

Sent as a photo caption (`send_photo`). Image: `./imagenes_promocionales/stake_logo.jpeg`

```
Únete al siguiente ENLACE para tener acceso al STAKE MAXIMO ⬇️
```

**Keyboard (InlineKeyboardMarkup):**
| Button Text | URL |
|---|---|
| ✅ INGRESA AL STAKE ACÁ ✅ | `{invite_link}` (dynamic) |

---

**Variant: `grupo_vip`**

Sent as a photo caption (`send_photo`). Image: `./imagenes_promocionales/magic_logo.jpeg`

```
Únete al siguiente ENLACE para tener acceso al GRUPO VIP ⬇️
```

**Keyboard (InlineKeyboardMarkup):**
| Button Text | URL |
|---|---|
| ✅ INGRESA AL VIP ACÁ ✅ | `{invite_link}` (dynamic) |

---

## `mensaje_recordatorio_venta`

**Parse mode:** none (not set)

**Message:**
```
Hermano todavía no nos llega tu pago te quedó alguna duda si ese el caso escríbeme @magic_peru 📲
                En toda caso si quieres info de los servicios dale click aca ⤵️
```

**Keyboard (InlineKeyboardMarkup):**
| Button Text | Callback Data |
|---|---|
| STAKE MAXIMA SEGURIDAD | `consulta_tipo_servicio:stake` |
| GRUPO VIP | `consulta_tipo_servicio:grupo_vip` |

**Side effect:** Also sends a notification message `"Se envio mensaje recodatario a {user_id}"` to `CHATBOT_RECORDATORIO_ID` (`-100YYYYYYYYYY`).

---

## `comando_recordatorio_chatbot_flujo_regular`

**Parse mode:** none (not set)

**Message:**
```
/mensaje_recordatorio {user_id}
```

**Keyboard:** none

**Note:** This message is sent to `CHATBOT_RECORDATORIO_ID` (`-100YYYYYYYYYY`), not to the end user. It's a forwarding/relay command intended for another bot process to pick up.

---

## Bonus: Other messages in the file

### `mensaje_inicial_completo` (L78-95)

**Parse mode:** none

**Message:**
```
Hola mi gato 🔮
Bienvenido a Magic Apuestas

Deseas información sobre nuestros servicios:
```

**Keyboard:**
| Button Text | Callback Data |
|---|---|
| STAKE MAXIMA SEGURIDAD | `consulta_tipo_servicio:stake` |
| GRUPO VIP | `consulta_tipo_servicio:grupo_vip` |
| CONSULTA PUNTUAL | `consulta_tipo_servicio:consulta_puntual` |

---

### `mensaje_inicial_directo_captura` (L99-112)

**Parse mode:** `HTML`

**Message:**
```
<strong>Hola 🔮 ¿qué servicio deseas validar?</strong>
```

**Keyboard:**
| Button Text | Callback Data |
|---|---|
| STAKE MAXIMA SEGURIDAD | `consulta_tipo_servicio:stake` |
| GRUPO VIP | `consulta_tipo_servicio:grupo_vip` |

---

### `mensaje_inicial_directo_texto` (L114-139)

**Parse mode:** `HTML`

**Message 1:**
```
<strong>Hola 🔮 ¿qué servicio deseas?</strong>
```

**Keyboard (on message 1):**
| Button Text | Callback Data |
|---|---|
| STAKE MAXIMA SEGURIDAD | `consulta_tipo_servicio:stake` |
| GRUPO VIP | `consulta_tipo_servicio:grupo_vip` |

**Message 2 (follow-up):**
```
<strong>OJO SI HAS REALIZADO TU PAGO SIMPLEMENTE ENVÍAMELO ACÁ</strong> 📲
```

---

### `mensaje_promo_bono_1` (L261-283)

**Parse mode:** `HTML`

**Message:**
```
<b>¡TE REGALO 70 LUCAS MI KING!</b>
Regístrate con el link exclusivo, haz tu primer depósito de mínimo S/.40 y listo tendrás 70 soles gratis.
Mira este video con el paso a paso de cómo llevarte los S/. 70 gratis ⬆️
```

**Keyboard:**
| Button Text | URL |
|---|---|
| OBTÉN TUS 70 SOLES GRATIS | `https://bit.ly/promobetsafemagic` |

---

### `mensaje_promo_bono_2` (L285-309)

**Parse mode:** `HTML`

**Message:**
```
<b>REGALO 70 LUCAS A TODOS!!</b>
<b>ULTIMO LLAMADO GENTE!!!!!</b>
Regístrate con el link exclusivo, haz tu primer depósito de minimo S/.40 y listo tendrás 70
soles gratis.
Mira este video con el paso a paso de cómo llevarte los S/. 70 gratis ⬆️��
```

**Keyboard:**
| Button Text | URL |
|---|---|
| OBTÉN TUS 70 SOLES GRATIS | `https://bit.ly/promobetsafemagic` |

---

### `aviso_informe_pasar_nueva_cuenta` (L312-317)

**Parse mode:** none

**Message:**
```
Hermano utiliza nuestro nuevo bot aquí @elmagopagos_bot 🔮
```

**Keyboard:** none

---

### `mensaje_recordatorio_compra_servicio` (L377-386)

**Parse mode:** none

**Message:**
```
Hola mi gato, para ingresar al {SERVICENAME} solo tienes que enviar el screenshot de tu pago y listo ✅
```
(where `{SERVICENAME}` is `service_name` with underscores removed and uppercased)

**Keyboard:** none

---

### `mensaje_consulta_informacion_tipo_servicio` (L388-401)

**Parse mode:** none

**Message:**
```
Mi gato, Has click sobre el servicio que desees conocer
Si tienes una duda puntual porfavor contacta al siguiente usuario, ojo no responderemos preguntas básicas. @magic_peru 🔮
```

**Keyboard:**
| Button Text | Callback Data |
|---|---|
| STAKE MAXIMA SEGURIDAD | `consulta_tipo_servicio:stake` |
| GRUPO VIP | `consulta_tipo_servicio:grupo_vip` |

---

### `mensaje_wsp_inicial_directo` (L467-479)

**Parse mode:** none

**Message:**
```
Hola mi gato 🔮, Por favor selecciona el servicio que desees validar
```

**Keyboard:**
| Button Text | Callback Data |
|---|---|
| STAKE MAXIMA SEGURIDAD | `servicio_seleccionado_wsp:stake` |
| GRUPO VIP | `servicio_seleccionado_wsp:grupo_vip` |

---

### `mensaje_wsp_envio_captura` (L481-484)

**Parse mode:** none

**Message:**
```
Ya casi... ahora envíame una captura de tu pago a este chat! 📸🔥
```

**Keyboard:** none

---

### `restriccion_por_duplicado_venta` (L488-509)

**Parse mode:** `HTML`

**Message:**
```html
<strong>🐾 ¡Mi gato!</strong>

<strong>Has adquirido el servicio:</strong> {tipo_servicio}

<strong>Fecha de compra:</strong> {purchase_date}

<strong>Monto:</strong> {monto_extraido_captura} soles

<strong>Revisa nuestro chat, ahí encontrarás el enlace.</strong>

<strong>De todas formas, también te lo dejo aquí ⬇️</strong>
```

**Keyboard:**
| Button Text | URL |
|---|---|
| ✅ INGRESA AL GRUPO ACÁ ✅ | `{invite_link}` (dynamic) |

---

### `restriccion_por_duplicado_venta_busines_user` (L512-523)

**Parse mode:** `HTML`

**Message:**
```html
<strong>⚠️ Validación de compra duplicada detectada</strong>

<strong>El usuario con ID:</strong> {user_id}

<strong>Ya adquirió previamente el servicio:</strong> {tipo_servicio}

<strong>Fecha de compra:</strong> {purchase_date}

<strong>Monto pagado:</strong> {monto_extraido_captura} soles

<strong>Enlace de acceso al grupo asociado:</strong> {invite_link}
```

**Keyboard:** none

