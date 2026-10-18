"""Configuración del despliegue (nunca contiene valores secretos)."""
import os
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()
BASE = Path(__file__).resolve().parent
REPORTES = BASE / 'reportes'
REPORTES.mkdir(exist_ok=True)
os.environ['REPORTES_DIR'] = str(REPORTES)

def configurar_secrets_streamlit(st):
    """Publica secretos de Streamlit solo en el entorno del proceso servidor."""
    for k in ('GROQ_API_KEY', 'LLM_MODEL', 'SUPABASE_URL', 'SUPABASE_KEY', 'APP_PASSWORD', 'GMAIL_CLIENT_ID', 'GMAIL_CLIENT_SECRET', 'GMAIL_REFRESH_TOKEN', 'GMAIL_ALLOWED_RECIPIENTS', 'GMAIL_ALLOW_ANY_RECIPIENT'):
        try:
            v = st.secrets.get(k)
        except (FileNotFoundError, KeyError, AttributeError):
            v = None
        if v:
            os.environ[k] = str(v)
    return bool(os.getenv('APP_PASSWORD'))
