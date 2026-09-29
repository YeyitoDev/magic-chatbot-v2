-- ============================================================================
-- 001 - Idempotencia de pagos y suscripciones (MySQL 8)
-- ============================================================================
-- Ejecutar ANTES de desplegar la versión que usa purchases.payment_ref.
--
-- 1. Detén el bot y los jobs para que no haya transacciones abiertas que
--    bloqueen el ALTER TABLE (metadata lock):
--        fly scale count 0 -a magic-services
--        fly scale count 0 -a magic-services-jobs
-- 2. Ejecuta los pasos en orden, revisando el resultado del paso A.
-- 3. Despliega y vuelve a escalar a 1.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- A) Diagnóstico: usuarios con más de una fila por servicio
-- ---------------------------------------------------------------------------
SELECT user_telegram_id, service_id, COUNT(*) AS filas,
       SUM(is_active) AS activas, MAX(end_date) AS max_end_date
FROM subscriptions
GROUP BY user_telegram_id, service_id
HAVING COUNT(*) > 1;

-- ---------------------------------------------------------------------------
-- B) Respaldo
-- ---------------------------------------------------------------------------
CREATE TABLE subscriptions_backup_001 AS SELECT * FROM subscriptions;

-- ---------------------------------------------------------------------------
-- C) Consolidar: una fila por (usuario, servicio)
--    Se conserva la fila activa con mayor end_date; si ninguna está activa,
--    la de mayor end_date. Empate: la de mayor subscription_id.
-- ---------------------------------------------------------------------------
DELETE s
FROM subscriptions s
JOIN subscriptions k
  ON k.user_telegram_id = s.user_telegram_id
 AND k.service_id = s.service_id
 AND (
        k.is_active > s.is_active
     OR (k.is_active = s.is_active AND k.end_date > s.end_date)
     OR (k.is_active = s.is_active AND k.end_date = s.end_date
         AND k.subscription_id > s.subscription_id)
 );

-- ---------------------------------------------------------------------------
-- D) Restricciones
-- ---------------------------------------------------------------------------
ALTER TABLE subscriptions
    ADD UNIQUE KEY uq_subscriptions_user_service (user_telegram_id, service_id);

ALTER TABLE purchases
    ADD COLUMN payment_ref VARCHAR(191) NULL,
    ADD UNIQUE KEY uq_purchases_payment_ref (payment_ref);

-- ---------------------------------------------------------------------------
-- E) Verificación (ambas deben devolver 0 filas / 1 fila respectivamente)
-- ---------------------------------------------------------------------------
SELECT user_telegram_id, service_id, COUNT(*)
FROM subscriptions GROUP BY 1, 2 HAVING COUNT(*) > 1;

SHOW COLUMNS FROM purchases LIKE 'payment_ref';

-- ---------------------------------------------------------------------------
-- Reversión (solo si hay que volver a la versión anterior del bot)
-- ---------------------------------------------------------------------------
-- ALTER TABLE purchases DROP INDEX uq_purchases_payment_ref, DROP COLUMN payment_ref;
-- ALTER TABLE subscriptions DROP INDEX uq_subscriptions_user_service;
-- Las filas consolidadas se pueden recuperar desde subscriptions_backup_001.
