"""
RUNT Scraper - Consulta pública de vehículos Colombia
API base: https://runtproapi.runt.gov.co/CYRConsultaVehiculoMS

SIMIT Scraper - Multas y comparendos Colombia
Portal: https://www.fcm.org.co/simit/#/estado-cuenta
"""

import requests
import base64
import json
import os
import time

import ddddocr

BASE_API = "https://runtproapi.runt.gov.co/CYRConsultaVehiculoMS"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Origin": "https://portalpublico.runt.gov.co",
    "Referer": "https://portalpublico.runt.gov.co/",
    "Content-Type": "application/json",
}

TIPOS_CONSULTA = {
    "PLACA_PROPIETARIO": "1",
    "VIN": "2",
    "SOAT": "3",
    "PVO": "4",
    "GUIA_MOVILIDAD": "5",
    "RTM": "6",
}

TIPOS_DOCUMENTO = {
    "CEDULA": "C",           # Cédula de Ciudadanía
    "CC": "C",
    "NIT": "N",              # NIT
    "PASAPORTE": "P",        # Pasaporte
    "PA": "P",
    "EXTRANJERIA": "E",      # Cédula de Extranjería
    "CE": "E",
    "DIPLOMATICO": "D",      # Carnet Diplomático
    "CD": "D",
    "CARNET": "D",
    "PPT": "PPT",            # Permiso por Protección Temporal
    "PROTECCION": "PPT",
    "REGISTRO_CIVIL": "RC",  # Registro Civil
    "RC": "RC",
    "TARJETA_IDENTIDAD": "TI",  # Tarjeta de Identidad
    "TI": "TI",
}

# Mapeo legible para mostrar en mensajes
NOMBRE_DOCUMENTO = {
    "C":   "Cédula de Ciudadanía",
    "N":   "NIT",
    "P":   "Pasaporte",
    "E":   "Cédula de Extranjería",
    "D":   "Carnet Diplomático",
    "PPT": "Permiso por Protección Temporal",
    "RC":  "Registro Civil",
    "TI":  "Tarjeta de Identidad",
}


def normalizar_tipo_documento(tipo: str) -> str:
    """
    Acepta código directo ("C", "N", "PPT", "TI", "RC") o alias legibles
    ("cedula", "CC", "nit", "extranjeria", "CE", etc.).
    Retorna el código de API que usa RUNT.
    """
    tipo_upper = tipo.upper().strip().replace(" ", "_")
    # Si ya es un código válido de API, devolverlo directo
    if tipo_upper in NOMBRE_DOCUMENTO:
        return tipo_upper
    # Buscar en aliases
    codigo = TIPOS_DOCUMENTO.get(tipo_upper)
    if codigo:
        return codigo
    raise ValueError(
        f"Tipo de documento no reconocido: '{tipo}'. "
        f"Opciones válidas: {', '.join(sorted(set(TIPOS_DOCUMENTO.keys())))}"
    )


class RuntScraper:
    def __init__(self, twocaptcha_api_key=None):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.token = None
        self.twocaptcha_key = twocaptcha_api_key
        self._ocr = ddddocr.DdddOcr(beta=True, show_ad=False)

    # ── Captcha ──────────────────────────────────────────────────────────────

    def _generar_captcha(self):
        r = self.session.get(f"{BASE_API}/captcha/libre-captcha/generar")
        r.raise_for_status()
        data = r.json()
        if data.get("error"):
            raise RuntimeError(f"Error generando captcha: {data.get('descripcionRespuesta')}")
        return data["id"], data["imagen"]

    def _resolver_captcha_ocr(self, imagen_b64: str) -> str:
        """Resuelve captcha localmente con ddddocr (sin dependencias externas)."""
        if imagen_b64.startswith("data:image/png;base64,"):
            imagen_b64 = imagen_b64[len("data:image/png;base64,"):]
        img_bytes = base64.b64decode(imagen_b64)
        text = self._ocr.classification(img_bytes)
        return text.strip()

    def _resolver_captcha_2captcha(self, imagen_b64: str) -> str:
        """Resuelve captcha usando el servicio 2captcha (más confiable)."""
        if not self.twocaptcha_key:
            raise RuntimeError("Se necesita API key de 2captcha")

        if imagen_b64.startswith("data:image/png;base64,"):
            imagen_b64 = imagen_b64[len("data:image/png;base64,"):]

        # Enviar imagen a 2captcha
        r = requests.post("http://2captcha.com/in.php", data={
            "key": self.twocaptcha_key,
            "method": "base64",
            "body": imagen_b64,
            "json": 1,
        })
        resp = r.json()
        if resp.get("status") != 1:
            raise RuntimeError(f"2captcha error al enviar: {resp}")

        captcha_id = resp["request"]

        # Esperar resultado (2captcha tarda ~15s)
        for _ in range(20):
            time.sleep(5)
            r2 = requests.get(f"http://2captcha.com/res.php?key={self.twocaptcha_key}&action=get&id={captcha_id}&json=1")
            resp2 = r2.json()
            if resp2.get("status") == 1:
                return resp2["request"]
            if resp2.get("request") != "CAPCHA_NOT_READY":
                raise RuntimeError(f"2captcha error: {resp2}")

        raise RuntimeError("2captcha timeout")

    def _obtener_configuracion(self):
        r = self.session.get(f"{BASE_API}/configuracion-sesion")
        r.raise_for_status()
        return r.json()

    # ── Autenticación / Consulta principal ───────────────────────────────────

    def consultar(self, placa: str, documento: str, tipo_documento: str = "C",
                  usar_2captcha: bool = False, max_intentos: int = 3) -> dict:
        """
        Consulta un vehículo por placa y documento del propietario.
        Retorna dict con todos los datos del vehículo.
        """
        placa = placa.upper().strip()
        documento = documento.strip()
        configuracion = self._obtener_configuracion()

        for intento in range(1, max_intentos + 1):
            print(f"[RUNT] Intento {intento}/{max_intentos} - Placa: {placa}")

            captcha_id, imagen = self._generar_captcha()
            print(f"[RUNT] Captcha ID: {captcha_id}")

            if usar_2captcha and self.twocaptcha_key:
                captcha_text = self._resolver_captcha_2captcha(imagen)
            else:
                captcha_text = self._resolver_captcha_ocr(imagen)

            print(f"[RUNT] Captcha resuelto: '{captcha_text}'")

            payload = {
                "procedencia": "NACIONAL",
                "tipoConsulta": TIPOS_CONSULTA["PLACA_PROPIETARIO"],
                "placa": placa,
                "tipoDocumento": tipo_documento,
                "documento": documento,
                "vin": None,
                "soat": None,
                "aseguradora": "",
                "rtm": None,
                "reCaptcha": None,
                "captcha": captcha_text,
                "valueCaptchaEncripted": "",
                "idLibreCaptcha": captcha_id,
                "verBannerSoat": False,
                "configuracion": configuracion,
            }

            r = self.session.post(f"{BASE_API}/auth", json=payload)
            resp = r.json()

            if resp.get("error") is True or resp.get("codigoResultado") == "ERROR":
                msg = resp.get("descripcionRespuesta", "Error desconocido")
                print(f"[RUNT] Error: {msg}")
                if "captcha" in msg.lower():
                    continue  # Reintentar con nuevo captcha
                raise RuntimeError(f"Error RUNT: {msg}")

            # Extraer y guardar token (campo real: "token" en la raíz)
            token = resp.get("token")
            if token:
                self.token = token
                self.session.headers.update({"Auth-Token": f"Bearer {token}"})
                print(f"[RUNT] Token obtenido: {token[:20]}...")

            return resp

        raise RuntimeError(f"Falló consulta después de {max_intentos} intentos")

    # ── Secciones adicionales (requieren token) ───────────────────────────────

    def _get_autenticado(self, path: str, params: dict = None) -> dict:
        if not self.token:
            raise RuntimeError("Sin token. Ejecute consultar() primero.")
        r = self.session.get(f"{BASE_API}{path}", params=params)
        r.raise_for_status()
        return r.json()

    def obtener_soat(self) -> dict:
        return self._get_autenticado("/soat")

    def obtener_responsabilidad_civil(self) -> dict:
        return self._get_autenticado("/responsabilidad-civil")

    def obtener_tecnomecanica(self, tipo: str = None) -> dict:
        params = {"tipo": tipo} if tipo else None
        print(f"[RTM-DEBUG] Llamando /rtms con params={params}")
        result = self._get_autenticado("/rtms", params)
        print(f"[RTM-DEBUG] Respuesta tipo={type(result).__name__}")
        if isinstance(result, dict):
            print(f"[RTM-DEBUG] keys={list(result.keys())}, revisiones={type(result.get('revisiones')).__name__}, len={len(result.get('revisiones') or [])}")
        elif isinstance(result, list):
            print(f"[RTM-DEBUG] lista directa, len={len(result)}, primer item keys={list(result[0].keys()) if result else '[]'}")
        return result

    def obtener_tarjeta_operacion(self) -> dict:
        return self._get_autenticado("/tarjeta-operacion")

    def obtener_limitaciones(self) -> dict:
        return self._get_autenticado("/limitaciones-propiedad")

    def obtener_datos_tecnicos(self) -> dict:
        return self._get_autenticado("/datos-tecnicos")

    def obtener_garantias(self) -> dict:
        return self._get_autenticado("/garantias")

    def obtener_garantias_prendas(self) -> dict:
        return self._get_autenticado("/garantias/prendas")

    def obtener_solicitudes(self) -> dict:
        return self._get_autenticado("/solicitudes")

    def obtener_blindaje(self) -> dict:
        return self._get_autenticado("/datos-blindaje")

    def obtener_poliza_caucion(self) -> dict:
        return self._get_autenticado("/poliza-caucion")

    def obtener_desintegracion(self) -> dict:
        return self._get_autenticado("/desintegracion")

    def obtener_certificado_desintegracion(self) -> dict:
        return self._get_autenticado("/certificado-desintegracion")

    def obtener_registro_inicial(self) -> dict:
        return self._get_autenticado("/registro-inicial")

    def obtener_registro_inicial_invc(self) -> dict:
        return self._get_autenticado("/registro-inicial/invc")

    def obtener_certificado_dijin(self) -> dict:
        return self._get_autenticado("/certificado-dijin")

    def obtener_normalizacion(self) -> dict:
        return self._get_autenticado("/normalizacion")

    def obtener_certificado_normalizacion(self) -> dict:
        return self._get_autenticado("/normalizacion/certificado")

    def obtener_permisos_pcr(self) -> dict:
        return self._get_autenticado("/permisos-pcr")

    def obtener_informacion_repotenciado(self) -> dict:
        return self._get_autenticado("/informacion-repotenciado")

    # ── Consulta completa (todo junto) ────────────────────────────────────────

    def consulta_completa(self, placa: str, documento: str,
                          tipo_documento: str = "C",
                          usar_2captcha: bool = False) -> dict:
        """
        Hace la consulta completa y retorna todos los datos relevantes
        listos para enviar por WhatsApp.
        """
        resultado = {}

        auth_resp = self.consultar(placa, documento, tipo_documento, usar_2captcha)
        resultado["auth"] = auth_resp

        id_clase = (auth_resp.get("infoVehiculo") or {}).get("idClaseVehiculo")
        print(f"[RTM-DEBUG] idClaseVehiculo extraído del auth: {repr(id_clase)}")

        secciones = [
            ("soat",                      self.obtener_soat),
            ("responsabilidad_civil",     self.obtener_responsabilidad_civil),
            ("tecnomecanica",             lambda: self.obtener_tecnomecanica(tipo=id_clase)),
            ("tarjeta_operacion",         self.obtener_tarjeta_operacion),
            ("limitaciones",              self.obtener_limitaciones),
            ("garantias",                 self.obtener_garantias),
            ("garantias_prendas",         self.obtener_garantias_prendas),
            ("solicitudes",               self.obtener_solicitudes),
            ("blindaje",                  self.obtener_blindaje),
            ("poliza_caucion",            self.obtener_poliza_caucion),
            ("desintegracion",            self.obtener_desintegracion),
            ("certificado_desintegracion",self.obtener_certificado_desintegracion),
            ("registro_inicial",          self.obtener_registro_inicial),
            ("registro_inicial_invc",     self.obtener_registro_inicial_invc),
            ("dijin",                     self.obtener_certificado_dijin),
            ("normalizacion",             self.obtener_normalizacion),
            ("normalizacion_certificado", self.obtener_certificado_normalizacion),
            ("permisos_pcr",              self.obtener_permisos_pcr),
            ("repotenciado",              self.obtener_informacion_repotenciado),
        ]

        for nombre, metodo in secciones:
            try:
                resultado[nombre] = metodo()
                print(f"[RUNT] {nombre}: OK")
            except Exception as e:
                resultado[nombre] = {"error": str(e)}
                print(f"[RUNT] {nombre}: ERROR - {e}")

        return resultado

    def formatear_para_whatsapp(self, datos: dict) -> str:
        """
        Convierte los datos a un mensaje de WhatsApp legible.
        Basado en los campos reales de la API RUNT.
        """
        lineas = ["*CONSULTA RUNT*\n"]
        auth = datos.get("auth", {})

        # ── Información general ───────────────────────────────────────────────
        info = auth.get("infoVehiculo") or {}
        if info and any(v for v in info.values() if v):
            lineas.append("*INFORMACIÓN GENERAL*")
            for label, key in [
                ("Placa", "placa"), ("Marca", "marca"), ("Línea", "linea"),
                ("Modelo", "modelo"), ("Color", "color"), ("Clase", "clase"),
                ("Tipo servicio", "tipoServicio"), ("Estado", "estadoAutomotor"),
                ("Organismo tránsito", "organismoTransito"), ("N° motor", "numMotor"),
                ("N° chasis", "numChasis"), ("Cilindraje", "cilindraje"),
                ("Combustible", "tipoCombustible"), ("Pasajeros", "pasajerosSentados"),
                ("Días matriculado", "diasMatriculado"), ("Prendas", "prendas"),
                ("Gravámenes", "gravamenes"),
            ]:
                val = info.get(key)
                if val:
                    lineas.append(f"  {label}: {val}")
            lineas.append("")

        # ── SOAT ─────────────────────────────────────────────────────────────
        soat_list = datos.get("soat")
        lineas.append("*PÓLIZAS SOAT*")
        if isinstance(soat_list, list) and soat_list:
            soat_ordenados = sorted(
                soat_list,
                key=lambda s: (s.get("fechaInicioPoliza") or s.get("fechaVencimSoat") or "")[:10],
                reverse=True,
            )
            for soat in soat_ordenados:
                estado = soat.get("estado", "N/D")
                prefijo = "✅" if "VIGENTE" in estado.upper() and "NO" not in estado.upper() else "❌"
                lineas.append(f"  {prefijo} N° SOAT: {soat.get('numSoat', 'N/D')}")
                lineas.append(f"     Inicio: {self._fmt_fecha(soat.get('fechaInicioPoliza'))}")
                lineas.append(f"     Vencimiento: {self._fmt_fecha(soat.get('fechaVencimSoat'))}")
                lineas.append(f"     Aseguradora: {soat.get('razonSocialAsegur', 'N/D')}")
                lineas.append(f"     Estado: {estado}")
        else:
            lineas.append("  Sin información")
        lineas.append("")

        # ── Responsabilidad Civil ─────────────────────────────────────────────
        rc_list = datos.get("responsabilidad_civil")
        lineas.append("*PÓLIZAS DE RESPONSABILIDAD CIVIL*")
        if isinstance(rc_list, list) and rc_list:
            rc_activas = [p for p in rc_list if p.get("estado", "").upper() == "ACTIVA"]
            for p in (rc_activas or [rc_list[-1]]):
                lineas.append(f"  Póliza: {p.get('numeroPoliza', 'N/D')}")
                lineas.append(f"  Tipo: {p.get('tipoPoliza', 'N/D')}")
                lineas.append(f"  Inicio: {p.get('fechaInicioVigencia', 'N/D')}")
                lineas.append(f"  Vencimiento: {p.get('fechaFinVigencia', 'N/D')}")
                lineas.append(f"  Entidad: {p.get('entidadExpide', 'N/D')}")
                lineas.append(f"  Estado: {p.get('estado', 'N/D')}")
        else:
            lineas.append("  Sin pólizas registradas")
        lineas.append("")

        # ── RTM Tecnomecánica ─────────────────────────────────────────────────
        rtm_data = datos.get("tecnomecanica")
        lineas.append("*REVISIÓN TÉCNICO MECÁNICA (RTM)*")
        # /rtms returns a list directly (like /soat), or a dict with "revisiones"
        if isinstance(rtm_data, list):
            rtm_revs = rtm_data
        elif isinstance(rtm_data, dict) and not rtm_data.get("error"):
            rtm_revs = rtm_data.get("revisiones") or []
        else:
            rtm_revs = []
        if rtm_revs:
            for rev in rtm_revs:
                lineas.append(f"  N° Certificado: {rev.get('nroCertificado', 'N/D')}")
                lineas.append(f"  Inicio: {self._fmt_fecha(rev.get('fechaInicio'))}")
                lineas.append(f"  Vencimiento: {self._fmt_fecha(rev.get('fechaVigencia'))}")
                lineas.append(f"  Estado: {rev.get('estado', 'N/D')}")
                lineas.append(f"  CDA: {rev.get('nombreCda', 'N/D')}")
        elif isinstance(rtm_data, dict):
            lineas.append(f"  {rtm_data.get('descripcionRespuesta') or 'Sin información'}")
        else:
            lineas.append("  Sin información")
        lineas.append("")

        # ── Solicitudes ───────────────────────────────────────────────────────
        sol = datos.get("solicitudes")
        if isinstance(sol, list) and sol:
            lineas.append("*SOLICITUDES*")
            for s in sol:
                lineas.append(f"  N° {s.get('noSolicitud', 'N/D')} — {s.get('estado', 'N/D')}")
                lineas.append(f"  Trámite: {s.get('tramitesRealizados', 'N/D').strip(', ')}")
                lineas.append(f"  Entidad: {s.get('entidad', 'N/D')}")
                lineas.append(f"  Fecha: {self._fmt_fecha(s.get('fechaSolicitud'))}")
            lineas.append("")

        # ── Blindaje ──────────────────────────────────────────────────────────
        blindaje = datos.get("blindaje")
        if isinstance(blindaje, dict) and blindaje.get("blindado") == "SI":
            lineas.append("*INFORMACIÓN BLINDAJE*")
            lineas.append(f"  Nivel: {blindaje.get('nivelBlindaje', 'N/D')}")
            lineas.append(f"  Tipo: {blindaje.get('tipoBlindajeNombre', 'N/D')}")
            lineas.append(f"  N° Resolución: {blindaje.get('numeroResolucion', 'N/D')}")
            lineas.append(f"  Fecha expedición cert.: {self._fmt_fecha(blindaje.get('fechaExpedicionCertificado'))}")
            lineas.append("")

        # ── Póliza Caución ────────────────────────────────────────────────────
        caucion = datos.get("poliza_caucion")
        if isinstance(caucion, dict) and caucion.get("noPoliza"):
            lineas.append("*PÓLIZA DE CAUCIÓN (DESINTEGRACIÓN)*")
            lineas.append(f"  N° Póliza: {caucion.get('noPoliza', 'N/D')}")
            lineas.append(f"  Estado: {caucion.get('estadoPoliza', 'N/D')}")
            lineas.append(f"  Expedición: {self._fmt_fecha(caucion.get('fechaExpedicion'))}")
            lineas.append(f"  Vigencia: {self._fmt_fecha(caucion.get('fechaVigenciaPoliza'))}")
            lineas.append(f"  N° Certificación: {caucion.get('noCertificacion', 'N/D')}")
            lineas.append("")

        # ── Desintegración ────────────────────────────────────────────────────
        desint = datos.get("desintegracion")
        if isinstance(desint, dict) and desint.get("desintegrar"):
            lineas.append("*COMPROMISO DESINTEGRACIÓN FÍSICA*")
            lineas.append(f"  Placa: {desint.get('placa', 'N/D')}")
            lineas.append(f"  Estado: {desint.get('desintegrar', 'N/D')}")
            lineas.append("")

        cert_desint = datos.get("certificado_desintegracion")
        if isinstance(cert_desint, dict) and cert_desint.get("noCertificado"):
            lineas.append("*CERTIFICADO DE DESINTEGRACIÓN*")
            lineas.append(f"  N° Certificado: {cert_desint.get('noCertificado', 'N/D')}")
            lineas.append(f"  Estado: {cert_desint.get('estadoCertificado', 'N/D')}")
            lineas.append(f"  Fecha: {self._fmt_fecha(cert_desint.get('fechaExpedicion'))}")
            lineas.append(f"  Entidad: {cert_desint.get('entidadDesintegradora', 'N/D')}")
            lineas.append("")

        # ── Registro Inicial ──────────────────────────────────────────────────
        reg = datos.get("registro_inicial")
        if isinstance(reg, dict) and reg.get("noCertificado"):
            lineas.append("*AUTORIZACIÓN REGISTRO INICIAL (VEHÍCULO CARGA)*")
            lineas.append(f"  N° Certificado: {reg.get('noCertificado', 'N/D')}")
            lineas.append(f"  Estado: {reg.get('estadoCertificado', 'N/D')}")
            lineas.append(f"  Fecha: {self._fmt_fecha(reg.get('fechaExpedicion'))}")
            lineas.append(f"  Placa reposición: {reg.get('placaReposicion', 'N/D')}")
            lineas.append("")

        reg_invc = datos.get("registro_inicial_invc")
        if isinstance(reg_invc, dict) and reg_invc.get("noCertificado"):
            lineas.append("*AUTORIZACIÓN REGISTRO INICIAL INVC (15%)*")
            lineas.append(f"  N° Certificado: {reg_invc.get('noCertificado', 'N/D')}")
            lineas.append(f"  Estado: {reg_invc.get('estadoCertificado', 'N/D')}")
            lineas.append(f"  Fecha: {self._fmt_fecha(reg_invc.get('fechaExpedicion'))}")
            lineas.append("")

        # ── DIJIN ─────────────────────────────────────────────────────────────
        dijin = datos.get("dijin")
        if isinstance(dijin, dict) and dijin.get("noCertificado"):
            lineas.append("*CERTIFICADO REVISIÓN DIJIN*")
            lineas.append(f"  N° Certificado: {dijin.get('noCertificado', 'N/D')}")
            lineas.append(f"  Entidad: {dijin.get('entidadCertificado', 'N/D')}")
            lineas.append(f"  Estado: {dijin.get('estadoCertificado', 'N/D')}")
            lineas.append(f"  Fecha: {self._fmt_fecha(dijin.get('fechaExpedicion'))}")
            lineas.append("")

        # ── Limitaciones / Multas ─────────────────────────────────────────────
        lim_list = datos.get("limitaciones")
        lineas.append("*LIMITACIONES A LA PROPIEDAD / MULTAS*")
        if isinstance(lim_list, list) and lim_list:
            for l in lim_list:
                lineas.append(f"  Tipo: {l.get('tipoLimitacion', 'N/D')}")
                lineas.append(f"  Valor multa: {l.get('valorMulta', 'N/D')}")
                lineas.append(f"  Entidad: {l.get('entidadJuridica', 'N/D')}")
                lineas.append(f"  Municipio: {l.get('municipio', 'N/D')}")
        else:
            lineas.append("  Sin limitaciones registradas")
        lineas.append("")

        # ── Garantías ─────────────────────────────────────────────────────────
        gar = datos.get("garantias") or []
        gar_prendas = datos.get("garantias_prendas") or []
        if gar or gar_prendas:
            lineas.append("*GARANTÍAS A FAVOR DE / GARANTÍAS MOBILIARIAS*")
            for g in gar:
                lineas.append(f"  Acreedor: {g.get('acreedor', 'N/D')}")
                lineas.append(f"  Tipo: {g.get('tipoGarantia', 'N/D')}")
                lineas.append(f"  Fecha: {self._fmt_fecha(g.get('fechaRegistro'))}")
            for p in gar_prendas:
                lineas.append(f"  Prenda — Acreedor: {p.get('acreedor', 'N/D')}")
                lineas.append(f"  Estado: {p.get('estado', 'N/D')}")
            lineas.append("")

        # ── Tarjeta de Operación ──────────────────────────────────────────────
        to = datos.get("tarjeta_operacion")
        lineas.append("*TARJETA DE OPERACIÓN*")
        if isinstance(to, dict) and any(v for v in to.values() if v):
            lineas.append(f"  N° Tarjeta: {to.get('nroTarjetaOperacion', 'N/D')}")
            lineas.append(f"  Empresa: {to.get('empresaAfiliadora', 'N/D')}")
            lineas.append(f"  Modalidad: {to.get('modalidadTransporte', 'N/D')}")
            lineas.append(f"  Servicio: {to.get('modalidadServicio', 'N/D')}")
            lineas.append(f"  Radio de acción: {to.get('radioAccion', 'N/D')}")
            lineas.append(f"  Inicio: {self._fmt_fecha(to.get('fechaInicio'))}")
            lineas.append(f"  Vencimiento: {self._fmt_fecha(to.get('fechaFin'))}")
            lineas.append(f"  Estado: {to.get('estado', 'N/D')}")
        else:
            lineas.append("  No aplica / Sin información")
        lineas.append("")

        # ── Normalización ─────────────────────────────────────────────────────
        norm_list = datos.get("normalizacion")
        if isinstance(norm_list, list):
            norm_activa = [n for n in norm_list if n.get("vehiculoNormalizado") not in (None, "NO DISPONIBLE")]
            if norm_activa:
                lineas.append("*NORMALIZACIÓN Y SANEAMIENTO*")
                for n in norm_activa:
                    lineas.append(f"  Estado normalización: {n.get('vehiculoNormalizado', 'N/D')}")
                    lineas.append(f"  Deficiencia matrícula: {n.get('deficienciaMatriculaInicial', 'N/D')}")
                    lineas.append(f"  N° Acto administrativo: {n.get('numeroActoAdministrativo', 'N/D')}")
                    lineas.append(f"  Fecha: {self._fmt_fecha(n.get('fecha'))}")
                lineas.append("")

        # ── PCR ───────────────────────────────────────────────────────────────
        pcr = datos.get("permisos_pcr")
        if isinstance(pcr, list) and pcr:
            lineas.append("*PERMISO DE CIRCULACIÓN RESTRINGIDA (PCR)*")
            for p in pcr:
                lineas.append(f"  N° Permiso: {p.get('nroPermiso', 'N/D')}")
                lineas.append(f"  Inicio: {self._fmt_fecha(p.get('fechaInicio'))}")
                lineas.append(f"  Vencimiento: {self._fmt_fecha(p.get('fechaFin'))}")
                lineas.append(f"  Estado: {p.get('estado', 'N/D')}")
            lineas.append("")

        # ── Repotenciado ──────────────────────────────────────────────────────
        repot = datos.get("repotenciado")
        if isinstance(repot, dict) and repot.get("repotenciado") not in (None, "NO"):
            lineas.append("*INFORMACIÓN REPOTENCIADO*")
            lineas.append(f"  Estado: {repot.get('repotenciado', 'N/D')}")
            lineas.append(f"  Modelo repotenciado: {repot.get('modeloRepotenciado', 'N/D')}")
            lineas.append(f"  Fecha: {self._fmt_fecha(repot.get('fechaRepotenciacion'))}")
            lineas.append("")

        # ── SIMIT ─────────────────────────────────────────────────────────────
        simit = datos.get("simit")
        lineas.append("*SIMIT — MULTAS Y COMPARENDOS*")
        if isinstance(simit, dict) and not simit.get("error"):
            paz_salvo = simit.get("pazSalvo", False)
            total = simit.get("totalGeneral", 0)
            multas = simit.get("multas") or []
            comparendos = simit.get("comparendos") or []
            acuerdos = simit.get("acuerdosPago") or []

            estado_str = "PAZ Y SALVO" if paz_salvo else "CON DEUDAS"
            lineas.append(f"  Estado: {estado_str}")
            lineas.append(f"  Comparendos: {len(comparendos)}")
            lineas.append(f"  Multas/Resoluciones: {len(multas)}")
            lineas.append(f"  Acuerdos de pago: {len(acuerdos)}")
            if total:
                lineas.append(f"  Total a pagar: ${int(total):,}".replace(",", "."))

            for m in multas:
                lineas.append(f"")
                lineas.append(f"  Resolución: {m.get('numeroResolucion', 'N/D')}")
                infrs = m.get("infracciones") or []
                if infrs:
                    cod = infrs[0].get("codigoInfraccion", "")
                    desc = infrs[0].get("descripcionInfraccion", "")
                    lineas.append(f"  Infracción: {cod} - {desc[:60]}")
                lineas.append(f"  Fecha resolución: {m.get('fechaResolucion', 'N/D')[:10]}")
                lineas.append(f"  Organismo: {m.get('organismoTransito', 'N/D')}")
                lineas.append(f"  Estado: {m.get('estadoCartera', 'N/D')}")
                lineas.append(f"  Valor: ${int(m.get('valorPagar', 0)):,}".replace(",", "."))
                if m.get("valorIntereses"):
                    lineas.append(f"  Intereses: ${int(m.get('valorIntereses', 0)):,}".replace(",", "."))
        elif isinstance(simit, dict) and simit.get("error"):
            lineas.append(f"  Error: {simit['error']}")
        else:
            lineas.append("  Sin información disponible")
        lineas.append("")

        return "\n".join(lineas)

    def _fmt_fecha(self, fecha: str) -> str:
        """Formatea fechas ISO a DD/MM/YYYY."""
        if not fecha:
            return "N/D"
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(fecha.replace("Z", "+00:00"))
            return dt.strftime("%d/%m/%Y")
        except Exception:
            return str(fecha)[:10]


# ── SIMIT Scraper ─────────────────────────────────────────────────────────────

class SimitScraper:
    """
    Consulta multas/comparendos SIMIT usando Playwright (headless Chrome).
    Playwright es necesario porque el portal usa weHateCaptcha (proof-of-work)
    y el backend tiene WAF que bloquea requests directos de Python.
    """

    SIMIT_URL = "https://www.fcm.org.co/simit/#/estado-cuenta"
    API_URL = "https://consultasimit.fcm.org.co/simit/microservices/estado-cuenta-simit/estadocuenta/consulta"

    def consultar(self, placa: str, timeout_captcha: int = 30) -> dict:
        """
        Consulta el estado de cuenta SIMIT para la placa dada.
        Retorna el dict completo con multas, comparendos, acuerdosPago, etc.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"error": "Playwright no instalado. Ejecutar: python -m playwright install chromium"}

        placa = placa.upper().strip()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            try:
                page.goto(self.SIMIT_URL, timeout=30000, wait_until="domcontentloaded")
                time.sleep(2)

                # Esperar a que weHateCaptcha resuelva el proof-of-work en background
                start = time.time()
                while time.time() - start < timeout_captcha:
                    whc_raw = page.evaluate("sessionStorage.getItem('whcQuestions')")
                    if whc_raw:
                        whc = json.loads(whc_raw)
                        if whc.get("questions") and len(whc["questions"]) > 0:
                            break
                    time.sleep(1)
                else:
                    return {"error": f"weHateCaptcha no resolvió en {timeout_captcha}s"}

                print(f"[SIMIT] Captcha resuelto ({int(time.time() - start)}s)")

                # Tomar un token de captcha del sessionStorage
                captcha_response = page.evaluate("""
                    (() => {
                        var whc = JSON.parse(sessionStorage.getItem('whcQuestions'));
                        var token = whc.questions.pop();
                        sessionStorage.setItem('whcQuestions', JSON.stringify(whc));
                        return JSON.stringify(token);
                    })()
                """)

                # Hacer la llamada a la API desde el contexto del browser (bypassa WAF)
                result = page.evaluate(f"""
                    async () => {{
                        const payload = {{
                            filtro: {json.dumps(placa)},
                            reCaptchaDTO: {{
                                response: {json.dumps(captcha_response)},
                                consumidor: '1'
                            }}
                        }};
                        const response = await fetch(
                            {json.dumps(self.API_URL)},
                            {{
                                method: 'POST',
                                headers: {{ 'Content-Type': 'application/json', 'Accept': '*/*' }},
                                body: JSON.stringify(payload)
                            }}
                        );
                        const text = await response.text();
                        return {{ status: response.status, body: text }};
                    }}
                """)

                if result["status"] != 200:
                    return {"error": f"SIMIT HTTP {result['status']}: {result['body'][:200]}"}

                return json.loads(result["body"])

            except Exception as e:
                return {"error": str(e)}
            finally:
                browser.close()


# ── Uso de ejemplo ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    placa = sys.argv[1] if len(sys.argv) > 1 else "RRC10H"
    documento = sys.argv[2] if len(sys.argv) > 2 else "1010960147"
    tipo_raw = sys.argv[3] if len(sys.argv) > 3 else "C"

    try:
        tipo_doc = normalizar_tipo_documento(tipo_raw)
    except ValueError as ve:
        print(f"Error: {ve}")
        sys.exit(1)

    nombre_doc = NOMBRE_DOCUMENTO.get(tipo_doc, tipo_doc)
    print(f"\nConsultando placa: {placa}, {nombre_doc}: {documento}\n")

    runt = RuntScraper()
    simit = SimitScraper()

    try:
        print("--- Consultando RUNT ---")
        datos = runt.consulta_completa(placa, documento, tipo_documento=tipo_doc)

        print("\n--- Consultando SIMIT ---")
        datos["simit"] = simit.consultar(placa)
        print(f"[SIMIT] Total: ${datos['simit'].get('totalGeneral', 0):,.0f}")

        print("\n=== MENSAJE WHATSAPP ===")
        print(runt.formatear_para_whatsapp(datos))

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error: {e}")