"""Agente 2: generación de PDF mediante parámetros validados, sin prompt al LLM."""
from datetime import date
from pathlib import Path
import threading
_LOCK = threading.RLock()

TIPOS = {
    'Inventario general': 'inventario',
    'Productos con stock bajo': 'stock_bajo',
    'Entradas de almacén': 'entradas',
    'Salidas de almacén': 'salidas',
    'Kardex general': 'kardex_general',
    'Kardex de un producto': 'kardex',
    'ABC por valor monetario': 'abc_monetario',
    'ABC por movimientos': 'abc_movimientos',
}
REQUIEREN_FECHAS = {'entradas', 'salidas', 'kardex', 'kardex_general'}
REQUIEREN_CODIGO = {'kardex'}
REQUIEREN_ABC = {'abc_monetario', 'abc_movimientos'}
MAX_BYTES = 10 * 1024 * 1024


def generar_reporte(tipo: str, inicio=None, fin=None, codigo='', clase='TODAS') -> dict:
    if tipo not in TIPOS.values():
        return {'error': 'Tipo de reporte no permitido.'}
    if tipo in REQUIEREN_FECHAS:
        if not isinstance(inicio, date) or not isinstance(fin, date) or inicio > fin:
            return {'error': 'Selecciona un rango de fechas válido (inicio no posterior al fin).'}
    if tipo in REQUIEREN_CODIGO and not codigo.strip():
        return {'error': 'Es obligatorio indicar el código exacto del producto.'}
    if tipo in REQUIEREN_ABC and clase not in ('A','B','C','TODAS'):
        return {'error': 'Clasificación ABC inválida.'}
    from generador_reportes import (
        generar_reporte_inventario, generar_reporte_stock_bajo,
        generar_reporte_movimientos, generar_reporte_kardex,
        generar_reporte_kardex_general, generar_reporte_abc,
    )
    try:
        with _LOCK:
            if tipo == 'inventario':
                archivo_generado = generar_reporte_inventario()
            elif tipo == 'stock_bajo':
                archivo_generado = generar_reporte_stock_bajo()
            elif tipo in ('entradas', 'salidas'):
                archivo_generado = generar_reporte_movimientos(tipo, inicio.isoformat(), fin.isoformat())
            elif tipo == 'kardex':
                archivo_generado = generar_reporte_kardex(codigo.strip().upper(), inicio.isoformat(), fin.isoformat())
            elif tipo == 'kardex_general':
                archivo_generado = generar_reporte_kardex_general(inicio.isoformat(), fin.isoformat())
            else:
                archivo_generado = generar_reporte_abc('monetario' if tipo == 'abc_monetario' else 'movimientos', clase)
    except Exception:
        return {'error': 'No fue posible generar el reporte. Revisa los registros del servidor.'}
    ruta = Path(archivo_generado).resolve()
    from config import REPORTES
    if ruta.parent != REPORTES.resolve() or not ruta.is_file() or ruta.suffix.lower() != '.pdf':
        return {'error': 'Ruta de reporte no autorizada.'}
    if ruta.stat().st_size > MAX_BYTES:
        ruta.unlink(missing_ok=True)
        return {'error': 'El PDF supera 10 MB. Reduce el rango de fechas.'}
    pdf = ruta.read_bytes()
    if not pdf.startswith(b'%PDF-'):
        return {'error': 'El archivo generado no es un PDF válido.'}
    # El PDF queda en memoria de la sesión para descargarlo y enviarlo.
    ruta.unlink(missing_ok=True)
    return {'ok': True, 'archivo': ruta.name, 'pdf': pdf, 'tipo': tipo}
