import os
import gspread
from datetime import datetime
import config

_gc_cache = None


def _get_sheet():
    """
    Autenticación flexible:
    - Si existe credentials.json tipo service account  → lo usa directamente.
    - Si existe credentials.json tipo OAuth desktop app → abre el navegador la
      primera vez y guarda el token en ~/.config/gspread/authorized_user.json.
    - Si no hay archivo → lanza error con instrucciones claras.
    """
    global _gc_cache
    if _gc_cache:
        return _gc_cache.open_by_key(config.GOOGLE_SHEETS_ID)

    creds_path = config.GOOGLE_CREDENTIALS_FILE

    if not os.path.exists(creds_path):
        raise FileNotFoundError(
            f"No se encontró '{creds_path}'.\n"
            "Sigue las instrucciones en SETUP.md para crear las credenciales de Google."
        )

    # Detectar tipo de credencial por el campo "type" dentro del JSON
    import json
    with open(creds_path) as f:
        creds_data = json.load(f)

    if creds_data.get("type") == "service_account":
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_file(
            creds_path,
            scopes=["https://www.googleapis.com/auth/spreadsheets"],
        )
        gc = gspread.authorize(creds)
    else:
        # OAuth Desktop app — abre el navegador la primera vez
        gc = gspread.oauth(credentials_filename=creds_path)

    _gc_cache = gc
    return gc.open_by_key(config.GOOGLE_SHEETS_ID)


def log_mensaje(telefono: str, nombre: str, estado: str,
                mensaje_usuario: str, respuesta_bot: str,
                cedula: str = "", placa: str = "", exitosa: bool = False) -> None:
    try:
        ws = _get_sheet().worksheet("Logs")
        ws.append_row([
            datetime.now().isoformat(),
            telefono, nombre, estado,
            mensaje_usuario[:500], respuesta_bot[:500],
            cedula, placa,
            "SI" if exitosa else "NO",
        ])
    except Exception as e:
        print(f"[Sheets] Error log_mensaje: {e}")


def get_conductor(telefono: str = None, cedula: str = None) -> dict:
    try:
        ws = _get_sheet().worksheet("Conductores")
        records = ws.get_all_records()
        for r in records:
            if telefono and str(r.get("Telefono", "")).strip() == str(telefono).strip():
                return r
            if cedula and str(r.get("Cedula", "")).strip() == str(cedula).strip():
                return r
    except Exception as e:
        print(f"[Sheets] Error get_conductor: {e}")
    return {}


def upsert_conductor(nombre: str, cedula: str, placa: str, telefono: str) -> None:
    try:
        ws = _get_sheet().worksheet("Conductores")
        records = ws.get_all_records()
        for i, r in enumerate(records, start=2):  # row 1 = header
            if str(r.get("Cedula", "")).strip() == str(cedula).strip():
                ws.update(f"A{i}:D{i}", [[nombre, cedula, placa, telefono]])
                return
        ws.append_row([nombre, cedula, placa, telefono, "SI"])
    except Exception as e:
        print(f"[Sheets] Error upsert_conductor: {e}")


def registrar_alerta(cedula: str, placa: str, documento: str,
                     hito: str, telefono: str) -> None:
    try:
        ws = _get_sheet().worksheet("Alertas_Enviadas")
        ws.append_row([
            datetime.now().strftime("%d/%m/%Y"),
            cedula, placa, documento, hito, telefono,
        ])
    except Exception as e:
        print(f"[Sheets] Error registrar_alerta: {e}")
