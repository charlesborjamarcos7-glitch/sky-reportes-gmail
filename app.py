"""Sky — Streamlit, dos agentes especializados (consultas / PDF y Gmail)."""
import hmac
import logging
import os
import uuid
from datetime import date, datetime, timedelta
import streamlit as st
from config import configurar_secrets_streamlit

st.set_page_config(page_title='Sky — Agente de Reportes', page_icon='📦', layout='wide', initial_sidebar_state='expanded')
configurar_secrets_streamlit(st)
if not os.environ.get('APP_PASSWORD'):
    st.error('Configura APP_PASSWORD en los Secrets de Streamlit Cloud antes de acceder a Sky.')
    st.stop()
if not st.session_state.get('autorizado', False):
    st.title('🔐 Sky — Acceso autorizado')
    with st.form('sky_login'):
        clave = st.text_input('Contraseña', type='password')
        entrar = st.form_submit_button('Entrar', use_container_width=True)
    if entrar:
        if hmac.compare_digest(clave, os.environ['APP_PASSWORD']):
            st.session_state.autorizado = True
            st.rerun()
        else:
            st.error('Contraseña incorrecta.')
    st.stop()

if 'tema' not in st.session_state: st.session_state.tema = 'Negro AMOLED'
if 'envios_hechos' not in st.session_state: st.session_state.envios_hechos = 0
TEMAS = {
    'Negro AMOLED': ('#000000', '#101010', '#f4f4f4', '#202020'),
    'Azul medianoche': ('#111927', '#192335', '#e8eef8', '#243249'),
    'Gris grafito': ('#181a1e', '#22252b', '#f1f3f5', '#30343b'),
    'Blanco minimalista': ('#f7f7f8', '#ffffff', '#202633', '#e9edf3'),
}
fondo, panel, texto, burbuja = TEMAS[st.session_state.tema]
st.markdown(f'''<style>
.stApp{{background:{fondo};color:{texto}}}
[data-testid="stSidebar"]{{background:{panel}}}
[data-testid="stChatMessage"]{{background:{burbuja};border-radius:14px;margin-bottom:7px}}
</style>''', unsafe_allow_html=True)

with st.sidebar:
    st.title('📄 Sky · Reportes')
    st.caption('Agente especializado en PDF y Gmail')
    st.selectbox('🎨 Apariencia', list(TEMAS), key='tema')
    st.divider()
    st.info('Reportes con botones y confirmación antes de enviar correos.')
    if st.button('Cerrar sesión', use_container_width=True):
        for clave in ('autorizado','reporte_actual','confirmacion_correo','envios_hechos'):
            st.session_state.pop(clave, None)
        st.rerun()
st.title("Sky · Agente de Reportes y Gmail")
from agente_reportes import TIPOS, REQUIEREN_FECHAS, REQUIEREN_CODIGO, REQUIEREN_ABC, generar_reporte
from gmail_cloud import validar_destinatario, configurado, enviar_pdf, diagnosticar_error_envio
st.header('📄 Agente 2 — Reportes PDF y Gmail')
st.caption('Selecciona el reporte con botones, genera el PDF y decide si quieres enviarlo.')
etiqueta = st.selectbox('¿Qué reporte quieres generar?', list(TIPOS))
tipo = TIPOS[etiqueta]
with st.form('formulario_reporte'):
    inicio = fin = None
    codigo = ''
    clase = 'TODAS'
    if tipo in REQUIEREN_FECHAS:
        col1, col2 = st.columns(2)
        with col1: inicio = st.date_input('Fecha inicial', value=date.today().replace(day=1))
        with col2: fin = st.date_input('Fecha final', value=date.today())
    if tipo in REQUIEREN_CODIGO:
        codigo = st.text_input('Código del producto (obligatorio)', max_chars=80)
    if tipo in REQUIEREN_ABC:
        clase = st.selectbox('Clasificación ABC', ['TODAS', 'A', 'B', 'C'])
    crear = st.form_submit_button('📄 Generar reporte PDF', type='primary', use_container_width=True)
if crear:
    st.session_state.pop('reporte_actual', None)
    st.session_state.pop('confirmacion_correo', None)
    if not all(os.getenv(x) for x in ('SUPABASE_URL', 'SUPABASE_KEY')):
        st.error('Faltan credenciales de Supabase en Secrets.')
    else:
        with st.spinner('Consultando Supabase y creando documento...'):
            try:
                resultado = generar_reporte(tipo, inicio, fin, codigo, clase)
            except Exception:
                resultado = {'error': 'Fallo al generar el PDF. Revisa los logs del servidor.'}
        if resultado.get('ok'):
            st.session_state.reporte_actual = resultado
            st.success('Reporte generado correctamente.')
        else:
            st.error(resultado.get('error', 'No se pudo generar el documento.'))
documento = st.session_state.get('reporte_actual')
if documento:
    st.divider()
    st.subheader('1. Descargar reporte')
    st.write('Archivo: **' + documento['archivo'] + '**')
    st.download_button('⬇️ Descargar PDF', data=documento['pdf'], file_name=documento['archivo'], mime='application/pdf', use_container_width=True)
    st.divider()
    st.subheader('2. Enviar reporte por Gmail (opcional)')
    if not configurado():
        st.warning('Gmail aún no está configurado. Agrega las credenciales OAuth a Streamlit Secrets. Puedes descargar el PDF mientras tanto.')
    elif st.session_state.envios_hechos >= 3:
        st.warning('Límite de demostración: 3 envíos por sesión. No se permiten más envíos desde esta sesión.')
    else:
        with st.form('form_preparar_correo'):
            destinatario = st.text_input('Correo del destinatario', placeholder='profesor@universidad.edu')
            preparar = st.form_submit_button('✉️ Preparar correo', use_container_width=True)
        if preparar:
            try:
                correo = validar_destinatario(destinatario)
                st.session_state.confirmacion_correo = {
                    'destinatario': correo,
                    'archivo': documento['archivo'],
                    'vence': datetime.now() + timedelta(minutes=10),
                }
            except ValueError as ex:
                st.session_state.pop('confirmacion_correo', None)
                st.error(str(ex))
        confirmacion = st.session_state.get('confirmacion_correo')
        if confirmacion and confirmacion['archivo'] == documento['archivo']:
            st.info('Confirma el envío de **' + confirmacion['archivo'] + '** a **' + confirmacion['destinatario'] + '**. No se ha enviado nada todavía.')
            a, b = st.columns(2)
            with a:
                confirmar = st.button('✅ Confirmar y enviar Gmail', type='primary', use_container_width=True)
            with b:
                cancelar = st.button('Cancelar envío', use_container_width=True)
            if cancelar:
                st.session_state.pop('confirmacion_correo', None)
                st.rerun()
            if confirmar:
                # Quitar autorización ANTES de llamar a Gmail para no duplicar un envío.
                st.session_state.pop('confirmacion_correo', None)
                if datetime.now() > confirmacion['vence']:
                    st.error('La confirmación caducó. Prepara el correo nuevamente.')
                elif st.session_state.envios_hechos >= 3:
                    st.error('Has alcanzado el límite de envíos de la demostración.')
                else:
                    st.session_state.envios_hechos += 1  # Reserva incluso ante resultado incierto.
                    with st.spinner('Solicitando envío a Gmail...'):
                        try:
                            resultado_envio = enviar_pdf(confirmacion['destinatario'], documento['archivo'], documento['pdf'])
                            st.success('Gmail aceptó el correo para ' + resultado_envio['destinatario'] + '. ID: ' + str(resultado_envio['id']))
                        except Exception as exc:
                            logging.getLogger('sky.gmail').error('Fallo Gmail en etapa de envío: %s', type(exc).__name__)
                            st.error(diagnosticar_error_envio(exc))
