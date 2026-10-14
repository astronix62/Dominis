"""Recadre l'affiche et intègre le logo et l'icône Dock à Dominis.py.
Outil de développement uniquement : nécessite Pillow, pas l'application.
"""
import base64
import io
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1] / 'Dominis'


def embedded(name, image):
    stream = io.BytesIO()
    image.save(stream, format='PNG', optimize=True)
    encoded = base64.b64encode(stream.getvalue()).decode('ascii')
    lines = '\n'.join('    b"' + encoded[i:i + 96] + '"' for i in range(0, len(encoded), 96))
    return name + ' = base64.b64decode(\n' + lines + '\n)\n'


with Image.open(ROOT / 'Dominis.jpg') as poster:
    # Coordonnées en pixels de l'affiche originale (677 × 676).
    crop = poster.crop((128, 128, 532, 532))
    logo = crop.resize((256, 256), Image.Resampling.LANCZOS).quantize(colors=192)
    # macOS ne masque pas automatiquement une NSImage fournie au Dock.
    # Tuile arrondie de 432 px, marge transparente de 40 px sur un canevas 512 px.
    # Suréchantillonnage du masque pour des contours doux à toutes les tailles.
    scale = 4
    mask = Image.new('L', (432 * scale, 432 * scale), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 432 * scale - 1, 432 * scale - 1),
                                           radius=96 * scale, fill=255)
    mask = mask.resize((432, 432), Image.Resampling.LANCZOS)
    tile = crop.resize((432, 432), Image.Resampling.LANCZOS).convert('RGBA')
    tile.putalpha(mask)
    dock = Image.new('RGBA', (512, 512), (0, 0, 0, 0))
    dock.paste(tile, (40, 40))

start, end = '# BEGIN EMBEDDED LOGO', '# END EMBEDDED LOGO'
app = ROOT / 'Dominis.py'
source = app.read_text(encoding='utf-8')
before, rest = source.split(start, 1)
_, after = rest.split(end, 1)
app.write_text(before + start + '\n' + embedded('LOGO_PNG', logo)
               + embedded('DOCK_ICON_PNG', dock) + end + after, encoding='utf-8')
