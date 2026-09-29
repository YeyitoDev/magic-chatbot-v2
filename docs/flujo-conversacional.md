# 🔄 Flujo Conversacional - Magic Chatbot v2

## Diagrama Principal

```mermaid
flowchart TD
    START(["👤 Usuario envía /start"]) --> REGISTER["📝 Registrar en BD (get_or_create)"]
    REGISTER --> DYNAMO["📊 DynamoDB (opcional - promos)"]
    DYNAMO --> MENU["📋 Mostrar Menú Principal"]
    
    MENU -->|"🎯 Grupo VIP"| VIP_INFO["🖼️ Enviar imágenes + info VIP"]
    MENU -->|"🎲 Stake"| STAKE_INFO["🖼️ Enviar imagen + info Stake"]
    MENU -->|"ℹ️ Información"| INFO["📖 Mostrar info servicios"]
    MENU -->|"❓ FAQ"| FAQ["📹 Enviar video explicativo"]
    
    VIP_INFO --> PRICING["💰 Mostrar precios y cuentas"]
    STAKE_INFO --> PRICING
    INFO --> MENU
    FAQ --> MENU
    
    PRICING -->|"✅ Sí comprar"| SELECT["🎯 Guardar servicio seleccionado"]
    PRICING -->|"❌ No"| BETSAFE["🎁 Mostrar promo BetSafe"]
    BETSAFE --> MENU
    
    SELECT --> WAIT_IMAGE["⏳ Esperar comprobante"]
    WAIT_IMAGE --> IMAGE["📸 Usuario envía imagen"]

    IMAGE --> OCR["🔍 Google Vision OCR"]
    OCR --> PARSE["🔢 Extraer monto + fecha"]
    PARSE -->|"❌ No detectado"| ERROR_OCR["⚠️ Pedir mejor imagen"]
    ERROR_OCR --> WAIT_IMAGE
    
    PARSE -->|"✅ Monto detectado"| DUP_CHECK{"🔄 ¿Duplicado\n24h?"}
    DUP_CHECK -->|"Sí"| DUP_MSG["ℹ️ Ya existe compra - enviar link"]
    DUP_MSG --> MENU
    
    DUP_CHECK -->|"No"| SEND_VALIDATOR["📤 Enviar imagen + botones al validador"]
    SEND_VALIDATOR --> CONFIRM_USER["✅ 'Recibí tu pago, validando...'"]
    
    CONFIRM_USER --> VALIDATOR_ACTION{"👤 Validador decide"}
    
    VALIDATOR_ACTION -->|"✅ Validar"| PROCESS["💾 Registrar Purchase + Subscription"]
    VALIDATOR_ACTION -->|"❌ Rechazar"| REJECT["🚫 Notificar rechazo al usuario"]
    VALIDATOR_ACTION -->|"🔵 Monto no reconocido"| MANUAL["✏️ Validación manual (/vm)"]
    
    MANUAL -->|"Selecciona servicio"| PROCESS
    MANUAL -->|"Cancela"| REJECT
    
    REJECT --> CLEANUP_IMG["🗑️ Eliminar imagen"]
    CLEANUP_IMG --> MENU

    PROCESS -->|"Grupo VIP"| CREATE_SUB["📅 Crear/Extender suscripción"]
    PROCESS -->|"Stake"| STAKE_OK["✅ Compra registrada"]
    
    CREATE_SUB --> INVITE["🔗 Generar link de invitación"]
    STAKE_OK --> INVITE
    
    INVITE --> SEND_LINK["📨 Enviar link + promo BetSafe"]
    SEND_LINK --> CLEANUP["🧹 Limpiar selección + imagen"]
    CLEANUP --> MENU
```

## Flujo WhatsApp (WSP)

```mermaid
flowchart TD
    WSP_START(["📱 Usuario envía /wsp"]) --> GET_CODE["🔢 Obtener código WhatsApp"]
    GET_CODE --> SHEETS["📊 Buscar en Google Sheets"]
    SHEETS -->|"✅ Encontrado"| DOWNLOAD["⬇️ Descargar imagen de transferencia"]
    SHEETS -->|"❌ No encontrado"| WSP_ERROR["⚠️ Código no válido"]
    
    DOWNLOAD --> OCR_WSP["🔍 Google Vision OCR"]
    OCR_WSP --> SEND_VALIDATOR_WSP["📤 Enviar al validador (+:wsp marker)"]
    SEND_VALIDATOR_WSP --> VALIDATOR_WSP{"👤 Validador"}
    
    VALIDATOR_WSP -->|"✅ Validar"| WSP_UPDATE["📝 Actualizar Sheets + BD"]
    VALIDATOR_WSP -->|"❌ Rechazar"| WSP_REJECT["🚫 Rechazar"]
    
    WSP_UPDATE --> SEND_LINK_WSP["🔗 Enviar link al usuario"]
```

## Pipeline de Jobs Programados

```mermaid
flowchart TD
    subgraph "⏰ Jobs Programados"
        REMINDER["🔄 Recordatorios\n(cada 10 min)"] --> CHECK_PENDING["📋 Revisar SelectedService"]
        CHECK_PENDING --> PHASE1{"reminder=0\n1min-24h?"}
        PHASE1 -->|"Sí"| SEND_PHOTO["📸 Enviar foto + precios"]
        SEND_PHOTO --> INC1["reminder++"]
        
        PHASE1 -->|"No"| PHASE2{"reminder=1\n>24h?"}
        PHASE2 -->|"Sí"| SEND_VIDEO["📹 Enviar video recordatorio"]
        SEND_VIDEO --> DELETE1["🗑️ Eliminar selección"]
        
        PHASE2 -->|"No"| PHASE3{"reminder≥2\n>48h?"}
        PHASE3 -->|"Sí"| DELETE2["🗑️ Eliminar selección expirada"]
        PHASE3 -->|"No"| SKIP["⏭️ Saltar"]
    end

    subgraph "🌙 Limpieza Diaria"
        CLEANUP_JOB["🧹 Job diario (20:00)"] --> GET_MEMBERS["📡 Obtener miembros (Telethon)"]
        GET_MEMBERS --> COMPARE["🔄 Comparar vs BD"]
        COMPARE --> CLASSIFY{"Clasificar"}
        CLASSIFY -->|"Activo"| KEEP["✅ Mantener"]
        CLASSIFY -->|"Expirado"| KICK["🚫 Kick del grupo"]
        CLASSIFY -->|"No registrado"| REPORT["📄 Guardar en clientes_especiales.json"]
        KICK --> UNBAN["🔓 Unban (permite rejoin)"]
        UNBAN --> LOG_AUDIT["📝 AuditLogger"]
    end
```

## Validación Manual (/vm)

```mermaid
flowchart TD
    VM(["👤 Validador envía /vm"]) --> PARSE_VM["🔢 Parsear: user_id, msg_id, monto, fecha"]
    PARSE_VM --> VALID_CHECK{"¿Validador\nautorizado?"}
    VALID_CHECK -->|"No"| DENY["⛔ Acceso denegado"]
    VALID_CHECK -->|"Sí"| DUP_CHECK2{"¿Duplicado?"}
    DUP_CHECK2 -->|"Sí"| DUP_WARN["⚠️ Ya existe compra"]
    DUP_CHECK2 -->|"No"| REGISTER["💾 Registrar compra"]
    REGISTER --> INVITE2["🔗 Enviar link al comprador"]
    INVITE2 --> CONFIRM_VALIDATOR["✅ Confirmar al validador"]
```

## Flujo API Externa (/valid)

```mermaid
flowchart TD
    API_START(["🌐 API externa registra pago"]) --> CSV["📄 Guardar en service_payments_api.csv"]
    CSV --> USER_VALID(["👤 Usuario envía /valid CODIGO"])
    USER_VALID --> CHECK_CSV["🔍 Buscar código en CSV"]
    CHECK_CSV -->|"❌ No encontrado"| CSV_ERR["⚠️ Código inválido"]
    CHECK_CSV -->|"Ya reclamado"| CLAIMED["ℹ️ Ya fue reclamado"]
    CHECK_CSV -->|"✅ Válido"| PROCESS_API["💾 Registrar compra"]
    PROCESS_API --> SEND_LINK_API["🔗 Enviar link + BetSafe"]
    SEND_LINK_API --> MARK_CLAIMED["✅ Marcar como reclamado en CSV"]
```

---

## 📊 Arquitectura de Capas

```mermaid
flowchart TB
    subgraph "Presentación"
        TG["📱 Telegram Bot API"]
        CMD["🖥️ CommandHandlers<br/>/start, /vm, /wsp, /valid, /id"]
        CB["🔘 CallbackHandlers<br/>validar_monto, consulta_tipo_servicio"]
        MSG["💬 MessageHandlers<br/>texto, imágenes (comprobantes)"]
        ERR["🚨 ErrorHandler<br/>global errors → Telegram alerts"]
    end

    subgraph "Lógica de Negocio"
        US["👤 UserService"]
        SS["💎 SubscriptionService<br/>process_purchase()"]
        PS["💳 PaymentService<br/>validate_payment()"]
        PRS["🏷️ PricingService<br/>match_price() + caché JSON"]
        PMS["📢 PromotionService<br/>DynamoDB pipeline"]
        RMS["⏰ ReminderService<br/>recordatorios fase 1,2,3"]
        GS["📊 GoogleSheetsService"]
        GV["🔍 GoogleVisionService"]
        TA["📡 TelegramAPIService"]
    end

    subgraph "Acceso a Datos"
        UR["🗄️ UserRepository"]
        SR["🗄️ ServiceRepository"]
        PR["🗄️ PurchaseRepository"]
        SUBR["🗄️ SubscriptionRepository"]
        SSR["🗄️ SelectedServiceRepository"]
    end

    subgraph "Infraestructura"
        DB[("🗄️ MySQL<br/>AWS RDS")]
        DDB[("📊 DynamoDB<br/>MAGIC-USER-SESSIONS-LOG")]
        GCP["☁️ Google Cloud<br/>Vision + Sheets"]
        CACHE["📁 pricing_cache.json"]
    end

    TG --> CMD & CB & MSG & ERR
    CMD & CB & MSG --> US & SS & PS & PRS & PMS & RMS
    US & SS & PS & PRS & PMS & RMS --> UR & SR & PR & SUBR & SSR
    UR & SR & PR & SUBR & SSR --> DB
    PMS --> DDB
    GS & GV --> GCP
    PRS --> CACHE
    ERR --> TG
```

---

## 📋 Resumen de Comandos

| Comando | Quién | Qué hace |
|---------|-------|----------|
| `/start` | Usuario | Registro + menú principal |
| `/vm uid mid monto [fecha]` | Validador | Validar monto manualmente |
| `/wsp codigo` | Usuario WSP | Registrar pago WhatsApp |
| `/valid codigo` | Usuario | Reclamar compra API externa |
| `/id` | Validador | Ver su Telegram ID |
| `/help` | Usuario | Ayuda → redirige a /start |