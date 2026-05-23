"""
Parser de documentos vehiculares colombianos.
Usa extractor_texto.py para sacar el texto crudo del PDF/imagen,
luego aplica regex para extraer campos específicos por tipo de documento.
"""

import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extractor_texto import extraer_texto_archivo

# ── Regex helpers ─────────────────────────────────────────────────────────────

_PLATE_RE  = re.compile(r'\b([A-Z]{2,3}\d{2,3}[A-Z]?\d?)\b')
_DATE_RE   = re.compile(r'\b(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})\b')
_NUM_RE    = re.compile(r'\b(\d{5,20})\b')


def _find_plate(text: str):
    m = _PLATE_RE.search(text.upper())
    return m.group(1) if m else None


def _find_after(text: str, *keywords) -> str:
    """Devuelve el primer valor no vacío que sigue a cualquiera de las keywords."""
    for kw in keywords:
        pattern = re.compile(
            re.escape(kw) + r'[\s:\.#\-]*([A-Z0-9\-\s\.]{2,60})',
            re.IGNORECASE,
        )
        m = pattern.search(text)
        if m:
            val = m.group(1).strip().rstrip('.,;')
            if val:
                return val
    return ""


def _find_dates(text: str) -> list:
    return _DATE_RE.findall(text)


def _find_long_number(text: str, after_keyword: str) -> str:
    pattern = re.compile(
        re.escape(after_keyword) + r'[\s:\.#Nno°\-]*(\d{4,20})',
        re.IGNORECASE,
    )
    m = pattern.search(text)
    return m.group(1).strip() if m else ""


# ── Parsers por tipo de documento ─────────────────────────────────────────────

def _parse_soat(text: str) -> dict:
    t = text.upper()
    dates = _find_dates(text)

    num_soat = (
        _find_long_number(text, "PÓLIZA NO")
        or _find_long_number(text, "POLIZA NO")
        or _find_long_number(text, "PÓLIZA N")
        or _find_long_number(text, "N° SOAT")
        or _find_long_number(text, "NUMERO DE POLIZA")
        or _find_long_number(text, "NO. POLIZA")
    )

    aseguradora = (
        _find_after(text, "ASEGURADORA", "ENTIDAD", "COMPAÑIA ASEGURADORA",
                    "COMPANY", "EXPEDIDA POR")
        or ""
    )

    propietario = (
        _find_after(text, "PROPIETARIO", "ASEGURADO", "TOMADOR", "NOMBRE")
        or ""
    )

    fecha_inicio = dates[0] if len(dates) > 0 else ""
    fecha_fin    = dates[1] if len(dates) > 1 else ""

    # Buscar explícitamente "VIGENTE DESDE" y "VIGENTE HASTA"
    m_desde = re.search(r'(?:VIGENTE?\s+DESDE|VALID FROM|INICIO VIGENCIA)[\s:]*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', t)
    m_hasta = re.search(r'(?:VIGENTE?\s+HASTA|VALID UNTIL|FIN VIGENCIA|VENCIMIENTO)[\s:]*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', t)
    if m_desde:
        fecha_inicio = m_desde.group(1)
    if m_hasta:
        fecha_fin = m_hasta.group(1)

    return {
        "num_soat":         num_soat,
        "fecha_inicio":     fecha_inicio,
        "fecha_vencimiento": fecha_fin,
        "aseguradora":      aseguradora[:80],
        "propietario":      propietario[:80],
    }


def _parse_tarjeta_operacion(text: str) -> dict:
    t = text.upper()
    dates = _find_dates(text)

    num_tarjeta = (
        _find_long_number(text, "TARJETA DE OPERACIÓN NO")
        or _find_long_number(text, "TARJETA DE OPERACION NO")
        or _find_long_number(text, "NÚMERO")
        or _find_long_number(text, "NUMERO")
        or _find_long_number(text, "NO.")
    )

    empresa = (
        _find_after(text, "EMPRESA", "EMPRESA AFILIADORA", "EMPRESA TRANSPORTADORA",
                    "RAZÓN SOCIAL", "RAZON SOCIAL")
        or ""
    )

    modalidad = _find_after(text, "MODALIDAD") or ""
    servicio  = _find_after(text, "SERVICIO", "CLASE DE SERVICIO") or ""

    m_inicio = re.search(r'(?:FECHA\s+INICIO|INICIO|DESDE)[\s:]*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', t)
    m_fin    = re.search(r'(?:FECHA\s+VENCIMIENTO|VENCIMIENTO|HASTA|FIN)[\s:]*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', t)

    return {
        "num_tarjeta":      num_tarjeta,
        "empresa":          empresa[:80],
        "modalidad":        modalidad[:40],
        "servicio":         servicio[:40],
        "fecha_inicio":     m_inicio.group(1) if m_inicio else (dates[0] if dates else ""),
        "fecha_vencimiento": m_fin.group(1) if m_fin else (dates[1] if len(dates) > 1 else ""),
    }


def _parse_poliza(text: str) -> dict:
    t = text.upper()
    dates = _find_dates(text)

    num_poliza = (
        _find_long_number(text, "PÓLIZA NO")
        or _find_long_number(text, "POLIZA NO")
        or _find_long_number(text, "N° DE PÓLIZA")
        or _find_long_number(text, "NO. POLIZA")
        or _find_long_number(text, "NÚMERO DE PÓLIZA")
    )

    aseguradora = (
        _find_after(text, "ASEGURADORA", "COMPAÑÍA", "COMPANIA", "ENTIDAD EXPEDIDORA")
        or ""
    )

    tipo_poliza = (
        _find_after(text, "TIPO DE PÓLIZA", "TIPO POLIZA", "CLASE DE PÓLIZA")
        or ""
    )

    m_inicio = re.search(r'(?:INICIO\s+VIGENCIA|DESDE|FECHA\s+INICIO)[\s:]*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', t)
    m_fin    = re.search(r'(?:FIN\s+VIGENCIA|HASTA|VENCIMIENTO|FECHA\s+FIN)[\s:]*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', t)

    return {
        "num_poliza":        num_poliza,
        "tipo_poliza":       tipo_poliza[:60],
        "aseguradora":       aseguradora[:80],
        "fecha_inicio":      m_inicio.group(1) if m_inicio else (dates[0] if dates else ""),
        "fecha_vencimiento": m_fin.group(1) if m_fin else (dates[1] if len(dates) > 1 else ""),
    }


def _parse_licencia(text: str) -> dict:
    t = text.upper()

    propietario = (
        _find_after(text, "PROPIETARIO", "NOMBRE DEL PROPIETARIO", "TITULAR")
        or ""
    )

    cedula = (
        _find_long_number(text, "C.C.")
        or _find_long_number(text, "CÉDULA")
        or _find_long_number(text, "CEDULA")
        or _find_long_number(text, "NIT")
        or ""
    )

    num_licencia = (
        _find_long_number(text, "LICENCIA NO")
        or _find_long_number(text, "NÚMERO DE LICENCIA")
        or _find_long_number(text, "NO. LICENCIA")
        or ""
    )

    organismo = (
        _find_after(text, "ORGANISMO DE TRÁNSITO", "ORGANISMO DE TRANSITO",
                    "SECRETARÍA DE TRÁNSITO", "SECRETARIA DE TRANSITO",
                    "ENTIDAD")
        or ""
    )

    dates = _find_dates(text)
    m_exp = re.search(r'(?:FECHA\s+EXPEDICI[OÓ]N|EXPEDICI[OÓ]N|FECHA)[\s:]*(\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})', t)

    return {
        "num_licencia":      num_licencia,
        "propietario":       propietario[:80],
        "cedula_propietario": cedula,
        "organismo":         organismo[:80],
        "fecha_expedicion":  m_exp.group(1) if m_exp else (dates[0] if dates else ""),
    }


# ── Función principal ─────────────────────────────────────────────────────────

def parse_pdf(pdf_bytes: bytes, pdf_type: str) -> dict:
    """
    Extrae texto del PDF y parsea campos específicos según el tipo.

    Args:
        pdf_bytes: Bytes crudos del archivo PDF
        pdf_type:  "SOAT" | "TARJETA_OPERACION" | "POLIZA" | "LICENCIA_TRANSITO"

    Returns:
        dict con campos normalizados. Incluye "raw_text" siempre.
        En caso de error: {"error": str, "tipo_doc": pdf_type}
    """
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name

    try:
        extracted = extraer_texto_archivo(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if not extracted.get("exito"):
        return {
            "error":    extracted.get("error", "No se pudo extraer el texto del PDF"),
            "tipo_doc": pdf_type,
            "raw_text": "",
        }

    raw_text = extracted.get("texto_completo", "")

    result = {
        "tipo_doc": pdf_type,
        "placa":    _find_plate(raw_text),
        "raw_text": raw_text,
        "paginas":  extracted.get("paginas", 0),
        "metodo":   extracted.get("metodo", ""),
    }

    parsers = {
        "SOAT":              _parse_soat,
        "TARJETA_OPERACION": _parse_tarjeta_operacion,
        "POLIZA":            _parse_poliza,
        "LICENCIA_TRANSITO": _parse_licencia,
    }

    if pdf_type in parsers:
        result.update(parsers[pdf_type](raw_text))

    return result


# ── Formato legible para WhatsApp ─────────────────────────────────────────────

PDF_NAMES = {
    "SOAT":              "SOAT",
    "TARJETA_OPERACION": "Tarjeta de Operación",
    "POLIZA":            "Póliza",
    "LICENCIA_TRANSITO": "Licencia de Tránsito",
}

_FIELDS_BY_TYPE = {
    "SOAT": [
        ("N° SOAT",       "num_soat"),
        ("Vigencia desde","fecha_inicio"),
        ("Vence",         "fecha_vencimiento"),
        ("Aseguradora",   "aseguradora"),
        ("Propietario",   "propietario"),
    ],
    "TARJETA_OPERACION": [
        ("N° Tarjeta",    "num_tarjeta"),
        ("Empresa",       "empresa"),
        ("Modalidad",     "modalidad"),
        ("Servicio",      "servicio"),
        ("Vigencia desde","fecha_inicio"),
        ("Vence",         "fecha_vencimiento"),
    ],
    "POLIZA": [
        ("N° Póliza",     "num_poliza"),
        ("Tipo",          "tipo_poliza"),
        ("Aseguradora",   "aseguradora"),
        ("Vigencia desde","fecha_inicio"),
        ("Vence",         "fecha_vencimiento"),
    ],
    "LICENCIA_TRANSITO": [
        ("N° Licencia",   "num_licencia"),
        ("Propietario",   "propietario"),
        ("Cédula",        "cedula_propietario"),
        ("Organismo",     "organismo"),
        ("Expedición",    "fecha_expedicion"),
    ],
}


def format_pdf_summary(pdf_type: str, data: dict) -> str:
    if data.get("error"):
        return f"⚠️ *{PDF_NAMES.get(pdf_type, pdf_type)}* — Error al leer: {data['error']}"

    lines = [f"*{PDF_NAMES.get(pdf_type, pdf_type)}*"]
    if data.get("placa"):
        lines.append(f"  Placa: {data['placa']}")
    for label, key in _FIELDS_BY_TYPE.get(pdf_type, []):
        val = data.get(key)
        if val:
            lines.append(f"  {label}: {val}")

    if len(lines) == 1:
        lines.append("  (No se detectaron campos estructurados — texto extraído pero sin datos reconocidos)")

    return "\n".join(lines)
