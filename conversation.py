"""
Máquina de estados para el bot Speedy.

Estado almacenado por número de teléfono (en memoria + consultado de Google Sheets
al inicio para recuperar conductores conocidos).
"""

import re
import threading
from typing import Optional

# ── Catálogos ─────────────────────────────────────────────────────────────────

PDF_OPTIONS = {
    "1": "SOAT",
    "2": "TARJETA_OPERACION",
    "3": "POLIZA",
    "4": "LICENCIA_TRANSITO",
}

PDF_LABELS = {
    "SOAT":              "SOAT",
    "TARJETA_OPERACION": "Tarjeta de Operación",
    "POLIZA":            "Póliza",
    "LICENCIA_TRANSITO": "Licencia de Tránsito",
}

DOC_OPTIONS = {
    "A": "C",   # Cédula de Ciudadanía
    "B": "N",   # NIT
    "C": "E",   # Cédula de Extranjería
    "D": "TI",  # Tarjeta de Identidad
    "E": "PPT", # Permiso por Protección Temporal
}

DOC_LABELS = {
    "A": "Cédula de Ciudadanía",
    "B": "NIT",
    "C": "Cédula de Extranjería",
    "D": "Tarjeta de Identidad",
    "E": "Permiso por Protección Temporal",
}

PLATE_RE = re.compile(r'\b([A-Z]{2,3}\d{2,3}[A-Z]?\d?)\b')

# ── Estado en memoria ─────────────────────────────────────────────────────────

_lock = threading.Lock()
_states: dict = {}


def _blank_state() -> dict:
    return {
        "state":           "WELCOME",
        "nombre":          "",
        "pdfs_requested":  [],
        "pdfs_collected":  {},
        "pdf_index":       0,
        "doc_type":        None,
        "documento":       None,
        "placa":           None,
        "runt_data":       None,
    }


def get_state(phone: str) -> dict:
    with _lock:
        if phone not in _states:
            _states[phone] = _blank_state()
        return dict(_states[phone])


def update_state(phone: str, updates: dict) -> None:
    with _lock:
        if phone not in _states:
            _states[phone] = _blank_state()
        _states[phone].update(updates)


def reset_state(phone: str) -> None:
    with _lock:
        _states[phone] = _blank_state()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_plate(text: str) -> Optional[str]:
    m = PLATE_RE.search(text.upper())
    return m.group(1) if m else None


def _is_digits_only(text: str) -> bool:
    return bool(re.match(r'^[\d\s\-\.]+$', text.strip()))


def _doc_menu() -> str:
    return (
        "¿Qué tipo de documento de identidad usarás?\n\n"
        "A. Cédula de Ciudadanía\n"
        "B. NIT\n"
        "C. Cédula de Extranjería\n"
        "D. Tarjeta de Identidad\n"
        "E. Permiso por Protección Temporal"
    )


# ── Procesador principal ──────────────────────────────────────────────────────

def process_message(phone: str, message: str, nombre: str = "",
                    has_media: bool = False,
                    media_bytes: bytes = None,
                    media_type: str = None) -> dict:
    """
    Procesa un mensaje entrante y retorna la respuesta.

    Returns dict:
        responses       list[str]   mensajes a enviar en orden
        trigger_runt    bool        True → el llamador debe lanzar consulta RUNT
        needs_pdf       bool        True → esperamos un PDF en el siguiente mensaje
    """
    state = get_state(phone)
    current = state["state"]
    msg = message.strip()
    msg_up = msg.upper()

    # Guardar nombre si lo tenemos
    if nombre and not state.get("nombre"):
        update_state(phone, {"nombre": nombre})

    # ── Comandos globales de reinicio ────────────────────────────────────────
    RESTART_WORDS = {"REINICIAR", "RESTART", "INICIO", "RESET", "MENU", "MENÚ"}
    if msg_up in RESTART_WORDS and current not in ("WELCOME",):
        reset_state(phone)
        update_state(phone, {"nombre": nombre})
        return process_message(phone, "hola", nombre)

    # ── WELCOME ──────────────────────────────────────────────────────────────
    if current == "WELCOME":
        update_state(phone, {"state": "PDF_SELECTION"})
        first_name = nombre.split()[0] if nombre else "conductor"
        return _r([
            f"¡Hola {first_name}! 👋🚗🚌🏍️ Soy *Speedy*, tu asistente de verificación vehicular 🔍\n\n"
            "Estoy aquí para verificar los datos de tu vehículo y asegurarme de que todo esté en orden 📋\n\n"
            "¿Tienes alguno de estos documentos en PDF?\n\n"
            "1️⃣ SOAT\n"
            "2️⃣ Tarjeta de Operación\n"
            "3️⃣ Póliza\n"
            "4️⃣ Licencia de Tránsito\n\n"
            "Escribe los *números* que tienes (ej: *1,2*) o escribe *0* si no tienes ninguno."
        ])

    # ── PDF_SELECTION ─────────────────────────────────────────────────────────
    elif current == "PDF_SELECTION":
        if msg_up in ("0", "NO", "NINGUNO", "NONE"):
            update_state(phone, {"state": "DOC_TYPE", "pdfs_requested": []})
            return _r([
                "Sin problema 👍\n\n"
                "Entonces pasemos directo a la verificación en el RUNT.\n\n"
                + _doc_menu()
            ])

        nums = re.findall(r'[1-4]', msg)
        if not nums:
            return _r([
                "⚠️ Por favor escribe los *números* de los documentos que tienes.\n"
                "Ejemplo: *1,2* para SOAT y Tarjeta de Operación 📝\n\n"
                "O escribe *0* si no tienes ningún PDF."
            ])

        pdfs = list(dict.fromkeys(PDF_OPTIONS[n] for n in nums))
        update_state(phone, {
            "state": "PDF_COLLECT",
            "pdfs_requested": pdfs,
            "pdf_index": 0,
            "pdfs_collected": {},
        })
        first = PDF_LABELS[pdfs[0]]
        return _r([f"📎 Perfecto! Envíame el PDF del *{first}*"], needs_pdf=True)

    # ── PDF_COLLECT ───────────────────────────────────────────────────────────
    elif current == "PDF_COLLECT":
        pdfs = state["pdfs_requested"]
        idx  = state["pdf_index"]
        current_pdf_type = pdfs[idx]
        current_label    = PDF_LABELS[current_pdf_type]

        if not has_media or not media_bytes:
            return _r([
                f"⚠️ Necesito que me envíes el archivo *PDF* del {current_label}.\n"
                "Por favor adjunta el archivo PDF directamente en el chat 📎"
            ], needs_pdf=True)

        # Parsear PDF
        from pdf_parser import parse_pdf, format_pdf_summary
        parsed = parse_pdf(media_bytes, current_pdf_type)
        collected = {**state["pdfs_collected"], current_pdf_type: parsed}
        next_idx = idx + 1
        update_state(phone, {"pdfs_collected": collected, "pdf_index": next_idx})

        if next_idx < len(pdfs):
            next_label = PDF_LABELS[pdfs[next_idx]]
            update_state(phone, {})  # state stays PDF_COLLECT
            return _r([f"✅ Recibido!\n\n📎 Ahora envíame el PDF de la *{next_label}*"], needs_pdf=True)

        # Todos los PDFs recolectados → mostrar resumen
        update_state(phone, {"state": "PDF_SHOWN"})
        summary_parts = ["📄 *Datos extraídos de tus documentos:*\n"]
        for pt, pd_data in collected.items():
            summary_parts.append(format_pdf_summary(pt, pd_data))
        summary_parts.append("")

        # Si el PDF trae placa, pre-llenar
        for pt, pd_data in collected.items():
            if pd_data.get("placa") and not state.get("placa"):
                update_state(phone, {"placa": pd_data["placa"].upper()})
                break

        return _r([
            "\n".join(summary_parts),
            "¿Todo bien con esa información? Escribe *listo* para continuar con la verificación en el RUNT 👇"
        ])

    # ── PDF_SHOWN ─────────────────────────────────────────────────────────────
    elif current == "PDF_SHOWN":
        update_state(phone, {"state": "DOC_TYPE"})
        return _r(["🔍 Perfecto! Ahora necesito verificar todo en el *RUNT*.\n\n" + _doc_menu()])

    # ── DOC_TYPE ──────────────────────────────────────────────────────────────
    elif current == "DOC_TYPE":
        choice = msg_up.strip()
        if choice not in DOC_OPTIONS:
            return _r([f"⚠️ Por favor responde con una letra: *A*, *B*, *C*, *D* o *E* 📝\n\n{_doc_menu()}"])
        doc_type = DOC_OPTIONS[choice]
        label    = DOC_LABELS[choice]
        update_state(phone, {"state": "DOC_NUMBER", "doc_type": doc_type})
        return _r([f"📝 Dame tu número de *{label}*:"])

    # ── DOC_NUMBER ────────────────────────────────────────────────────────────
    elif current == "DOC_NUMBER":
        doc = re.sub(r'[\s\-\.]', '', msg)
        if not doc or len(doc) < 4 or not re.match(r'^[\dA-Za-z]+$', doc):
            return _r([
                "⚠️ Por favor ingresa solo el *número* de tu documento (sin puntos ni espacios) 📝\n"
                "Ejemplo: *1010960147*"
            ])

        update_state(phone, {"documento": doc})

        # ¿Ya tenemos placa pre-llenada (de PDF o de Conductores)?
        if state.get("placa") or get_state(phone).get("placa"):
            placa_ya = get_state(phone).get("placa")
            update_state(phone, {"state": "PLATE_CONFIRM"})
            return _r([
                f"✅ Documento guardado.\n\n"
                f"Veo que ya tenemos tu placa registrada: *{placa_ya}*\n"
                "¿Es correcta? Escribe *si* para confirmar o escribe la placa correcta."
            ])

        update_state(phone, {"state": "PLATE"})
        return _r(["🚗 Dame el número de *placa* de tu vehículo (ej: *ABC123*):"])

    # ── PLATE_CONFIRM ─────────────────────────────────────────────────────────
    elif current == "PLATE_CONFIRM":
        if msg_up in ("SI", "SÍ", "YES", "S", "OK", "CORRECTO"):
            update_state(phone, {"state": "TRIGGER_RUNT"})
            return _r(
                ["⏳ Consultando en el *RUNT* y *SIMIT*... Esto puede tardar unos segundos 🔍"],
                trigger_runt=True,
            )
        placa = _extract_plate(msg)
        if placa:
            update_state(phone, {"placa": placa, "state": "TRIGGER_RUNT"})
            return _r(
                [f"✅ Placa *{placa}* registrada.\n\n⏳ Consultando en el *RUNT* y *SIMIT*... 🔍"],
                trigger_runt=True,
            )
        return _r([
            "⚠️ No reconocí esa placa. Escríbela así: *ABC123* 🚗\n"
            "O escribe *si* para confirmar la placa que ya tenemos."
        ])

    # ── PLATE ────────────────────────────────────────────────────────────────
    elif current == "PLATE":
        placa = _extract_plate(msg)
        if not placa:
            return _r([
                "⚠️ No reconozco ese formato de placa 🚗\n"
                "Por favor escríbela así: *ABC123* o *AB123C*"
            ])
        update_state(phone, {"placa": placa, "state": "TRIGGER_RUNT"})
        return _r(
            [f"✅ Placa *{placa}* registrada.\n\n⏳ Consultando en el *RUNT* y *SIMIT*... esto puede tardar unos segundos 🔍"],
            trigger_runt=True,
        )

    # ── RUNT_DONE ─────────────────────────────────────────────────────────────
    elif current == "RUNT_DONE":
        update_state(phone, {"state": "DONE"})
        return _r([
            "¡Gracias por usar *Speedy* 🚗✨!\n\n"
            "Si necesitas hacer otra consulta, escribe *REINICIAR* 🔄"
        ])

    # ── DONE / fallback ───────────────────────────────────────────────────────
    else:
        reset_state(phone)
        update_state(phone, {"nombre": nombre})
        return process_message(phone, "hola", nombre)


def _r(responses: list, trigger_runt: bool = False, needs_pdf: bool = False) -> dict:
    return {"responses": responses, "trigger_runt": trigger_runt, "needs_pdf": needs_pdf}
