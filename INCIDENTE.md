# Análisis de Incidente Productivo — Parte B

## 1. Síntomas Reportados
* El cliente `cliente1` poseía `1.000.000 PYG` e intentó transferir `800.000 PYG`.
* Ante demora en la respuesta, presionó el botón dos veces y reintentó por red.
* **Resultado erróneo:** Se debitaron `1.600.000 PYG`, la cuenta origen quedó en saldo negativo (`-600.000 PYG`) y el destino recibió dos créditos de `800.000 PYG`.

## 2. Causas Raíz Identificadas

1. **Ausencia de Idempotencia (Backend y Frontend):**
   * El endpoint de transferencias procesaba cada solicitud HTTP como una operación independiente sin exigir ni validar una `Idempotency-Key` única por intención de pago.
   * En el frontend, el botón de envío no se deshabilitaba durante la petición en curso, permitiendo múltiples clics simultáneos.
2. **Condición de Carrera (*Race Condition*) por Falta de Bloqueo Transaccional:**
   * Dos hilos concurrentes leyeron el saldo inicial (`1.000.000 PYG`) al mismo tiempo bajo nivel de aislamiento por defecto (`READ COMMITTED`) sin bloquear la fila (`UPDLOCK`). Ambos validaron que `1.000.000 >= 800.000` y ejecutaron el débito en paralelo.
3. **Falta de Restricción de Integridad en Base de Datos:**
   * La columna `saldo` en `tbq_cuentas` carecía de una restricción `CHECK (saldo >= 0)` que impidiera a nivel de motor confirmar una transacción con saldo negativo.

## 3. Corrección Aplicada en el Código

* **Nivel Base de Datos (`sql/01_schema.sql`):**
  * Se agregó `idempotency_key VARCHAR(100) NOT NULL UNIQUE` en `tbq_transferencias`.
  * Se agregó `saldo DECIMAL(18, 2) NOT NULL DEFAULT 0.00 CHECK (saldo >= 0)` en `tbq_cuentas`.
* **Nivel Backend (`backend/app/ledger_sentinel.py`):**
  * Verificación temprana de `idempotency_key`: si la clave ya existe, se retorna inmediatamente la transferencia original sin volver a debitar.
  * Bloqueo pesimista a nivel de fila mediante `.with_for_update()` (que SQL Server traduce a `WITH (UPDLOCK, ROWLOCK)`), ordenando los IDs de cuenta (`sorted([origen_id, destino_id])`) para evitar interbloqueos (*deadlocks*).
  * Ejecución atómica (`commit` / `rollback`) de saldos, asientos en `tbq_movimientos`, auditoría en `tbq_auditoria` y evento en `tbq_outbox`.
* **Nivel Frontend (`frontend/src/App.tsx`):**
  * Generación de un UUID v4 (`idemKey`) por cada intento de transferencia, reutilizado en reintentos de red y renovado únicamente al completar con éxito.
  * Bloqueo del botón (`disabled={enviandoTx}`) mientras la petición está en vuelo.

## 4. Validación y Pasos de Corrección de Datos

* **Validación automatizada:** Se implementaron `test_03_idempotencia_no_duplica_debito` y `test_06_concurrencia_50_transferencias_simultaneas` en `backend/tests/test_transfers.py`, demostrando que ante reintentos idénticos o 50 hilos paralelos el saldo nunca queda negativo y nunca se duplica el débito.
* **Remediación operativa de los datos afectados (sin alterar el historial inmutable):**
  * No se borran ni editan los registros históricos en `tbq_movimientos`.
  * Un usuario con rol `OPERADOR` ejecuta la reversa oficial (`POST /api/transferencias/{id}/reversar`) sobre la segunda transferencia duplicada, generando los contra-asientos (`REVERSA_DEBITO` en destino por `800.000 PYG` y `REVERSA_CREDITO` en origen por `800.000 PYG`), restaurando el saldo de `cliente1` a `200.000 PYG` y dejando trazabilidad completa en `tbq_auditoria`.
