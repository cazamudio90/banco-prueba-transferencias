import uuid
import pytest
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.models import Usuario, Cuenta, Movimiento, Transferencia, TipoCambio
from app.auth import hash_password

# Base de datos SQLite en memoria aislada para ejecutar los tests rápido y sin alterar datos reales
SQLALCHEMY_TEST_URL = "sqlite://"
test_engine = create_engine(
    SQLALCHEMY_TEST_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_database():
    """Reinicia las tablas y datos semilla antes de cada prueba."""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()

    hashed = hash_password("Password123!")
    u1 = Usuario(username="cliente1", password_hash=hashed, nombre_completo="Juan Pérez", rol="CLIENTE")
    u2 = Usuario(username="cliente2", password_hash=hashed, nombre_completo="María Gómez", rol="CLIENTE")
    op1 = Usuario(username="operador1", password_hash=hashed, nombre_completo="Carlos López", rol="OPERADOR")
    db.add_all([u1, u2, op1])
    db.flush()

    c1_pyg = Cuenta(usuario_id=u1.id, numero_cuenta="100100001234", moneda="PYG", saldo=Decimal("1000000.00"))
    c1_usd = Cuenta(usuario_id=u1.id, numero_cuenta="100100005678", moneda="USD", saldo=Decimal("500.00"))
    c2_pyg = Cuenta(usuario_id=u2.id, numero_cuenta="200200004321", moneda="PYG", saldo=Decimal("200000.00"))
    db.add_all([c1_pyg, c1_usd, c2_pyg])

    tc = TipoCambio(moneda_origen="USD", moneda_destino="PYG", tasa_compra=Decimal("7750"), tasa_venta=Decimal("7850"))
    db.add(tc)
    db.commit()
    db.close()

def get_token(username: str) -> str:
    res = client.post("/api/auth/login", data={"username": username, "password": "Password123!"})
    assert res.status_code == 200
    return res.json()["access_token"]

def test_01_transferencia_exitosa_y_asientos():
    token = get_token("cliente1")
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())}

    res = client.post(
        "/api/transferencias",
        json={"cuenta_origen_id": 1, "numero_cuenta_destino": "200200004321", "monto": "250000"},
        headers=headers,
    )
    assert res.status_code == 201
    assert res.json()["estado"] == "COMPLETADA"

    # Verificar saldos actualizados
    cuentas = client.get("/api/cuentas", headers={"Authorization": f"Bearer {token}"}).json()
    assert Decimal(cuentas[0]["saldo"]) == Decimal("750000.00")

def test_02_saldo_insuficiente_y_decimales_pyg():
    token = get_token("cliente1")

    # Intento con decimales en PYG
    res_dec = client.post(
        "/api/transferencias",
        json={"cuenta_origen_id": 1, "numero_cuenta_destino": "200200004321", "monto": "100.50"},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())},
    )
    assert res_dec.status_code == 400

    # Intento mayor al saldo disponible (1.000.000)
    res_saldo = client.post(
        "/api/transferencias",
        json={"cuenta_origen_id": 1, "numero_cuenta_destino": "200200004321", "monto": "5000000"},
        headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())},
    )
    assert res_saldo.status_code == 400

def test_03_idempotencia_no_duplica_debito():
    token = get_token("cliente1")
    idem_key = str(uuid.uuid4())
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": idem_key}
    payload = {"cuenta_origen_id": 1, "numero_cuenta_destino": "200200004321", "monto": "100000"}

    r1 = client.post("/api/transferencias", json=payload, headers=headers)
    r2 = client.post("/api/transferencias", json=payload, headers=headers)

    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]

    # Saldo debe haberse descontado una sola vez (1.000.000 - 100.000 = 900.000)
    cuentas = client.get("/api/cuentas", headers={"Authorization": f"Bearer {token}"}).json()
    assert Decimal(cuentas[0]["saldo"]) == Decimal("900000.00")

def test_04_acceso_cuenta_ajena_prohibido():
    token_c1 = get_token("cliente1")

    # cliente1 intenta ver movimientos de cuenta 3 (de cliente2)
    res_mov = client.get("/api/cuentas/3/movimientos", headers={"Authorization": f"Bearer {token_c1}"})
    assert res_mov.status_code == 403

    # cliente1 intenta transferir desde cuenta 3 (de cliente2)
    res_tx = client.post(
        "/api/transferencias",
        json={"cuenta_origen_id": 3, "numero_cuenta_destino": "100100001234", "monto": "50000"},
        headers={"Authorization": f"Bearer {token_c1}", "Idempotency-Key": str(uuid.uuid4())},
    )
    assert res_tx.status_code == 403

def test_05_reversa_operador_y_restriccion_cliente():
    token_c1 = get_token("cliente1")
    token_op = get_token("operador1")

    # Crear transferencia
    tx = client.post(
        "/api/transferencias",
        json={"cuenta_origen_id": 1, "numero_cuenta_destino": "200200004321", "monto": "300000"},
        headers={"Authorization": f"Bearer {token_c1}", "Idempotency-Key": str(uuid.uuid4())},
    ).json()
    tx_id = tx["id"]

    # Cliente intenta reversar -> 403 Forbidden
    res_forbidden = client.post(f"/api/transferencias/{tx_id}/reversar", headers={"Authorization": f"Bearer {token_c1}"})
    assert res_forbidden.status_code == 403

    # Operador reversa -> 200 OK y devuelve saldo a 1.000.000
    res_ok = client.post(f"/api/transferencias/{tx_id}/reversar", headers={"Authorization": f"Bearer {token_op}"})
    assert res_ok.status_code == 200
    assert res_ok.json()["estado"] == "REVERSADA"

    cuentas = client.get("/api/cuentas", headers={"Authorization": f"Bearer {token_c1}"}).json()
    assert Decimal(cuentas[0]["saldo"]) == Decimal("1000000.00")

def test_06_concurrencia_50_transferencias_simultaneas():
    """RA6: 50 solicitudes paralelas de 50.000 PYG contra cuenta con 1.000.000 PYG.
    Solo deben aprobarse 20 y 30 deben rechazarse, dejando saldo exacto en 0.00 (nunca negativo).
    """
    token = get_token("cliente1")

    def send_transfer(_):
        return client.post(
            "/api/transferencias",
            json={"cuenta_origen_id": 1, "numero_cuenta_destino": "200200004321", "monto": "50000"},
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid.uuid4())},
        ).status_code

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(send_transfer, range(50)))

    exitosas = results.count(201)
    rechazadas = results.count(400)

    assert exitosas == 20
    assert rechazadas == 30

    cuentas = client.get("/api/cuentas", headers={"Authorization": f"Bearer {token}"}).json()
    assert Decimal(cuentas[0]["saldo"]) == Decimal("0.00")

def test_07_asistente_ia_enmascaramiento_pii():
    token = get_token("cliente1")
    reclamo = (
        "Hola, soy Juan con CI 4.123.456, mi cuenta es 100100001234, "
        "correo juan@correo.com y tel 0981-555-123. Me hicieron un cobro doble por fraude."
    )
    res = client.post(
        "/api/reclamos/analizar",
        json={"texto": reclamo},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["categoria"] in ["FRAUDE", "TRANSFERENCIA", "TARJETA", "CUENTA", "OTRO"]
    assert data["prioridad"] in ["ALTA", "MEDIA", "BAJA"]
    assert len(data["resumen"]) <= 200

    # Verificar que no se filtró ningún dato sensible en el texto enmascarado
    masked = data["texto_enmascarado"]
    assert "4.123.456" not in masked
    assert "100100001234" not in masked
    assert "juan@correo.com" not in masked
    assert "0981-555-123" not in masked
