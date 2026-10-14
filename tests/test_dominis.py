"""Régressions : aucune lecture/écriture dans la base personnelle du dépôt."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import shutil
import subprocess
import os
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.request import Request, ProxyHandler, build_opener
from urllib.error import HTTPError

LOCAL_OPENER = build_opener(ProxyHandler({}))

APP = Path(__file__).resolve().parents[1] / 'Dominis' / 'Dominis.py'
spec = importlib.util.spec_from_file_location('dominis', APP)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)


class DominisTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_patch = patch.object(app, 'DB', Path(self.temp.name) / 'data.db')
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        app.EXIT_READY.clear()
        app.init_db()

    def bundle(self, name='Dominis'):
        return {'application': name, 'version': 1, 'scis': [
            {'id': 'source', 'name': 'SCI de test'}], 'records': []}

    def test_old_and_new_exports_remain_importable(self):
        for name in ('Aurea', 'Dominis'):
            p = {'text': json.dumps(self.bundle(name)), 'mapping': {'source': 'new'}}
            with app.connect() as c:
                app.import_bundle(c, p)
        with app.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM scis').fetchone()[0], 2)

    def test_unknown_export_rejected(self):
        with self.assertRaises(ValueError):
            app.parse_import({'text': json.dumps(self.bundle('Unknown'))})

    def test_new_export_identity_and_round_trip(self):
        with app.connect() as c:
            sid = app.save_record(c, {'kind': 'sci', 'data': {'name': 'SCI témoin'}})
            bundle = app.export_bundle(c, {'scis': [sid], 'kinds': ['properties']})
        self.assertEqual(bundle['application'], 'Dominis')
        self.assertEqual(app.parse_import({'text': json.dumps(bundle)})['scis'][0]['name'], 'SCI témoin')

    def test_sync_exit_preserves_data_and_backs_up(self):
        with app.connect() as c:
            sid = app.save_record(c, {'kind': 'sci', 'data': {'name': 'SCI à conserver'}})
        app.sync_exit()
        with app.connect() as c:
            self.assertEqual(json.loads(c.execute('SELECT data FROM scis WHERE id=?', (sid,)).fetchone()[0])['name'], 'SCI à conserver')
            self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        backups = list(Path(self.temp.name).rglob('dominis-*.db'))
        self.assertEqual(len(backups), 1)
        with sqlite3.connect(backups[0]) as c:
            self.assertEqual(c.execute('SELECT id FROM scis').fetchone()[0], sid)

    def test_http_logo_and_authentication(self):
        server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = 'http://127.0.0.1:' + str(server.server_port)
            for path in ('/logo.png', '/favicon.ico'):
                with LOCAL_OPENER.open(url + path) as r:
                    self.assertEqual(r.headers['Content-Type'], 'image/png')
                    self.assertTrue(r.read().startswith(b'\x89PNG\r\n\x1a\n'))
            with LOCAL_OPENER.open(url) as r:
                html = r.read().decode()
                self.assertIn('Dominis — Gestion patrimoniale', html)
                self.assertNotIn('AURÉA', html)
            with self.assertRaises(HTTPError) as e:
                LOCAL_OPENER.open(url + '/api/state')
            self.assertEqual(e.exception.code, 403)
            with LOCAL_OPENER.open(Request(url + '/api/state', headers={'X-Dominis-Token': app.TOKEN})) as r:
                self.assertEqual(json.load(r)['scis'], [])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def native_close(self, consent, sync_error=None):
        window = Mock()
        window.evaluate_js.side_effect = lambda script, callback: callback(consent)
        with patch.object(app, 'WINDOW', window), patch.object(app, 'sync_exit', side_effect=sync_error) as sync:
            self.assertFalse(app.on_native_closing())
            # Attendre la fin du worker, y compris le chemin d'annulation.
            self.assertTrue(app.NATIVE_CLOSE_LOCK.acquire(timeout=3))
            app.NATIVE_CLOSE_LOCK.release()
        return window, sync

    def test_native_close_saves_before_destroy(self):
        window, sync = self.native_close(True)
        sync.assert_called_once()
        window.destroy.assert_called_once()
        self.assertTrue(app.EXIT_READY.is_set())
        self.assertTrue(app.on_native_closing())

    def test_native_close_cancel_keeps_window_and_server(self):
        window, sync = self.native_close(False)
        sync.assert_not_called()
        window.destroy.assert_not_called()
        self.assertFalse(app.EXIT_READY.is_set())

    def test_native_close_failure_keeps_window(self):
        window, sync = self.native_close(True, ValueError('Sauvegarde impossible'))
        sync.assert_called_once()
        window.destroy.assert_not_called()
        self.assertFalse(app.EXIT_READY.is_set())

    def test_native_close_invalid_result_is_not_consent(self):
        window, sync = self.native_close({'error': 'JavaScript'})
        sync.assert_not_called()
        window.destroy.assert_not_called()

    def test_native_close_does_not_start_two_workers(self):
        app.NATIVE_CLOSE_LOCK.acquire()
        try:
            with patch.object(app, 'WINDOW') as window:
                self.assertFalse(app.on_native_closing())
                window.evaluate_js.assert_not_called()
        finally:
            app.NATIVE_CLOSE_LOCK.release()

    def test_browser_quit_stops_server_after_backup(self):
        server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(app, 'SERVER', server), patch.object(app, 'WINDOW', None), patch.object(app, 'PREVIEW', False):
                req = Request('http://127.0.0.1:' + str(server.server_port) + '/api/quit',
                              data=b'{}', headers={'X-Dominis-Token': app.TOKEN})
                with LOCAL_OPENER.open(req) as r:
                    self.assertTrue(json.load(r)['ok'])
                thread.join(timeout=5)
                self.assertFalse(thread.is_alive())
                self.assertEqual(len(list(Path(self.temp.name).rglob('dominis-*.db'))), 1)
        finally:
            server.shutdown()
            server.server_close()

    def run_launcher(self, result):
        folder = Path(self.temp.name) / 'Dominis avec espaces'
        folder.mkdir()
        launcher = folder / 'Lancer_Dominis.command'
        shutil.copy2(APP.parent / launcher.name, launcher)
        python = folder / '.venv' / 'bin' / 'python'
        python.parent.mkdir(parents=True)
        python.write_text('#!/bin/bash\nif [ "$1" = "-c" ]; then exit 0; fi\nprintf "%s\\n" "$@" > arguments.txt\nexit ' + str(result) + '\n')
        python.chmod(0o755)
        outcome = subprocess.run(['bash', str(launcher)], input='\n', text=True,
                                 capture_output=True, cwd=self.temp.name,
                                 env={**os.environ, 'TERM_PROGRAM': 'test'}, timeout=10)
        self.assertEqual((folder / 'arguments.txt').read_text(encoding="utf-8").splitlines(), ['Dominis.py', '--desktop'])
        return outcome

    @unittest.skipIf(os.name == "nt", "Lanceur bash macOS")
    def test_launcher_normal_exit(self):
        self.assertEqual(self.run_launcher(0).returncode, 0)

    @unittest.skipIf(os.name == "nt", "Lanceur bash macOS")
    def test_launcher_preserves_failure_exit_code(self):
        self.assertEqual(self.run_launcher(7).returncode, 7)

    def test_launcher_uses_renamed_file_and_is_executable(self):
        folder = APP.parent
        for name in ('Lancer_Dominis.command', 'Lancer_Dominis.bat'):
            text = (folder / name).read_text(encoding="utf-8")
            self.assertIn('Dominis.py --desktop', text)
            self.assertNotIn('aurea.py', text)
        if os.name != 'nt':
            self.assertTrue((folder / 'Lancer_Dominis.command').stat().st_mode & 0o111)


if __name__ == '__main__':
    unittest.main()
