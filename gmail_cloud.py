"""Gmail API OAuth2: solo se invoca tras una confirmación humana en la UI."""
import base64
import os
import re
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
    perfil = servicio.users().getProfile(userId='me').execute()
    remitente = perfil.get('emailAddress')
    msg = EmailMessage()
    msg['From'] = remitente
    msg['To'] = destinatario
    msg['Subject'] = 'Sky — Reporte de inventario'
    msg.set_content('Adjunto encontrarás el reporte PDF generado desde Sky — Agente de IA para Almacén.')
    msg.add_attachment(pdf, maintype='application', subtype='pdf', filename=archivo)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode('ascii')
    resultado = servicio.users().messages().send(userId='me', body={'raw': raw}).execute()
    return {'id': resultado.get('id'), 'destinatario': destinatario, 'archivo': archivo}
