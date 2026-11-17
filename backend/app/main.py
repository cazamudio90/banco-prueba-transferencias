import json
import logging
import time
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import text, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Usuario, Cuenta, Movimiento, Transferencia
from app.auth import authenticate_user, create_access_token, get_current_user, require_operator
from app.ledger_sentinel import LedgerSentinel
from app.ai_assistant import analyze_claim

# Configuración de Logs Estructurados en JSON (RA4)
class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_obj = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None),
            "path": getattr(record, "path", None),
            "status_code": getattr(record, "status_code", None),
            "duration_ms": getattr(record, "duration_ms", None),
        }
        return json.dumps({k: v for k, v in log_obj.items() if v is not None})

logger = logging.getLogger("zeta_banco")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)

app = FastAPI(title="Banco Prueba S.A. - Módulo de Transferencias", version="1.0.0")

# CORS restrictivo (RA3)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Correlation-ID"],
)

# Middleware de Observabilidad (Correlation ID + Latencia) y Cabeceras de Seguridad (RA3, RA4)
@app.middleware("http")
async def observability_and_security_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = correlation_id
    start_time = time.perf_counter()

    response = await call_next(request)

    duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cache-Control"] = "no-store"

    logger.info(
        f"{request.method} {request.url.path}",
        extra={
            "correlation_id": correlation_id,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response

# --- Esquemas Pydantic ---
class TransferRequest(BaseModel):
    cuenta_origen_id: int
    numero_cuenta_destino: str = Field(..., min_length=4, max_length=20)
    monto: Decimal

class ClaimRequest(BaseModel):
    texto: str = Field(..., min_length=5, max_length=2000)

# --- Endpoints ---

@app.post("/api/auth/login")
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    ip = request.client.host if request.client else None
    user = authenticate_user(db, form_data.username, form_data.password, request.state.correlation_id, ip)
    token = create_access_token(data={"sub": user.username, "rol": user.rol})
    return {
        "access_token": token,
        "token_type": "bearer",
        "usuario": {
            "id": user.id,
            "username": user.username,
            "nombre_completo": user.nombre_completo,
            "rol": user.rol,
        }
    }

@app.get("/api/cuentas")
def list_my_accounts(
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """RF2: Lista solo las cuentas del cliente autenticado con número enmascarado."""
    cuentas = db.query(Cuenta).filter(Cuenta.usuario_id == current_user.id, Cuenta.activa == True).all()
    return [
        {
            "id": c.id,
            "numero_enmascarado": f"****{c.numero_cuenta[-4:]}",
            "moneda": c.moneda,
            "saldo": str(c.saldo),
        }
        for c in cuentas
    ]

@app.get("/api/cuentas/{cuenta_id}/movimientos")
def list_account_movements(
    cuenta_id: int,
    fecha_desde: Optional[datetime] = Query(None),
    fecha_hasta: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """RF2 y RF3: Valida propiedad de la cuenta y devuelve movimientos paginados en orden descendente."""
    cuenta = db.query(Cuenta).filter(Cuenta.id == cuenta_id).first()
    if not cuenta or cuenta.usuario_id != current_user.id:
        raise HTTPException(status_code=403, detail="No tiene acceso a esta cuenta.")

    query = db.query(Movimiento).filter(Movimiento.cuenta_id == cuenta_id)
    if fecha_desde:
        query = query.filter(Movimiento.fecha >= fecha_desde)
    if fecha_hasta:
        query = query.filter(Movimiento.fecha <= fecha_hasta)

    total = query.count()
    items = (
        query.order_by(Movimiento.fecha.desc(), Movimiento.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": m.id,
                "transferencia_id": m.transferencia_id,
                "tipo": m.tipo,
                "monto": str(m.monto),
                "saldo_anterior": str(m.saldo_anterior),
                "saldo_posterior": str(m.saldo_posterior),
                "descripcion": m.descripcion,
                "fecha": m.fecha.isoformat(),
            }
            for m in items
        ]
    }

@app.post("/api/transferencias", status_code=201)
def create_transfer(
    payload: TransferRequest,
    request: Request,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """RF4 y RF6: Ejecuta transferencia atómica con clave de idempotencia."""
    if current_user.rol != "CLIENTE":
        raise HTTPException(status_code=403, detail="Solo los clientes pueden iniciar transferencias.")

    ip = request.client.host if request.client else None
    sentinel = LedgerSentinel(db)
    transfer = sentinel.execute_transfer(
        user_id=current_user.id,
        origin_account_id=payload.cuenta_origen_id,
        destination_account_number=payload.numero_cuenta_destino,
        amount=payload.monto,
        idempotency_key=idempotency_key,
        correlation_id=request.state.correlation_id,
        ip_origin=ip,
    )

    return {
        "id": transfer.id,
        "idempotency_key": transfer.idempotency_key,
        "monto_origen": str(transfer.monto_origen),
        "moneda_origen": transfer.moneda_origen,
        "monto_destino": str(transfer.monto_destino),
        "moneda_destino": transfer.moneda_destino,
        "tasa_aplicada": str(transfer.tasa_aplicada),
        "estado": transfer.estado,
        "creado_en": transfer.creado_en.isoformat(),
    }

@app.get("/api/operador/transferencias")
def list_all_transfers_operator(
    operator: Usuario = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Permite al operador listar transferencias recientes para gestionar reversas (RF5)."""
    transfers = db.query(Transferencia).order_by(Transferencia.creado_en.desc()).limit(50).all()
    return [
        {
            "id": t.id,
            "monto_origen": str(t.monto_origen),
            "moneda_origen": t.moneda_origen,
            "estado": t.estado,
            "creado_en": t.creado_en.isoformat(),
            "reversado_en": t.reversado_en.isoformat() if t.reversado_en else None,
        }
        for t in transfers
    ]

@app.post("/api/transferencias/{transfer_id}/reversar")
def reverse_transfer_endpoint(
    transfer_id: int,
    request: Request,
    operator: Usuario = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """RF5: Reversa exclusiva de operador dentro de las 24 horas."""
    ip = request.client.host if request.client else None
    sentinel = LedgerSentinel(db)
    transfer = sentinel.reverse_transfer(
        transfer_id=transfer_id,
        operator_id=operator.id,
        correlation_id=request.state.correlation_id,
        ip_origin=ip,
    )
    return {
        "id": transfer.id,
        "estado": transfer.estado,
        "reversado_en": transfer.reversado_en.isoformat(),
    }

@app.post("/api/reclamos/analizar")
async def analyze_claim_endpoint(
    payload: ClaimRequest,
    current_user: Usuario = Depends(get_current_user)
):
    """RF9: Clasifica reclamo enmascarando PII antes de consultar el LLM."""
    return await analyze_claim(payload.texto)

@app.get("/health")
def health_check(db: Session = Depends(get_db)):
    """RA4: Endpoint de salud verificando conexión a SQL Server."""
    try:
        db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "database": "disconnected"})

@app.get("/metrics")
def basic_metrics(db: Session = Depends(get_db)):
    """RA4: Métricas básicas de transferencias por estado."""
    rows = db.query(Transferencia.estado, func.count(Transferencia.id)).group_by(Transferencia.estado).all()
    return {"transferencias_por_estado": {estado: count for estado, count in rows}}
