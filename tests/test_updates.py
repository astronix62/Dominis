"""Mises à jour : réseau simulé, fichiers et bases exclusivement temporaires."""
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
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener

LOCAL_OPENER = build_opener(ProxyHandler({}))

from test_dominis import app, APP


def source(version='v0.0.2', extra=''):
    return (f"APP_VERSION = '{version}'\nUPDATE_PROTOCOL = 1\nDB_SCHEMA_VERSION = 1\nMIN_PYTHON = (3, 10)\n" + extra).encode()


def release(raw, version='v0.0.2'):
    return {'tag_name': version, 'draft': False, 'prerelease': False, 'assets': [
        {'name': 'Dominis.py', 'state': 'uploaded', 'size': len(raw),
         'browser_download_url': app.RELEASE_DOWNLOADS + version + '/Dominis.py',
         'digest': 'sha256:' + hashlib.sha256(raw).hexdigest()}]}


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.target = self.folder / 'Dominis.py'
        self.original = b'# Programme original\n'
        self.target.write_bytes(self.original)
        self.target.chmod(0o755)
        for name, value in [('DB', self.folder / 'data.db'), ('PREVIEW', False),
                            ('UPDATE_RELEASE', None), ('PENDING_UPDATE', None),
                            ('UPDATE_STATE', {'status': 'idle', 'latest': None, 'message': '', 'dismissed': False}),
                            ('INSTANCE_GUARD', None), ('START_ARGS', [])]:
            p = patch.object(app, name, value); p.start(); self.addCleanup(p.stop)
        app.UPDATE_BUSY.clear(); app.EXIT_READY.clear()
        self.addCleanup(app.UPDATE_BUSY.clear); self.addCleanup(app.EXIT_READY.clear)
        app.init_db()
        self.db_before = app.DB.read_bytes()

    def plan(self, raw=None, version='v0.0.2'):
        raw = raw if raw is not None else source(version)
        info = app.release_info(release(raw, version))
        with patch.object(app, 'github_bytes', return_value=raw):
            return app.stage_update(info, self.target)

    def test_numeric_versions(self):
        self.assertGreater(app.version_tuple('v0.0.10'), app.version_tuple('v0.0.9'))
        self.assertGreater(app.version_tuple('v1.0.0'), app.version_tuple('v0.99.99'))
        for value in ('0.0.1', 'v0.01.0', 'v1.2.3-beta', '../v1', None, 'v1.0'):
            with self.subTest(value=value), self.assertRaises(ValueError): app.version_tuple(value)

    def test_release_requires_exact_asset_and_official_url(self):
        data = release(source())
        for field, value in [('name', 'dominis.py'), ('state', 'new'),
                             ('browser_download_url', 'https://evil.example/Dominis.py'), ('size', 0), ('digest', 'bad')]:
            invalid = json.loads(json.dumps(data)); invalid['assets'][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): app.release_info(invalid)
        for field in ('draft', 'prerelease'):
            with self.assertRaises(ValueError): app.release_info({**data, field: True})
        with self.assertRaises(ValueError): app.release_info({**data, 'assets': data['assets'] * 2})

    def test_download_rejects_untrusted_redirects(self):
        for url in ('http://github.com/file', 'https://evil.example/file', 'file:///tmp/file',
                    'https://github.com:444/file', 'https://user@github.com/file'):
            with self.subTest(url=url), self.assertRaises(ValueError): app.validate_github_url(url)
        app.validate_github_url('https://release-assets.githubusercontent.com/file?signature=value')

    def test_source_validation_without_execution(self):
        sentinel = self.folder / 'executed'
        raw = source(extra=f"open({str(sentinel)!r}, 'w').write('no')\n")
        app.validate_update_source(raw, 'v0.0.2')
        self.assertFalse(sentinel.exists())
        for bad in (raw.replace(b'v0.0.2', b'v0.0.3'), b'<html>Error</html>',
                    raw.replace(b'UPDATE_PROTOCOL = 1', b'UPDATE_PROTOCOL = 2'),
                    raw.replace(b'DB_SCHEMA_VERSION = 1', b'DB_SCHEMA_VERSION = 2'),
                    raw.replace(b'(3, 10)', b'(99, 0)'), raw + b"APP_VERSION='v0.0.2'\n"):
            with self.subTest(bad=bad[:60]), self.assertRaises((ValueError, SyntaxError)):
                app.validate_update_source(bad, 'v0.0.2')

    def test_stage_does_not_replace_script_or_touch_database(self):
        plan = self.plan()
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual((plan['folder'] / 'previous.tmp').read_bytes(), self.original)
        self.assertEqual(app.DB.read_bytes(), self.db_before)
        self.assertEqual((plan['folder'] / 'candidate.tmp').stat().st_mode & 0o777, self.target.stat().st_mode & 0o777)

    def test_bad_digest_or_truncated_download_keeps_original(self):
        raw = source(); info = app.release_info(release(raw))
        for bad in (raw[:-1], raw.replace(b'v0.0.2', b'v0.0.3')):
            with patch.object(app, 'github_bytes', return_value=bad), self.assertRaises(ValueError):
                app.stage_update(info, self.target)
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(app.DB.read_bytes(), self.db_before)
        self.assertFalse(list(self.folder.glob('.dominis-update-*')))

    def test_available_current_older_and_later_semantics(self):
        for version, status in [('v99.0.0', 'available'), (app.APP_VERSION, 'current'), ('v0.0.0', 'current')]:
            data = release(source(version), version)
            with patch.object(app, 'github_bytes', return_value=json.dumps(data).encode()): app.check_updates()
            self.assertEqual(app.update_snapshot()['status'], status)
        app.update_state(dismissed=True)
        with patch.object(app, 'github_bytes', return_value=json.dumps(release(source())).encode()): app.check_updates()
        self.assertTrue(app.update_snapshot()['dismissed'])

    def test_network_errors_are_not_current(self):
        for error in (TimeoutError('hors ligne'), HTTPError(app.RELEASES_API, 404, '', {}, None),
                      HTTPError(app.RELEASES_API, 403, '', {}, None), ValueError('JSON invalide')):
            with patch.object(app, 'github_bytes', side_effect=error): app.check_updates()
            self.assertEqual(app.update_snapshot()['status'], 'unavailable')

    def test_preview_never_checks_or_installs(self):
        with patch.object(app, 'PREVIEW', True), patch.object(app, 'github_bytes') as network:
            app.start_update_check()
            with self.assertRaises(ValueError): app.start_update_install()
            network.assert_not_called()
        self.assertEqual(app.update_snapshot()['status'], 'disabled')

    def test_install_refuses_missing_release_and_double_install(self):
        with self.assertRaises(ValueError): app.start_update_install()
        app.UPDATE_BUSY.set()
        with self.assertRaises(ValueError): app.start_update_install()

    def test_backup_failure_aborts_before_replacement(self):
        plan = self.plan(); app.UPDATE_RELEASE = app.release_info(release(source())); app.UPDATE_BUSY.set()
        with patch.object(app, 'stage_update', return_value=plan), patch.object(app, 'make_safety_backup', side_effect=OSError('disque plein')), patch.object(app, 'close_for_update') as close:
            app.install_update()
            close.assert_not_called()
        self.assertEqual(app.update_snapshot()['status'], 'failed')
        self.assertFalse(app.UPDATE_BUSY.is_set())
        self.assertIsNone(app.PENDING_UPDATE)
        self.assertFalse(plan['folder'].exists())
        self.assertEqual(self.target.read_bytes(), self.original)
        self.assertEqual(app.DB.read_bytes(), self.db_before)

    def test_install_makes_mandatory_backup_even_if_preference_is_off(self):
        with app.connect() as c:
            st = app.settings(c); st['auto_backup'] = False
            c.execute("UPDATE meta SET value=? WHERE key='settings'", (json.dumps(st),))
        plan = self.plan(); app.UPDATE_RELEASE = app.release_info(release(source())); app.UPDATE_BUSY.set()
        with patch.object(app, 'stage_update', return_value=plan), patch.object(app.time, 'sleep'), patch.object(app, 'close_for_update') as close:
            app.install_update(); close.assert_called_once()
        self.assertEqual(app.PENDING_UPDATE, plan)
        self.assertEqual(len(list((self.folder / 'sauvegardes').glob('*.db'))), 1)
        self.assertEqual(self.target.read_bytes(), self.original)

    def test_supervisor_success_restarts_and_cleans_up(self):
        # Véritable processus Python enfant avec accusé de démarrage.
        code = """import json, os
from pathlib import Path
Path(os.environ['DOMINIS_UPDATE_READY']).write_text(json.dumps({'version':APP_VERSION,'nonce':os.environ['DOMINIS_UPDATE_NONCE']}))
import time
time.sleep(.4)
"""
        raw = source(extra=code); plan = self.plan(raw)
        self.assertEqual(app.launch_updated(plan, timeout=5), 0)
        self.assertEqual(self.target.read_bytes(), raw)
        self.assertFalse(plan['folder'].exists())
        self.assertEqual(len(list(self.folder.glob('*.py'))), 1)
        self.assertEqual(app.DB.read_bytes(), self.db_before)

    def ready_source(self, version='v0.0.1', extra=''):
        ready = """import json, os, time
from pathlib import Path
Path(os.environ['DOMINIS_UPDATE_READY']).write_text(json.dumps({'version':APP_VERSION,'nonce':os.environ['DOMINIS_UPDATE_NONCE']}))
time.sleep(.5)
"""
        return source(version, extra=ready + extra)

    def test_supervisor_rolls_back_failed_start(self):
        previous = self.ready_source('v0.0.1')
        self.target.write_bytes(previous)
        plan = self.plan(source(extra='raise RuntimeError("test startup failure")\n'))
        with patch.object(app, 'APP_VERSION', 'v0.0.1'):
            self.assertEqual(app.launch_updated(plan, timeout=3), 0)
        self.assertEqual(self.target.read_bytes(), previous)
        self.assertFalse(plan['folder'].exists())
        self.assertEqual(app.DB.read_bytes(), self.db_before)

    def test_supervisor_rolls_back_unresponsive_start(self):
        previous = self.ready_source('v0.0.1')
        self.target.write_bytes(previous)
        plan = self.plan(source(extra='import time\ntime.sleep(20)\n'))
        with patch.object(app, 'APP_VERSION', 'v0.0.1'):
            self.assertEqual(app.launch_updated(plan, timeout=.25), 0)
        self.assertEqual(self.target.read_bytes(), previous)
        self.assertEqual(app.DB.read_bytes(), self.db_before)

    def test_supervisor_does_not_overwrite_external_change(self):
        changed = self.ready_source(app.APP_VERSION, extra='# Changed by user\n')
        plan = self.plan()
        self.target.write_bytes(changed)
        self.assertEqual(app.launch_updated(plan, timeout=2), 0)
        self.assertEqual(self.target.read_bytes(), changed)

    def test_native_supervisor_handoff_is_platform_appropriate(self):
        from types import SimpleNamespace
        detached = os.name != 'nt'
        marker = self.folder / 'detached-child-finished'
        extra = f"\nfrom pathlib import Path\ntime.sleep(1.0)\nPath({str(marker)!r}).write_text('alive')\n"
        plan = self.plan(self.ready_source('v0.0.2', extra=extra))
        fake_sys = SimpleNamespace(platform='darwin' if detached else 'win32', executable=sys.executable)
        with patch.object(app, 'sys', fake_sys), patch.object(app, 'START_ARGS', ['--desktop']):
            self.assertEqual(app.launch_updated(plan, timeout=5), 0)
        if detached:
            self.assertFalse(marker.exists(), 'Le superviseur macOS doit sortir dès l’accusé, sans attendre l’enfant.')
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not marker.exists():
            time.sleep(.05)
        self.assertTrue(marker.exists(), 'L’instance mise à jour doit survivre à la sortie du superviseur GUI.')
        self.assertFalse(plan['folder'].exists())

    def test_instance_guard_prevents_parallel_local_instances(self):
        guard = app.InstanceGuard(self.folder)
        try:
            with self.assertRaises(OSError): app.InstanceGuard(self.folder)
        finally: guard.close()
        app.InstanceGuard(self.folder).close()

    def test_writes_and_quit_are_blocked_during_installation(self):
        server = app.DominisHTTPServer(('127.0.0.1', 0), app.Handler)
        t = threading.Thread(target=server.serve_forever, daemon=True); t.start()
        app.UPDATE_BUSY.set()
        try:
            for endpoint in ('settings', 'save', 'restore', 'quit', 'update/install'):
                req = Request(f'http://127.0.0.1:{server.server_port}/api/{endpoint}', data=b'{}', headers={'X-Dominis-Token': app.TOKEN})
                with self.assertRaises(HTTPError) as exc: LOCAL_OPENER.open(req)
                self.assertEqual(exc.exception.code, 409)
            self.assertFalse(app.on_native_closing())
        finally:
            server.shutdown(); server.server_close(); t.join(timeout=2)
        self.assertEqual(app.DB.read_bytes(), self.db_before)


class PrepareTestCopyTests(unittest.TestCase):
    def test_prepares_v000_without_personal_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'test copy'
            tool = APP.parents[1] / 'tools' / 'prepare_update_test.py'
            result = subprocess.run([sys.executable, str(tool), str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("APP_VERSION = 'v0.0.0'", (target / 'Dominis.py').read_text(encoding="utf-8"))
            self.assertEqual({f.name for f in target.iterdir()}, {'Dominis.py', 'Lancer_Dominis.command', 'Lancer_Dominis.bat', 'Dominis.jpg'})
            self.assertIn(f"APP_VERSION = '{app.APP_VERSION}'", APP.read_text(encoding="utf-8"))

    def test_refuses_to_overwrite_nonempty_test_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp); (target / 'data.db').write_bytes(b'preserve')
            tool = APP.parents[1] / 'tools' / 'prepare_update_test.py'
            result = subprocess.run([sys.executable, str(tool), str(target)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((target / 'data.db').read_bytes(), b'preserve')


class RealUpgradeTest(unittest.TestCase):
    def test_v000_to_v001_preserves_data_restarts_and_offers_again_next_launch(self):
        self.run_upgrade('v0.0.0', 'v0.0.1')

    def test_v001_to_v002_preserves_data_restarts_and_offers_again_next_launch(self):
        self.run_upgrade('v0.0.1', 'v0.0.2')

    def run_upgrade(self, old_version, new_version):
        with tempfile.TemporaryDirectory(prefix='Dominis test ') as temp:
            folder = Path(temp)
            if old_version == 'v0.0.0':
                # Utiliser réellement l'outil demandé, puis vérifier son résultat avant
                # d'injecter le seul faux transport réseau nécessaire au test hors ligne.
                tool = APP.parents[1] / 'tools' / 'prepare_update_test.py'
                subprocess.run([sys.executable, str(tool), str(folder)], check=True, capture_output=True)
                expected = APP.read_bytes().replace(
                    f"APP_VERSION = '{app.APP_VERSION}'".encode(), b"APP_VERSION = 'v0.0.0'", 1)
                self.assertEqual((folder / 'Dominis.py').read_bytes(), expected)
            original_source = APP.read_text(encoding='utf-8').replace(
                f"APP_VERSION = '{app.APP_VERSION}'", f"APP_VERSION = '{new_version}'", 1)
            # Seule la fonction réseau est simulée. Tout le reste est le vrai programme.
            fixture = '''
import faulthandler
faulthandler.dump_traceback_later(15, repeat=True)
def github_bytes(url, limit, accept):
    if url == RELEASES_API: return (ROOT / 'release.json').read_bytes()
    return (ROOT / 'release-payload.bin').read_bytes()
'''
            source_new = original_source.replace("if __name__=='__main__':", fixture + "\nif __name__=='__main__':")
            source_old = source_new.replace(f"APP_VERSION = '{new_version}'", f"APP_VERSION = '{old_version}'", 1)
            (folder / 'Dominis.py').write_text(source_old, encoding="utf-8", newline="\n")
            raw = source_new.encode()
            (folder / 'release-payload.bin').write_bytes(raw)
            (folder / 'release.json').write_text(json.dumps(release(raw, new_version)))
            with patch.object(app, 'DB', folder / 'data.db'):
                app.init_db()
                with app.connect() as c:
                    sid = app.save_record(c, {'kind': 'sci', 'data': {'name': 'SCI À conserver', 'capital': 1200}})
                    app.save_record(c, {'kind': 'documents', 'sci': sid, 'data': {'name': 'Contrat', 'blob': 'dGVzdA=='}})
                    st = app.settings(c); st.update(auto_backup=False, last_page='settings', theme='light')
                    c.execute("UPDATE meta SET value=? WHERE key='settings'", (json.dumps(st),))
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
            url = f'http://127.0.0.1:{port}'
            command = [sys.executable, '-u', str(folder / 'Dominis.py'), '--no-browser', '--port', str(port)]
            log = open(folder / 'test.log', 'w', encoding='utf-8', buffering=1)
            processes = []
            child_env = {**os.environ, 'PYTHONUNBUFFERED': '1', 'PYTHONFAULTHANDLER': '1',
                         'NO_PROXY': 'localhost,127.0.0.1', 'no_proxy': 'localhost,127.0.0.1'}
            def start():
                proc = subprocess.Popen(command, stdout=log, stderr=log, env=child_env)
                processes.append(proc); return proc
            def get(path, token=None, payload=None):
                headers = {'X-Dominis-Token': token} if token else {}
                req = Request(url + path, headers=headers, data=json.dumps(payload).encode() if payload is not None else None)
                with LOCAL_OPENER.open(req, timeout=2) as r: return r.read()
            def wait(fn, timeout=30, label='condition'):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if processes and processes[-1].poll() is not None:
                        log.flush()
                        raise AssertionError(f'Le processus Dominis s’est arrêté pendant {label} '
                                             f'({processes[-1].returncode}); log: '
                                             + (folder / 'test.log').read_text(encoding="utf-8"))
                    try:
                        result = fn()
                        if result: return result
                    except (OSError, ValueError): pass
                    time.sleep(.1)
                log.flush()
                log_tail = ' | '.join((folder / 'test.log').read_text(encoding='utf-8').splitlines()[-8:])
                raise AssertionError(f'Timeout pendant {label}; log: {log_tail}')
            def token():
                return get('/').decode().split("const TOKEN='")[1].split("'", 1)[0]
            def available(tok):
                data = json.loads(get('/api/update', tok)); return data if data['status']=='available' else None
            try:
                p = start(); tok = wait(token, label='initial server token')
                self.assertFalse(wait(lambda: available(tok), label='initial release status')['dismissed'])
                get('/api/update/later', tok, {})
                self.assertTrue(json.loads(get('/api/update', tok))['dismissed'])
                get('/api/quit', tok, {}); self.assertEqual(p.wait(timeout=10), 0)
                p = start(); tok = wait(token, label='server token after the first quit')
                before = wait(lambda: available(tok), label='release status after the first quit'); self.assertFalse(before['dismissed'])
                state_before = json.loads(get('/api/state', tok))
                # Mise à jour effective et redémarrage réel avec le même port.
                db_bytes_before = (folder / 'data.db').read_bytes()
                get('/api/update/install', tok, {})
                def upgraded():
                    h = json.loads(get('/api/health'))
                    return h if h['version']==new_version and h['instance']!=before['instance'] else None
                wait(upgraded, label='health check after installing the update')
                tok = wait(token, label='session token after update')
                after = json.loads(get('/api/state', tok))
                self.assertEqual(after['scis'], state_before['scis'])
                self.assertEqual(after['records'], state_before['records'])
                self.assertEqual(after['settings'], state_before['settings'])
                self.assertEqual(after['app_version'], new_version)
                self.assertEqual((folder / 'data.db').read_bytes(), db_bytes_before)
                self.assertEqual(json.loads(get('/api/update', tok))['restart_notice']['kind'], 'success')
                dashboard_script = get('/').decode()
                self.assertIn("page='dashboard';tab='overview';scope='';render();", dashboard_script)
                self.assertIn('pollUpdates();', dashboard_script)
                self.assertIsNone(p.poll(), 'Le processus parent doit garder le lanceur ouvert.')
                self.assertEqual(len(list(folder.glob('Dominis.py'))), 1)
                self.assertTrue(list((folder / 'sauvegardes').glob('*.db')))
                wait(lambda: not list(folder.glob('.dominis-update-*')), label='update staging directory cleanup')
                self.assertEqual((folder / 'Dominis.py').read_bytes(), raw)
                # La version installée ne doit plus proposer la même Release.
                def current(token):
                    state = json.loads(get('/api/update', token))
                    return state if state['status'] == 'current' else None
                self.assertEqual(wait(lambda: current(tok), label='new version status')['current'], new_version)
                get('/api/quit', tok, {}); self.assertEqual(p.wait(timeout=10), 0)
                p = start(); tok = wait(token, label='token after final restart')
                self.assertEqual(wait(lambda: current(tok), label='latest version status after final restart')['latest'], new_version)
                self.assertIsNone(json.loads(get('/api/update', tok))['restart_notice'])
                get('/api/quit', tok, {}); self.assertEqual(p.wait(timeout=10), 0)
            finally:
                # En cas d'échec, demander l'arrêt à l'instance enfant avant le superviseur.
                try: get('/api/quit', token(), {})
                except Exception: pass
                for proc in processes:
                    if proc.poll() is None:
                        try: proc.wait(timeout=4)
                        except subprocess.TimeoutExpired: proc.terminate(); proc.wait(timeout=5)
                log.close()


if __name__ == '__main__': unittest.main()
