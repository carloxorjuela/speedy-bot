"""
Speedy — Scheduler de alertas de vencimiento
Corre en background y revisa diariamente si algún conductor
tiene SOAT, RTM o Tarjeta de Operación próximos a vencer.
Envía WhatsApp y registra en hoja Alertas_Enviadas.

Uso:
    python alerts_scheduler.py          # Corre inmediatamente + cada día a las 9am
    python alerts_scheduler.py --now    # Solo corre una vez y sale
"""

import sys
import json
import sqlite3
import os
import time
from datetime import datetime, timedelta

import schedule

import config
import whatsapp_client as wa
import sheets_logger as sheets

DB_PATH = os.path.join(os.path.dirname(__file__), "carplus.db")

# Días de anticipación para cada alerta
ALERTAS_CONFIG = {
    "SOAT":              [30, 15, 7],
    "RTM":               [30, 15, 7],
    "TARJETA_OPERACION": [30, 15, 7],
    "POLIZA_RC":         [30, 15],
}


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _parse_date(s: str):
    """Parsea fecha ISO o DD/MM/YYYY → datetime. Retorna None si falla."""
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(s)[:len(fmt)], fmt)
        except (ValueError, TypeError):
            continue
    return None


def _dias_para_vencer(fecha_str: str) -> int | None:
    dt = _parse_date(fecha_str)
    if not dt:
        return None
    return (dt.date() - datetime.now().date()).days


def _alerta_ya_enviada(cedula: str, placa: str, documento: str, hito: str) -> bool:
    """Revisa en Alertas_Enviadas si ya se mandó esta alerta hoy."""
    try:
        registros = sheets._get_sheet().worksheet("Alertas_Enviadas").get_all_records()
        hoy = datetime.now().strftime("%d/%m/%Y")
        for r in registros:
            if (str(r.get("Cedula", "")) == str(cedula)
                    and str(r.get("Placa", "")) == str(placa)
                    and str(r.get("Documento", "")) == str(documento)
                    and str(r.get("Hito", "")) == str(hito)
                    and str(r.get("Fecha", "")) == hoy):
                return True
    except Exception as e:
        print(f"[Alerts] No pude verificar duplicados: {e}")
    return False


def _mensaje_alerta(nombre: str, placa: str, tipo: str, dias: int, fecha: str) -> str:
    nombres_doc = {
        "SOAT":              "SOAT 🚗",
        "RTM":               "Revisión Técnico Mecánica (RTM) 🔧",
        "TARJETA_OPERACION": "Tarjeta de Operación 📋",
        "POLIZA_RC":         "Póliza de Responsabilidad Civil 📃",
    }
    nombre_doc = nombres_doc.get(tipo, tipo)
    primer_nombre = nombre.split()[0] if nombre else "Conductor"

    if dias <= 0:
        urgencia = f"⛔ *VENCIDO hace {abs(dias)} día(s)*"
    elif dias <= 7:
        urgencia = f"🔴 *Vence en {dias} día(s)*"
    elif dias <= 15:
        urgencia = f"🟠 *Vence en {dias} días*"
    else:
        urgencia = f"🟡 *Vence en {dias} días*"

    return (
        f"⚠️ *Alerta de vencimiento — Speedy*\n\n"
        f"Hola {primer_nombre}, te recordamos que tu:\n\n"
        f"📄 *{nombre_doc}*\n"
        f"🚘 Placa: *{placa}*\n"
        f"{urgencia} ({fecha})\n\n"
        f"Renuévalo cuanto antes para evitar sanciones. "
        f"Si ya lo renovaste, escríbenos para actualizar tu información. 🙏"
    )


def revisar_y_enviar_alertas():
    print(f"\n[Alerts] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} — Revisando vencimientos...")

    # Leer conductores activos de Google Sheets
    conductores = []
    try:
        ws = sheets._get_sheet().worksheet("Conductores")
        conductores = [r for r in ws.get_all_records() if r.get("Activo", "SI") == "SI"]
        print(f"[Alerts] {len(conductores)} conductores activos en Sheets")
    except Exception as e:
        print(f"[Alerts] Error leyendo Conductores desde Sheets: {e}")
        return

    alertas_enviadas = 0

    for conductor in conductores:
        nombre   = str(conductor.get("Nombre", ""))
        cedula   = str(conductor.get("Cedula", "")).strip()
        placa    = str(conductor.get("Placa", "")).strip().upper()
        telefono = str(conductor.get("Telefono", "")).strip()

        if not placa or not telefono:
            continue

        # Buscar última consulta RUNT en caché SQLite
        try:
            with _get_db() as conn:
                row = conn.execute(
                    "SELECT * FROM placas_cache WHERE placa = ?", (placa,)
                ).fetchone()
        except Exception as e:
            print(f"[Alerts] Error SQLite para {placa}: {e}")
            continue

        if not row:
            print(f"[Alerts] Sin datos en caché para placa {placa} — omitiendo")
            continue

        # Campos a revisar: (tipo, campo_fecha_en_db)
        campos = [
            ("SOAT",              row["soat_vence"]),
            ("RTM",               row["rtm_vence"]),
            ("TARJETA_OPERACION", row["tarjeta_op_vence"]),
        ]

        for tipo, fecha_str in campos:
            dias = _dias_para_vencer(fecha_str)
            if dias is None:
                continue

            umbrales = ALERTAS_CONFIG.get(tipo, [30])
            for umbral in umbrales:
                # Alertar cuando dias == umbral (o vencido y sin alerta de hoy)
                if dias == umbral or (dias <= 0 and umbral == umbrales[-1]):
                    hito = f"{tipo}_{umbral}d"
                    if _alerta_ya_enviada(cedula, placa, tipo, hito):
                        print(f"[Alerts] Ya enviada: {placa} {hito}")
                        continue

                    msg = _mensaje_alerta(nombre, placa, tipo, dias, fecha_str)
                    if wa.send_text(telefono, msg):
                        sheets.registrar_alerta(cedula, placa, tipo, hito, telefono)
                        alertas_enviadas += 1
                        print(f"[Alerts] ✅ Alerta enviada: {placa} — {hito} — {telefono}")
                    else:
                        print(f"[Alerts] ❌ Falló envío: {placa} — {telefono}")
                    break  # Solo un umbral por tipo por día

    print(f"[Alerts] Listo — {alertas_enviadas} alertas enviadas.\n")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    run_once = "--now" in sys.argv

    if run_once:
        revisar_y_enviar_alertas()
    else:
        print("[Alerts] Scheduler iniciado — corre diariamente a las 09:00 AM")
        print("[Alerts] Corriendo primera revisión ahora...")
        revisar_y_enviar_alertas()

        schedule.every().day.at("09:00").do(revisar_y_enviar_alertas)

        while True:
            schedule.run_pending()
            time.sleep(60)
