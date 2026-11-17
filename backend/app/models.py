from sqlalchemy import Column, Integer, String, Numeric, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
from app.database import Base

class Usuario(Base):
    __tablename__ = "tbq_usuarios"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    nombre_completo = Column(String(100), nullable=False)
    rol = Column(String(20), nullable=False)
    intentos_fallidos = Column(Integer, default=0, nullable=False)
    bloqueado_hasta = Column(DateTime, nullable=True)
    activo = Column(Boolean, default=True, nullable=False)
    creado_en = Column(DateTime, server_default=func.sysutcdatetime(), nullable=False)

class Cuenta(Base):
    __tablename__ = "tbq_cuentas"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("tbq_usuarios.id"), nullable=False)
    numero_cuenta = Column(String(20), unique=True, nullable=False)
    moneda = Column(String(3), nullable=False)
    saldo = Column(Numeric(18, 2), default=0, nullable=False)
    activa = Column(Boolean, default=True, nullable=False)
    creado_en = Column(DateTime, server_default=func.sysutcdatetime(), nullable=False)

class TipoCambio(Base):
    __tablename__ = "tbq_tipos_cambio"

    id = Column(Integer, primary_key=True, index=True)
    moneda_origen = Column(String(3), nullable=False)
    moneda_destino = Column(String(3), nullable=False)
    tasa_compra = Column(Numeric(18, 6), nullable=False)
    tasa_venta = Column(Numeric(18, 6), nullable=False)
    vigente_desde = Column(DateTime, server_default=func.sysutcdatetime(), nullable=False)

class Transferencia(Base):
    __tablename__ = "tbq_transferencias"

    id = Column(Integer, primary_key=True, index=True)
    idempotency_key = Column(String(100), unique=True, nullable=False)
    cuenta_origen_id = Column(Integer, ForeignKey("tbq_cuentas.id"), nullable=False)
    cuenta_destino_id = Column(Integer, ForeignKey("tbq_cuentas.id"), nullable=False)
    monto_origen = Column(Numeric(18, 2), nullable=False)
    moneda_origen = Column(String(3), nullable=False)
    monto_destino = Column(Numeric(18, 2), nullable=False)
    moneda_destino = Column(String(3), nullable=False)
    tasa_aplicada = Column(Numeric(18, 6), default=1, nullable=False)
    estado = Column(String(20), nullable=False)
    motivo_rechazo = Column(String(255), nullable=True)
    creado_en = Column(DateTime, server_default=func.sysutcdatetime(), nullable=False)
    completado_en = Column(DateTime, nullable=True)
    reversado_en = Column(DateTime, nullable=True)
    reversado_por_id = Column(Integer, ForeignKey("tbq_usuarios.id"), nullable=True)

class Movimiento(Base):
    __tablename__ = "tbq_movimientos"

    id = Column(Integer, primary_key=True, index=True)
    cuenta_id = Column(Integer, ForeignKey("tbq_cuentas.id"), nullable=False)
    transferencia_id = Column(Integer, ForeignKey("tbq_transferencias.id"), nullable=True)
    tipo = Column(String(20), nullable=False)
    monto = Column(Numeric(18, 2), nullable=False)
    saldo_anterior = Column(Numeric(18, 2), nullable=False)
    saldo_posterior = Column(Numeric(18, 2), nullable=False)
    descripcion = Column(String(255), nullable=False)
    fecha = Column(DateTime, server_default=func.sysutcdatetime(), nullable=False)

class Auditoria(Base):
    __tablename__ = "tbq_auditoria"

    id = Column(Integer, primary_key=True, index=True)
    usuario_id = Column(Integer, ForeignKey("tbq_usuarios.id"), nullable=True)
    accion = Column(String(50), nullable=False)
    detalle = Column(String(500), nullable=False)
    correlation_id = Column(String(64), nullable=True)
    ip_origen = Column(String(45), nullable=True)
    fecha = Column(DateTime, server_default=func.sysutcdatetime(), nullable=False)

class Outbox(Base):
    __tablename__ = "tbq_outbox"

    id = Column(Integer, primary_key=True, index=True)
    aggregate_type = Column(String(50), nullable=False)
    aggregate_id = Column(Integer, nullable=False)
    event_type = Column(String(50), nullable=False)
    payload = Column(Text, nullable=False)
    estado = Column(String(20), default="PENDIENTE", nullable=False)
    intentos = Column(Integer, default=0, nullable=False)
    creado_en = Column(DateTime, server_default=func.sysutcdatetime(), nullable=False)
    procesado_en = Column(DateTime, nullable=True)
