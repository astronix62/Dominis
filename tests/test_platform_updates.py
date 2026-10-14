"""TLS sans magasin système, refus des faux certificats et icône native.
Pillow et trustme sont facultatifs localement et installés dans la matrice CI.
"""
import hashlib
import io
import ssl
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import URLError
from urllib.request import HTTPSHandler, ProxyHandler, build_opener

from test_dominis import app

try:
    from PIL import Image
except ImportError:
    Image = None
try:
    import trustme
except ImportError:
    trustme = None


class TLSUpdateTests(unittest.TestCase):
    def test_missing_system_roots_are_repaired_without_disabling_verification(self):
        # Reproduit Python/macOS sans Install Certificates.command.
        empty = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        self.assertEqual(empty.cert_store_stats()['x509_ca'], 0)
        with patch.object(app.ssl, 'create_default_context', return_value=empty):
            context = app.github_ssl_context()
        self.assertIs(context, empty)
        self.assertGreater(context.cert_store_stats()['x509_ca'], 100)
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertEqual(hashlib.sha256(app.TLS_CA_PEM.encode('ascii')).hexdigest(), app.TLS_CA_SHA256)

    def test_existing_system_roots_are_preserved(self):
        context = ssl.create_default_context()
        original = set(context.get_ca_certs(binary_form=True))
        with patch.object(app.ssl, 'create_default_context', return_value=context):
            app.github_ssl_context()
        self.assertTrue(original.issubset(set(context.get_ca_certs(binary_form=True))))
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_api_and_asset_requests_share_verified_context(self):
        for url, accept in ((app.RELEASES_API, 'application/vnd.github+json'),
                            (app.RELEASE_DOWNLOADS + 'v0.0.2/Dominis.py', 'application/octet-stream')):
            response = Mock(url=url, headers={})
            response.read.side_effect = [b'payload', b'']
            opener = Mock()
            opener.open.return_value.__enter__ = Mock(return_value=response)
            opener.open.return_value.__exit__ = Mock(return_value=False)
            with patch.object(app, 'build_opener', return_value=opener) as factory:
                self.assertEqual(app.github_bytes(url, 100, accept), b'payload')
            redirects, https = factory.call_args.args
            self.assertIsInstance(redirects, app.GitHubRedirects)
            self.assertIsInstance(https, HTTPSHandler)
            self.assertEqual(https._context.verify_mode, ssl.CERT_REQUIRED)
            self.assertTrue(https._context.check_hostname)
            self.assertGreater(https._context.cert_store_stats()['x509_ca'], 100)

    def test_ssl_failure_explained_and_stale_release_cleared(self):
        for wrapped in (False, True):
            error = ssl.SSLCertVerificationError(1, 'unable to get local issuer certificate')
            if wrapped: error = URLError(error)
            with patch.object(app, 'UPDATE_RELEASE', {'version': 'v99.0.0'}), \
                 patch.object(app, 'UPDATE_STATE', {'status': 'checking', 'latest': 'v99.0.0'}), \
                 patch.object(app, 'github_bytes', side_effect=error) as network:
                app.check_updates()
                network.assert_called_once()  # Aucun nouvel essai en HTTPS non vérifié.
                state = app.update_snapshot()
                self.assertEqual(state['status'], 'unavailable')
                self.assertIsNone(state['latest'])
                self.assertIsNone(app.UPDATE_RELEASE)
                self.assertIn('certificat non vérifiable', state['message'])
                self.assertIn('date et l’heure', state['message'])

    @unittest.skipIf(trustme is None, 'Installer requirements-dev.txt pour le test TLS local')
    def test_real_tls_trust_and_hostname_validation(self):
        ca = trustme.CA()
        certificate = ca.issue_cert('localhost')
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        certificate.configure_cert(server_context)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'verified')

            def log_message(self, *args): pass

        server = app.DominisHTTPServer(('127.0.0.1', 0), Handler)
        server.socket = server_context.wrap_socket(server.socket, server_side=True)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            # Magasin système absent : seule la CA embarquée de test est utilisée.
            with patch.object(app.ssl, 'create_default_context', side_effect=lambda: ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)), \
                 patch.object(app, 'TLS_CA_PEM', ca.cert_pem.bytes().decode('ascii')):
                context = app.github_ssl_context()
            client = build_opener(ProxyHandler({}), HTTPSHandler(context=context))
            with client.open(f'https://localhost:{server.server_port}', timeout=3) as response:
                self.assertEqual(response.read(), b'verified')
            # Une bonne CA ne dispense jamais de vérifier le nom du serveur.
            with self.assertRaises(URLError) as wrong_host:
                client.open(f'https://127.0.0.1:{server.server_port}', timeout=3)
            self.assertIsInstance(wrong_host.exception.reason, ssl.SSLCertVerificationError)
            # Le véritable magasin Dominis ne fait pas confiance à cette CA de test.
            client = build_opener(ProxyHandler({}), HTTPSHandler(context=app.github_ssl_context()))
            with self.assertRaises(URLError) as untrusted:
                client.open(f'https://localhost:{server.server_port}', timeout=3)
            self.assertIsInstance(untrusted.exception.reason, ssl.SSLCertVerificationError)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)


class DockIconTests(unittest.TestCase):
    @unittest.skipIf(Image is None, 'Installer requirements-dev.txt pour le contrôle des pixels')
    def test_dock_icon_has_transparent_margins_and_rounded_corners(self):
        image = Image.open(io.BytesIO(app.DOCK_ICON_PNG))
        self.assertEqual(image.size, (512, 512))
        self.assertEqual(image.mode, 'RGBA')
        alpha = image.getchannel('A')
        for point in ((0, 0), (511, 0), (0, 511), (511, 511), (40, 40), (471, 471), (256, 20)):
            self.assertEqual(alpha.getpixel(point), 0)
        for point in ((256, 40), (40, 256), (256, 256), (471, 256)):
            self.assertEqual(alpha.getpixel(point), 255)
        self.assertTrue(any(alpha.histogram()[1:255]))
        self.assertNotEqual(app.DOCK_ICON_PNG, app.LOGO_PNG)

    def test_macos_uses_dock_icon_not_square_web_logo(self):
        application, image, data, process = Mock(), Mock(), Mock(), Mock()
        modules = {'AppKit': SimpleNamespace(NSApplication=application, NSImage=image),
                   'Foundation': SimpleNamespace(NSData=data, NSProcessInfo=process)}
        with patch.object(sys, 'platform', 'darwin'), patch.dict(sys.modules, modules):
            app.set_macos_identity()
        data.dataWithBytes_length_.assert_called_once_with(app.DOCK_ICON_PNG, len(app.DOCK_ICON_PNG))
        application.sharedApplication().setApplicationIconImage_.assert_called_once_with(image.alloc().initWithData_.return_value)

    def test_other_platforms_do_not_import_appkit(self):
        with patch.object(sys, 'platform', 'win32'), patch.dict(sys.modules, {'AppKit': None}):
            app.set_macos_identity()


if __name__ == '__main__': unittest.main()
