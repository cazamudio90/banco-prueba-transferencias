USE BancoPruebaDB;
GO

-- Contraseña para todos los usuarios semilla: Password123!
-- Hash generado con bcrypt (cost 12)
DECLARE @HashDefault VARCHAR(255) = '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj4J/HS.i8eO';

INSERT INTO tbq_usuarios (username, password_hash, nombre_completo, rol) VALUES
('cliente1', @HashDefault, 'Juan Pérez', 'CLIENTE'),
('cliente2', @HashDefault, 'María Gómez', 'CLIENTE'),
('operador1', @HashDefault, 'Carlos López (Soporte)', 'OPERADOR');

-- Cuentas para cliente1 (id=1) y cliente2 (id=2)
INSERT INTO tbq_cuentas (usuario_id, numero_cuenta, moneda, saldo) VALUES
(1, '100100001234', 'PYG', 35000000.00), -- 35 millones PYG
(1, '100100005678', 'USD', 5000.00),     -- 5 mil USD
(2, '200200004321', 'PYG', 12000000.00), -- 12 millones PYG
(2, '200200008765', 'USD', 1500.00);     -- 1.5 mil USD

-- Tipos de cambio iniciales PYG <-> USD (RA1)
INSERT INTO tbq_tipos_cambio (moneda_origen, moneda_destino, tasa_compra, tasa_venta) VALUES
('USD', 'PYG', 7750.000000, 7850.000000),
('PYG', 'USD', 7750.000000, 7850.000000);

-- Movimientos iniciales de ejemplo (RF3)
INSERT INTO tbq_movimientos (cuenta_id, tipo, monto, saldo_anterior, saldo_posterior, descripcion, fecha) VALUES
(1, 'CREDITO', 35000000.00, 0.00, 35000000.00, 'Depósito inicial de apertura', DATEADD(day, -5, SYSUTCDATETIME())),
(2, 'CREDITO', 5000.00, 0.00, 5000.00, 'Depósito inicial de apertura USD', DATEADD(day, -5, SYSUTCDATETIME())),
(3, 'CREDITO', 12000000.00, 0.00, 12000000.00, 'Depósito inicial de apertura', DATEADD(day, -3, SYSUTCDATETIME())),
(4, 'CREDITO', 1500.00, 0.00, 1500.00, 'Depósito inicial de apertura USD', DATEADD(day, -3, SYSUTCDATETIME()));
GO
