"""Intègre le magasin Mozilla fourni par certifi (dépendance de développement).
Usage : python -m pip install --upgrade certifi && python tools/embed_certificates.py
Le script distribué reste autonome, sans pip ni téléchargement de certificats.
"""
import base64
import gzip
import hashlib
from importlib.metadata import distribution
from pathlib import Path
import ssl

import certifi

ROOT = Path(__file__).resolve().parents[1]
raw = Path(certifi.where()).read_bytes()
context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
context.load_verify_locations(cadata=raw.decode('ascii'))
assert context.cert_store_stats()['x509_ca'] > 100
encoded = base64.b64encode(gzip.compress(raw, mtime=0)).decode('ascii')
lines = '\n'.join('    b"' + encoded[i:i + 96] + '"' for i in range(0, len(encoded), 96))
start, end = '# BEGIN EMBEDDED CERTIFICATES', '# END EMBEDDED CERTIFICATES'
block = (start + '\n# Mozilla CA bundle via certifi ; licence MPL-2.0, voir THIRD_PARTY_NOTICES.md.\n'
         + '# This Source Code Form is subject to the terms of the Mozilla Public License,\n'
         + '# v. 2.0. If a copy of the MPL was not distributed with this file, You can obtain\n'
         + '# one at https://mozilla.org/MPL/2.0/.\n'
         + f'# Unmodified PEM source: https://pypi.org/project/certifi/{distribution("certifi").version}/#files\n'
         + f'TLS_CA_VERSION = {certifi.__version__!r}\n'
         + f'TLS_CA_SHA256 = {hashlib.sha256(raw).hexdigest()!r}\n'
         + 'TLS_CA_PEM = gzip.decompress(base64.b64decode(\n' + lines + '\n)).decode("ascii")\n' + end)
app = ROOT / 'Dominis' / 'Dominis.py'
source = app.read_text(encoding='utf-8')
before, rest = source.split(start, 1)
_, after = rest.split(end, 1)
app.write_text(before + block + after, encoding='utf-8')
dist = distribution('certifi')
license_path = next(p for p in dist.files if str(p).endswith('/licenses/LICENSE'))
licenses = ROOT / 'licenses'
licenses.mkdir(exist_ok=True)
(licenses / 'certifi-MPL-2.0.txt').write_bytes(dist.locate_file(license_path).read_bytes())
print(f'Certificats certifi {certifi.__version__} intégrés : {context.cert_store_stats()["x509_ca"]} autorités.')
