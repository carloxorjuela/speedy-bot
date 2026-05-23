import sys
import os
import json
import time
import sqlite3
import traceback
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory

# ── Path resolution ──────────────────────────────────────────────────────────
# Support both Docker (/app) and local execution (directory of this file)
_HERE = os.path.dirname(os.path.abspath(__file__))
for _candidate in ('/app', _HERE):
    if _candidate not in sys.path:
        sys.path.insert(0, _candidate)

from runt_scraper import RuntScraper, SimitScraper

# ── App setup ────────────────────────────────────────────────────────────────
app = Flask(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
ADMIN_KEY = os.environ.get('ADMIN_KEY', 'speedy-admin-2026')
DB_PATH   = os.path.join(_HERE, 'carplus.db')

# ── Database ──────────────────────────────────────────────────────────────────
def get_db():
    """Return a thread-local SQLite connection with row_factory set."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist."""
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS consultas (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp         TEXT    NOT NULL,
                placa             TEXT    NOT NULL,
                cedula_masked     TEXT,
                success           INTEGER NOT NULL DEFAULT 0,
                error_msg         TEXT,
                response_time_ms  INTEGER,
                ip                TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS placas_cache (
                placa            TEXT PRIMARY KEY,
                cedula_masked    TEXT,
                ultima_consulta  TEXT,
                datos_json       TEXT,
                marca            TEXT,
                modelo           TEXT,
                anio             TEXT,
                color            TEXT,
                clase            TEXT,
                estado_vehiculo  TEXT,
                soat_vence       TEXT,
                soat_aseguradora TEXT,
                soat_estado      TEXT,
                rtm_vence        TEXT,
                rtm_cda          TEXT,
                rtm_estado       TEXT,
                rc_vence         TEXT,
                rc_estado        TEXT,
                tarjeta_op_vence TEXT,
                tarjeta_op_estado TEXT,
                simit_paz_salvo  INTEGER DEFAULT 0,
                simit_total      REAL DEFAULT 0
            )
        """)
        conn.commit()


init_db()

# ── Utilities ─────────────────────────────────────────────────────────────────
def mask_cedula(c: str) -> str:
    """Show first 2 and last 2 characters; mask the rest with '*'."""
    if not c:
        return ''
    c = str(c)
    if len(c) <= 4:
        return c
    return c[:2] + '*' * (len(c) - 4) + c[-2:]


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _get_client_ip() -> str:
    # Respect X-Forwarded-For when behind a proxy
    xff = request.headers.get('X-Forwarded-For', '')
    if xff:
        return xff.split(',')[0].strip()
    return request.remote_addr or ''


def _log_consulta(placa: str, cedula_masked: str, success: bool,
                  error_msg: str | None, response_time_ms: int, ip: str):
    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO consultas
                   (timestamp, placa, cedula_masked, success, error_msg, response_time_ms, ip)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (_now_iso(), placa, cedula_masked, int(success),
                 error_msg, response_time_ms, ip)
            )
            conn.commit()
    except Exception:
        traceback.print_exc()  # Never let logging crash the request

# ── Placa cache helper ────────────────────────────────────────────────────────
def _upsert_placa_cache(placa: str, cedula_masked: str, datos: dict):
    """Parse datos dict and upsert into placas_cache."""
    try:
        auth = datos.get('auth', {}) or {}
        info = (auth.get('infoVehiculo') or {})

        # SOAT — pick the policy with the latest expiry date (not simply last in list)
        soat_list = datos.get('soat') or []
        soat_vence = soat_aseguradora = soat_estado = None
        if isinstance(soat_list, list) and soat_list:
            valid = [s for s in soat_list if s.get('fechaVencimSoat')]
            s = max(valid, key=lambda x: x['fechaVencimSoat']) if valid else soat_list[0]
            raw = s.get('fechaVencimSoat', '') or ''
            soat_vence = raw[:10] if raw else None
            soat_aseguradora = s.get('razonSocialAsegur')
            soat_estado = s.get('estado')

        # RTM — API returns a list directly (like /soat), or a dict with "revisiones"
        tec_raw = datos.get('tecnomecanica')
        if isinstance(tec_raw, list):
            revs = tec_raw
        elif isinstance(tec_raw, dict) and not tec_raw.get('error'):
            revs = tec_raw.get('revisiones') or []
        else:
            revs = []
        rtm_vence = rtm_cda = rtm_estado = None
        if revs:
            valid_r = [r for r in revs if r.get('fechaVigencia')]
            rev = max(valid_r, key=lambda x: x['fechaVigencia']) if valid_r else revs[0]
            raw = rev.get('fechaVigencia', '') or ''
            rtm_vence = raw[:10] if raw else None
            rtm_cda = rev.get('nombreCda')
            rtm_estado = rev.get('estado')

        # Responsabilidad Civil — prefer active policy with latest expiry
        rc_list = datos.get('responsabilidad_civil') or []
        rc_vence = rc_estado = None
        if isinstance(rc_list, list) and rc_list:
            activas = [p for p in rc_list if (p.get('estado') or '').upper() == 'ACTIVA']
            pool = activas if activas else rc_list
            valid_rc = [p for p in pool if p.get('fechaFinVigencia')]
            rc_item = max(valid_rc, key=lambda x: x['fechaFinVigencia']) if valid_rc else pool[0]
            raw = rc_item.get('fechaFinVigencia', '') or ''
            rc_vence = raw[:10] if raw else None
            rc_estado = rc_item.get('estado')

        # Tarjeta operación
        to = datos.get('tarjeta_operacion') or {}
        to_vence = to_estado = None
        if isinstance(to, dict):
            raw = to.get('fechaFin', '') or ''
            to_vence = raw[:10] if raw else None
            to_estado = to.get('estado')

        # SIMIT
        simit = datos.get('simit') or {}
        paz_salvo = int(bool(simit.get('pazSalvo', False))) if isinstance(simit, dict) else 0
        simit_total = float(simit.get('totalGeneral', 0) or 0) if isinstance(simit, dict) else 0.0

        with get_db() as conn:
            conn.execute("""
                INSERT INTO placas_cache
                    (placa, cedula_masked, ultima_consulta, datos_json,
                     marca, modelo, anio, color, clase, estado_vehiculo,
                     soat_vence, soat_aseguradora, soat_estado,
                     rtm_vence, rtm_cda, rtm_estado,
                     rc_vence, rc_estado,
                     tarjeta_op_vence, tarjeta_op_estado,
                     simit_paz_salvo, simit_total)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(placa) DO UPDATE SET
                    cedula_masked=excluded.cedula_masked,
                    ultima_consulta=excluded.ultima_consulta,
                    datos_json=excluded.datos_json,
                    marca=excluded.marca, modelo=excluded.modelo, anio=excluded.anio,
                    color=excluded.color, clase=excluded.clase, estado_vehiculo=excluded.estado_vehiculo,
                    soat_vence=excluded.soat_vence, soat_aseguradora=excluded.soat_aseguradora, soat_estado=excluded.soat_estado,
                    rtm_vence=excluded.rtm_vence, rtm_cda=excluded.rtm_cda, rtm_estado=excluded.rtm_estado,
                    rc_vence=excluded.rc_vence, rc_estado=excluded.rc_estado,
                    tarjeta_op_vence=excluded.tarjeta_op_vence, tarjeta_op_estado=excluded.tarjeta_op_estado,
                    simit_paz_salvo=excluded.simit_paz_salvo, simit_total=excluded.simit_total
            """, (
                placa, cedula_masked, _now_iso(), json.dumps(datos, ensure_ascii=False),
                info.get('marca'), info.get('linea'), info.get('modelo'),
                info.get('color'), info.get('clase'), info.get('estadoAutomotor'),
                soat_vence, soat_aseguradora, soat_estado,
                rtm_vence, rtm_cda, rtm_estado,
                rc_vence, rc_estado,
                to_vence, to_estado,
                paz_salvo, simit_total
            ))
            conn.commit()
    except Exception:
        traceback.print_exc()

# ── CORS helper ───────────────────────────────────────────────────────────────
def _cors(response):
    response.headers['Access-Control-Allow-Origin']  = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-Admin-Key'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    return response


@app.after_request
def after_request(response):
    return _cors(response)


@app.before_request
def handle_options():
    if request.method == 'OPTIONS':
        resp = app.make_default_options_response()
        return _cors(resp)

# ── Auth decorator ────────────────────────────────────────────────────────────
def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = (
            request.headers.get('X-Admin-Key')
            or request.args.get('key', '')
        )
        if key != ADMIN_KEY:
            return jsonify({'ok': False, 'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated

# ── Static file serving ───────────────────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory(_HERE, 'index.html')


@app.route('/admin')
def admin():
    return send_from_directory(_HERE, 'admin.html')

# ── Health check ──────────────────────────────────────────────────────────────
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'timestamp': _now_iso()})

# ── Main query endpoint ───────────────────────────────────────────────────────
@app.route('/consultar', methods=['POST'])
def consultar():
    body   = request.get_json(force=True, silent=True) or {}
    placa  = str(body.get('placa',  '')).upper().strip()
    cedula = str(body.get('cedula', '')).strip()
    ip     = _get_client_ip()

    if not placa or not cedula:
        return jsonify({'ok': False, 'error': 'placa y cedula son requeridos'}), 400

    cedula_masked = mask_cedula(cedula)
    t0 = time.monotonic()

    try:
        runt  = RuntScraper()
        simit = SimitScraper()

        datos = runt.consulta_completa(placa, cedula)
        datos['simit'] = simit.consultar(placa)
        _upsert_placa_cache(placa, cedula_masked, datos)

        mensaje = runt.formatear_para_whatsapp(datos)

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        _log_consulta(placa, cedula_masked, True, None, elapsed_ms, ip)

        return jsonify({'ok': True, 'mensaje': mensaje, 'datos': datos})

    except Exception as exc:
        traceback.print_exc()
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        _log_consulta(placa, cedula_masked, False, str(exc), elapsed_ms, ip)
        return jsonify({'ok': False, 'error': str(exc)}), 500

# ── Placas page ───────────────────────────────────────────────────────────────
@app.route('/placas')
def placas_page():
    return send_from_directory(_HERE, 'placas.html')

# ── Admin: placas cache ───────────────────────────────────────────────────────
@app.route('/admin/placas', methods=['GET'])
@require_admin
def admin_placas():
    try:
        conn = get_db()
        rows = conn.execute("""
            SELECT placa, cedula_masked, ultima_consulta,
                   marca, modelo, anio, color, clase, estado_vehiculo,
                   soat_vence, soat_aseguradora, soat_estado,
                   rtm_vence, rtm_cda, rtm_estado,
                   rc_vence, rc_estado,
                   tarjeta_op_vence, tarjeta_op_estado,
                   simit_paz_salvo, simit_total
            FROM placas_cache ORDER BY ultima_consulta DESC
        """).fetchall()
        conn.close()
        return jsonify({'ok': True, 'placas': [dict(r) for r in rows]})
    except Exception as exc:
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(exc)}), 500


@app.route('/admin/placas/<placa>/datos', methods=['GET'])
@require_admin
def admin_placa_datos(placa):
    try:
        conn = get_db()
        row = conn.execute(
            'SELECT datos_json FROM placas_cache WHERE placa = ?', (placa.upper(),)
        ).fetchone()
        conn.close()
        if not row:
            return jsonify({'ok': False, 'error': 'Placa no encontrada'}), 404
        return jsonify({'ok': True, 'datos': json.loads(row['datos_json'])})
    except Exception as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 500

# ── Admin: metrics ────────────────────────────────────────────────────────────
@app.route('/admin/metrics', methods=['GET'])
@require_admin
def admin_metrics():
    try:
        conn = get_db()

        total_consultas = conn.execute(
            'SELECT COUNT(*) FROM consultas'
        ).fetchone()[0]

        consultas_hoy = conn.execute(
            "SELECT COUNT(*) FROM consultas WHERE timestamp LIKE ?",
            (_today_str() + '%',)
        ).fetchone()[0]

        success_count = conn.execute(
            'SELECT COUNT(*) FROM consultas WHERE success = 1'
        ).fetchone()[0]

        tasa_exito = (
            round(success_count / total_consultas * 100, 2)
            if total_consultas else 0.0
        )

        tiempo_promedio_row = conn.execute(
            'SELECT AVG(response_time_ms) FROM consultas WHERE response_time_ms IS NOT NULL'
        ).fetchone()[0]
        tiempo_promedio_ms = int(tiempo_promedio_row) if tiempo_promedio_row else 0

        # Top 10 placas
        top_placas_rows = conn.execute(
            """SELECT placa, COUNT(*) AS consultas
               FROM consultas
               GROUP BY placa
               ORDER BY consultas DESC
               LIMIT 10"""
        ).fetchall()
        top_placas = [{'placa': r['placa'], 'consultas': r['consultas']} for r in top_placas_rows]

        # Consultas por día — últimos 7 días
        dias_rows = conn.execute(
            """SELECT substr(timestamp, 1, 10)        AS dia,
                      COUNT(*)                        AS total,
                      SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) AS exitosas
               FROM consultas
               WHERE timestamp >= date('now', '-6 days')
               GROUP BY dia
               ORDER BY dia"""
        ).fetchall()
        consultas_por_dia = [
            {'dia': r['dia'], 'total': r['total'], 'exitosas': r['exitosas']}
            for r in dias_rows
        ]

        # Consultas por hora (0–23)
        horas_rows = conn.execute(
            """SELECT substr(timestamp, 12, 2) || ':00' AS hora,
                      COUNT(*)                          AS n
               FROM consultas
               GROUP BY hora
               ORDER BY hora"""
        ).fetchall()
        consultas_por_hora = [{'hora': r['hora'], 'n': r['n']} for r in horas_rows]

        conn.close()

        return jsonify({
            'total_consultas':    total_consultas,
            'consultas_hoy':      consultas_hoy,
            'tasa_exito':         tasa_exito,
            'tiempo_promedio_ms': tiempo_promedio_ms,
            'top_placas':         top_placas,
            'consultas_por_dia':  consultas_por_dia,
            'consultas_por_hora': consultas_por_hora,
        })

    except Exception as exc:
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(exc)}), 500

# ── Admin: paginated logs ─────────────────────────────────────────────────────
@app.route('/admin/logs', methods=['GET'])
@require_admin
def admin_logs():
    try:
        page     = max(1, int(request.args.get('page',     1)))
        per_page = max(1, min(200, int(request.args.get('per_page', 50))))
        offset   = (page - 1) * per_page

        conn = get_db()

        total = conn.execute('SELECT COUNT(*) FROM consultas').fetchone()[0]

        rows = conn.execute(
            """SELECT id, timestamp, placa, cedula_masked,
                      success, error_msg, response_time_ms, ip
               FROM consultas
               ORDER BY id DESC
               LIMIT ? OFFSET ?""",
            (per_page, offset)
        ).fetchall()

        conn.close()

        logs = [
            {
                'id':               r['id'],
                'timestamp':        r['timestamp'],
                'placa':            r['placa'],
                'cedula_masked':    r['cedula_masked'],
                'success':          bool(r['success']),
                'error_msg':        r['error_msg'],
                'response_time_ms': r['response_time_ms'],
                'ip':               r['ip'],
            }
            for r in rows
        ]

        return jsonify({
            'total':    total,
            'page':     page,
            'per_page': per_page,
            'logs':     logs,
        })

    except Exception as exc:
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(exc)}), 500


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)
