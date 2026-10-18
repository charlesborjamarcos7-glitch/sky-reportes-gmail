import os
from datetime import date, timedelta
from decimal import Decimal
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
URL = os.getenv('SUPABASE_URL')
KEY = os.getenv('SUPABASE_KEY')
if not URL or not KEY:
    raise RuntimeError('Configura SUPABASE_URL y SUPABASE_KEY en .env')
supabase = create_client(URL, KEY)

PAGINA = 200
MAX_DETALLES_CONSULTA = 50000


def numero(valor):
    return Decimal(str(valor or 0))


def leer_paginas(tabla, columnas='*', filtros=None, orden=None, max_filas=MAX_DETALLES_CONSULTA):
    """Lectura paginada y filtrada. No utiliza escrituras."""
    datos = []
    while True:
        consulta = supabase.table(tabla).select(columnas)
        for campo, op, valor in (filtros or []):
            if op == 'eq':
                consulta = consulta.eq(campo, valor)
            elif op == 'gte':
                consulta = consulta.gte(campo, valor)
            elif op == 'lt':
                consulta = consulta.lt(campo, valor)
            elif op == 'in':
                consulta = consulta.in_(campo, valor)
            else:
                raise ValueError(f'Filtro no permitido: {op}')
        if orden:
            consulta = consulta.order(orden)
        tamaño = min(PAGINA, max_filas - len(datos))
        if tamaño <= 0:
            raise ValueError('Consulta demasiado extensa; reduce el periodo.')
        lote = consulta.range(len(datos), len(datos) + tamaño - 1).execute().data or []
        datos.extend(lote)
        if len(lote) < tamaño:
            return datos
        if len(datos) >= max_filas:
            raise ValueError('Consulta demasiado extensa; reduce el periodo.')


def periodo(inicio, fin):
    a = date.fromisoformat(inicio)
    b = date.fromisoformat(fin)
    if a > b:
        raise ValueError('La fecha inicial supera la final.')
    if (b - a).days > 366:
        raise ValueError('Consulta un periodo máximo de 367 días.')
    return a.isoformat(), (b + timedelta(days=1)).isoformat()


def consultar_resumen_inventario():
    """Conteo directo de productos distintos (código único) y unidades registradas."""
    try:
        productos = leer_paginas('productos', columnas='cod_producto,stock_actual')
        return {
            'total_productos_distintos': len({p['cod_producto'] for p in productos}),
            'total_unidades_stock': float(sum((numero(p.get('stock_actual')) for p in productos), Decimal(0))),
            'nota': 'Productos distintos significa códigos únicos; unidades es la suma de stock_actual.'
        }
    except Exception as e:
        return {'error': str(e)}



def consultar_valor_inventario():
    """Valorización actual a precio de compra registrado; no es valor de venta."""
    try:
        productos = leer_paginas('productos',
                                columnas='cod_producto,stock_actual,precio_compra')
        total = sum((numero(p.get('stock_actual')) * numero(p.get('precio_compra'))
                     for p in productos), Decimal('0'))
        sin_precio = sum(p.get('precio_compra') is None for p in productos)
        return {
            'total_productos': len(productos),
            'valor_inventario_soles': float(total),
            'productos_sin_precio_compra': sin_precio,
            'metodo': 'Suma de stock_actual × precio_compra para todos los productos.',
            'advertencia': ('Hay productos sin precio de compra; se contabilizan a cero.'
                            if sin_precio else 'Todos los productos tienen precio de compra.'),
        }
    except Exception as exc:
        return {'error': str(exc)}

def consultar_todos_productos():
    """Lista el catálogo completo sin requerir filtro de búsqueda."""
    try:
        columnas = ('cod_producto,nombre,marca,categoria,stock_actual,'
                    'stock_minimo,stock_maximo,precio_compra,precio_venta_menor,'
                     'ubicacion,proveedor,cod_proveedor,estado_stock')
        productos = leer_paginas('productos_inventario', columnas=columnas, orden='cod_producto')
        return {'total_productos': len(productos), 'productos': productos,
                'nota': 'Listado completo leído de Supabase, sin filtros.'}
    except Exception as exc:
        return {'error': str(exc)}


def consultar_kardex_general(fecha_inicio, fecha_fin):
    """Movimientos de todos los productos, con resúmenes precisos y muestra limitada."""
    try:
        inicio, hasta = periodo(fecha_inicio, fecha_fin)
        movimientos = leer_paginas('kardex_productos', filtros=[
            ('fecha', 'gte', inicio), ('fecha', 'lt', hasta)], orden='fecha')
        entradas = salidas = Decimal(0)
        ajustes = 0
        por_producto = {}
        for m in movimientos:
            codigo = str(m.get('cod_producto') or 'SIN_CODIGO')
            info = por_producto.setdefault(codigo, {
                'codigo': codigo, 'producto': m.get('producto') or codigo,
                'movimientos': 0, 'entradas': 0.0, 'salidas': 0.0,
                'ajustes': 0, 'stock_ultimo_movimiento': None
            })
            info['movimientos'] += 1
            info['stock_ultimo_movimiento'] = m.get('stock_nuevo')
            tipo = str(m.get('tipo') or '').upper()
            motivo = str(m.get('motivo_movimiento') or '').upper()
            cantidad = numero(m.get('cantidad'))
            if 'AJUSTE' in tipo or 'AJUSTE' in motivo:
                ajustes += 1
                info['ajustes'] += 1
            elif tipo == 'ENTRADA':
                entradas += cantidad
                info['entradas'] += float(cantidad)
            elif tipo == 'SALIDA':
                salidas += cantidad
                info['salidas'] += float(cantidad)
        detalle = sorted(por_producto.values(), key=lambda x: (-x['movimientos'], x['codigo']))
        return {
            'fecha_inicio': fecha_inicio, 'fecha_fin': fecha_fin,
            'total_movimientos': len(movimientos),
            'total_productos_con_movimientos': len(detalle),
            'cantidad_entradas_sin_ajustes': float(entradas),
            'cantidad_salidas_sin_ajustes': float(salidas),
            'total_ajustes_detectados': ajustes,
            'productos_resumen': detalle[:30],
            'productos_resumen_parcial': len(detalle) > 30,
            'movimientos': movimientos[:15],
            'movimientos_parciales': len(movimientos) > 15,
            'nota': 'Kardex general: el stock final de cada fila representa su último movimiento en el periodo, no necesariamente su stock actual.'
        }
    except Exception as e:
        return {'error': str(e)}


def consultar_producto(texto):
    texto = str(texto).strip()
    if not texto:
        return {'error': 'Indica el nombre o código del producto.'}
    if len(texto) > 100:
        return {'error': 'La búsqueda es demasiado larga.'}
    # Dos búsquedas independientes evitan interpolar filtros OR complejos.
    # Escapar comodines % y _ de ILIKE; se tratan como texto literal.
    patron = '%' + texto.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
    columnas = ('cod_producto,nombre,marca,categoria,stock_actual,'
                'stock_minimo,stock_maximo,precio_compra,precio_venta_menor,'
                     'ubicacion,proveedor,cod_proveedor,estado_stock')
    try:
        por_nombre = supabase.table('productos_inventario').select(columnas).ilike('nombre', patron).limit(50).execute().data or []
        por_codigo = supabase.table('productos_inventario').select(columnas).ilike('cod_producto', patron).limit(50).execute().data or []
        unicos = {str(p['cod_producto']): p for p in por_nombre + por_codigo}
        productos = sorted(unicos.values(), key=lambda p: str(p.get('nombre', '')))
        return {'productos': productos[:30], 'total_recuperados': len(productos),
                'resultados_limitados': len(por_nombre) == 50 or len(por_codigo) == 50 or len(productos) > 30,
                'nota': 'Resultados parciales si se alcanza el límite de búsqueda.'}
    except Exception as e:
        return {'error': str(e)}


def consultar_stock_bajo():
    try:
        datos = leer_paginas('stock_bajo', orden='cod_producto')
        return {'total_productos': len(datos), 'productos': datos}
    except Exception as e:
        return {'error': str(e)}


def consultar_movimientos(tipo, fecha_inicio, fecha_fin):
    tipo = str(tipo).strip().lower()
    if tipo not in ('entradas', 'salidas'):
        return {'error': 'Usa entradas o salidas.'}
    try:
        inicio, hasta = periodo(fecha_inicio, fecha_fin)
        cabeceras = leer_paginas(tipo, filtros=[('fecha', 'gte', inicio), ('fecha', 'lt', hasta)], orden='fecha')
        campo_id = 'id_entrada' if tipo == 'entradas' else 'id_salida'
        monto = 'total_compra' if tipo == 'entradas' else 'total_venta'
        detalle_tabla = 'detalle_entradas' if tipo == 'entradas' else 'detalle_salidas'
        ids = list({c[campo_id] for c in cabeceras})
        detalles = []
        # Traer solamente detalles de movimientos seleccionados, en bloques.
        for i in range(0, len(ids), 75):
            detalles.extend(leer_paginas(detalle_tabla, filtros=[(campo_id, 'in', ids[i:i+75])]))
        lineas = {}
        for d in detalles:
            codigo = str(d.get('cod_producto') or 'SIN_CODIGO')
            lineas[codigo] = lineas.get(codigo, 0) + 1
        return {'tipo': tipo, 'fecha_inicio': fecha_inicio, 'fecha_fin': fecha_fin,
                'total_operaciones': len(cabeceras), 'total_lineas_detalle': len(detalles),
                'total_monetario': float(sum((numero(c.get(monto)) for c in cabeceras), Decimal(0))),
                'productos_por_lineas': sorted(lineas.items(), key=lambda x: (-x[1], x[0]))[:30],
                'movimientos': cabeceras[:20], 'movimientos_limitados': len(cabeceras) > 20,
                'nota': 'Ranking por número de líneas, no por unidades.'}
    except Exception as e:
        return {'error': str(e)}


def consultar_kardex(codigo, fecha_inicio, fecha_fin):
    codigo = str(codigo).strip().upper()
    if not codigo:
        return {'error': 'Indica el código del producto.'}
    try:
        inicio, hasta = periodo(fecha_inicio, fecha_fin)
        movimientos = leer_paginas('kardex_productos', filtros=[('cod_producto', 'eq', codigo),
                                ('fecha', 'gte', inicio), ('fecha', 'lt', hasta)], orden='fecha')
        movimientos.sort(key=lambda m: (str(m.get('fecha') or ''), int(m.get('id_movimiento') or 0)))
        entradas = salidas = Decimal(0)
        ajustes = []
        for m in movimientos:
            tipo = str(m.get('tipo') or '').upper()
            motivo = str(m.get('motivo_movimiento') or '').upper()
            if 'AJUSTE' in motivo or 'AJUSTE' in tipo:
                ajustes.append(m)
            elif tipo == 'ENTRADA':
                entradas += numero(m.get('cantidad'))
            elif tipo == 'SALIDA':
                salidas += numero(m.get('cantidad'))
        return {'codigo': codigo, 'fecha_inicio': fecha_inicio, 'fecha_fin': fecha_fin,
                'total_movimientos': len(movimientos), 'cantidad_entradas_sin_ajustes': float(entradas),
                'cantidad_salidas_sin_ajustes': float(salidas), 'total_ajustes_detectados': len(ajustes),
                'stock_ultimo_movimiento_periodo': movimientos[-1].get('stock_nuevo') if movimientos else None,
                'movimientos': movimientos,
                'nota': 'Los ajustes se excluyen de los totales ordinarios de entrada/salida.'}
    except Exception as e:
        return {'error': str(e)}


def consultar_abc(tipo, clasificacion='TODAS'):
    tipo = str(tipo).lower().strip()
    clase = str(clasificacion).upper().strip()
    tablas = {'monetario': 'clasificacion_abc', 'movimientos': 'clasificacion_abc_movimientos'}
    if tipo not in tablas or clase not in ('A', 'B', 'C', 'TODAS'):
        return {'error': 'Tipo o clasificación inválidos.'}
    try:
        filtros = [] if clase == 'TODAS' else [('clasificacion', 'eq', clase)]
        productos = leer_paginas(tablas[tipo], filtros=filtros, orden='cod_producto')
        resumen = {'A': 0, 'B': 0, 'C': 0}
        for p in productos:
            c = p.get('clasificacion')
            if c in resumen:
                resumen[c] += 1
        indicador = 'valor_inventario' if tipo == 'monetario' else 'frecuencia_movimientos'
        productos.sort(key=lambda p: numero(p.get(indicador)), reverse=True)
        return {'tipo': tipo, 'filtro': clase, 'total_productos': len(productos),
                'resumen': resumen, 'productos': productos[:30],
                'resultados_limitados': len(productos) > 30,
                'nota': 'Resumen corresponde al filtro seleccionado.'}
    except Exception as e:
        return {'error': str(e)}


# FASE 1 SKY: consumo estimado a partir de salidas de Kardex (solo lectura).
# No confundimos movimientos de ajustes con demanda ni frecuencia con unidades.
def _salidas_periodo(fecha_inicio, fecha_fin):
    inicio, hasta = periodo(fecha_inicio, fecha_fin)
    movimientos = leer_paginas(
        'kardex_productos',
        columnas='cod_producto,fecha,tipo,motivo_movimiento,cantidad',
        filtros=[('fecha', 'gte', inicio), ('fecha', 'lt', hasta)],
        orden='fecha',
    )
    totales = {}
    registros = 0
    advertencias = 0
    for m in movimientos:
        tipo = str(m.get('tipo') or '').strip().upper()
        motivo = str(m.get('motivo_movimiento') or '').strip().upper()
        if 'AJUSTE' in tipo or 'AJUSTE' in motivo or tipo != 'SALIDA':
            continue
        codigo = str(m.get('cod_producto') or '').strip()
        if not codigo:
            advertencias += 1
            continue
        try:
            cantidad = numero(m.get('cantidad'))
        except Exception:
            advertencias += 1
            continue
        if cantidad <= 0:
            advertencias += 1
            continue
        totales[codigo] = totales.get(codigo, Decimal(0)) + cantidad
        registros += 1
    return totales, registros, advertencias


def _catalogo_analisis():
    filas = leer_paginas('productos', columnas='cod_producto,nombre,categoria,stock_actual', orden='cod_producto')
    return {str(p['cod_producto']): p for p in filas if p.get('cod_producto')}


def analizar_consumo(fecha_inicio, fecha_fin, modo='mayor', limite=10):
    """Unidades salidas, promedio por día calendario y productos sin salidas.

    'Sin salidas' no significa que el producto jamás haya tenido movimientos,
    ni demuestra obsolescencia o ausencia de ventas futuras.
    """
    modo = str(modo).strip().lower()
    if modo not in ('mayor', 'menor', 'sin_salidas', 'todos'):
        return {'error': 'Modo inválido: mayor, menor, sin_salidas o todos.'}
    if type(limite) is not int or limite < 1 or limite > 100:
        return {'error': 'El límite debe ser un entero entre 1 y 100.'}
    try:
        inicio, _ = periodo(fecha_inicio, fecha_fin)
        dias = (date.fromisoformat(fecha_fin) - date.fromisoformat(inicio)).days + 1
        catalogo = _catalogo_analisis()
        salidas, registros, advertencias = _salidas_periodo(fecha_inicio, fecha_fin)
        # Productos eliminados del catálogo no desaparecen del total de movimientos.
        codigos = set(catalogo) | set(salidas)
        filas = []
        for codigo in codigos:
            p = catalogo.get(codigo, {})
            cantidad = salidas.get(codigo, Decimal(0))
            filas.append({
                'codigo': codigo,
                'producto': p.get('nombre') or '(No está en el catálogo actual)',
                'categoria': p.get('categoria'),
                'stock_actual': p.get('stock_actual'),
                'unidades_salidas': float(cantidad),
                'promedio_diario_unidades': round(float(cantidad / dias), 4),
            })
        if modo == 'sin_salidas':
            filas = [r for r in filas if r['codigo'] in catalogo and r['unidades_salidas'] == 0]
            filas.sort(key=lambda r: r['codigo'])
        elif modo == 'menor':
            # 'Menor consumo' solo entre productos con salidas; para cero usar sin_salidas.
            filas = [r for r in filas if r['unidades_salidas'] > 0]
            filas.sort(key=lambda r: (r['unidades_salidas'], r['codigo']))
        else:
            filas.sort(key=lambda r: (-r['unidades_salidas'], r['codigo']))
        total = sum(salidas.values(), Decimal(0))
        return {
            'fecha_inicio': fecha_inicio, 'fecha_fin': fecha_fin, 'dias_calendario': dias,
            'modo': modo, 'total_productos_catalogo': len(catalogo),
            'productos_con_salidas': len(salidas),
            'total_registros_salida': registros,
            'total_unidades_salidas': float(total),
            'promedio_diario_global': round(float(total / dias), 4),
            'total_productos_en_resultado': len(filas),
            'productos': filas[:limite],
            'resultados_limitados': len(filas) > limite,
            'registros_invalidos_omitidos': advertencias,
            'metodologia': ('Unidades de movimientos tipo SALIDA en kardex_productos, excluyendo '
                            'ajustes; promedio dividido entre días calendario del periodo. '
                            'No es rotación contable (faltan existencias medias históricas).'),
            'advertencia': ('Sin salidas significa que no se registran SALIDAS ordinarias en este intervalo; '
                            'no equivale a inventario obsoleto. Datos sujetos a calidad y cobertura del Kardex.'),
        }
    except Exception as exc:
        return {'error': str(exc)}


def comparar_consumo(inicio_1, fin_1, inicio_2, fin_2, limite=10):
    """Compara periodos por unidades y promedio diario para distinta duración."""
    if type(limite) is not int or not (1 <= limite <= 100):
        return {'error': 'El límite debe ser un entero entre 1 y 100.'}
    try:
        periodo(inicio_1, fin_1)
        periodo(inicio_2, fin_2)
        dias_1 = (date.fromisoformat(fin_1) - date.fromisoformat(inicio_1)).days + 1
        dias_2 = (date.fromisoformat(fin_2) - date.fromisoformat(inicio_2)).days + 1
        catalogo = _catalogo_analisis()
        salidas_1, operaciones_1, errores_1 = _salidas_periodo(inicio_1, fin_1)
        salidas_2, operaciones_2, errores_2 = _salidas_periodo(inicio_2, fin_2)
        t1 = sum(salidas_1.values(), Decimal(0))
        t2 = sum(salidas_2.values(), Decimal(0))
        diario_1, diario_2 = t1 / dias_1, t2 / dias_2
        variacion = float((diario_2 - diario_1) / diario_1 * 100) if diario_1 else None
        productos = []
        for codigo in set(salidas_1) | set(salidas_2):
            a, b = salidas_1.get(codigo, Decimal(0)), salidas_2.get(codigo, Decimal(0))
            productos.append({
                'codigo': codigo,
                'producto': catalogo.get(codigo, {}).get('nombre') or '(No está en el catálogo actual)',
                'unidades_periodo_1': float(a),
                'unidades_periodo_2': float(b),
                'diferencia_unidades': float(b-a),
                'diferencia_promedio_diario': round(float(b/dias_2-a/dias_1), 4),
            })
        productos.sort(key=lambda x: (-abs(x['diferencia_promedio_diario']), x['codigo']))
        return {
            'periodo_1': {'inicio': inicio_1, 'fin': fin_1, 'dias': dias_1, 'unidades': float(t1),
                          'promedio_diario': round(float(diario_1), 4), 'registros_salida': operaciones_1},
            'periodo_2': {'inicio': inicio_2, 'fin': fin_2, 'dias': dias_2, 'unidades': float(t2),
                          'promedio_diario': round(float(diario_2), 4), 'registros_salida': operaciones_2},
            'variacion_porcentual_promedio_diario': round(variacion, 2) if variacion is not None else None,
            'variacion_no_calculable': diario_1 == 0,
            'productos_con_cambios': len(productos),
            'productos': productos[:limite],
            'resultados_limitados': len(productos) > limite,
            'registros_invalidos_omitidos': errores_1 + errores_2,
            'metodologia': ('Comparación de unidades de SALIDA ordinaria. Porcentajes basados en promedio '
                            'diario para comparar periodos de diferente duración. '
                            'Si el primer periodo tuvo cero salidas, no se calcula porcentaje.'),
        }
    except Exception as exc:
        return {'error': str(exc)}



# FASE 2 SKY: diagnostico de sobrestock y productos con inventario sin salidas.
# Se mantiene la modalidad exclusivamente de consulta: no hay escrituras.
def _inventario_para_diagnostico():
    """Extrae campos del catalogo actual, sin depender de vistas ABC."""
    return leer_paginas(
        'productos',
        columnas=('cod_producto,nombre,categoria,stock_actual,stock_maximo,'
                  'precio_compra,fecha_registro'),
        orden='cod_producto',
    )


def _importe_inventario(stock, precio):
    """None indica valorizacion no disponible, NO importe cero."""
    if precio is None:
        return None
    costo = numero(precio)
    if costo < 0:
        return None
    return round(float(stock * costo), 2)


def analizar_sobrestock(limite=10):
    """Stock actual mayor que stock maximo: cuantifica exceso y valor a costo.

    No interpreta stock_maximo inexistente o cero como limite valido.
    """
    if type(limite) is not int or not 1 <= limite <= 100:
        return {'error': 'El límite debe ser un entero entre 1 y 100.'}
    try:
        productos = _inventario_para_diagnostico()
        filas = []
        sin_maximo = sin_precio = datos_invalidos = 0
        exceso_total = Decimal(0)
        capital_exceso = Decimal(0)
        for p in productos:
            try:
                stock = numero(p.get('stock_actual'))
                if stock < 0:
                    datos_invalidos += 1
                    continue
                maximo_raw = p.get('stock_maximo')
                if maximo_raw in (None, ''):
                    sin_maximo += 1
                    continue
                maximo = numero(maximo_raw)
                if maximo <= 0:
                    sin_maximo += 1
                    continue
                exceso = stock - maximo
                if exceso <= 0:
                    continue
                valor = _importe_inventario(exceso, p.get('precio_compra'))
            except (ValueError, TypeError, ArithmeticError):
                datos_invalidos += 1
                continue
            if valor is None:
                sin_precio += 1
            else:
                capital_exceso += Decimal(str(valor))
            exceso_total += exceso
            filas.append({
                'codigo': p.get('cod_producto'), 'producto': p.get('nombre'),
                'categoria': p.get('categoria'), 'stock_actual': float(stock),
                'stock_maximo': float(maximo), 'unidades_exceso': float(exceso),
                'precio_compra': p.get('precio_compra'),
                'valor_exceso_soles': valor,
            })
        filas.sort(key=lambda r: (-r['unidades_exceso'], str(r['codigo'])))
        return {
            'tipo': 'sobrestock', 'total_productos_revisados': len(productos),
            'total_productos_con_sobrestock': len(filas),
            'total_unidades_exceso': float(exceso_total),
            'valor_exceso_con_precio_disponible_soles': round(float(capital_exceso), 2),
            'productos_con_exceso_sin_precio_valido': sin_precio,
            'productos_sin_maximo_valido': sin_maximo,
            'registros_invalidos_omitidos': datos_invalidos,
            'productos': filas[:limite], 'resultados_limitados': len(filas)>limite,
            'metodologia': ('Sobrestock = stock_actual > stock_maximo > 0. '
                            'Exceso = stock_actual - stock_maximo. '
                            'Valor de exceso = unidades excedentes por precio de compra.'),
            'advertencia': ('La suma monetaria excluye productos sin precio de compra valido; '
                            'puede ser parcial. Un stock maximo sin configurar no implica sobrestock.'),
        }
    except Exception as exc:
        return {'error': str(exc)}


def analizar_inventario_sin_salidas(fecha_inicio, fecha_fin, limite=10):
    """Existencias positivas sin SALIDAS ordinarias en periodo indicado.

    Se excluyen productos incorporados despues del inicio cuando su fecha
    de registro es conocida. No equivale a diagnostico de obsolescencia.
    """
    if type(limite) is not int or not 1 <= limite <= 100:
        return {'error': 'El límite debe ser un entero entre 1 y 100.'}
    try:
        inicio, _ = periodo(fecha_inicio, fecha_fin)
        productos = _inventario_para_diagnostico()
        salidas, registros, err_salidas = _salidas_periodo(fecha_inicio, fecha_fin)
        filas = []
        registros_posteriores = sin_fecha_alta = sin_precio = datos_invalidos = 0
        capital = Decimal(0)
        unidades = Decimal(0)
        for p in productos:
            try:
                stock = numero(p.get('stock_actual'))
                if stock <= 0:
                    if stock < 0:
                        datos_invalidos += 1
                    continue
                codigo = str(p.get('cod_producto') or '').strip()
                if not codigo:
                    datos_invalidos += 1
                    continue
                if salidas.get(codigo, Decimal(0)) > 0:
                    continue
                alta_raw = p.get('fecha_registro')
                if alta_raw:
                    alta = date.fromisoformat(str(alta_raw)[:10])
                    if alta > date.fromisoformat(inicio):
                        registros_posteriores += 1
                        continue
                else:
                    sin_fecha_alta += 1
                valor = _importe_inventario(stock, p.get('precio_compra'))
            except (ValueError, TypeError, ArithmeticError):
                datos_invalidos += 1
                continue
            if valor is None:
                sin_precio += 1
            else:
                capital += Decimal(str(valor))
            unidades += stock
            filas.append({
                'codigo': codigo, 'producto': p.get('nombre'),
                'categoria': p.get('categoria'), 'stock_actual': float(stock),
                'unidades_salidas_periodo': 0,
                'precio_compra': p.get('precio_compra'),
                'valor_stock_soles': valor,
                'fecha_registro': p.get('fecha_registro'),
            })
        filas.sort(key=lambda r: (-(r['valor_stock_soles'] if r['valor_stock_soles'] is not None else -1), str(r['codigo'])))
        return {
            'tipo': 'sin_salidas_con_stock', 'fecha_inicio': fecha_inicio,
            'fecha_fin': fecha_fin, 'total_productos_revisados': len(productos),
            'total_productos_sin_salidas_con_stock': len(filas),
            'total_unidades_en_stock': float(unidades),
            'valor_stock_con_precio_disponible_soles': round(float(capital), 2),
            'productos_sin_precio_valido': sin_precio,
            'productos_sin_fecha_registro': sin_fecha_alta,
            'productos_registrados_despues_del_inicio_excluidos': registros_posteriores,
            'registros_salida_ordinaria_en_periodo': registros,
            'registros_salida_invalidos_omitidos': err_salidas,
            'registros_invalidos_omitidos': datos_invalidos,
            'productos': filas[:limite], 'resultados_limitados': len(filas)>limite,
            'metodologia': ('Productos del catalogo actual con stock_actual > 0 sin SALIDA '
                            'ordinaria registrada entre ambas fechas inclusivas; '
                            'se excluyen ajustes y productos con alta posterior al inicio conocido.'),
            'advertencia': ('Sin salidas en el periodo NO significa obsoleto ni permite '
                            'afirmar que jamas tuvo ventas. El valor es capital en stock '
                            'sin salidas recientes, no una perdida ni un sobrestock. '
                            'Depende de la integridad del historial de Kardex.'),
        }
    except Exception as exc:
        return {'error': str(exc)}

# FASE 3 SKY: Reposición sugerida; siempre solo lectura.
# Las reglas se basan en stock min/max y, cuando se especifica, consumo histórico.
from decimal import ROUND_CEILING


def recomendar_reposicion(metodo='minmax', dias_entrega=None, dias_historial=90, limite=10):
    """Propone compras sin ejecutarlas. No presume plazos reales de proveedores.

    minmax: stock por debajo de mínimo -> sugerir hasta máximo.
    demanda: punto de pedido = consumo diario * plazo + stock mínimo (reserva
    configurada); compra hasta maximo, si basta para cubrir punto de pedido.
    """
    if metodo not in ('minmax', 'demanda'):
        return {'error': 'Método inválido; usa minmax o demanda.'}
    if type(limite) is not int or not 1 <= limite <= 100:
        return {'error': 'El límite debe ser un entero entre 1 y 100.'}
    if type(dias_historial) is not int or not 7 <= dias_historial <= 365:
        return {'error': 'Los días de historial deben estar entre 7 y 365.'}
    if metodo == 'demanda' and (type(dias_entrega) is not int or not 1 <= dias_entrega <= 365):
        return {'error': ('Para calcular reposición basada en demanda, indica dias_entrega '
                          'como entero de 1 a 365. No se inventará el plazo del proveedor.')}
    if dias_entrega is not None and (type(dias_entrega) is not int or not 1 <= dias_entrega <= 365):
        return {'error': 'Los días de entrega deben estar entre 1 y 365.'}
    try:
        hoy = date.today()
        inicio = hoy - timedelta(days=dias_historial - 1)
        salidas, registros, omitidos = _salidas_periodo(inicio.isoformat(), hoy.isoformat())
        productos = leer_paginas('productos', columnas=(
            'cod_producto,nombre,categoria,stock_actual,stock_minimo,stock_maximo,precio_compra'),
            orden='cod_producto')
        resultados = []
        incompletos = []
        invalidos = 0
        sin_consumo = 0
        total_unidades = Decimal(0)
        total_costo = Decimal(0)
        costo_incompleto = 0
        for p in productos:
            codigo = str(p.get('cod_producto') or '').strip()
            if not codigo:
                invalidos += 1
                continue
            try:
                if p.get('stock_actual') is None or p.get('stock_minimo') is None or p.get('stock_maximo') is None:
                    incompletos.append(codigo)
                    continue
                stock = numero(p['stock_actual'])
                minimo = numero(p['stock_minimo'])
                maximo = numero(p['stock_maximo'])
                if stock < 0 or minimo < 0 or maximo <= 0 or minimo > maximo:
                    invalidos += 1
                    continue
                consumo = salidas.get(codigo, Decimal(0))
                diario = consumo / Decimal(dias_historial)
                if metodo == 'demanda':
                    if consumo == 0:
                        sin_consumo += 1
                        # Sin demanda observada, no se inventa un punto de pedido;
                        # se permite solo advertir de stock bajo en el modo minmax.
                        continue
                    punto = (diario * Decimal(dias_entrega) + minimo).to_integral_value(rounding=ROUND_CEILING)
                    umbral = punto
                else:
                    punto = None
                    umbral = minimo
                if stock >= umbral:
                    continue
                objetivo = maximo
                cantidad = (objetivo - stock).to_integral_value(rounding=ROUND_CEILING)
                if cantidad <= 0:
                    continue
                costo = _importe_inventario(cantidad, p.get('precio_compra'))
                if costo is None:
                    costo_incompleto += 1
                else:
                    total_costo += Decimal(str(costo))
                total_unidades += cantidad
                deficit_cobertura = bool(metodo == 'demanda' and maximo < punto)
                resultados.append({
                    'codigo': codigo, 'producto': p.get('nombre'), 'categoria': p.get('categoria'),
                    'stock_actual': float(stock), 'stock_minimo': float(minimo),
                    'stock_maximo': float(maximo), 'unidades_salidas_historial': float(consumo),
                    'consumo_promedio_diario': round(float(diario), 4),
                    'dias_entrega_supuestos_por_usuario': dias_entrega if metodo == 'demanda' else None,
                    'punto_pedido_estimado': float(punto) if punto is not None else None,
                    'cantidad_sugerida': float(cantidad), 'costo_estimado_soles': costo,
                    'prioridad': ('CRITICA' if stock == 0 else 'ALTA' if stock < minimo else 'MEDIA'),
                    'maximo_no_cubre_punto_estimado': deficit_cobertura,
                })
            except (ValueError, TypeError, ArithmeticError):
                invalidos += 1
        prioridad = {'CRITICA': 0, 'ALTA': 1, 'MEDIA': 2}
        resultados.sort(key=lambda x: (prioridad[x['prioridad']],
                                      -x['cantidad_sugerida'], str(x['codigo'])))
        return {
            'metodo': metodo, 'inicio_historial': inicio.isoformat(), 'fin_historial': hoy.isoformat(),
            'dias_historial': dias_historial, 'dias_entrega': dias_entrega if metodo == 'demanda' else None,
            'productos_evaluados': len(productos), 'productos_con_reposicion_sugerida': len(resultados),
            'unidades_totales_sugeridas': float(total_unidades),
            'costo_estimado_parcial_soles': round(float(total_costo), 2),
            'productos_sugeridos_sin_precio': costo_incompleto,
            'productos_sin_parametros': len(incompletos),
            'productos_sin_consumo_observado_excluidos': sin_consumo,
            'registros_invalidos_omitidos': invalidos + omitidos,
            'registros_salidas_observados': registros,
            'productos': resultados[:limite], 'resultados_limitados': len(resultados) > limite,
            'metodologia': ('minmax: si stock_actual < stock_minimo, sugerir máximo - actual. '
                            'demanda: si stock_actual < techo(consumo diario * días_entrega + mínimo), '
                            'sugerir máximo - actual. El mínimo se usa como reserva configurada.'),
            'advertencia': ('Son propuestas de compra y no órdenes. No descuentan pedidos en tránsito; '
                            'no se conoce la demanda no atendida por quiebres de stock. '
                            'El plazo de entrega no proviene del proveedor y debe darlo el usuario '
                            'para el método demanda. El costo puede ser parcial. Verifique '
                            'parametrización y unidades antes de comprar.'),
        }
    except Exception as exc:
        return {'error': str(exc)}



# FASE 4 SKY: auditoría preventiva de calidad, exclusivamente de lectura.
# Los hallazgos son señales de revisión y NO modifican registros.
def auditar_calidad_inventario(fecha_inicio=None, fecha_fin=None, limite=20):
    """Revisa parámetros de productos y, opcionalmente, coherencia de movimientos.

    Fechas: ambas o ninguna. Si se indican, revisa Kardex en el intervalo inclusivo.
    No interpreta la ausencia de un movimiento como error de inventario.
    """
    if type(limite) is not int or not 1 <= limite <= 100:
        return {'error': 'El límite debe ser un entero entre 1 y 100.'}
    if (fecha_inicio is None) != (fecha_fin is None):
        return {'error': 'Para auditar movimientos indica fecha_inicio y fecha_fin juntos.'}
    if fecha_inicio is not None:
        try:
            inicio, hasta = periodo(fecha_inicio, fecha_fin)
        except (ValueError, TypeError) as exc:
            return {'error': f'Periodo inválido: {exc}'}
    else:
        inicio = hasta = None

    from collections import Counter
    conteos = Counter()
    problemas = []
    afectados = set()
    def registrar(nivel, codigo, elemento, detalle, referencia='productos'):
        conteos[nivel] += 1
        afectados.add((referencia, codigo))
        problemas.append({'nivel': nivel, 'codigo': codigo, 'elemento': elemento,
                          'detalle': detalle, 'fuente': referencia})

    def decimal_validado(valor):
        d = Decimal(str(valor))
        if not d.is_finite():
            raise ValueError('No es un número finito')
        return d

    try:
        productos = leer_paginas('productos', columnas=(
            'cod_producto,nombre,stock_actual,stock_minimo,stock_maximo,'
            'precio_compra,precio_venta_menor,precio_venta_mayor,'
            'factor_conversion,cod_proveedor,ubicacion'), orden='cod_producto')
        vistos = set()
        for fila in productos:
            codigo = str(fila.get('cod_producto') or '').strip()
            if not codigo:
                registrar('CRITICO', '(sin código)', 'cod_producto', 'Código ausente')
                continue
            if codigo in vistos:
                registrar('CRITICO', codigo, 'cod_producto', 'Código repetido en los resultados')
            vistos.add(codigo)
            if not str(fila.get('nombre') or '').strip():
                registrar('ALTO', codigo, 'nombre', 'Nombre de producto vacío')
            valores = {}
            campos = ('stock_actual', 'stock_minimo', 'stock_maximo', 'precio_compra',
                      'precio_venta_menor', 'precio_venta_mayor', 'factor_conversion')
            for campo in campos:
                raw = fila.get(campo)
                if raw is None or str(raw).strip() == '':
                    if campo in ('stock_actual', 'stock_minimo', 'stock_maximo', 'precio_compra'):
                        registrar('ALTO', codigo, campo, 'Campo requerido no registrado')
                    continue
                try:
                    val = decimal_validado(raw)
                except (ValueError, TypeError, ArithmeticError):
                    registrar('ALTO', codigo, campo, 'Valor numérico inválido')
                    continue
                valores[campo] = val
                if campo == 'factor_conversion' and val <= 0:
                    registrar('ALTO', codigo, campo, 'El factor de conversión debe ser mayor que cero')
                elif campo == 'stock_actual' and val < 0:
                    registrar('CRITICO', codigo, campo, 'Existencia negativa')
                elif campo != 'factor_conversion' and campo != 'stock_actual' and val < 0:
                    registrar('ALTO', codigo, campo, 'Valor negativo')
            minimo, maximo = valores.get('stock_minimo'), valores.get('stock_maximo')
            if minimo is not None and maximo is not None and minimo > maximo:
                registrar('ALTO', codigo, 'stock_minimo/stock_maximo',
                          'Stock mínimo supera el máximo')
            if maximo is not None and maximo == 0:
                registrar('MEDIO', codigo, 'stock_maximo', 'Máximo cero: revisar parametrización')
            if not str(fila.get('cod_proveedor') or '').strip():
                registrar('MEDIO', codigo, 'cod_proveedor', 'Proveedor no asociado')
            if not str(fila.get('ubicacion') or '').strip():
                registrar('MEDIO', codigo, 'ubicacion', 'Ubicación no registrada')

        movimientos_revisados = 0
        ajustes_omitidos = 0
        if inicio is not None:
            movimientos = leer_paginas('kardex_productos', columnas=(
                'id_movimiento,fecha,cod_producto,tipo,motivo_movimiento,cantidad,'
                'stock_anterior,stock_nuevo'),
                filtros=[('fecha', 'gte', inicio), ('fecha', 'lt', hasta)], orden='fecha')
            movimientos.sort(key=lambda m: (
                str(m.get('fecha') or ''), str(m.get('id_movimiento') or '')))
            movimientos_revisados = len(movimientos)
            anterior_por_codigo = {}
            for m in movimientos:
                codigo = str(m.get('cod_producto') or '').strip()
                mid = str(m.get('id_movimiento') or '(sin id)')
                tipo = str(m.get('tipo') or '').upper().strip()
                motivo = str(m.get('motivo_movimiento') or '').upper().strip()
                if not codigo:
                    registrar('ALTO', '(sin código)', 'cod_producto',
                              f'Movimiento {mid} sin código de producto', 'kardex_productos')
                    continue
                if codigo not in vistos:
                    registrar('ALTO', codigo, 'cod_producto',
                              f'Movimiento {mid} de producto ausente del catálogo actual', 'kardex_productos')
                valores = []
                for campo in ('cantidad', 'stock_anterior', 'stock_nuevo'):
                    raw = m.get(campo)
                    try:
                        if raw is None or str(raw).strip() == '':
                            raise ValueError('vacío')
                        valores.append(decimal_validado(raw))
                    except (ValueError, TypeError, ArithmeticError):
                        registrar('ALTO', codigo, campo,
                                  f'Valor ausente o inválido en movimiento {mid}', 'kardex_productos')
                        valores.append(None)
                cantidad, ant, nuevo = valores
                if 'AJUSTE' in tipo or 'AJUSTE' in motivo:
                    ajustes_omitidos += 1
                elif tipo in ('ENTRADA', 'SALIDA') and all(v is not None for v in valores):
                    if cantidad <= 0:
                        registrar('ALTO', codigo, 'cantidad',
                                  f'Cantidad no positiva en movimiento {mid}', 'kardex_productos')
                    else:
                        esperado = ant + cantidad if tipo == 'ENTRADA' else ant - cantidad
                        if esperado != nuevo:
                            registrar('CRITICO', codigo, 'stock_anterior/stock_nuevo',
                                      f'Movimiento {mid}: stock nuevo no concuerda con {tipo.lower()} y cantidad',
                                      'kardex_productos')
                elif tipo not in ('ENTRADA', 'SALIDA'):
                    registrar('MEDIO', codigo, 'tipo',
                              f'Tipo de movimiento no reconocido en registro {mid}', 'kardex_productos')
                # Comprobar continuidad solo en pares de movimientos consecutivos observados.
                # Puede haber correcciones no representadas en el Kardex: se trata como alerta.
                previo = anterior_por_codigo.get(codigo)
                if previo is not None and ant is not None and previo != ant:
                    registrar('MEDIO', codigo, 'continuidad',
                              f'Saldo anterior del movimiento {mid} no coincide con saldo nuevo previo observado',
                              'kardex_productos')
                anterior_por_codigo[codigo] = nuevo

        orden = {'CRITICO': 0, 'ALTO': 1, 'MEDIO': 2}
        problemas.sort(key=lambda x: (orden[x['nivel']], x['codigo'], x['elemento'], x['detalle']))
        return {
            'tipo': 'auditoria_calidad', 'solo_lectura': True,
            'productos_revisados': len(productos),
            'movimientos_revisados': movimientos_revisados,
            'ajustes_identificados': ajustes_omitidos,
            'periodo_movimientos': {'inicio': fecha_inicio, 'fin': fecha_fin} if inicio else None,
            'total_hallazgos': len(problemas),
            'productos_o_registros_afectados': len(afectados),
            'hallazgos_por_nivel': {k: conteos[k] for k in ('CRITICO', 'ALTO', 'MEDIO')},
            'hallazgos': problemas[:limite],
            'resultados_limitados': len(problemas) > limite,
            'metodologia': ('Revisión de integridad y coherencia interna de campos del catálogo. '
                            'Si hay fechas, comprueba cantidades y saldos de entradas/salidas ordinarias del Kardex.'),
            'advertencia': ('Los hallazgos son alertas de revisión, no pruebas definitivas de pérdidas, fraude '
                            'o errores de stock físico. No se ejecutaron cambios. '
                            'No se detectan duplicados fuera de las filas disponibles ni salidas omitidas '
                            'en el historial. La continuidad puede verse afectada por ajustes no representados.'),
        }
    except Exception as exc:
        return {'error': f'No se completó la auditoría de calidad: {exc}'}

if __name__ == '__main__':
    print('\nHERRAMIENTAS DE INVENTARIO')
    print('1. Buscar producto\n2. Consultar stock bajo\n3. Consultar entradas\n4. Consultar salidas\n5. Consultar Kardex\n6. ABC monetario\n7. ABC por movimientos')
    opcion = input('Selecciona una opción: ').strip()
    if opcion == '1':
        resultado = consultar_producto(input('Nombre o código: '))
    elif opcion == '2':
        resultado = consultar_stock_bajo()
    elif opcion in ('3', '4'):
        a = input('Fecha inicial (AAAA-MM-DD): ').strip()
        b = input('Fecha final (AAAA-MM-DD): ').strip()
        resultado = consultar_movimientos('entradas' if opcion == '3' else 'salidas', a, b)
    elif opcion == '5':
        codigo = input('Código: ')
        a = input('Fecha inicial (AAAA-MM-DD): ').strip()
        b = input('Fecha final (AAAA-MM-DD): ').strip()
        resultado = consultar_kardex(codigo, a, b)
    elif opcion in ('6', '7'):
        clase = input('Clasificación (A/B/C/TODAS): ').strip()
        resultado = consultar_abc('monetario' if opcion == '6' else 'movimientos', clase)
    else:
        resultado = {'error': 'Opción inválida.'}
    if 'error' in resultado:
        print('ERROR:', resultado['error'])
    else:
        for k, v in resultado.items():
            if k in ('productos', 'movimientos'):
                print(f'{k}: {len(v)} registros mostrados')
                for fila in v[:10]:
                    print('  ', fila)
            else:
                print(f'{k}: {v}')
