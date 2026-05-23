"""
=============================================================
EXTRACTOR DE TEXTO - DOCUMENTOS VEHICULARES
Para integración con n8n + chatbot
=============================================================

Este script recibe archivos (PDF o imágenes) que sube un conductor
y extrae TODO el texto de cada uno por separado.

Modos de uso:

1. DESDE LÍNEA DE COMANDO (para probar):
   python extractor_texto.py archivo1.pdf archivo2.jpg archivo3.png

2. DESDE N8N (como módulo):
   from extractor_texto import extraer_texto_archivo, extraer_texto_base64
   
   # Opción A: desde ruta de archivo
   resultado = extraer_texto_archivo("/ruta/al/soat.pdf")
   
   # Opción B: desde base64 (como llega del chatbot)
   resultado = extraer_texto_base64(base64_string, "soat.pdf")

Salida JSON por documento:
{
    "archivo": "soat.pdf",
    "tipo_archivo": "pdf",
    "paginas": 1,
    "texto_completo": "todo el texto extraído...",
    "texto_por_pagina": {"1": "texto pagina 1..."},
    "exito": true,
    "error": null
}

Requisitos:
   pip install pypdf Pillow pytesseract pdf2image

Para imágenes (OCR) también necesitas Tesseract instalado:
   - Windows: https://github.com/UB-Mannheim/tesseract/wiki
   - Mac: brew install tesseract tesseract-lang
   - Linux: sudo apt install tesseract-ocr tesseract-ocr-spa
=============================================================
"""

import json
import sys
import os
import base64
import tempfile
from pathlib import Path
from datetime import datetime, timezone


# ═══════════════════════════════════════════════════════════
# EXTRACCIÓN DE PDF
# ═══════════════════════════════════════════════════════════

def extraer_texto_pdf(filepath: str) -> dict:
    """Extrae todo el texto de un PDF, página por página."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return _error(filepath, "pypdf no instalado. Ejecuta: pip install pypdf")

    try:
        reader = PdfReader(filepath)
        num_paginas = len(reader.pages)
        texto_por_pagina = {}
        texto_completo_parts = []

        for i, page in enumerate(reader.pages, 1):
            texto = page.extract_text() or ""
            texto = texto.strip()
            texto_por_pagina[str(i)] = texto
            if texto:
                texto_completo_parts.append(texto)

        texto_completo = "\n\n".join(texto_completo_parts)

        # Si pypdf no extrajo texto (PDF escaneado), intentar OCR
        if not texto_completo.strip():
            return _extraer_pdf_ocr(filepath, num_paginas)

        return {
            "archivo": os.path.basename(filepath),
            "tipo_archivo": "pdf",
            "paginas": num_paginas,
            "texto_completo": texto_completo,
            "texto_por_pagina": texto_por_pagina,
            "metodo": "pypdf",
            "exito": True,
            "error": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        return _error(filepath, str(e))


def _detectar_idioma_ocr() -> str:
    """Detecta qué idiomas de Tesseract están disponibles."""
    try:
        import pytesseract
        idiomas = pytesseract.get_languages()
        if "spa" in idiomas:
            return "spa+eng"
        return "eng"
    except Exception:
        return "eng"


def _extraer_pdf_ocr(filepath: str, num_paginas: int) -> dict:
    """Fallback: convierte PDF a imágenes y aplica OCR."""
    try:
        from pdf2image import convert_from_path
        import pytesseract
    except ImportError:
        return {
            "archivo": os.path.basename(filepath),
            "tipo_archivo": "pdf",
            "paginas": num_paginas,
            "texto_completo": "",
            "texto_por_pagina": {},
            "metodo": "pypdf_vacio",
            "exito": True,
            "error": "PDF sin texto extraíble (escaneado). Instala pdf2image y pytesseract para OCR.",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    try:
        lang = _detectar_idioma_ocr()
        imagenes = convert_from_path(filepath, dpi=300)
        texto_por_pagina = {}
        texto_completo_parts = []

        for i, img in enumerate(imagenes, 1):
            texto = pytesseract.image_to_string(img, lang=lang)
            texto = texto.strip()
            texto_por_pagina[str(i)] = texto
            if texto:
                texto_completo_parts.append(texto)

        return {
            "archivo": os.path.basename(filepath),
            "tipo_archivo": "pdf",
            "paginas": len(imagenes),
            "texto_completo": "\n\n".join(texto_completo_parts),
            "texto_por_pagina": texto_por_pagina,
            "metodo": f"ocr_tesseract_{lang}",
            "exito": True,
            "error": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return _error(filepath, f"OCR falló: {str(e)}")


# ═══════════════════════════════════════════════════════════
# EXTRACCIÓN DE IMÁGENES (OCR)
# ═══════════════════════════════════════════════════════════

def extraer_texto_imagen(filepath: str) -> dict:
    """Extrae texto de una imagen usando OCR."""
    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        return _error(filepath, "Pillow o pytesseract no instalados. Ejecuta: pip install Pillow pytesseract")

    try:
        img = Image.open(filepath)

        # Si la imagen es muy pequeña, escalar para mejor OCR
        w, h = img.size
        if w < 1000 or h < 1000:
            scale = max(1500 / w, 1500 / h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        lang = _detectar_idioma_ocr()
        texto = pytesseract.image_to_string(img, lang=lang)
        texto = texto.strip()

        return {
            "archivo": os.path.basename(filepath),
            "tipo_archivo": "imagen",
            "paginas": 1,
            "texto_completo": texto,
            "texto_por_pagina": {"1": texto},
            "metodo": "ocr_tesseract",
            "exito": True,
            "error": None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        return _error(filepath, str(e))


# ═══════════════════════════════════════════════════════════
# FUNCIONES PRINCIPALES (para n8n)
# ═══════════════════════════════════════════════════════════

def extraer_texto_archivo(filepath: str) -> dict:
    """
    Función principal. Recibe ruta de archivo, detecta tipo y extrae texto.
    Usar desde n8n o cualquier backend.
    """
    if not os.path.exists(filepath):
        return _error(filepath, "Archivo no encontrado")

    ext = Path(filepath).suffix.lower()

    if ext == ".pdf":
        return extraer_texto_pdf(filepath)
    elif ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"):
        return extraer_texto_imagen(filepath)
    else:
        return _error(filepath, f"Formato no soportado: {ext}")


def extraer_texto_base64(b64_string: str, nombre_archivo: str) -> dict:
    """
    Recibe archivo como base64 (como llega del chatbot/WhatsApp).
    Guarda temporalmente, extrae texto y limpia.
    """
    ext = Path(nombre_archivo).suffix.lower()
    if not ext:
        ext = ".pdf"  # default

    try:
        contenido = base64.b64decode(b64_string)
    except Exception as e:
        return _error(nombre_archivo, f"Error decodificando base64: {str(e)}")

    # Guardar temporal
    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp.write(contenido)
        tmp_path = tmp.name

    try:
        resultado = extraer_texto_archivo(tmp_path)
        resultado["archivo"] = nombre_archivo  # Nombre original, no el temporal
        return resultado
    finally:
        os.unlink(tmp_path)  # Limpiar archivo temporal


def extraer_multiples(archivos: list) -> list:
    """
    Procesa múltiples archivos de una vez.
    archivos: lista de rutas o lista de dicts {"base64": "...", "nombre": "..."}
    """
    resultados = []
    for item in archivos:
        if isinstance(item, str):
            resultados.append(extraer_texto_archivo(item))
        elif isinstance(item, dict):
            if "base64" in item and "nombre" in item:
                resultados.append(extraer_texto_base64(item["base64"], item["nombre"]))
            elif "ruta" in item:
                resultados.append(extraer_texto_archivo(item["ruta"]))
            else:
                resultados.append(_error("desconocido", "Dict debe tener 'base64'+'nombre' o 'ruta'"))
        else:
            resultados.append(_error("desconocido", f"Tipo no soportado: {type(item)}"))
    return resultados


# ═══════════════════════════════════════════════════════════
# UTILIDADES
# ═══════════════════════════════════════════════════════════

def _error(filepath: str, mensaje: str) -> dict:
    return {
        "archivo": os.path.basename(filepath) if filepath else "desconocido",
        "tipo_archivo": None,
        "paginas": 0,
        "texto_completo": "",
        "texto_por_pagina": {},
        "metodo": None,
        "exito": False,
        "error": mensaje,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════
# EJECUCIÓN DESDE TERMINAL (para probar)
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python extractor_texto.py archivo1.pdf archivo2.jpg ...")
        print("\nEjemplo:")
        print('  python extractor_texto.py "C:\\Users\\Samuel\\Downloads\\PWR324 (1).pdf"')
        print('  python extractor_texto.py soat.pdf tarjeta.jpg licencia.png poliza.pdf')
        sys.exit(1)

    archivos = sys.argv[1:]
    resultados = extraer_multiples(archivos)

    # Imprimir resumen
    print("\n" + "═" * 65)
    print("  EXTRACCIÓN DE TEXTO - RESUMEN")
    print("═" * 65)

    for r in resultados:
        icono = "✅" if r["exito"] else "❌"
        chars = len(r["texto_completo"])
        print(f"  {icono}  {r['archivo']}")
        print(f"      Páginas: {r['paginas']} │ Caracteres: {chars} │ Método: {r['metodo']}")
        if r["error"]:
            print(f"      ⚠️  {r['error']}")
        print()

    # Guardar JSON
    salida = "extraccion_texto_resultado.json"
    with open(salida, "w", encoding="utf-8") as f:
        json.dump(resultados, f, ensure_ascii=False, indent=2)
    print(f"💾 JSON guardado: {salida}")

    # Mostrar preview del texto por archivo
    print("\n" + "═" * 65)
    print("  PREVIEW DEL TEXTO EXTRAÍDO")
    print("═" * 65)
    for r in resultados:
        if r["exito"] and r["texto_completo"]:
            print(f"\n📄 {r['archivo']} ({r['paginas']} pág)")
            print("─" * 65)
            preview = r["texto_completo"][:500]
            if len(r["texto_completo"]) > 500:
                preview += "\n... [truncado]"
            print(preview)
            print()
