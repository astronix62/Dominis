"""Recadre l'affiche originale et intègre son logo PNG à Dominis.py.
Outil de développement uniquement : nécessite Pillow, pas l'application.
"""
import base64
import io
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1] / 'Dominis'
with Image.open(ROOT / 'Dominis.jpg') as poster:
    # Coordonnées en pixels de l'affiche originale (677 × 676).
    logo = poster.crop((128, 128, 532, 532)).resize((256, 256), Image.Resampling.LANCZOS)
    logo = logo.quantize(colors=192)
    stream = io.BytesIO()
    logo.save(stream, format='PNG', optimize=True)
encoded = base64.b64encode(stream.getvalue()).decode('ascii')
lines = '\n'.join('    b"' + encoded[i:i + 96] + '"' for i in range(0, len(encoded), 96))
start, end = '# BEGIN EMBEDDED LOGO', '# END EMBEDDED LOGO'
app = ROOT / 'Dominis.py'
source = app.read_text(encoding='utf-8')
before, rest = source.split(start, 1)
_, after = rest.split(end, 1)
app.write_text(before + start + '\nLOGO_PNG = base64.b64decode(\n' + lines + '\n)\n' + end + after, encoding='utf-8')
