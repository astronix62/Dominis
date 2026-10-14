"""Sauvegardes hebdomadaires : copies SQLite privées, séparées de data.db."""
import datetime as dt
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from test_dominis import app


class WeeklyAutoSaveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='Dominis auto-save ')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.db = self.folder / 'data.db'
        self.db_patch = patch.object(app, 'DB', self.db)
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        self.preview_patch = patch.object(app, 'PREVIEW', False)
        self.preview_patch.start()
        self.addCleanup(self.preview_patch.stop)
        self.primary_missing_patch = patch.object(app, 'PRIMARY_DB_MISSING', False)
        self.primary_missing_patch.start()
        self.addCleanup(self.primary_missing_patch.stop)
        self.notice_patch = patch.object(app, 'AUTO_SAVE_NOTICE', None)
        self.notice_patch.start()
        self.addCleanup(self.notice_patch.stop)
        app.init_db()

    def add_full_data(self):
        with app.connect() as connection:
            sci_id = app.save_record(connection, {
                'kind': 'sci', 'data': {'name': 'SCI à sauvegarder', 'capital': 1200}
            })
            document_id = app.save_record(connection, {
                'kind': 'documents', 'sci': sci_id,
                'data': {'name': 'Statuts', 'filename': 'statuts.pdf',
                         'mime': 'application/pdf', 'blob': 'cGRmLWRlLXRlc3Q='}
            })
        return sci_id, document_id

    def set_settings(self, **values):
        with app.connect() as connection:
            preferences = app.settings(connection)
            preferences.update(values)
            connection.execute('UPDATE meta SET value=? WHERE key=\'settings\'',
                               (json.dumps(preferences),))

    def test_first_launch_writes_complete_sqlite_copy_without_switching_database(self):
        sci_id, document_id = self.add_full_data()
        primary_path = app.DB.resolve()
        saved = app.maybe_create_weekly_auto_save(dt.date(2026, 10, 14))

        self.assertEqual(saved.name, '2026-10-14-save.db')
        self.assertEqual(saved.parent, self.folder / 'auto-save')
        self.assertNotEqual(saved.resolve(), primary_path)
        self.assertEqual(app.DB.resolve(), primary_path)
        self.assertEqual(len(app.auto_save_files()), 1)
        self.assertEqual(saved.read_bytes()[:16], b'SQLite format 3\x00')

        with sqlite3.connect(saved) as backup:
            self.assertEqual(backup.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(backup.execute('SELECT id FROM scis').fetchone()[0], sci_id)
            document = json.loads(backup.execute(
                'SELECT data FROM records WHERE id=? AND kind=\'documents\'', (document_id,)
            ).fetchone()[0])
            self.assertEqual(document['blob'], 'cGRmLWRlLXRlc3Q=')
            self.assertEqual(document['filename'], 'statuts.pdf')

        with app.connect() as primary:
            self.assertEqual(primary.execute('SELECT id FROM scis').fetchone()[0], sci_id)
            preferences = app.settings(primary)
            self.assertEqual(preferences['last_auto_save_week'], '2026-W42')
            self.assertTrue(preferences['weekly_auto_save'])

    def test_only_one_copy_per_iso_week_even_after_relaunch(self):
        first = app.maybe_create_weekly_auto_save(dt.date(2026, 10, 14))
        second = app.maybe_create_weekly_auto_save(dt.date(2026, 10, 18))
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual([p.name for p in app.auto_save_files()], ['2026-10-14-save.db'])

    def test_first_launch_later_in_week_uses_that_day_as_backup_date(self):
        saved = app.maybe_create_weekly_auto_save(dt.date(2026, 10, 22))
        self.assertEqual(saved.name, '2026-10-22-save.db')
        self.assertEqual(app.auto_save_week(dt.date(2026, 10, 22)), '2026-W43')

    def test_iso_week_year_boundary_does_not_create_a_second_copy(self):
        first = app.maybe_create_weekly_auto_save(dt.date(2026, 12, 28))
        second = app.maybe_create_weekly_auto_save(dt.date(2027, 1, 3))
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(app.auto_save_week(dt.date(2026, 12, 28)), '2026-W53')
        self.assertEqual(app.auto_save_week(dt.date(2027, 1, 3)), '2026-W53')
        self.assertEqual(len(app.auto_save_files()), 1)

    def test_new_third_copy_removes_only_the_oldest_auto_save(self):
        folder = self.folder / 'auto-save'
        folder.mkdir()
        for day in ('2026-09-30', '2026-10-07'):
            (folder / f'{day}-save.db').write_bytes(b'old placeholder')
        safety_folder = self.folder / 'sauvegardes'
        safety_folder.mkdir()
        safety = safety_folder / 'dominis-safety.db'
        safety.write_bytes(b'keep')

        saved = app.maybe_create_weekly_auto_save(dt.date(2026, 10, 14))
        self.assertEqual(saved.name, '2026-10-14-save.db')
        self.assertEqual([p.name for p in app.auto_save_files()],
                         ['2026-10-07-save.db', '2026-10-14-save.db'])
        self.assertFalse((folder / '2026-09-30-save.db').exists())
        self.assertEqual(safety.read_bytes(), b'keep')

    def test_weekly_switch_is_independent_from_existing_close_backup(self):
        self.set_settings(weekly_auto_save=False, auto_backup=True)
        self.assertIsNone(app.maybe_create_weekly_auto_save(dt.date(2026, 10, 14)))
        self.assertEqual(app.auto_save_files(), [])

        app.sync_exit()
        safety = list((self.folder / 'sauvegardes').glob('*.db'))
        self.assertEqual(len(safety), 1)
        self.assertEqual(app.auto_save_files(), [])

    def test_preview_never_creates_an_auto_save(self):
        with patch.object(app, 'PREVIEW', True):
            self.assertIsNone(app.maybe_create_weekly_auto_save(dt.date(2026, 10, 14)))
        self.assertEqual(app.auto_save_files(), [])

    def test_snapshot_failure_keeps_database_and_week_marker_unchanged(self):
        original_database = self.db.read_bytes()
        with patch.object(app, 'write_database_snapshot', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError, 'disk full'):
                app.maybe_create_weekly_auto_save(dt.date(2026, 10, 14))

        self.assertEqual(self.db.read_bytes(), original_database)
        self.assertEqual(app.auto_save_files(), [])
        with app.connect() as primary:
            self.assertEqual(app.settings(primary)['last_auto_save_week'], '')

    def test_missing_data_db_is_detected_but_auto_save_is_not_used_as_the_live_database(self):
        self.add_full_data()
        saved = app.maybe_create_weekly_auto_save(dt.date(2026, 10, 14))
        self.db.unlink()

        self.assertTrue(app.primary_db_has_recovery_copies())
        self.assertEqual(app.DB, self.db)
        app.init_db()
        self.assertEqual(app.DB, self.db)
        self.assertTrue(self.db.is_file())
        self.assertNotEqual(app.DB.resolve(), saved.resolve())
        self.assertFalse(app.primary_db_has_recovery_copies())

        # La récupération lit la copie comme source, mais réinjecte son contenu dans data.db.
        app.PRIMARY_DB_MISSING = True
        app.restore(saved.read_bytes())
        self.assertFalse(app.PRIMARY_DB_MISSING)
        self.assertEqual(app.DB.resolve(), self.db.resolve())
        with app.connect() as primary:
            self.assertEqual(primary.execute('SELECT count(*) FROM scis').fetchone()[0], 1)
        self.assertTrue(saved.is_file())


if __name__ == '__main__':
    unittest.main()
