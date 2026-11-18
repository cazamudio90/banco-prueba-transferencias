import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from sqlalchemy.orm import Session
from sqlalchemy import func
from fastapi import HTTPException
from app.models import Cuenta, Transferencia, Movimiento, Auditoria, Outbox, TipoCambio

class LedgerSentinel:
    DAILY_LIMIT_PYG = Decimal("20000000")
    DAILY_LIMIT_USD = Decimal("3000.00")

    def __init__(self, db: Session):
        self.db = db

    def _validate_amount_precision(self, amount: Decimal, currency: str):
        if amount <= Decimal("0"):
            raise HTTPException(status_code=400, detail="El monto debe ser mayor a cero.")
        if currency == "PYG" and amount % 1 != 0:
            raise HTTPException(status_code=400, detail="Los montos en PYG no admiten decimales.")
        if currency == "USD" and amount.as_tuple().exponent < -2:
            raise HTTPException(status_code=400, detail="Los montos en USD admiten máximo 2 decimales.")

    def _check_daily_limit(self, user_id: int, amount: Decimal, currency: str):
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        total_today = (
            self.db.query(func.coalesce(func.sum(Transferencia.monto_origen), Decimal("0")))
            .join(Cuenta, Transferencia.cuenta_origen_id == Cuenta.id)
            .filter(
                Cuenta.usuario_id == user_id,
                Transferencia.moneda_origen == currency,
                Transferencia.estado == "COMPLETADA",
                Transferencia.creado_en >= today_start
            )
            .scalar()
        )

        limit = self.DAILY_LIMIT_PYG if currency == "PYG" else self.DAILY_LIMIT_USD
        if Decimal(str(total_today)) + amount > limit:
            raise HTTPException(
                status_code=400,
                detail=f"Supera el límite diario permitido de {limit} {currency}."
            )

    def _calculate_exchange(self, amount: Decimal, orig_curr: str, dest_curr: str) -> tuple[Decimal, Decimal]:
        if orig_curr == dest_curr:
            return amount, Decimal("1.000000")

        rate_record = (
            self.db.query(TipoCambio)
            .filter(
                TipoCambio.moneda_origen == orig_curr,
                TipoCambio.moneda_destino == dest_curr
            )
            .order_by(TipoCambio.vigente_desde.desc())
            .first()
        )
        if not rate_record:
            raise HTTPException(status_code=400, detail="Tipo de cambio no disponible para estas monedas.")

        if orig_curr == "USD" and dest_curr == "PYG":
            rate = Decimal(str(rate_record.tasa_compra))
            converted = (amount * rate).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        else:
            rate = Decimal(str(rate_record.tasa_venta))
            converted = (amount / rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return converted, rate

    def execute_transfer(
        self,
        user_id: int,
        origin_account_id: int,
        destination_account_number: str,
        amount: Decimal,
        idempotency_key: str,
        correlation_id: str = None,
        ip_origen: str = None
    ) -> Transferencia:
        # 1. Idempotencia (RF6)
        existing = self.db.query(Transferencia).filter_by(idempotency_key=idempotency_key).first()
        if existing:
            return existing

        try:
            # 2. Buscar destino para ordenar bloqueos por ID (previene deadlocks)
            dest_lookup = self.db.query(Cuenta).filter_by(numero_cuenta=destination_account_number).first()
            if not dest_lookup:
                raise HTTPException(status_code=404, detail="La cuenta destino no existe.")
            if origin_account_id == dest_lookup.id:
                raise HTTPException(status_code=400, detail="La cuenta destino debe ser distinta a la de origen.")

            # Bloqueo pesimista (UPDLOCK, ROWLOCK en SQL Server)
            ids_to_lock = sorted([origin_account_id, dest_lookup.id])
            locked_accounts = (
                self.db.query(Cuenta)
                .filter(Cuenta.id.in_(ids_to_lock))
                .with_for_update()
                .all()
            )
            acc_map = {acc.id: acc for acc in locked_accounts}
            origin_acc = acc_map.get(origin_account_id)
            dest_acc = acc_map.get(dest_lookup.id)

            # 3. Validaciones de seguridad y negocio (RF2, RF4)
            if not origin_acc or origin_acc.usuario_id != user_id:
                raise HTTPException(status_code=403, detail="No tiene permisos sobre la cuenta de origen.")
            if not origin_acc.activa or not dest_acc.activa:
                raise HTTPException(status_code=400, detail="Ambas cuentas deben estar activas.")

            self._validate_amount_precision(amount, origin_acc.moneda)
            self._check_daily_limit(user_id, amount, origin_acc.moneda)

            origin_balance = Decimal(str(origin_acc.saldo))
            if origin_balance < amount:
                raise HTTPException(status_code=400, detail="Saldo insuficiente en la cuenta de origen.")

            # 4. Conversión de moneda si aplica (RA1)
            amount_dest, applied_rate = self._calculate_exchange(amount, origin_acc.moneda, dest_acc.moneda)

            now = datetime.now(timezone.utc)
            transfer = Transferencia(
                idempotency_key=idempotency_key,
                cuenta_origen_id=origin_acc.id,
                cuenta_destino_id=dest_acc.id,
                monto_origen=amount,
                moneda_origen=origin_acc.moneda,
                monto_destino=amount_dest,
                moneda_destino=dest_acc.moneda,
                tasa_aplicada=applied_rate,
                estado="COMPLETADA",
                creado_en=now,
                completado_en=now
            )
            self.db.add(transfer)
            self.db.flush()

            # 5. Actualizar saldos y registrar asientos inmutables (RF3, RF4)
            dest_balance = Decimal(str(dest_acc.saldo))
            new_origin_balance = origin_balance - amount
            new_dest_balance = dest_balance + amount_dest

            origin_acc.saldo = new_origin_balance
            dest_acc.saldo = new_dest_balance

            mov_debit = Movimiento(
                cuenta_id=origin_acc.id,
                transferencia_id=transfer.id,
                tipo="DEBITO",
                monto=amount,
                saldo_anterior=origin_balance,
                saldo_posterior=new_origin_balance,
                descripcion=f"Transferencia enviada a ****{dest_acc.numero_cuenta[-4:]}",
                fecha=now
            )
            mov_credit = Movimiento(
                cuenta_id=dest_acc.id,
                transferencia_id=transfer.id,
                tipo="CREDITO",
                monto=amount_dest,
                saldo_anterior=dest_balance,
                saldo_posterior=new_dest_balance,
                descripcion=f"Transferencia recibida de ****{origin_acc.numero_cuenta[-4:]}",
                fecha=now
            )
            self.db.add_all([mov_debit, mov_credit])

            # 6. Auditoría (RF8) y Outbox (RA2)
            audit = Auditoria(
                usuario_id=user_id,
                accion="TRANSFERENCIA_COMPLETADA",
                detalle=f"Transferencia #{transfer.id} por {amount} {origin_acc.moneda}",
                correlation_id=correlation_id,
                ip_origen=ip_origen,
                fecha=now
            )
            outbox_event = Outbox(
                aggregate_type="TRANSFERENCIA",
                aggregate_id=transfer.id,
                event_type="TRANSFERENCIA_COMPLETADA",
                payload=json.dumps({
                    "transfer_id": transfer.id,
                    "monto_origen": str(amount),
                    "moneda_origen": origin_acc.moneda,
                    "estado": "COMPLETADA"
                }),
                estado="PENDIENTE",
                creado_en=now
            )
            self.db.add_all([audit, outbox_event])

            self.db.commit()
            self.db.refresh(transfer)
            return transfer

        except HTTPException:
            self.db.rollback()
            raise
        except Exception as e:
            self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Error interno procesando transferencia: {str(e)}")

    def reverse_transfer(
        self,
        transfer_id: int,
        operator_id: int,
        correlation_id: str = None,
        ip_origen: str = None
    ) -> Transferencia:
        try:
            transfer = self.db.query(Transferencia).filter_by(id=transfer_id).with_for_update().first()
            if not transfer:
                raise HTTPException(status_code=404, detail="Transferencia no encontrada.")
            if transfer.estado != "COMPLETADA":
                raise HTTPException(status_code=400, detail="Solo se pueden reversar transferencias COMPLETADAS.")

            now = datetime.now(timezone.utc)
            created_utc = transfer.creado_en.replace(tzinfo=timezone.utc) if transfer.creado_en.tzinfo is None else transfer.creado_en
            if now - created_utc > timedelta(hours=24):
                raise HTTPException(status_code=400, detail="El plazo máximo de 24 horas para reversar ha expirado.")

            ids_to_lock = sorted([transfer.cuenta_origen_id, transfer.cuenta_destino_id])
            locked_accounts = self.db.query(Cuenta).filter(Cuenta.id.in_(ids_to_lock)).with_for_update().all()
            acc_map = {acc.id: acc for acc in locked_accounts}

            origin_acc = acc_map[transfer.cuenta_origen_id]
            dest_acc = acc_map[transfer.cuenta_destino_id]

            dest_balance = Decimal(str(dest_acc.saldo))
            amount_dest = Decimal(str(transfer.monto_destino))
            if dest_balance < amount_dest:
                raise HTTPException(status_code=400, detail="La cuenta destino no tiene saldo suficiente para reversar.")

            origin_balance = Decimal(str(origin_acc.saldo))
            amount_orig = Decimal(str(transfer.monto_origen))

            new_dest_balance = dest_balance - amount_dest
            new_origin_balance = origin_balance + amount_orig

            dest_acc.saldo = new_dest_balance
            origin_acc.saldo = new_origin_balance

            transfer.estado = "REVERSADA"
            transfer.reversado_en = now
            transfer.reversado_por_id = operator_id

            # Contra-asientos inmutables (RF5)
            mov_rev_debit = Movimiento(
                cuenta_id=dest_acc.id,
                transferencia_id=transfer.id,
                tipo="REVERSA_DEBITO",
                monto=amount_dest,
                saldo_anterior=dest_balance,
                saldo_posterior=new_dest_balance,
                descripcion=f"Reversa de transferencia #{transfer.id}",
                fecha=now
            )
            mov_rev_credit = Movimiento(
                cuenta_id=origin_acc.id,
                transferencia_id=transfer.id,
                tipo="REVERSA_CREDITO",
                monto=amount_orig,
                saldo_anterior=origin_balance,
                saldo_posterior=new_origin_balance,
                descripcion=f"Devolución por reversa de transferencia #{transfer.id}",
                fecha=now
            )
            self.db.add_all([mov_rev_debit, mov_rev_credit])

            audit = Auditoria(
                usuario_id=operator_id,
                accion="TRANSFERENCIA_REVERSADA",
                detalle=f"Operador reversó transferencia #{transfer.id}",
                correlation_id=correlation_id,
                ip_origen=ip_origen,
                fecha=now
            )
            outbox_event = Outbox(
                aggregate_type="TRANSFERENCIA",
                aggregate_id=transfer.id,
                event_type="TRANSFERENCIA_REVERSADA",
                payload=json.dumps({"transfer_id": transfer.id, "estado": "REVERSADA"}),
                estado="PENDIENTE",
                creado_en=now
            )
            self.db.add_all([audit, outbox_event])

            self.db.commit()
            self.db.refresh(transfer)
            return transfer

        except HTTPException:
            self.db.rollback()
            raise
        except Exception as e:
            self.db.rollback()
            raise HTTPException(status_code=500, detail=f"Error al reversar transferencia: {str(e)}")
