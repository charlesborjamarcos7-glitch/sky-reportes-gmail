"""Gmail API OAuth2: solo se invoca tras una confirmación humana en la UI."""
import base64
import os
import re
import logging

logger = logging.getLogger(__name__)
from email.message import EmailMessage

SCOPE = 'https://www.googleapis.com/auth/gmail.send'
EMAIL_RE = re.compile(r'^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$')


def validar_destinatario(correo):
    correo = (correo or '').strip()
    if len(correo) > 254 or not EMAIL_RE.fullmatch(correo):
        raise ValueError('Introduce una dirección de correo válida.')
    autorizados = {x.strip().casefold() for x in os.getenv('GMAIL_ALLOWED_RECIPIENTS', '').split(',') if x.strip()}
    cualquiera = os.getenv('GMAIL_ALLOW_ANY_RECIPIENT', '').strip().lower() == 'true'
    if not autorizados and not cualquiera:
        raise ValueError('Configura GMAIL_ALLOWED_RECIPIENTS en Secrets para permitir el envío.')
    if not cualquiera and correo.casefold() not in autorizados:
        raise ValueError('Ese destinatario no está autorizado. Agrégalo a GMAIL_ALLOWED_RECIPIENTS en Secrets.')
    return correo


def configurado():
    return all(os.getenv(x) for x in ('GMAIL_CLIENT_ID', 'GMAIL_CLIENT_SECRET', 'GMAIL_REFRESH_TOKEN'))


def enviar_pdf(destinatario, archivo, pdf):
    destinatario = validar_destinatario(destinatario)
    if not configurado():
        raise RuntimeError('Faltan credenciales de Gmail en Streamlit Secrets.')
    if not isinstance(pdf, bytes) or not pdf.startswith(b'%PDF-') or len(pdf) > 10 * 1024 * 1024:
        raise ValueError('PDF inválido o demasiado grande.')
    if not re.fullmatch(r'[\w.\-]+\.pdf', archivo):
        raise ValueError('Nombre de archivo PDF inválido.')
    # Cargar dependencias de Gmail solo al enviar; permite usar reportes sin OAuth configurado.
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    creds = Credentials(
        token=None, refresh_token=os.environ['GMAIL_REFRESH_TOKEN'],
        token_uri='https://oauth2.googleapis.com/token',
        client_id=os.environ['GMAIL_CLIENT_ID'],
        client_secret=os.environ['GMAIL_CLIENT_SECRET'],
        scopes=[SCOPE],
    )
    creds.refresh(Request())
    servicio = build('gmail', 'v1', credentials=creds, cache_discovery=False)
    # gmail.send NO autoriza users.getProfile. Gmail identifica al remitente
    # desde la cuenta OAuth, sin consultar el perfil ni ampliar los permisos.
    msg = EmailMessage()
    msg['To'] = destinatario
    msg['Subject'] = 'Sky — Reporte de inventario'
    msg.set_content('Adjunto encontrarás el reporte PDF generado desde Sky — Agente de IA para Almacén.')
    msg.add_attachment(pdf, maintype='application', subtype='pdf', filename=archivo)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode('ascii')
    resultado = servicio.users().messages().send(userId='me', body={'raw': raw}).execute()
    return {'id': resultado.get('id'), 'destinatario': destinatario, 'archivo': archivo}


def diagnosticar_error_envio(exc):
    """Explicación segura para la UI; evita mostrar tokens y datos sensibles."""
    try:
        from google.auth.exceptions import RefreshError
        from googleapiclient.errors import HttpError
    except ImportError:
        RefreshError = ()
        HttpError = ()

    if isinstance(exc, RefreshError):
        return ('Google rechazó la autorización OAuth. Verifica que CLIENT_ID, '
                'CLIENT_SECRET y REFRESH_TOKEN correspondan a la misma autorización. '
                'Si el token caducó o fue revocado, genera uno nuevo con permiso gmail.send.')
    if isinstance(exc, HttpError):
        estado = getattr(getattr(exc, 'resp', None), 'status', None)
        if estado == 401:
            return 'Gmail rechazó las credenciales (HTTP 401). Revisa el token OAuth.'
        if estado == 403:
            return ('Gmail denegó la operación (HTTP 403). Comprueba que la API de Gmail '
                    'esté habilitada y que el token tenga permiso gmail.send.')
        if estado == 429:
            return 'Gmail aplicó un límite de solicitudes (HTTP 429). Espera antes de probar.'
        if estado is not None:
            return f'Gmail respondió con un error HTTP {estado}. Revisa el registro del servidor.'
        return 'Gmail devolvió un error de API. Revisa el registro del servidor.'
    if isinstance(exc, (ValueError, RuntimeError)):
        # Solo mensajes conocidos, no exponer detalles externos.
        texto = str(exc)
        if texto.startswith(('Introduce una dirección', 'Ese destinatario', 'Configura GMAIL_',
                             'Faltan credenciales', 'PDF inválido', 'Nombre de archivo')):
            return texto
    return ('No se pudo confirmar el envío. Consulta los registros de Streamlit. '
            'Antes de reintentar, revisa la carpeta Enviados de Gmail.')
