"""
Speedy — Bot WhatsApp de verificación vehicular
Webhook directo con Meta Business API + RUNT + PDF parser + Google Sheets
"""

import threading
import traceback

from flask import Flask, request, jsonify

import config
import whatsapp_client as wa
import sheets_logger as sheets
from conversation import (
    get_state, update_state, reset_state, process_message
)
from cross_reference import comparar, formatear_resultado
from runt_scraper import RuntScraper, SimitScraper, normalizar_tipo_documento

app = Flask(__name__)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_webhook_entry(data: dict):
    """
    Extrae (phone, name, msg_text, has_media, media_id, media_mime) de un
    payload de Meta WhatsApp Cloud API.
    Retorna None si no hay mensajes relevantes.
    """
    try:
        entry   = data["entry"][0]
        changes = entry["changes"][0]["value"]
        msgs    = changes.get("messages")
        if not msgs:
            return None

        msg  = msgs[0]
        phone = msg["from"]
        name  = (changes.get("contacts") or [{}])[0].get("profile", {}).get("name", "")
        msg_type = msg.get("type", "text")

        text      = ""
        has_media = False
        media_id  = None
        media_mime = None

        if msg_type == "text":
            text = msg.get("text", {}).get("body", "")
        elif msg_type == "document":
            doc = msg.get("document", {})
            media_id   = doc.get("id")
            media_mime = doc.get("mime_type", "")
            has_media  = True
            text       = doc.get("filename", "")
        elif msg_type == "image":
            img = msg.get("image", {})
            media_id   = img.get("id")
            media_mime = img.get("mime_type", "image/jpeg")
            has_media  = True
        elif msg_type == "interactive":
            # Button reply
            text = (msg.get("interactive", {})
                       .get("button_reply", {})
                       .get("title", ""))
        else:
            text = ""

        return phone, name, text, has_media, media_id, media_mime
    except (KeyError, IndexError, TypeError):
        return None


def _log(phone: str, nombre: str, estado: str,
         msg_usuario: str, respuesta_bot: str,
         exitosa: bool = False) -> None:
    st = get_state(phone)
    threading.Thread(
        target=sheets.log_mensaje,
        args=(phone, nombre, estado, msg_usuario, respuesta_bot,
              st.get("documento", ""), st.get("placa", ""), exitosa),
        daemon=True,
    ).start()


# ── RUNT worker (ejecutado en hilo background) ────────────────────────────────

def _run_runt_and_reply(phone: str, nombre: str) -> None:
    """Ejecuta la consulta RUNT+SIMIT y envía los resultados por WhatsApp."""
    st = get_state(phone)
    placa      = st.get("placa", "")
    documento  = st.get("documento", "")
    tipo_raw   = st.get("doc_type", "C")
    pdf_data   = st.get("pdfs_collected", {})

    try:
        tipo = normalizar_tipo_documento(tipo_raw)
    except ValueError:
        tipo = "C"

    try:
        runt  = RuntScraper(twocaptcha_api_key=config.TWOCAPTCHA_KEY or None)
        simit = SimitScraper()

        datos = runt.consulta_completa(
            placa, documento,
            tipo_documento=tipo,
            usar_2captcha=bool(config.TWOCAPTCHA_KEY),
        )
        datos["simit"] = simit.consultar(placa)

        update_state(phone, {"runt_data": datos, "state": "RUNT_DONE"})

        # Guardar conductor en Sheets
        info = (datos.get("auth", {}) or {}).get("infoVehiculo", {}) or {}
        sheets.upsert_conductor(nombre, documento, placa, phone)

        # Enviar resultado RUNT
        runt_msg = runt.formatear_para_whatsapp(datos)
        wa.send_text(phone, runt_msg)

        # Cross-reference con PDFs (si los hay)
        if pdf_data:
            discrepancias = comparar(pdf_data, datos)
            wa.send_text(phone, formatear_resultado(discrepancias))

        wa.send_text(
            phone,
            "¿Necesitas algo más? Escribe *REINICIAR* para hacer otra consulta 🔄"
        )

        _log(phone, nombre, "RUNT_DONE", "[consulta RUNT]", runt_msg[:500], exitosa=True)

    except Exception as e:
        err = str(e)
        print(f"[Speedy] Error RUNT para {phone}: {err}")
        traceback.print_exc()
        wa.send_text(
            phone,
            f"❌ Hubo un error al consultar el RUNT:\n_{err}_\n\n"
            "Por favor verifica que la placa y el documento sean correctos e intenta de nuevo. "
            "Escribe *REINICIAR* para volver al inicio."
        )
        update_state(phone, {"state": "DONE"})
        _log(phone, nombre, "RUNT_ERROR", "[consulta RUNT]", err)


# ── Webhook Meta ──────────────────────────────────────────────────────────────

@app.route("/webhook", methods=["GET"])
def webhook_verify():
    """Verificación del webhook de Meta."""
    mode      = request.args.get("hub.mode")
    token     = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == config.WHATSAPP_VERIFY_TOKEN:
        print("[Speedy] Webhook verificado ✅")
        return challenge, 200
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def webhook_receive():
    """Recibe mensajes de Meta y los procesa en background."""
    data = request.get_json(silent=True) or {}

    # Retornar 200 inmediatamente a Meta (obligatorio)
    threading.Thread(target=_handle_message, args=(data,), daemon=True).start()
    return "OK", 200


def _handle_message(data: dict) -> None:
    """Lógica de manejo completa (corre en hilo separado)."""
    parsed = _parse_webhook_entry(data)
    if not parsed:
        return

    phone, nombre, text, has_media, media_id, media_mime = parsed
    print(f"[Speedy] {phone} ({nombre}): '{text}' | media={has_media}")

    # Descargar media si es PDF
    media_bytes = None
    if has_media and media_id:
        is_pdf = media_mime and "pdf" in media_mime.lower()
        if is_pdf:
            try:
                media_bytes = wa.download_media(media_id)
                print(f"[Speedy] PDF descargado: {len(media_bytes)} bytes")
            except Exception as e:
                print(f"[Speedy] Error descargando media: {e}")
                wa.send_text(phone, "❌ No pude descargar el PDF. Intenta enviarlo de nuevo 📎")
                return
        else:
            wa.send_text(
                phone,
                "⚠️ Por favor envía el documento como archivo *PDF* (no como imagen) 📎"
            )
            return

    # Procesar a través de la máquina de estados
    result = process_message(
        phone, text, nombre,
        has_media=bool(media_bytes),
        media_bytes=media_bytes,
        media_type=media_mime,
    )

    # Enviar respuestas
    wa.send_messages(phone, result["responses"])

    # Log
    st = get_state(phone)
    _log(phone, nombre, st["state"], text, " | ".join(result["responses"]))

    # Si el estado machine indica que hay que correr RUNT → lanzar en background
    if result.get("trigger_runt"):
        update_state(phone, {"state": "QUERYING_RUNT"})
        threading.Thread(
            target=_run_runt_and_reply,
            args=(phone, nombre),
            daemon=True,
        ).start()


# ── Health check ──────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "bot": "Speedy"}), 200


@app.route("/state/<phone>", methods=["GET"])
def debug_state(phone: str):
    """Debug: ver estado de un usuario (solo usar en desarrollo)."""
    return jsonify(get_state(phone)), 200


@app.route("/reset/<phone>", methods=["POST"])
def debug_reset(phone: str):
    """Debug: reiniciar estado de un usuario."""
    reset_state(phone)
    return jsonify({"reset": True}), 200


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"""
╔══════════════════════════════════════════╗
║  🚗  Speedy Bot — Verificación Vehicular  ║
║  Puerto: {config.PORT:<5}  Debug: {config.DEBUG}            ║
║  Webhook: POST /webhook                  ║
║  Health:  GET  /health                   ║
╚══════════════════════════════════════════╝
    """)
    app.run(host="0.0.0.0", port=config.PORT, debug=config.DEBUG)
