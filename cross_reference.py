"""
Compara datos extraídos de PDFs contra datos del RUNT/SIMIT.
Retorna lista de discrepancias en texto legible para WhatsApp.
"""

import re
from typing import Optional


def _norm_str(s) -> str:
    if not s:
        return ""
    return re.sub(r'\s+', ' ', str(s)).strip().upper()


def _norm_num(s) -> str:
    if not s:
        return ""
    return re.sub(r'[\s\-\.]', '', str(s)).upper()


def _fecha_corta(s) -> str:
    if not s:
        return ""
    return str(s)[:10]


def comparar(pdf_data: dict, runt_data: dict) -> list:
    """
    pdf_data: {pdf_type: parsed_dict, ...}  (resultado de pdf_parser.parse_pdf)
    runt_data: resultado de RuntScraper.consulta_completa()

    Retorna lista de strings describiendo discrepancias.
    Lista vacía = todo coincide.
    """
    discrepancias = []
    auth = runt_data.get("auth", {}) or {}
    info = auth.get("infoVehiculo", {}) or {}
    runt_placa = _norm_num(info.get("placa", ""))

    for pdf_type, data in pdf_data.items():
        if data.get("_stub") or data.get("error"):
            continue

        # ── Placa (común a todos los docs) ────────────────────────────────
        pdf_placa = _norm_num(data.get("placa", ""))
        if pdf_placa and runt_placa and pdf_placa != runt_placa:
            discrepancias.append(
                f"🔴 *Placa ({pdf_type})*: PDF dice `{pdf_placa}` pero RUNT tiene `{runt_placa}`"
            )

        # ── SOAT ──────────────────────────────────────────────────────────
        if pdf_type == "SOAT":
            soat_list = runt_data.get("soat") or []
            if isinstance(soat_list, list) and soat_list:
                runt_soat = soat_list[-1]
                pdf_num = _norm_num(data.get("num_soat", ""))
                runt_num = _norm_num(runt_soat.get("numSoat", ""))
                if pdf_num and runt_num and pdf_num != runt_num:
                    discrepancias.append(
                        f"🔴 *N° SOAT*: PDF dice `{pdf_num}` pero RUNT tiene `{runt_num}`"
                    )

                pdf_venc = _fecha_corta(data.get("fecha_vencimiento", ""))
                runt_venc = _fecha_corta(runt_soat.get("fechaVencimSoat", ""))
                if pdf_venc and runt_venc and pdf_venc[:7] != runt_venc[:7]:  # compare YYYY-MM
                    discrepancias.append(
                        f"🟡 *Vencimiento SOAT*: PDF dice `{pdf_venc}` — RUNT dice `{runt_venc}`"
                    )

                pdf_aseg = _norm_str(data.get("aseguradora", ""))
                runt_aseg = _norm_str(runt_soat.get("razonSocialAsegur", ""))
                if pdf_aseg and runt_aseg and pdf_aseg not in runt_aseg and runt_aseg not in pdf_aseg:
                    discrepancias.append(
                        f"🟡 *Aseguradora SOAT*: PDF dice `{pdf_aseg}` — RUNT dice `{runt_aseg}`"
                    )

        # ── TARJETA DE OPERACIÓN ──────────────────────────────────────────
        elif pdf_type == "TARJETA_OPERACION":
            to_runt = runt_data.get("tarjeta_operacion") or {}
            if isinstance(to_runt, dict):
                pdf_num = _norm_num(data.get("num_tarjeta", ""))
                runt_num = _norm_num(to_runt.get("nroTarjetaOperacion", ""))
                if pdf_num and runt_num and pdf_num != runt_num:
                    discrepancias.append(
                        f"🔴 *N° Tarjeta Operación*: PDF dice `{pdf_num}` — RUNT tiene `{runt_num}`"
                    )

                pdf_emp = _norm_str(data.get("empresa", ""))
                runt_emp = _norm_str(to_runt.get("empresaAfiliadora", ""))
                if pdf_emp and runt_emp and pdf_emp not in runt_emp and runt_emp not in pdf_emp:
                    discrepancias.append(
                        f"🟡 *Empresa (T.O.)*: PDF dice `{pdf_emp}` — RUNT dice `{runt_emp}`"
                    )

        # ── PÓLIZA ────────────────────────────────────────────────────────
        elif pdf_type == "POLIZA":
            rc_list = runt_data.get("responsabilidad_civil") or []
            if isinstance(rc_list, list) and rc_list:
                pdf_num = _norm_num(data.get("num_poliza", ""))
                runt_nums = [_norm_num(p.get("numeroPoliza", "")) for p in rc_list]
                if pdf_num and pdf_num not in runt_nums:
                    discrepancias.append(
                        f"🔴 *N° Póliza RC*: PDF dice `{pdf_num}` — RUNT no la registra"
                    )

        # ── LICENCIA DE TRÁNSITO ──────────────────────────────────────────
        elif pdf_type == "LICENCIA_TRANSITO":
            pdf_cedula = _norm_num(data.get("cedula_propietario", ""))
            # RUNT no expone la cédula del propietario directamente,
            # pero podemos comparar el nombre si el PDF lo trae
            pdf_nombre = _norm_str(data.get("propietario", ""))
            runt_organismo = _norm_str(info.get("organismoTransito", ""))
            pdf_organismo = _norm_str(data.get("organismo", ""))
            if pdf_organismo and runt_organismo and pdf_organismo not in runt_organismo and runt_organismo not in pdf_organismo:
                discrepancias.append(
                    f"🟡 *Organismo tránsito*: PDF dice `{pdf_organismo}` — RUNT dice `{runt_organismo}`"
                )

    return discrepancias


def formatear_resultado(discrepancias: list) -> str:
    if not discrepancias:
        return (
            "✅ *Todo coincide* — Los datos de tus PDFs coinciden con el RUNT.\n"
            "Tu documentación está en orden 👍"
        )

    lineas = [
        f"⚠️ *Se encontraron {len(discrepancias)} diferencia(s) entre tus PDFs y el RUNT:*\n"
    ] + discrepancias + [
        "\nTe recomendamos verificar estos datos con tu organismo de tránsito. 📋"
    ]
    return "\n".join(lineas)
