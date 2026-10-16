"""Régressions : aucune lecture/écriture dans la base personnelle du dépôt."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import shutil
import subprocess
import os
import socket
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
        backup = sqlite3.connect(backups[0])
        try:
            self.assertEqual(backup.execute('SELECT id FROM scis').fetchone()[0], sid)
        finally:
            backup.close()

    def test_local_server_bind_does_not_require_reverse_dns(self):
        with patch.object(socket, 'getfqdn', side_effect=AssertionError('Unexpected reverse DNS lookup')):
            server = app.DominisHTTPServer(('127.0.0.1', 0), app.Handler)
        try:
            self.assertEqual(server.server_name, '127.0.0.1')
            self.assertGreater(server.server_port, 0)
        finally:
            server.server_close()

    def test_http_logo_and_authentication(self):
        server = app.DominisHTTPServer(('127.0.0.1', 0), app.Handler)
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
        server = app.DominisHTTPServer(('127.0.0.1', 0), app.Handler)
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

    def test_task_reminders_important_and_read_reminders_validation(self):
        with app.connect() as c:
            sci_id = app.save_record(c, {'kind': 'sci', 'data': {'name': 'SCI Rappels', 'opening_date': '2026-01-01'}})
            task_id = app.save_record(c, {
                'kind': 'tasks',
                'sci': sci_id,
                'data': {
                    'name': 'Déclaration 2072',
                    'due': '2026-05-01',
                    'category': 'Fiscalité',
                    'status': 'À faire',
                    'important': True,
                    'reminders_enabled': True,
                    'reminder_count': 2,
                    'reminders': ['2026-04-15', '2026-04-28'],
                    'read_reminders': ['2026-04-15'],
                },
            })
            c.commit()
            st = app.state(c)
            rec = next(r for r in st['records'] if r['id'] == task_id)
            self.assertTrue(rec['important'])
            self.assertTrue(rec['reminders_enabled'])
            self.assertEqual(rec['reminder_count'], 2)
            self.assertEqual(rec['reminders'], ['2026-04-15', '2026-04-28'])
            self.assertEqual(rec['read_reminders'], ['2026-04-15'])

            # Disabled reminders normalize list and count to empty / 0
            cleaned = app.clean('tasks', {
                'name': 'AG ordinaire',
                'due': '2026-06-01',
                'important': False,
                'reminders_enabled': False,
                'reminder_count': 3,
                'reminders': ['2026-05-20'],
            })
            self.assertFalse(cleaned['important'])
            self.assertFalse(cleaned['reminders_enabled'])
            self.assertEqual(cleaned['reminder_count'], 0)
            self.assertEqual(cleaned['reminders'], [])

            # Invalid reminder date is rejected
            with self.assertRaises(ValueError):
                app.clean('tasks', {
                    'name': 'Test invalide',
                    'due': '2026-06-01',
                    'reminders_enabled': True,
                    'reminders': ['not-a-date'],
                })

    def test_table_columns_settings_persistence_and_validation(self):
        server = app.DominisHTTPServer(('127.0.0.1', 0), app.Handler)
        port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            custom_cols = {
                'entries': {'order': ['label', 'amount', 'date', 'sci', 'category'], 'hidden': ['category']},
                'tasks': {'order': ['name', 'due', 'status', 'sci', 'category'], 'hidden': []},
            }
            req = Request(
                f'http://127.0.0.1:{port}/api/settings',
                data=json.dumps({'table_columns': custom_cols}).encode(),
                headers={'Content-Type': 'application/json', 'X-Dominis-Token': app.TOKEN},
            )
            with LOCAL_OPENER.open(req, timeout=5) as r:
                self.assertEqual(r.status, 200)

            with app.connect() as c:
                st = app.settings(c)
                self.assertEqual(st['table_columns'], custom_cols)

            bad_req = Request(
                f'http://127.0.0.1:{port}/api/settings',
                data=json.dumps({'table_columns': ['invalid']}).encode(),
                headers={'Content-Type': 'application/json', 'X-Dominis-Token': app.TOKEN},
            )
            with self.assertRaises(HTTPError) as ctx:
                LOCAL_OPENER.open(bad_req, timeout=5)
            self.assertEqual(ctx.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()

    def test_ui_template_contains_table_gear_bell_and_macos_notifications(self):
        self.assertIn('table-gear-btn', app.HTML)
        self.assertIn('bell-badge', app.HTML)
        self.assertIn('mac-notif-container', app.HTML)
        self.assertIn('f-task-important', app.HTML)
        self.assertIn('f-task-reminders-toggle', app.HTML)
        self.assertIn('f-reminder-count', app.HTML)
        self.assertIn("r.direction==='Recette'?'green':'red'", app.HTML)

    def test_property_photo_round_trip_and_crop_geometry(self):
        tiny_png = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
        with app.connect() as c:
            sci = app.save_record(c, {'kind': 'sci', 'data': {'name': 'SCI Photo', 'opening_date': '2026-01-01'}})
            prop = app.save_record(c, {'kind': 'properties', 'sci': sci, 'data': {
                'name': 'Immeuble', 'address': '1 rue du Port', 'value': 100000,
                'photo': tiny_png, 'photo_x': 42, 'photo_y': 8, 'photo_zoom': 1.75,
            }})
            saved = app.unpack(c.execute('SELECT * FROM records WHERE id=?', (prop,)).fetchone())
            self.assertEqual(saved['photo'], tiny_png)
            self.assertEqual(saved['photo_x'], 42)
            self.assertEqual(saved['photo_y'], 8)
            self.assertEqual(saved['photo_zoom'], 1.75)
            # Un bien sans photo ne conserve aucune donnée de cadrage inventée.
            plain = app.save_record(c, {'kind': 'properties', 'sci': sci, 'data': {
                'name': 'Studio', 'address': '2 rue du Port', 'photo': '', 'photo_x': 12}}) 
            plain_saved = app.unpack(c.execute('SELECT * FROM records WHERE id=?', (plain,)).fetchone())
            self.assertNotIn('photo', plain_saved)
            # Une photo retirée disparaît réellement du bien enregistré.
            app.save_record(c, {'kind': 'properties', 'id': prop, 'sci': sci, 'data': {
                'name': 'Immeuble', 'address': '1 rue du Port', 'photo': ''}})
            updated = app.unpack(c.execute('SELECT * FROM records WHERE id=?', (prop,)).fetchone())
            self.assertNotIn('photo', updated)

    def test_document_folders_persist_and_validate(self):
        server = app.DominisHTTPServer(('127.0.0.1', 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            folders = [{'id': 'f-statuts', 'name': 'Statuts & AG'}, {'id': 'f-perso', 'name': 'Contentieux'}]
            req = Request('http://127.0.0.1:' + str(server.server_port) + '/api/settings',
                          data=json.dumps({'doc_folders': folders}).encode(),
                          headers={'Content-Type': 'application/json', 'X-Dominis-Token': app.TOKEN})
            with LOCAL_OPENER.open(req, timeout=5) as r:
                self.assertEqual(r.status, 200)
            with app.connect() as c:
                self.assertEqual(app.settings(c)['doc_folders'], folders)
            bad = Request('http://127.0.0.1:' + str(server.server_port) + '/api/settings',
                          data=json.dumps({'doc_folders': 'Statuts'}).encode(),
                          headers={'Content-Type': 'application/json', 'X-Dominis-Token': app.TOKEN})
            with self.assertRaises(HTTPError) as ctx:
                LOCAL_OPENER.open(bad, timeout=5)
            self.assertEqual(ctx.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
        with app.connect() as c:
            sci = app.save_record(c, {'kind': 'sci', 'data': {'name': 'SCI Dossiers', 'opening_date': '2026-01-01'}})
            doc = app.save_record(c, {'kind': 'documents', 'sci': sci, 'data': {
                'name': 'Bail signé', 'category': 'Bail', 'folder_id': 'f-immobilier', 'notes': 'Classé.'}})
            stored = app.unpack(c.execute('SELECT * FROM records WHERE id=?', (doc,)).fetchone())
            self.assertEqual(stored['folder_id'], 'f-immobilier')
            # Un dossier inconnu reste accepté (chaîne libre) mais n'altère aucune donnée.
            other = app.save_record(c, {'kind': 'documents', 'sci': sci, 'data': {
                'name': 'Note', 'folder_id': ''}})
            self.assertEqual(app.unpack(c.execute('SELECT * FROM records WHERE id=?', (other,)).fetchone()).get('folder_id', ''), '')

    def test_document_preview_endpoint_and_query_token(self):
        png = (b'\x89PNG\r\n\x1a\n' + b'\x00' * 24)
        with app.connect() as c:
            sci = app.save_record(c, {'kind': 'sci', 'data': {'name': 'SCI Aperçu', 'opening_date': '2026-01-01'}})
            image = app.save_record(c, {'kind': 'documents', 'sci': sci, 'data': {
                'name': 'Façade', 'category': 'Diagnostic', 'filename': 'facade.png', 'mime': 'image/png',
                'blob': app.base64.b64encode(png).decode()}})
            note = app.save_record(c, {'kind': 'documents', 'sci': sci, 'data': {'name': 'Note seule', 'category': 'Autre'}})
            c.commit()
            image_row = c.execute('SELECT * FROM records WHERE id=?', (image,)).fetchone()
            preview = app.build_document_preview(image_row)
            self.assertEqual(preview['preview_type'], 'image')
            self.assertTrue(preview['data_url'].startswith('data:image/png;base64,'))
            self.assertEqual(preview['name'], 'Façade')
            note_row = c.execute('SELECT * FROM records WHERE id=?', (note,)).fetchone()
            self.assertEqual(app.build_document_preview(note_row)['preview_type'], 'note')
            self.assertNotIn('blob', app.build_document_preview(note_row))
            for filename, mime, payload, expected in [
                ('quittance.pdf', 'application/pdf', b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n', 'pdf'),
                ('releve.csv', 'text/csv', b'date;libelle\n01/07/2021;Loyer\n', 'csv'),
                ('bail.txt', 'text/plain', 'Bail notarié'.encode(), 'text'),
                ('archive.zip', 'application/zip', b'PK\x03\x04pas un classeur', 'binary'),
            ]:
                with self.subTest(filename=filename):
                    doc = app.save_record(c, {'kind': 'documents', 'sci': sci, 'data': {
                        'name': filename, 'filename': filename, 'mime': mime,
                        'blob': app.base64.b64encode(payload).decode()}})
                    row = c.execute('SELECT * FROM records WHERE id=?', (doc,)).fetchone()
                    preview = app.build_document_preview(row)
                    self.assertEqual(preview['preview_type'], expected)
                    if expected == 'csv':
                        self.assertEqual(preview['rows'][1][1], 'Loyer')
        server = app.DominisHTTPServer(('127.0.0.1', 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = 'http://127.0.0.1:' + str(server.server_port)
            with patch.object(app, 'PREVIEW', True):
                with LOCAL_OPENER.open(base + '/api/document?id=' + image + '&token=' + app.TOKEN, timeout=5) as r:
                    self.assertEqual(r.read(), png)
                # Le cadre d'aperçu (iframe) ne peut pas porter d'en-tête : le jeton passe en paramètre.
                with LOCAL_OPENER.open(base + '/api/document-preview?id=' + image + '&token=' + app.TOKEN, timeout=5) as r:
                    body = json.load(r)
                self.assertEqual(body['preview_type'], 'image')
                with self.assertRaises(HTTPError) as ctx:
                    LOCAL_OPENER.open(base + '/api/document-preview?id=' + image + '&token=faux', timeout=5)
                self.assertEqual(ctx.exception.code, 403)
                with self.assertRaises(HTTPError) as ctx:
                    LOCAL_OPENER.open(base + '/api/document-preview?id=introuvable&token=' + app.TOKEN, timeout=5)
                self.assertEqual(ctx.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()

    def test_ui_template_contains_photo_preview_folders_and_sidebar_fix(self):
        self.assertIn('prop-crop-box', app.HTML)
        self.assertIn('f-photo-file', app.HTML)
        self.assertIn('photoCropBake', app.HTML)
        self.assertIn('photoPosition', app.HTML)
        self.assertIn('object-position', app.HTML)
        self.assertIn('16:5', app.HTML)
        self.assertIn('1600 × 500 px', app.HTML)
        self.assertIn('doc-folders-bar', app.HTML)
        self.assertIn('folder_id', app.HTML)
        self.assertIn('data-doc-open', app.HTML)
        self.assertIn('documentPreview', app.HTML)
        self.assertIn('doc-preview-stage', app.HTML)
        self.assertIn('docPreviewStageZoom', app.HTML)
        self.assertIn('doc-preview-modal', app.HTML)
        self.assertIn(".empty button{", app.HTML)
        self.assertIn('user-lock', app.HTML)
        self.assertIn('body.collapsed .user-details,body.collapsed .user-lock', app.HTML)
        self.assertIn('Pièce jointe limitée à 500 Mo', app.HTML)
        self.assertIn('Import limité à 500 Mo', app.HTML)
        self.assertIn('MAX_TASK_REMINDERS', Path(APP).read_text(encoding='utf-8'))
        self.assertIn('MAX_TASK_REMINDERS = 365', Path(APP).read_text(encoding='utf-8'))
        self.assertIn('XLSX_MAX_RECORDS = 200000', Path(APP).read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
