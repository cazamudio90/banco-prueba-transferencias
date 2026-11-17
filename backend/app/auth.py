import os
from datetime import datetime, timedelta, timezone
import jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Usuario, Auditoria

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "clave-secreta-super-segura-zeta-banco-2026")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15  # Requisito RF1: 15 minutos o menos

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def authenticate_user(db: Session, username: str, password: str, correlation_id: str = None, ip_origin: str = None) -> Usuario:
    user = db.query(Usuario).filter(Usuario.username == username).first()
    now = datetime.now(timezone.utc)

    if not user or not user.activo:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas.")

    # Verificar bloqueo temporal por 5 intentos fallidos (RA3)
    if user.bloqueado_hasta:
        blocked_utc = user.bloqueado_hasta.replace(tzinfo=timezone.utc) if user.bloqueado_hasta.tzinfo is None else user.bloqueado_hasta
        if now < blocked_utc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuario bloqueado temporalmente por intentos fallidos.")
        else:
            user.bloqueado_hasta = None
            user.intentos_fallidos = 0

    if not verify_password(password, user.password_hash):
        user.intentos_fallidos += 1
        if user.intentos_fallidos >= 5:
            user.bloqueado_hasta = now + timedelta(minutes=15)
        
        db.add(Auditoria(
            usuario_id=user.id,
            accion="LOGIN_FALLIDO",
            detalle=f"Intento fallido #{user.intentos_fallidos} para usuario {username}",
            correlation_id=correlation_id,
            ip_origin=ip_origin,
            fecha=now
        ))
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas.")

    # Login exitoso: resetear contador y auditar (RF8)
    user.intentos_fallidos = 0
    user.bloqueado_hasta = None
    db.add(Auditoria(
        usuario_id=user.id,
        accion="LOGIN_EXITOSO",
        detalle=f"Inicio de sesión exitoso de {username}",
        correlation_id=correlation_id,
        ip_origin=ip_origin,
        fecha=now
    ))
    db.commit()
    return user

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Usuario:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token inválido o expirado.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception

    user = db.query(Usuario).filter(Usuario.username == username, Usuario.activo == True).first()
    if user is None:
        raise credentials_exception
    return user

def require_operator(current_user: Usuario = Depends(get_current_user)) -> Usuario:
    if current_user.rol != "OPERADOR":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acceso restringido a operadores.")
    return current_user
