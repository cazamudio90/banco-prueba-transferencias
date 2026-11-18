# Banco Prueba S.A. — Módulo de Transferencias

Solución integral desarrollada en **React + TypeScript** (Frontend), **Python + FastAPI** (Backend) y **SQL Server** (Base de datos), implementando el motor transaccional `LedgerSentinel` con control de concurrencia, idempotencia, reversas operativas y asistente de reclamos con IA.

## Estructura del Repositorio

```text
├── backend/
│   ├── app/
│   │   ├── main.py             # Endpoints REST, seguridad HTTP, logs JSON, /health y /metrics
│   │   ├── database.py         # Pool de conexiones SQLAlchemy hacia SQL Server
│   │   ├── models.py           # Modelos ORM mapeados a tablas con prefijo tbq_
│   │   ├── auth.py             # Autenticación JWT (15 min), bcrypt y bloqueo por intentos fallidos
│   │   ├── ledger_sentinel.py  # Clase LedgerSentinel: motor atómico de transferencias y reversas
│   │   └── ai_assistant.py     # Enmascaramiento PII y clasificación de reclamos con LLM/reglas
│   ├── tests/
│   │   └── test_transfers.py   # Pruebas unitarias, integración, idempotencia y concurrencia (50 hilos)
│   └── requirements.txt
├── frontend/                   # Aplicación SPA en React + TypeScript (Vite)
├── sql/
│   ├── 01_schema.sql           # DDL de tablas con prefijo tbq_, restricciones e índices
│   └── 02_seed.sql             # Datos semilla iniciales
├── docker-compose.yml          # Orquestación de SQL Server 2022
├── INCIDENTE.md                # Diagnóstico y solución de la Parte B
└── RESPUESTAS.md               # Respuestas técnicas de la Parte C
```

## Usuarios Semilla

| Usuario | Contraseña | Rol | Descripción |
| :--- | :--- | :--- | :--- |
| `cliente1` | `Password123!` | `CLIENTE` | Posee cuentas en PYG (`35.000.000`) y USD (`5.000,00`) |
| `cliente2` | `Password123!` | `CLIENTE` | Posee cuentas en PYG (`12.000.000`) y USD (`1.500,00`) |
| `operador1` | `Password123!` | `OPERADOR` | Puede consultar operaciones y ejecutar reversas (< 24h) |

## Variables de Entorno

El sistema funciona con valores por defecto locales, pero admite las siguientes variables:

* `DATABASE_URL`: Cadena de conexión a SQL Server (ej. `mssql+pymssql://sa:TuPasswordSegura123!@localhost:1433/BancoPruebaDB`).
* `JWT_SECRET_KEY`: Clave de firma para tokens JWT (vencimiento fijo de 15 minutos).
* `LLM_API_KEY`: Clave opcional para proveedor LLM (OpenAI-compatible). Si está vacía, el asistente opera en modo simulado determinístico sin fallar.
* `LLM_API_URL`: Endpoint del modelo (por defecto `https://openai.com`).
* `LLM_MODEL`: Modelo a utilizar (por defecto `gpt-4o-mini`).

## Guía de Arranque Rápido

### 1. Base de Datos (SQL Server)
* **Opción Docker:** Ejecutar `docker compose up -d` y correr `sql/01_schema.sql` seguido de `sql/02_seed.sql`.
* **Opción Local (SQL Server Express / Developer):** Abrir SSMS, ejecutar `sql/01_schema.sql` y luego `sql/02_seed.sql`.

### 2. Backend (FastAPI)
```bash
cd backend
python -m venv venv
# En Windows: .\venv\Scripts\Activate.ps1 | En Linux/Mac: source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```
La API estará disponible en `http://127.0.0.1:8000` (Documentación Swagger en `/docs` y salud en `/health`).

### 3. Frontend (React + TypeScript)
```bash
cd frontend
npm install
npm run dev
```
Abrir `http://localhost:5173` en el navegador.

### 4. Ejecutar Pruebas Automatizadas
```bash
cd backend
python -m pytest -v
```

## Decisiones de Arquitectura y Seguridad
* **Precisión monetaria:** Uso estricto de `DECIMAL(18, 2)` en SQL Server y `Decimal` en Python (`ROUND_HALF_UP`), eliminando cualquier tipo `float`.
* **Prevención de *deadlocks* y saldos negativos:** Bloqueo pesimista (`with_for_update()` -> `WITH (UPDLOCK, ROWLOCK)`) ordenando siempre los IDs de cuenta de menor a mayor antes de bloquear, complementado con `CHECK (saldo >= 0)` en base de datos.
* **Idempotencia:** Cabecera `Idempotency-Key` con restricción `UNIQUE` en `tbq_transferencias` y clave UUID generada por intento desde el cliente web.
* **Patrón Outbox:** Registro transaccional de eventos en `tbq_outbox` dentro de la misma unidad de trabajo ACID que la transferencia y la auditoría.
