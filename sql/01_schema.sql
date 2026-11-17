CREATE DATABASE BancoPruebaDB;
GO

USE BancoPruebaDB;
GO

-- 1. Usuarios (RF1)
CREATE TABLE tbq_usuarios (
    id INT IDENTITY(1,1) PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    nombre_completo VARCHAR(100) NOT NULL,
    rol VARCHAR(20) NOT NULL CHECK (rol IN ('CLIENTE', 'OPERADOR')),
    intentos_fallidos INT NOT NULL DEFAULT 0,
    bloqueado_hasta DATETIME2 NULL,
    activo BIT NOT NULL DEFAULT 1,
    creado_en DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);

-- 2. Cuentas (RF2, RF7)
CREATE TABLE tbq_cuentas (
    id INT IDENTITY(1,1) PRIMARY KEY,
    usuario_id INT NOT NULL FOREIGN KEY REFERENCES tbq_usuarios(id),
    numero_cuenta VARCHAR(20) NOT NULL UNIQUE,
    moneda VARCHAR(3) NOT NULL CHECK (moneda IN ('PYG', 'USD')),
    saldo DECIMAL(18, 2) NOT NULL DEFAULT 0.00 CHECK (saldo >= 0),
    activa BIT NOT NULL DEFAULT 1,
    creado_en DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);

-- 3. Tipos de Cambio (RA1 - Moneda cruzada)
CREATE TABLE tbq_tipos_cambio (
    id INT IDENTITY(1,1) PRIMARY KEY,
    moneda_origen VARCHAR(3) NOT NULL,
    moneda_destino VARCHAR(3) NOT NULL,
    tasa_compra DECIMAL(18, 6) NOT NULL,
    tasa_venta DECIMAL(18, 6) NOT NULL,
    vigente_desde DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);

-- 4. Transferencias (RF4, RF5, RF6, RA1)
CREATE TABLE tbq_transferencias (
    id INT IDENTITY(1,1) PRIMARY KEY,
    idempotency_key VARCHAR(100) NOT NULL UNIQUE,
    cuenta_origen_id INT NOT NULL FOREIGN KEY REFERENCES tbq_cuentas(id),
    cuenta_destino_id INT NOT NULL FOREIGN KEY REFERENCES tbq_cuentas(id),
    monto_origen DECIMAL(18, 2) NOT NULL CHECK (monto_origen > 0),
    moneda_origen VARCHAR(3) NOT NULL CHECK (moneda_origen IN ('PYG', 'USD')),
    monto_destino DECIMAL(18, 2) NOT NULL CHECK (monto_destino > 0),
    moneda_destino VARCHAR(3) NOT NULL CHECK (moneda_destino IN ('PYG', 'USD')),
    tasa_aplicada DECIMAL(18, 6) NOT NULL DEFAULT 1.000000,
    estado VARCHAR(20) NOT NULL CHECK (estado IN ('PENDIENTE', 'COMPLETADA', 'RECHAZADA', 'REVERSADA')),
    motivo_rechazo VARCHAR(255) NULL,
    creado_en DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    completado_en DATETIME2 NULL,
    reversado_en DATETIME2 NULL,
    reversado_por_id INT NULL FOREIGN KEY REFERENCES tbq_usuarios(id)
);

-- 5. Movimientos / Asientos contables inmutables (RF3, RF5)
CREATE TABLE tbq_movimientos (
    id INT IDENTITY(1,1) PRIMARY KEY,
    cuenta_id INT NOT NULL FOREIGN KEY REFERENCES tbq_cuentas(id),
    transferencia_id INT NULL FOREIGN KEY REFERENCES tbq_transferencias(id),
    tipo VARCHAR(20) NOT NULL CHECK (tipo IN ('DEBITO', 'CREDITO', 'REVERSA_DEBITO', 'REVERSA_CREDITO')),
    monto DECIMAL(18, 2) NOT NULL CHECK (monto > 0),
    saldo_anterior DECIMAL(18, 2) NOT NULL,
    saldo_posterior DECIMAL(18, 2) NOT NULL,
    descripcion VARCHAR(255) NOT NULL,
    fecha DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);
CREATE INDEX idx_movimientos_cuenta_fecha ON tbq_movimientos(cuenta_id, fecha DESC);

-- 6. Auditoría (RF8)
CREATE TABLE tbq_auditoria (
    id INT IDENTITY(1,1) PRIMARY KEY,
    usuario_id INT NULL FOREIGN KEY REFERENCES tbq_usuarios(id),
    accion VARCHAR(50) NOT NULL,
    detalle VARCHAR(500) NOT NULL,
    correlation_id VARCHAR(64) NULL,
    ip_origen VARCHAR(45) NULL,
    fecha DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);

-- 7. Outbox para eventos (RA2)
CREATE TABLE tbq_outbox (
    id INT IDENTITY(1,1) PRIMARY KEY,
    aggregate_type VARCHAR(50) NOT NULL,
    aggregate_id INT NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    payload NVARCHAR(MAX) NOT NULL,
    estado VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE' CHECK (estado IN ('PENDIENTE', 'PROCESADO', 'ERROR')),
    intentos INT NOT NULL DEFAULT 0,
    creado_en DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME(),
    procesado_en DATETIME2 NULL
);
GO
