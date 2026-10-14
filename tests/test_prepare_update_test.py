"""Préparation isolée et contrôle de la Release, sans aucune publication réseau."""
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from test_dominis import app, APP
from test_updates import release

spec = importlib.util.spec_from_file_location('prepare', APP.parents[1] / 'tools' / 'prepare_update_test.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class PrepareUpdateTestTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='Préparer Dominis ')
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name)
        self.target = self.home / 'Dominis'
        self.raw = APP.read_bytes()
        self.version = app.APP_VERSION
        stdout_patch = patch('sys.stdout', new_callable=io.StringIO)
        self.stdout = stdout_patch.start()
        self.addCleanup(stdout_patch.stop)

    def test_source_version_for_requested_scenario(self):
        self.assertEqual(self.version, 'v0.0.1')

    def assert_copy(self, target):
        self.assertEqual({p.name for p in target.iterdir()}, set(prepare.APP_FILES))
        expected = self.raw.replace(b"APP_VERSION = 'v0.0.1'", b"APP_VERSION = 'v0.0.0'", 1)
        self.assertEqual((target / 'Dominis.py').read_bytes(), expected)
        app.validate_update_source(expected, 'v0.0.0')
        for name in prepare.APP_FILES[1:]:
            self.assertEqual((target / name).read_bytes(), (APP.parent / name).read_bytes())
        self.assertEqual(APP.read_bytes(), self.raw)
        if os.name != 'nt':
            self.assertTrue((target / 'Lancer_Dominis.command').stat().st_mode & 0o111)

    def test_default_is_complete_dominis_folder_without_personal_data(self):
        with patch.object(prepare.Path, 'home', return_value=self.home):
            result = prepare.prepare()
        self.assertEqual(result, self.home / 'Dominis-test' / 'Dominis')
        self.assert_copy(result)
        self.assertIn('Release non vérifiée', self.stdout.getvalue())

    def test_cli_without_arguments_from_another_working_directory(self):
        result = subprocess.run(
            [sys.executable, str(prepare.ROOT / 'tools' / 'prepare_update_test.py')],
            cwd=self.home, env={**os.environ, 'HOME': str(self.home), 'USERPROFILE': str(self.home)},
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_copy(self.home / 'Dominis-test' / 'Dominis')

    def test_explicit_empty_folder_and_byte_identical_files(self):
        self.target.mkdir()
        prepare.prepare(self.target)
        self.assert_copy(self.target)

    def test_second_run_refuses_without_changing_any_file(self):
        prepare.prepare(self.target)
        before = {p.name: p.read_bytes() for p in self.target.iterdir()}
        with self.assertRaisesRegex(ValueError, 'doit être vide'):
            prepare.prepare(self.target)
        self.assertEqual({p.name: p.read_bytes() for p in self.target.iterdir()}, before)

    def test_refuses_repository_and_file_destination(self):
        for target in (prepare.ROOT, APP.parent / 'test-forbidden'):
            with self.assertRaisesRegex(ValueError, 'en dehors du dépôt'):
                prepare.prepare(target)
        self.target.write_bytes(b'preserve')
        with self.assertRaisesRegex(ValueError, 'doit être vide'):
            prepare.prepare(self.target)
        self.assertEqual(self.target.read_bytes(), b'preserve')

    def test_incomplete_source_fails_before_creating_destination(self):
        root = self.home / 'fake-repo'
        (root / 'Dominis').mkdir(parents=True)
        with patch.object(prepare, 'ROOT', root), self.assertRaisesRegex(ValueError, 'introuvable'):
            prepare.prepare(self.target)
        self.assertFalse(self.target.exists())

    def test_check_release_requires_same_tag(self):
        data = release(self.raw, 'v0.0.2')
        with patch.object(app, 'github_bytes', return_value=json.dumps(data).encode()), \
             self.assertRaisesRegex(ValueError, 'dernière Release est v0.0.2'):
            prepare.verify_release(app, self.raw, self.version)

    def test_old_asset_and_wrong_digest_are_rejected_before_creation(self):
        for data in (release(b'old asset', self.version), release(self.raw, self.version)):
            data['assets'][0]['digest'] = 'sha256:' + '0' * 64
            with patch.object(prepare, 'load_application', return_value=app), \
                 patch.object(app, 'github_bytes', return_value=json.dumps(data).encode()) as network, \
                 self.assertRaisesRegex(ValueError, 'pièce jointe'):
                prepare.prepare(self.target, check_release=True)
            network.assert_called_once()
            self.assertFalse(self.target.exists())

    def test_matching_release_download_is_verified_before_creation(self):
        data = release(self.raw, self.version)
        with patch.object(prepare, 'load_application', return_value=app), \
             patch.object(app, 'github_bytes', side_effect=[json.dumps(data).encode(), self.raw]) as network:
            prepare.prepare(self.target, check_release=True)
        self.assertEqual(network.call_count, 2)
        self.assert_copy(self.target)
        self.assertIn('Release v0.0.1 vérifiée', self.stdout.getvalue())

    def test_no_github_digest_still_requires_byte_identical_download(self):
        data = release(self.raw, self.version)
        data['assets'][0].pop('digest')
        for payload, success in ((self.raw, True), (self.raw + b'\n# different\n', False)):
            with patch.object(app, 'github_bytes', side_effect=[json.dumps(data).encode(), payload]):
                if success:
                    prepare.verify_release(app, self.raw, self.version)
                else:
                    with self.assertRaisesRegex(ValueError, 'exactement au fichier local'):
                        prepare.verify_release(app, self.raw, self.version)

    def test_network_failure_never_creates_test_folder(self):
        for error in (TimeoutError('hors ligne'), HTTPError(app.RELEASES_API, 403, '', {}, None)):
            with patch.object(prepare, 'load_application', return_value=app), \
                 patch.object(app, 'github_bytes', side_effect=error), self.assertRaises(OSError):
                prepare.prepare(self.target, check_release=True)
            self.assertFalse(self.target.exists())


if __name__ == '__main__': unittest.main()
