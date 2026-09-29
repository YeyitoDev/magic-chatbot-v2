# Migraciones de base de datos

Las migraciones son scripts SQL (MySQL 8) que se aplican **a mano, antes de desplegar** la versión
del código que las necesita. No se ejecutan al iniciar el bot: un `ALTER TABLE` con el bot
corriendo queda bloqueado esperando el *metadata lock* de sus transacciones abiertas.

Al arrancar, `core/schema.py` verifica que existan las columnas que el código espera; si falta
alguna, el bot se detiene con un mensaje que indica qué migración aplicar.

| Archivo | Cambios |
|---|---|
| `001_subscription_idempotency.sql` | `UNIQUE (user_telegram_id, service_id)` en `subscriptions` (consolidando duplicados) y columna `purchases.payment_ref` con índice `UNIQUE` |

## Aplicar `001_subscription_idempotency.sql`

1. **Detén el bot y los jobs** para liberar conexiones:

   ```bash
   fly scale count 0 -a magic-services
   fly scale count 0 -a magic-services-jobs   # solo si esa app existe
   ```

   Evita también que corra algún workflow de GitHub Actions en ese momento (limpieza a las
   07:00 y avisos a las 08:00 hora de Lima).

2. Conéctate a la BD de producción con un cliente MySQL y ejecuta el script **por secciones**:

   - **A. Diagnóstico:** lista los usuarios con más de una fila por servicio. Revisa el resultado;
     la sección C conservará, para cada uno, la fila activa con mayor `end_date`.
   - **B. Respaldo:** crea `subscriptions_backup_001` con una copia completa de la tabla.
   - **C. Consolidar:** elimina las filas duplicadas.
   - **D. Restricciones:** agrega `uq_subscriptions_user_service` y `purchases.payment_ref`
     con `uq_purchases_payment_ref`.
   - **E. Verificación:** la primera consulta debe devolver 0 filas y la segunda, la columna
     `payment_ref`.

3. Despliega la nueva versión y vuelve a escalar:

   ```bash
   fly deploy -a magic-services
   fly scale count 1 -a magic-services
   fly scale count 1 -a magic-services-jobs   # solo si esa app existe
   ```

4. Revisa los logs de arranque (`fly logs -a magic-services`): no debe aparecer
   `Faltan columnas en la BD`.

## Reversión

Si se vuelve a una versión anterior del bot, revierte también el esquema: el código anterior crea
una fila nueva al renovar una suscripción desactivada, y eso choca con el `UNIQUE` de
`subscriptions`.

```sql
ALTER TABLE purchases DROP INDEX uq_purchases_payment_ref, DROP COLUMN payment_ref;
ALTER TABLE subscriptions DROP INDEX uq_subscriptions_user_service;
```

Las filas eliminadas en la consolidación se pueden recuperar desde `subscriptions_backup_001`.
Cuando la versión nueva esté estable, esa tabla de respaldo se puede borrar.
