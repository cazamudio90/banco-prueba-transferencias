const API_URL = "http://127.0.0.1:8000";

export interface Usuario {
  id: number;
  username: string;
  nombre_completo: string;
  rol: "CLIENTE" | "OPERADOR";
}

export interface Cuenta {
  id: number;
  numero_enmascarado: string;
  moneda: "PYG" | "USD";
  saldo: string;
}

export interface Movimiento {
  id: number;
  transferencia_id: number | null;
  tipo: string;
  monto: string;
  saldo_anterior: string;
  saldo_posterior: string;
  descripcion: string;
  fecha: string;
}

export async function loginApi(username: string, password: string) {
  const form = new URLSearchParams();
  form.append("username", username);
  form.append("password", password);

  const res = await fetch(`${API_URL}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: form.toString(),
  });

  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Error al iniciar sesión");
  }
  return res.json();
}

export async function getCuentas(token: string): Promise<Cuenta[]> {
  const res = await fetch(`${API_URL}/api/cuentas`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Error al cargar cuentas");
  return res.json();
}

export async function getMovimientos(
  token: string,
  cuentaId: number,
  page: number,
  fechaDesde?: string,
  fechaHasta?: string
) {
  const params = new URLSearchParams({ page: String(page), page_size: "10" });
  if (fechaDesde) params.append("fecha_desde", `${fechaDesde}T00:00:00`);
  if (fechaHasta) params.append("fecha_hasta", `${fechaHasta}T23:59:59`);

  const res = await fetch(`${API_URL}/api/cuentas/${cuentaId}/movimientos?${params}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Error al cargar movimientos");
  return res.json();
}

export async function crearTransferencia(
  token: string,
  cuentaOrigenId: number,
  numeroCuentaDestino: string,
  monto: string,
  idempotencyKey: string
) {
  const res = await fetch(`${API_URL}/api/transferencias`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify({
      cuenta_origen_id: cuentaOrigenId,
      numero_cuenta_destino: numeroCuentaDestino,
      monto,
    }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Error en la transferencia");
  return data;
}

export async function analizarReclamo(token: string, texto: string) {
  const res = await fetch(`${API_URL}/api/reclamos/analizar`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ texto }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Error analizando reclamo");
  return data;
}

export async function getTransferenciasOperador(token: string) {
  const res = await fetch(`${API_URL}/api/operador/transferencias`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Error cargando transferencias");
  return res.json();
}

export async function reversarTransferencia(token: string, transferId: number) {
  const res = await fetch(`${API_URL}/api/transferencias/${transferId}/reversar`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Error al reversar");
  return data;
}
