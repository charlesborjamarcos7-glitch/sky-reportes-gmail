import ast
from pathlib import Path
raiz = Path(__file__).resolve().parents[1]
for nombre in ("app.py", "config.py", "herramientas_inventario.py"):
    ast.parse((raiz/nombre).read_text(encoding="utf-8"))
print("Estructura OK")
