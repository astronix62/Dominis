"""Installation forcée d'une Release : identique, plus ancienne, plus récente.

Le parcours forcé est exercé pour de vrai : un processus Dominis démarre, reçoit
`{"force": true}` sur `/api/update/check`, expose la relation de version, puis
`{"force": true}` sur `/api/update/install` remplace réellement `Dominis.py` et
redémarre. Seule la fonction réseau `github_bytes` est simulée, comme dans
`tests/test_updates.py`.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import Request

from test_dominis import app, APP, LOCAL_OPENER


def source(version):
    return (f"APP_VERSION = '{version}'\nUPDATE_PROTOCOL = 1\nDB_SCHEMA_VERSION = 1\n"
            "MIN_PYTHON = (3, 10)\nprint('ok')\n").encode()


def release(raw, version):
    return {'tag_name': version, 'draft': False, 'prerelease': False, 'assets': [
        {'name': 'Dominis.py', 'state': 'uploaded', 'size': len(raw),
         'browser_download_url': app.RELEASE_DOWNLOADS + version + '/Dominis.py',
         'digest': 'sha256:' + hashlib.sha256(raw).hexdigest()}]}


class ForcedCheckTests(unittest.TestCase):
    """Sémantique de la vérification forcée, sans processus externe."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name, value in [('DB', Path(self.tmp.name) / 'data.db'), ('PREVIEW', False),
                            ('UPDATE_RELEASE', None), ('PENDING_UPDATE', None),
                            ('INSTANCE_GUARD', None), ('START_ARGS', [])]:
            p = patch.object(app, name, value); p.start(); self.addCleanup(p.stop)
        state = {'status': 'idle', 'latest': None, 'checked_at': None, 'message': '',
                 'dismissed': False, 'relation': None, 'forced': False}
        p = patch.object(app, 'UPDATE_STATE', state); p.start(); self.addCleanup(p.stop)
        app.UPDATE_BUSY.clear(); app.UPDATE_FORCE_REQUESTED.clear(); app.EXIT_READY.clear()
        self.addCleanup(app.UPDATE_BUSY.clear)
        self.addCleanup(app.UPDATE_FORCE_REQUESTED.clear)
        app.init_db()

    def check(self, tag, force=False):
        app.UPDATE_RELEASE = None
        app.UPDATE_STATE.update(status='idle', latest=None, relation=None, forced=False)
        app.UPDATE_BUSY.clear()
        data = release(source(tag), tag)
        with patch.object(app, 'github_bytes', return_value=json.dumps(data).encode()):
            app.check_updates(force=force)
        return app.update_snapshot()

    def test_relation_is_reported_for_every_release(self):
        cases = [('v99.0.0', 'newer'), (app.APP_VERSION, 'same'), ('v0.0.1', 'older')]
        for tag, relation in cases:
            with self.subTest(tag=tag):
                self.assertEqual(app.version_relation(tag), relation)

    def test_ordinary_check_never_stages_an_equal_or_older_release(self):
        for tag in (app.APP_VERSION, 'v0.0.1'):
            with self.subTest(tag=tag):
                snap = self.check(tag)
                self.assertEqual(snap['status'], 'current')
                self.assertFalse(snap['staged'])
                self.assertFalse(snap['forced'])

    def test_forced_check_stages_every_release_and_reports_the_relation(self):
        for tag, relation in [('v99.0.0', 'newer'), (app.APP_VERSION, 'same'), ('v0.0.1', 'older')]:
            with self.subTest(tag=tag):
                snap = self.check(tag, force=True)
                self.assertTrue(snap['staged'], snap)
                self.assertTrue(snap['forced'])
                self.assertEqual(snap['relation'], relation)
                self.assertEqual(snap['latest'], tag)
                # Une version identique ou plus ancienne ne devient pas une
                # proposition spontanée : l'état reste « current ».
                expected = 'available' if relation == 'newer' else 'current'
                self.assertEqual(snap['status'], expected)

    def test_ordinary_install_refuses_an_equal_or_older_release(self):
        for tag in (app.APP_VERSION, 'v0.0.1'):
            with self.subTest(tag=tag):
                self.check(tag, force=True)
                with self.assertRaises(ValueError):
                    app.start_update_install()
                self.assertFalse(app.UPDATE_BUSY.is_set())

    def test_forced_install_accepts_every_staged_release(self):
        for tag in ('v99.0.0', app.APP_VERSION, 'v0.0.1'):
            with self.subTest(tag=tag):
                self.check(tag, force=True)
                started = []
                with patch.object(app.threading, 'Thread',
                                  side_effect=lambda target=None, args=(), daemon=None:
                                  started.append(target) or type('T', (), {'start': lambda s: None})()):
                    app.start_update_install(force=True)
                self.assertTrue(app.UPDATE_BUSY.is_set())
                self.assertEqual(app.update_snapshot()['status'], 'downloading')
                self.assertTrue(app.update_snapshot()['forced'])
                self.assertEqual(len(started), 1)
                app.UPDATE_BUSY.clear()

    def test_install_without_a_staged_release_is_refused_even_when_forced(self):
        for forced in (False, True):
            with self.subTest(forced=forced), self.assertRaises(ValueError):
                app.start_update_install(force=forced)

    def test_preview_never_checks_or_installs_even_when_forced(self):
        with patch.object(app, 'PREVIEW', True), patch.object(app, 'github_bytes') as network:
            app.start_update_check(force=True)
            with self.assertRaises(ValueError):
                app.start_update_install(force=True)
            network.assert_not_called()
        self.assertEqual(app.update_snapshot()['status'], 'disabled')

    def test_forced_request_is_not_lost_while_a_check_is_running(self):
        app.UPDATE_STATE['status'] = 'checking'
        app.start_update_check(force=True)
        self.assertTrue(app.UPDATE_FORCE_REQUESTED.is_set())
        app.start_update_check(force=False)
        self.assertTrue(app.UPDATE_FORCE_REQUESTED.is_set())

    def test_running_check_is_replayed_as_forced(self):
        data = release(source('v0.0.1'), 'v0.0.1')
        calls = []
        with patch.object(app, 'github_bytes',
                          side_effect=lambda *a: calls.append(a) or json.dumps(data).encode()):
            app.UPDATE_FORCE_REQUESTED.set()
            app.check_updates()
        snap = app.update_snapshot()
        self.assertEqual(len(calls), 2)
        self.assertTrue(snap['forced'])
        self.assertEqual(snap['relation'], 'older')
        self.assertTrue(snap['staged'])
        self.assertFalse(app.UPDATE_FORCE_REQUESTED.is_set())

    def test_network_errors_and_unstable_releases_are_never_staged(self):
        for tag, patcher in [
            ('draft', {'draft': True}), ('prerelease', {'prerelease': True}),
        ]:
            with self.subTest(case=tag):
                data = release(source('v99.0.0'), 'v99.0.0'); data.update(patcher)
                with patch.object(app, 'github_bytes', return_value=json.dumps(data).encode()):
                    app.check_updates(force=True)
                self.assertEqual(app.update_snapshot()['status'], 'unavailable')
                self.assertFalse(app.update_snapshot()['staged'])
        with patch.object(app, 'github_bytes', side_effect=TimeoutError('hors ligne')):
            app.check_updates(force=True)
        snap = app.update_snapshot()
        self.assertEqual(snap['status'], 'unavailable')
        self.assertIsNone(snap['relation'])
        self.assertFalse(snap['staged'])

    def test_digest_mismatch_still_blocks_a_forced_install(self):
        good = release(source('v0.0.1'), 'v0.0.1')
        altered = source('v0.0.1') + '# ligne ajoutée\n'.encode()

        def fake(url, limit, accept):
            return json.dumps(good).encode() if url == app.RELEASES_API else altered
        with patch.object(app, 'github_bytes', side_effect=fake):
            app.check_updates(force=True)
        self.assertTrue(app.update_snapshot()['staged'])
        with patch.object(app, 'github_bytes', side_effect=fake), self.assertRaises(ValueError):
            app.stage_update(dict(app.UPDATE_RELEASE), Path(self.tmp.name) / 'Dominis.py')

    def test_force_flags_travel_through_the_http_api(self):
        server = app.DominisHTTPServer(('127.0.0.1', 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = 'http://127.0.0.1:' + str(server.server_port)
        data = release(source(app.APP_VERSION), app.APP_VERSION)
        with patch.object(app, 'github_bytes', return_value=json.dumps(data).encode()):
            app.check_updates(force=True)
        try:
            # Le forçage passe bien par le corps de la requête.
            req = Request(base + '/api/update/check', data=json.dumps({'force': True}).encode(),
                          headers={'Content-Type': 'application/json', 'X-Dominis-Token': app.TOKEN})
            with LOCAL_OPENER.open(req, timeout=5) as r:
                self.assertEqual(r.status, 200)
            with patch.object(app, 'start_update_install') as install:
                req = Request(base + '/api/update/install', data=json.dumps({'force': True}).encode(),
                              headers={'Content-Type': 'application/json', 'X-Dominis-Token': app.TOKEN})
                with LOCAL_OPENER.open(req, timeout=5) as r:
                    self.assertEqual(r.status, 200)
                install.assert_called_once_with(True)
            with patch.object(app, 'start_update_install') as install:
                req = Request(base + '/api/update/install', data=b'{}',
                              headers={'Content-Type': 'application/json', 'X-Dominis-Token': app.TOKEN})
                with LOCAL_OPENER.open(req, timeout=5) as r:
                    self.assertEqual(r.status, 200)
                install.assert_called_once_with(False)
        finally:
            app.UPDATE_BUSY.clear()


class RealForcedDowngradeTest(unittest.TestCase):
    """Retour arrière réel : remplacement du script et redémarrage effectif."""

    def test_forcing_an_older_release_replaces_the_script_and_restarts(self):
        installed, forced = app.APP_VERSION, 'v0.0.2'
        self.assertLess(app.version_tuple(forced), app.version_tuple(installed))
        # Préfixe ASCII et nettoyage tolérant : sous Windows, un dossier
        # temporaire dont un fichier est encore verrouillé par l'enfant ferait
        # échouer le test alors que le parcours vérifié est correct.
        with tempfile.TemporaryDirectory(prefix='Dominis forcage ',
                                         ignore_cleanup_errors=True) as temp:
            folder = Path(temp)
            payload = APP.read_text(encoding='utf-8').replace(
                f"APP_VERSION = '{installed}'", f"APP_VERSION = '{forced}'", 1)
            fixture = ("\nimport faulthandler\nfaulthandler.dump_traceback_later(15, repeat=True)\n"
                       "def github_bytes(url, limit, accept):\n"
                       "    if url == RELEASES_API: return (ROOT / 'release.json').read_bytes()\n"
                       "    return (ROOT / 'release-payload.bin').read_bytes()\n")
            payload = payload.replace("if __name__=='__main__':", fixture + "\nif __name__=='__main__':")
            raw = payload.encode()
            (folder / 'Dominis.py').write_text(payload.replace(
                f"APP_VERSION = '{forced}'", f"APP_VERSION = '{installed}'", 1), encoding='utf-8', newline='\n')
            (folder / 'release-payload.bin').write_bytes(raw)
            (folder / 'release.json').write_text(json.dumps(release(raw, forced)))

            with patch.object(app, 'DB', folder / 'data.db'):
                app.init_db()
                with app.connect() as c:
                    sid = app.save_record(c, {'kind': 'sci', 'data': {'name': 'SCI À conserver', 'capital': 1200}})
                    app.save_record(c, {'kind': 'documents', 'sci': sid, 'data': {'name': 'Contrat', 'blob': 'dGVzdA=='}})
                    st = app.settings(c); st.update(auto_backup=False)
                    c.execute("UPDATE meta SET value=? WHERE key='settings'", (json.dumps(st),))

            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            url = f'http://127.0.0.1:{port}'
            command = [sys.executable, '-u', str(folder / 'Dominis.py'), '--no-browser', '--port', str(port)]
            log = open(folder / 'test.log', 'w', encoding='utf-8', buffering=1)
            processes = []
            env = {**os.environ, 'PYTHONUNBUFFERED': '1', 'PYTHONFAULTHANDLER': '1',
                   'NO_PROXY': 'localhost,127.0.0.1', 'no_proxy': 'localhost,127.0.0.1'}

            def get(path, token=None, payload=None):
                headers = {'X-Dominis-Token': token} if token else {}
                req = Request(url + path, headers=headers,
                              data=json.dumps(payload).encode() if payload is not None else None)
                with LOCAL_OPENER.open(req, timeout=3) as r:
                    return r.read()

            def read_log():
                # Sous Windows, l'enfant hérite du descripteur : une lecture peut
                # échouer transitoirement (WinError 32) sans que le test soit en cause.
                try:
                    log.flush()
                    return (folder / 'test.log').read_text(encoding='utf-8', errors='replace')
                except OSError as exc:
                    return f'(journal illisible : {exc})'

            def wait(fn, timeout=40, label='condition'):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if processes and processes[-1].poll() is not None:
                        raise AssertionError(f'Processus arrêté pendant {label} '
                                             f'({processes[-1].returncode}); log: ' + read_log())
                    try:
                        result = fn()
                        if result:
                            return result
                    except (OSError, ValueError):
                        pass
                    time.sleep(.1)
                tail = ' | '.join(read_log().splitlines()[-8:])
                raise AssertionError(f'Timeout pendant {label}; log: {tail}')

            def token():
                return get('/').decode().split("const TOKEN='")[1].split("'", 1)[0]

            try:
                processes.append(subprocess.Popen(command, stdout=log, stderr=log, env=env))
                tok = wait(token, label='jeton de session')
                wait(lambda: json.loads(get('/api/health'))['version'] == installed and True,
                     label='version installée au démarrage')
                # Une vérification ordinaire ne propose rien : la Release est plus ancienne.
                state_before = json.loads(get('/api/state', tok))

                get('/api/update/check', tok, {'force': True})

                def forced_ready():
                    data = json.loads(get('/api/update', tok))
                    return data if data.get('staged') and data.get('forced') and data['status'] != 'checking' else None
                snap = wait(forced_ready, label='vérification forcée')
                self.assertEqual(snap['relation'], 'older')
                self.assertEqual(snap['latest'], forced)
                self.assertEqual(snap['status'], 'current')
                self.assertEqual(snap['current'], installed)

                # Sans forçage, l'installation d'une version antérieure est refusée
                # et le script en place n'est pas touché.
                script_before = (folder / 'Dominis.py').read_bytes()
                req = Request(url + '/api/update/install', data=b'{}',
                              headers={'X-Dominis-Token': tok})
                with self.assertRaises(Exception):
                    LOCAL_OPENER.open(req, timeout=3)
                self.assertEqual((folder / 'Dominis.py').read_bytes(), script_before)

                get('/api/update/install', tok, {'force': True})

                def downgraded():
                    h = json.loads(get('/api/health'))
                    return h if h['version'] == forced and h['instance'] != snap['instance'] else None
                wait(downgraded, label='redémarrage sur la version antérieure')
                tok = wait(token, label='jeton après retour arrière')
                after = json.loads(get('/api/state', tok))
                self.assertEqual(after['scis'], state_before['scis'])
                self.assertEqual(after['app_version'], forced)
                self.assertEqual((folder / 'Dominis.py').read_bytes(), raw)
                # Les données et la sauvegarde obligatoire sont préservées.
                self.assertTrue(list((folder / 'sauvegardes').glob('*.db')))
                with patch.object(app, 'DB', folder / 'data.db'):
                    with app.connect() as c:
                        self.assertEqual(len(list(c.execute('SELECT * FROM scis'))), 1)
                self.assertNotEqual((folder / 'data.db').read_bytes(), b'')
                get('/api/quit', tok, {})
                # `wait()` s'arrête dès qu'un processus est terminé : la fermeture
                # finale est donc attendue directement ici.
                self.assertEqual(processes[-1].wait(timeout=20), 0)
            finally:
                # Comme dans tests/test_updates.py : demander l'arrêt à l'enfant
                # avant le superviseur, attendre réellement sa fin, puis seulement
                # fermer le journal. Sous Windows, un descripteur encore hérité par
                # un enfant verrouille test.log et fait échouer le nettoyage du
                # dossier temporaire (WinError 32 / 267).
                try:
                    get('/api/quit', token(), {})
                except Exception:
                    pass
                for proc in processes:
                    if proc.poll() is None:
                        try:
                            proc.wait(timeout=6)
                        except subprocess.TimeoutExpired:
                            proc.terminate()
                            try:
                                proc.wait(timeout=6)
                            except subprocess.TimeoutExpired:
                                proc.kill(); proc.wait()
                log.close()


class ForcedUpdateUiTests(unittest.TestCase):
    """L'interface expose le bouton, les trois messages et le parcours de forçage."""

    def test_panel_offers_the_force_button(self):
        self.assertIn('data-update-action="force"', app.HTML)
        self.assertIn('Forcer la mise à jour', app.HTML)
        self.assertIn('function forceUpdate()', app.HTML)
        self.assertIn('function offerForcedUpdate(', app.HTML)
        self.assertIn('function relationText(', app.HTML)
        self.assertIn('function renderVersionPanel(', app.HTML)
        self.assertIn("api('update/check',{force:true})", app.HTML)
        self.assertIn("api('update/install',{force:!!force})", app.HTML)
        self.assertIn("data-update-action=\"force-install\"", app.HTML)
        self.assertIn("else if(a==='force')await forceUpdate()", app.HTML)
        self.assertIn("else if(a==='force-install')await beginUpdate(true)", app.HTML)

    def test_warnings_differ_for_same_and_older_releases(self):
        self.assertIn('Avertissement : retour à une version antérieure', app.HTML)
        self.assertIn('Réinstaller la même version ?', app.HTML)
        self.assertIn('Je comprends, forcer le retour arrière', app.HTML)
        self.assertIn('Réinstaller cette version', app.HTML)
        # Le cas « plus ancienne » ouvre une fenêtre de confirmation teintée en danger.
        self.assertIn("""<button class="${danger?'danger':'primary'}" data-update-action="force-install">""", app.HTML)
        self.assertIn("danger=relation==='older'", app.HTML)

    def test_toggle_button_is_not_squeezed_by_a_long_description(self):
        self.assertIn('.toggle{height:23px;width:41px;flex:0 0 auto;', app.HTML)
        self.assertIn('.task-param-row>div{flex:1 1 auto;min-width:0}', app.HTML)
        self.assertIn('.setting-row>.toggle,.setting-row>.theme-choice{flex:0 0 auto}', app.HTML)


if __name__ == '__main__':
    unittest.main()
