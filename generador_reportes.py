"""Reportes PDF de Sky — Agente de IA para Almacén, solo lectura.

Requiere herramientas_inventario.py y las variables SUPABASE_* ya configuradas.
Ejecución: python generador_reportes.py
"""
import os
from datetime import datetime
from decimal import Decimal
from html import escape
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle

from herramientas_inventario import (
    consultar_stock_bajo, consultar_kardex, leer_paginas, periodo,
    supabase, numero,
)

load_dotenv()


def _fonts():
    for regular, bold in [
        ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]:
        if Path(regular).is_file() and Path(bold).is_file():
            if "AlmacenRegular" not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont("AlmacenRegular", regular))
                pdfmetrics.registerFont(TTFont("AlmacenBold", bold))
            return "AlmacenRegular", "AlmacenBold"
    return "Helvetica", "Helvetica-Bold"


def _fmt(v, moneda=False):
    if v is None or v == "":
        return "—"
    try:
        n = Decimal(str(v))
        return ("S/ " if moneda else "") + f"{n:,.2f}"
    except Exception:
        return str(v)


def _fecha(v):
    return str(v or "—").replace("T", " ")[:19]


def _comprobar(datos):
    if not isinstance(datos, list):
        raise ValueError("La fuente no devolvió una lista válida")
    if len(datos) > 50000:
        raise ValueError("El reporte es demasiado extenso. Reduce el periodo.")
    return datos


def _pdf(tipo, titulo, columnas, filas, resumen, fuente, nota=""):
    """Render único para todos los reportes, con cabecera repetida y paginación."""
    output = Path(os.getenv("REPORTES_DIR", "reportes"))
    output.mkdir(parents=True, exist_ok=True)
    destino = output / f"{tipo}_{datetime.now():%Y%m%d_%H%M%S}_{uuid4().hex[:8]}.pdf"
    regular, bold = _fonts()
    st = getSampleStyleSheet()
    st_title = ParagraphStyle("TituloInventario", parent=st["Title"], fontName=bold,
                              textColor=colors.HexColor("#20344e"), fontSize=17, leading=22)
    st_text = ParagraphStyle("TextoInventario", parent=st["Normal"], fontName=regular,
                             fontSize=9, leading=13)
    st_cell = ParagraphStyle("CeldaInventario", parent=st_text, fontSize=7, leading=10, alignment=TA_CENTER)
    st_head = ParagraphStyle("CabeceraInventario", parent=st_cell, fontName=bold,
                             textColor=colors.white, alignment=TA_CENTER)

    def p(x, s=st_cell):
        return Paragraph(escape(str(x if x is not None else "—")), s)

    width, _ = landscape(A4)
    usable = width - 32*mm
    weights = [float(col[1]) for col in columnas]
    widths = [usable * w/sum(weights) for w in weights]
    data = [[p(name, st_head) for name, _ in columnas]]
    for fila in filas:
        if len(fila) != len(columnas):
            raise ValueError("Cantidad incorrecta de columnas del reporte")
        data.append([p(valor) for valor in fila])
    if len(data) == 1:
        data.append([p("Sin registros")]+[p("") for _ in columnas[1:]])
    table = LongTable(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0,0),(-1,0), colors.HexColor("#243B53")),
        ("ROWBACKGROUNDS", (0,1),(-1,-1), [colors.white, colors.HexColor("#F1F5F9")]),
        ("VALIGN", (0,0),(-1,-1), "MIDDLE"),
        ("ALIGN", (0,0),(-1,-1), "CENTER"),
        ("TOPPADDING", (0,0),(-1,-1), 6),
        ("BOTTOMPADDING", (0,0),(-1,-1), 6),
        ("LEFTPADDING", (0,0),(-1,-1), 5),
        ("RIGHTPADDING", (0,0),(-1,-1), 5),
    ]))
    story = [p("Sky — Agente de IA para Almacén", st_text), Spacer(1, 2*mm),
             p(titulo, st_title), Spacer(1, 3*mm),
             p(f"Generado: {datetime.now():%d/%m/%Y %H:%M} | Fuente: {fuente}", st_text),
             Spacer(1, 4*mm)]
    for line in resumen:
        story.append(p(line, st_text))
    story += [Spacer(1, 6*mm), table]
    if nota:
        story.extend([Spacer(1, 5*mm), p("Nota: " + nota, st_text)])
    doc = SimpleDocTemplate(str(destino), pagesize=landscape(A4),
                            leftMargin=16*mm, rightMargin=16*mm,
                            topMargin=18*mm, bottomMargin=17*mm)
    def pie(canvas, document):
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.setFont(regular, 8)
        canvas.drawString(16*mm, 11*mm, "Sky — Agente de IA para Almacén")
        canvas.drawRightString(width-16*mm, 11*mm, f"Página {document.page}")
    doc.build(story, onFirstPage=pie, onLaterPages=pie)
    return str(destino.resolve())


def generar_reporte_stock_bajo():
    r = consultar_stock_bajo()
    if not isinstance(r, dict) or r.get("error"):
        raise RuntimeError((r or {}).get("error", "Error al consultar stock bajo"))
    datos = _comprobar(r.get("productos", []))
    if r.get("total_productos") != len(datos):
        raise ValueError("Resultado incompleto de stock bajo")
    filas = [[d.get("cod_producto"), d.get("nombre"), d.get("categoria"),
              _fmt(d.get("stock_actual")), _fmt(d.get("stock_minimo")),
              d.get("estado_stock")] for d in datos]
    return _pdf("stock_bajo", "REPORTE DE STOCK BAJO",
                [("Código", 14),("Producto", 38),("Categoría", 20),
                 ("Stock actual", 13),("Stock mínimo", 13),("Estado", 17)],
                filas, [f"Productos identificados: {len(datos)}"], "stock_bajo",
                "Los valores proceden de la vista stock_bajo. No se modifica el inventario.")


def generar_reporte_inventario():
    datos = _comprobar(leer_paginas("productos_inventario", orden="cod_producto"))
    filas = [[d.get("cod_producto"), d.get("nombre"), d.get("categoria"),
              _fmt(d.get("stock_actual")), _fmt(d.get("stock_minimo")),
              _fmt(d.get("precio_compra"), True), d.get("estado_stock")] for d in datos]
    valor = sum((numero(d.get("stock_actual"))*numero(d.get("precio_compra")) for d in datos), Decimal(0))
    return _pdf("inventario", "REPORTE DE INVENTARIO GENERAL",
                [("Código",14),("Producto",36),("Categoría",17),("Stock",12),
                 ("Mínimo",12),("Precio compra",16),("Estado",15)], filas,
                [f"Productos consultados: {len(datos)}", f"Valorización estimada (stock × precio compra): {_fmt(valor, True)}"],
                "productos_inventario", "La valorización se basa en el precio de compra registrado.")


def generar_reporte_movimientos(tipo, fecha_inicio, fecha_fin):
    tipo = tipo.strip().lower()
    if tipo not in ("entradas", "salidas"):
        raise ValueError("Usa 'entradas' o 'salidas'")
    desde, hasta = periodo(fecha_inicio, fecha_fin)
    datos = _comprobar(leer_paginas(tipo, filtros=[("fecha","gte",desde),("fecha","lt",hasta)], orden="fecha"))
    id_campo = "id_entrada" if tipo == "entradas" else "id_salida"
    monto_campo = "total_compra" if tipo == "entradas" else "total_venta"
    total = sum((numero(d.get(monto_campo)) for d in datos), Decimal(0))
    filas = [[d.get(id_campo), _fecha(d.get("fecha")), d.get("documento"),
              d.get("cod_proveedor") if tipo == "entradas" else d.get("cliente"),
              _fmt(d.get(monto_campo), True)] for d in datos]
    return _pdf(tipo, "REPORTE DE " + tipo.upper(),
                [("ID",10),("Fecha",22),("Documento",25),
                 ("Proveedor" if tipo == "entradas" else "Cliente",40),("Importe",21)],
                filas, [f"Periodo: {fecha_inicio} a {fecha_fin}",
                       f"Operaciones: {len(datos)} | Total registrado: {_fmt(total,True)}"],
                tipo, "Importes extraídos de encabezados de operaciones; no son cantidades de unidades.")


def generar_reporte_kardex(codigo, fecha_inicio, fecha_fin):
    r = consultar_kardex(codigo, fecha_inicio, fecha_fin)
    if not isinstance(r, dict) or r.get("error"):
        raise RuntimeError((r or {}).get("error", "Error al consultar Kardex"))
    datos = _comprobar(r.get("movimientos", []))
    if r.get("total_movimientos") != len(datos):
        raise ValueError("Kardex incompleto")
    filas = [[_fecha(m.get("fecha")), m.get("tipo"), m.get("motivo_movimiento"),
              _fmt(m.get("cantidad")), _fmt(m.get("stock_anterior")),
              _fmt(m.get("stock_nuevo"))] for m in datos]
    return _pdf("kardex", "REPORTE KARDEX - " + str(codigo).upper(),
                [("Fecha",25),("Tipo",16),("Motivo",32),("Cantidad",14),
                 ("Stock anterior",19),("Stock nuevo",19)], filas,
                [f"Periodo: {fecha_inicio} a {fecha_fin}",
                 f"Movimientos: {len(datos)} | Entradas sin ajustes: {_fmt(r.get('cantidad_entradas_sin_ajustes'))}",
                 f"Salidas sin ajustes: {_fmt(r.get('cantidad_salidas_sin_ajustes'))} | Ajustes detectados: {r.get('total_ajustes_detectados',0)}"],
                "kardex_productos", "Los ajustes no se incluyen en los totales ordinarios de entradas y salidas.")


def generar_reporte_abc(tipo, clasificacion="TODAS"):
    tipo = tipo.strip().lower()
    clase = clasificacion.strip().upper()
    tablas = {"monetario":"clasificacion_abc", "movimientos":"clasificacion_abc_movimientos"}
    if tipo not in tablas or clase not in ("A","B","C","TODAS"):
        raise ValueError("Tipo o clasificación inválida")
    filtros = [] if clase == "TODAS" else [("clasificacion", "eq", clase)]
    datos = _comprobar(leer_paginas(tablas[tipo], filtros=filtros, orden="cod_producto"))
    indicador = "valor_inventario" if tipo == "monetario" else "frecuencia_movimientos"
    datos.sort(key=lambda d: numero(d.get(indicador)), reverse=True)
    resumen = {"A":0,"B":0,"C":0}
    for d in datos:
        if d.get("clasificacion") in resumen:
            resumen[d["clasificacion"]] += 1
    filas = [[d.get("cod_producto"), d.get("nombre"), d.get("clasificacion"),
              _fmt(d.get(indicador), tipo == "monetario"),
              _fmt(d.get("porcentaje_participacion")),
              _fmt(d.get("porcentaje_acumulado"))] for d in datos]
    return _pdf("abc_"+tipo, "CLASIFICACIÓN ABC - " + tipo.upper(),
                [("Código",15),("Producto",39),("ABC",10),
                 ("Valor inventario" if tipo == "monetario" else "Frecuencia",20),
                 ("Participación %",17),("Acumulado %",17)], filas,
                [f"Filtro: {clase} | Productos: {len(datos)}",
                 f"Distribución del filtro — A: {resumen['A']} | B: {resumen['B']} | C: {resumen['C']}"],
                tablas[tipo], "Se respetan las clasificaciones calculadas en Supabase; no se recalcula ABC.")



def generar_reporte_kardex_general(fecha_inicio, fecha_fin):
    """Kardex de TODOS los productos: cada movimiento real del periodo, sin muestra."""
    desde, hasta = periodo(fecha_inicio, fecha_fin)
    datos = _comprobar(leer_paginas(
        "kardex_productos",
        filtros=[("fecha", "gte", desde), ("fecha", "lt", hasta)],
        orden="fecha",
    ))
    datos.sort(key=lambda m: (str(m.get("fecha") or ""), int(m.get("id_movimiento") or 0)))
    entradas = salidas = Decimal(0)
    ajustes = 0
    for m in datos:
        tipo = str(m.get("tipo") or "").upper()
        motivo = str(m.get("motivo_movimiento") or "").upper()
        if "AJUSTE" in tipo or "AJUSTE" in motivo:
            ajustes += 1
        elif tipo == "ENTRADA":
            entradas += numero(m.get("cantidad"))
        elif tipo == "SALIDA":
            salidas += numero(m.get("cantidad"))
    filas = [
        [_fecha(m.get("fecha")), m.get("cod_producto"),
         m.get("producto") or m.get("cod_producto"), m.get("tipo"),
         _fmt(m.get("cantidad")), _fmt(m.get("stock_anterior")),
         _fmt(m.get("stock_nuevo")), m.get("documento") or "—"]
        for m in datos
    ]
    return _pdf(
        "kardex_general", "REPORTE KARDEX GENERAL",
        [("Fecha", 20), ("Código", 14), ("Producto", 27), ("Tipo", 13),
         ("Cantidad", 12), ("Anterior", 13), ("Nuevo", 13), ("Documento", 20)],
        filas,
        [f"Periodo: {fecha_inicio} a {fecha_fin}",
         f"Movimientos: {len(datos)} | Productos con actividad: {len({m.get('cod_producto') for m in datos})}",
         f"Entradas (sin ajustes): {_fmt(entradas)} | Salidas (sin ajustes): {_fmt(salidas)} | Ajustes: {ajustes}"],
        "kardex_productos",
        "Las existencias anterior y nueva corresponden a cada movimiento; no equivalen necesariamente al stock actual."
    )

def main():
    print("\nGENERADOR DE REPORTES PDF")
    print("1. Stock bajo\n2. Inventario general\n3. Entradas\n4. Salidas")
    print("5. Kardex\n6. ABC monetario\n7. ABC por movimientos")
    opcion = input("Selecciona una opción: ").strip()
    try:
        if opcion == "1":
            ruta = generar_reporte_stock_bajo()
        elif opcion == "2":
            ruta = generar_reporte_inventario()
        elif opcion in ("3", "4"):
            inicio = input("Fecha inicial (AAAA-MM-DD): ").strip()
            fin = input("Fecha final (AAAA-MM-DD): ").strip()
            ruta = generar_reporte_movimientos("entradas" if opcion == "3" else "salidas", inicio, fin)
        elif opcion == "5":
            codigo = input("Código de producto: ").strip()
            inicio = input("Fecha inicial (AAAA-MM-DD): ").strip()
            fin = input("Fecha final (AAAA-MM-DD): ").strip()
            ruta = generar_reporte_kardex(codigo, inicio, fin)
        elif opcion in ("6", "7"):
            clase = input("Clasificación (A/B/C/TODAS): ").strip()
            ruta = generar_reporte_abc("monetario" if opcion == "6" else "movimientos", clase)
        else:
            print("Opción inválida")
            return
        print("\nPDF GENERADO CORRECTAMENTE\nArchivo:", ruta)
    except Exception as ex:
        print("\nERROR AL GENERAR PDF:", ex)


if __name__ == "__main__":
    main()
