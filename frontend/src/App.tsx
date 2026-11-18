import React, { useState, useEffect } from "react";
import {
  loginApi,
  getCuentas,
  getMovimientos,
  crearTransferencia,
  analizarReclamo,
  getTransferenciasOperador,
  reversarTransferencia,
  type Usuario,
  type Cuenta,
  type Movimiento,
} from "./api";


export default function App() {
  const [token, setToken] = useState<string | null>(null);
  const [usuario, setUsuario] = useState<Usuario | null>(null);
  const [username, setUsername] = useState("cliente1");
  const [password, setPassword] = useState("Password123!");
  const [error, setError] = useState<string | null>(null);
  const [mensaje, setMensaje] = useState<string | null>(null);

  // Estado Cliente
  const [cuentas, setCuentas] = useState<Cuenta[]>([]);
  const [cuentaSeleccionada, setCuentaSeleccionada] = useState<number | null>(null);
  const [movimientos, setMovimientos] = useState<Movimiento[]>([]);
  const [page, setPage] = useState(1);
  const [totalMov, setTotalMov] = useState(0);
  const [fechaDesde, setFechaDesde] = useState("");
  const [fechaHasta, setFechaHasta] = useState("");

  // Estado Transferencia (con Idempotency-Key por intento)
  const [destino, setDestino] = useState("200200004321");
  const [monto, setMonto] = useState("");
  const [enviandoTx, setEnviandoTx] = useState(false);
  const [idemKey, setIdemKey] = useState(() => crypto.randomUUID());

  // Estado Reclamo IA (RF9)
  const [textoReclamo, setTextoReclamo] = useState("");
  const [resultadoIA, setResultadoIA] = useState<any>(null);
  const [analizandoIA, setAnalizandoIA] = useState(false);

  // Estado Operador (RF5)
  const [txOperador, setTxOperador] = useState<any[]>([]);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const data = await loginApi(username, password);
      setToken(data.access_token);
      setUsuario(data.usuario);
    } catch (err: any) {
      setError(err.message);
    }
  };

  const cargarDatos = async () => {
    if (!token || !usuario) return;
    try {
      if (usuario.rol === "CLIENTE") {
        const listaCuentas = await getCuentas(token);
        setCuentas(listaCuentas);
             const idActiva = cuentaSeleccionada ?? (listaCuentas.length > 0 ? listaCuentas[0].id : null);
        setCuentaSeleccionada(idActiva);
        if (idActiva) {
          const movData = await getMovimientos(token, idActiva, page, fechaDesde, fechaHasta);
          setMovimientos(movData.items);
          setTotalMov(movData.total);
        }
      } else {
        const listaTx = await getTransferenciasOperador(token);
        setTxOperador(listaTx);
      }
    } catch (err: any) {
      setError(err.message);
    }
  };

  useEffect(() => {
    cargarDatos();
  }, [token, usuario, cuentaSeleccionada, page]);

  const handleTransferir = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !cuentaSeleccionada || enviandoTx) return;
    setError(null);
    setMensaje(null);
    setEnviandoTx(true);
    try {
      const res = await crearTransferencia(token, cuentaSeleccionada, destino, monto, idemKey);
      setMensaje(`Transferencia #${res.id} completada por ${res.monto_origen} ${res.moneda_origen}`);
      setMonto("");
      setIdemKey(crypto.randomUUID()); // Nueva clave para la próxima operación
      await cargarDatos();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setEnviandoTx(false);
    }
  };

  const handleAnalizarReclamo = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!token || !textoReclamo.trim()) return;
    setAnalizandoIA(true);
    setError(null);
    try {
      const res = await analizarReclamo(token, textoReclamo);
      setResultadoIA(res);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setAnalizandoIA(false);
    }
  };

  const handleReversar = async (txId: number) => {
    if (!token) return;
    setError(null);
    setMensaje(null);
    try {
      await reversarTransferencia(token, txId);
      setMensaje(`Transferencia #${txId} reversada correctamente.`);
      await cargarDatos();
    } catch (err: any) {
      setError(err.message);
    }
  };

  if (!token || !usuario) {
    return (
      <div style={{ maxWidth: 400, margin: "60px auto", fontFamily: "sans-serif" }}>
        <h2>Banco Prueba S.A.</h2>
        <p>Ingreso al Portal de Transferencias</p>
        {error && <div style={{ color: "red", marginBottom: 12 }}>{error}</div>}
        <form onSubmit={handleLogin} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Usuario" required />
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Contraseña" required />
          <button type="submit">Ingresar</button>
        </form>
        <small style={{ display: "block", marginTop: 16, color: "#555" }}>
          Usuarios prueba: cliente1, cliente2, operador1 (Clave: Password123!)
        </small>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 960, margin: "24px auto", fontFamily: "sans-serif", padding: "0 16px" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", borderBottom: "1px solid #ccc", paddingBottom: 12 }}>
        <div>
          <strong>Banco Prueba S.A.</strong> — {usuario.nombre_completo} ({usuario.rol})
        </div>
        <button onClick={() => { setToken(null); setUsuario(null); }}>Cerrar sesión</button>
      </header>

      {error && <div style={{ background: "#fee", color: "#900", padding: 10, marginTop: 12 }}>{error}</div>}
      {mensaje && <div style={{ background: "#efe", color: "#060", padding: 10, marginTop: 12 }}>{mensaje}</div>}

      {usuario.rol === "CLIENTE" ? (
        <>
          <h3>Mis Cuentas</h3>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
            {cuentas.map((c) => (
              <div
                key={c.id}
                onClick={() => { setCuentaSeleccionada(c.id); setPage(1); }}
                style={{
                  border: cuentaSeleccionada === c.id ? "2px solid #0055aa" : "1px solid #ccc",
                  padding: 14,
                  borderRadius: 6,
                  cursor: "pointer",
                  minWidth: 200,
                }}
              >
                <div>Cuenta: <strong>{c.numero_enmascarado}</strong></div>
                <div style={{ fontSize: 20, marginTop: 6 }}>{c.saldo} {c.moneda}</div>
              </div>
            ))}
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24, marginTop: 24 }}>
            <section style={{ border: "1px solid #ddd", padding: 16, borderRadius: 6 }}>
              <h3>Nueva Transferencia</h3>
              <form onSubmit={handleTransferir} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <label>Cuenta Destino (ej. 200200004321):</label>
                <input value={destino} onChange={(e) => setDestino(e.target.value)} required />
                <label>Monto:</label>
                <input type="number" step="any" value={monto} onChange={(e) => setMonto(e.target.value)} required />
                <button type="submit" disabled={enviandoTx}>
                  {enviandoTx ? "Procesando..." : "Transferir ahora"}
                </button>
              </form>
            </section>

            <section style={{ border: "1px solid #ddd", padding: 16, borderRadius: 6 }}>
              <h3>Asistente de Reclamos (IA)</h3>
              <form onSubmit={handleAnalizarReclamo} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                <textarea
                  rows={3}
                  placeholder="Describe tu reclamo (los datos personales se ocultan automáticamente)..."
                  value={textoReclamo}
                  onChange={(e) => setTextoReclamo(e.target.value)}
                  required
                />
                                <button type="submit" disabled={analizandoIA}>
                  {analizandoIA ? "Analizando..." : "Clasificar Reclamo"}
                </button>
              </form>
              {resultadoIA && (
                <div style={{ marginTop: 12, background: "#f7f7f7", padding: 10, fontSize: 14 }}>
                  <div><strong>Categoría:</strong> {resultadoIA.categoria} | <strong>Prioridad:</strong> {resultadoIA.prioridad}</div>
                  <div><strong>Resumen:</strong> {resultadoIA.resumen}</div>
                  <div style={{ color: "#666", marginTop: 4 }}><small>Texto enviado (enmascarado): {resultadoIA.texto_enmascarado}</small></div>
                </div>
              )}
            </section>
          </div>

          <h3 style={{ marginTop: 28 }}>Movimientos de la Cuenta</h3>
          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            <input type="date" value={fechaDesde} onChange={(e) => setFechaDesde(e.target.value)} />
            <input type="date" value={fechaHasta} onChange={(e) => setFechaHasta(e.target.value)} />
            <button onClick={() => { setPage(1); cargarDatos(); }}>Filtrar</button>
          </div>

          <table border={1} cellPadding={8} style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Tipo</th>
                <th>Descripción</th>
                <th>Monto</th>
                <th>Saldo Posterior</th>
              </tr>
            </thead>
            <tbody>
              {movimientos.map((m) => (
                <tr key={m.id}>
                  <td>{new Date(m.fecha).toLocaleString()}</td>
                  <td>{m.tipo}</td>
                  <td>{m.descripcion}</td>
                  <td>{m.monto}</td>
                  <td>{m.saldo_posterior}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <div style={{ marginTop: 12, display: "flex", gap: 12, alignItems: "center" }}>
            <button disabled={page <= 1} onClick={() => setPage(page - 1)}>Anterior</button>
            <span>Página {page} (Total: {totalMov})</span>
            <button disabled={page * 10 >= totalMov} onClick={() => setPage(page + 1)}>Siguiente</button>
          </div>
        </>
      ) : (
        <section style={{ marginTop: 20 }}>
          <h3>Panel de Operador — Gestión de Reversas (RF5)</h3>
          <table border={1} cellPadding={8} style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th>ID</th>
                <th>Monto</th>
                <th>Moneda</th>
                <th>Estado</th>
                <th>Fecha</th>
                <th>Acción</th>
              </tr>
            </thead>
            <tbody>
              {txOperador.map((t) => (
                <tr key={t.id}>
                  <td>#{t.id}</td>
                  <td>{t.monto_origen}</td>
                  <td>{t.moneda_origen}</td>
                  <td>{t.estado}</td>
                  <td>{new Date(t.creado_en).toLocaleString()}</td>
                  <td>
                    {t.estado === "COMPLETADA" ? (
                      <button onClick={() => handleReversar(t.id)}>Reversar</button>
                    ) : (
                      <span>-</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
