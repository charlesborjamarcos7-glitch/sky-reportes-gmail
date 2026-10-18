# Sky · Agente 2 — Reportes PDF y Gmail

**PROYECTO AUTÓNOMO**. Sube el CONTENIDO de esta carpeta a su propio repositorio GitHub `sky-reportes-gmail`, conservando `app.py` en la raíz.

- Streamlit Community Cloud: `app.py`; Python 3.11 recomendado.
- Secrets: `APP_PASSWORD`, `SUPABASE_URL`, `SUPABASE_KEY`, `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`, `GMAIL_ALLOWED_RECIPIENTS`.
- Genera PDF con botones; fechas para entradas, salidas y Kardex; código para Kardex individual, clasificación para ABC.
- Descargar PDF o preparar correo autorizado y pulsar CONFIRMAR para enviar; el servicio no envía sin confirmación.
- `GMAIL_ALLOW_ANY_RECIPIENT = "false"` recomendado (valor predeterminado): permite solo emails enumerados.
- El límite de tres correos es POR SESIÓN, no global. No lo expongas sin una contraseña privada y usuarios de confianza.
- Los archivos PDF se almacenan temporalmente y se borran del disco después de generarse.
- NO subas `.env`, `credentials.json`, `token.json` ni claves OAuth; configúralos exclusivamente en los Secrets de Streamlit.

El mismo proyecto Supabase puede alimentar ambos agentes. Si Gmail devuelve `invalid_grant`, revisa la validez del refresh token y el OAuth de Google.
