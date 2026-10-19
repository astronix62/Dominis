"""Régressions v0.0.5 : filtre d'année global, synchronisation et dossiers par SCI.

Ces tests couvrent les défauts corrigés :
  * le filtre d'année de la trésorerie ne filtrait rien côté interface ;
  * l'option « Toutes les années » n'existait pas ;
  * l'aperçu d'un document déclenchait un téléchargement (page blanche) ;
  * les dossiers de classement étaient partagés par toutes les SCI.
"""
import base64
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from test_dominis import app, LOCAL_OPENER

PDF = b'%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n'
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 24
HTML_TRAP = b'<html><script>alert(1)</script></html>'


def open_url(url, data=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token is not None:
        headers['X-Dominis-Token'] = token
    body = json.dumps(data).encode() if data is not None else None
    return LOCAL_OPENER.open(Request(url, data=body, headers=headers), timeout=5)


class FilterAndFolderTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='Dominis filtres ')
        self.addCleanup(self.temp.cleanup)
        self.db_patch = patch.object(app, 'DB', Path(self.temp.name) / 'data.db')
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        app.EXIT_READY.clear()
        app.init_db()
        self.server = app.DominisHTTPServer(('127.0.0.1', 0), app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)
        self.preview_patch = patch.object(app, 'PREVIEW', True)
        self.preview_patch.start()
        self.addCleanup(self.preview_patch.stop)

    def api(self, path, data=None):
        with open_url(self.base + '/api/' + path, data, app.TOKEN) as r:
            return r.status, json.load(r)

    def state(self):
        return self.api('state')[1]

    def two_scis(self):
        with app.connect() as c:
            first = app.save_record(c, {'kind': 'sci', 'data': {'name': 'SCI Littoral'}})
            second = app.save_record(c, {'kind': 'sci', 'data': {'name': 'SCI Opale'}})
        return first, second


class YearFilterTests(FilterAndFolderTestCase):
    def test_year_setting_accepts_all_years_and_rejects_nonsense(self):
        for value, expected in [('all', 'all'), (2023, 2023), ('2024', 2024), (None, 'all')]:
            with self.subTest(value=value):
                self.assertEqual(self.api('settings', {'year': value})[0], 200)
                self.assertEqual(self.state()['settings']['year'], expected)
        for value in (1800, 'abc', [], 3000):
            with self.subTest(value=value):
                with self.assertRaises(HTTPError) as ctx:
                    self.api('settings', {'year': value})
                self.assertEqual(ctx.exception.code, 400)

    def test_normalize_year_setting(self):
        self.assertEqual(app.normalize_year_setting('all'), app.YEAR_ALL)
        self.assertEqual(app.normalize_year_setting(2025), 2025)
        self.assertEqual(app.normalize_year_setting('2025'), 2025)
        self.assertEqual(app.normalize_year_setting(None), app.YEAR_ALL)
        for bad in ('abc', 1800, 3000, {}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                app.normalize_year_setting(bad)

    def test_ui_year_filter_is_global_shared_and_applied_to_the_listing(self):
        # Une seule valeur d'année, partagée par toutes les pages et tous les
        # filtres affichés (en-tête de SCI + barre d'outils de la trésorerie).
        self.assertIn("const YEAR_ALL='all'", app.HTML)
        self.assertIn('Toutes les années', app.HTML)
        self.assertIn('class="year-select"', app.HTML)
        self.assertIn('function syncYearSelects', app.HTML)
        self.assertIn("el.classList.contains('year-select')", app.HTML)
        # Le filtre d'année est réellement appliqué au contenu du tableau.
        self.assertIn('yearMatches(r,kind)', app.HTML)
        self.assertIn("kind==='entries'?String(r.date||'').slice(0,4)===String(activeYear())", app.HTML)
        # Plus de doublon d'identifiant HTML sur le filtre d'année.
        self.assertNotIn('id="year"', app.HTML)
        self.assertIn('id="year-${yearSelectSeq}"', app.HTML)

    def test_imported_years_switch_the_global_filter(self):
        # Un classeur importé sur plusieurs exercices bascule le filtre sur
        # « Toutes les années » : la vue d'ensemble affiche alors les mouvements.
        self.assertIn('b.years.length>1||!b.years.includes(activeYear())', app.HTML)
        self.assertIn('await setPref({year:want})', app.HTML)


class DocumentViewTests(FilterAndFolderTestCase):
    def add_document(self, sci, filename, mime, payload, name=None):
        with app.connect() as c:
            ident = app.save_record(c, {'kind': 'documents', 'sci': sci, 'data': {
                'name': name or filename, 'category': 'Autre', 'date': '2024-03-01',
                'filename': filename, 'mime': mime, 'size': len(payload),
                'blob': base64.b64encode(payload).decode()}})
        return ident

    def test_pdf_preview_is_served_inline_with_its_real_mime(self):
        sci, _ = self.two_scis()
        ident = self.add_document(sci, 'Statuts-signés.pdf', 'application/pdf', PDF)
        with open_url(self.base + '/api/document-view?id=' + ident + '&token=' + app.TOKEN) as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.headers['Content-Type'], 'application/pdf')
            disposition = r.headers['Content-Disposition']
            self.assertTrue(disposition.startswith('inline;'), disposition)
            self.assertIn("filename*=UTF-8''Statuts-sign%C3%A9s.pdf", disposition)
            self.assertEqual(r.read(), PDF)
        # Le bouton « Télécharger » conserve un vrai téléchargement.
        with open_url(self.base + '/api/document?id=' + ident + '&token=' + app.TOKEN) as r:
            self.assertTrue(r.headers['Content-Disposition'].startswith('attachment;'))
            self.assertEqual(r.headers['Content-Type'], 'application/octet-stream')

    def test_preview_payload_points_to_the_inline_endpoint(self):
        sci, _ = self.two_scis()
        ident = self.add_document(sci, 'rapport.pdf', 'application/pdf', PDF)
        with open_url(self.base + '/api/document-preview?id=' + ident + '&token=' + app.TOKEN) as r:
            preview = json.load(r)
        self.assertEqual(preview['preview_type'], 'pdf')
        self.assertEqual(preview['view_url'], '/api/document-view?id=' + ident)
        # L'interface n'ouvre plus le téléchargement dans le cadre d'aperçu.
        self.assertIn('/api/document-view?id=', app.HTML)
        self.assertNotIn('<iframe class="doc-preview-frame" src="/api/document?id=', app.HTML)

    def test_html_and_unknown_formats_are_never_rendered_inline(self):
        sci, _ = self.two_scis()
        trapped = self.add_document(sci, 'piege.html', 'text/html', HTML_TRAP)
        with open_url(self.base + '/api/document-view?id=' + trapped + '&token=' + app.TOKEN) as r:
            # Un fichier importé ne doit pas pouvoir exécuter de script dans
            # l'origine qui porte le jeton de session.
            self.assertNotIn('text/html', r.headers['Content-Type'])
        archive = self.add_document(sci, 'archive.zip', 'application/zip', b'PK\x03\x04pas un classeur')
        with self.assertRaises(HTTPError) as ctx:
            open_url(self.base + '/api/document-view?id=' + archive + '&token=' + app.TOKEN)
        self.assertEqual(ctx.exception.code, 400)

    def test_document_view_mime_helper(self):
        cases = [
            ('a.pdf', '', PDF, 'application/pdf', True),
            ('a.png', '', PNG, 'image/png', True),
            ('sans-extension', 'application/pdf', PDF, 'application/pdf', True),
            ('a.html', 'text/html', HTML_TRAP, 'text/plain; charset=utf-8', True),
            ('a.svg', 'image/svg+xml', b'<svg/>', 'application/octet-stream', False),
            ('a.zip', 'application/zip', b'PK\x03\x04', 'application/octet-stream', False),
        ]
        for filename, declared, raw, mime, viewable in cases:
            with self.subTest(filename=filename):
                self.assertEqual(app.document_view_mime(filename, declared, raw), (mime, viewable))


class DocFoldersPerSciTests(FilterAndFolderTestCase):
    def test_new_sci_receives_its_own_default_folders(self):
        first, second = self.two_scis()
        folders = self.state()['settings']['doc_folders_by_sci']
        self.assertEqual(set(folders), {first, second})
        self.assertEqual([f['id'] for f in folders[first]],
                         [f['id'] for f in app.DEFAULT_DOC_FOLDERS])
        # Deux sociétés distinctes : deux listes distinctes, pas un objet partagé.
        self.assertIsNot(folders[first], folders[second])

    def test_renaming_a_folder_does_not_touch_the_other_sci(self):
        first, second = self.two_scis()
        folders = self.state()['settings']['doc_folders_by_sci']
        folders[first][0]['name'] = 'Statuts SCI Littoral'
        folders[first].append({'id': 'f-contentieux', 'name': 'Contentieux'})
        self.assertEqual(self.api('settings', {'doc_folders_by_sci': folders})[0], 200)
        stored = self.state()['settings']['doc_folders_by_sci']
        self.assertEqual(stored[first][0]['name'], 'Statuts SCI Littoral')
        self.assertIn('f-contentieux', [f['id'] for f in stored[first]])
        self.assertEqual(stored[second][0]['name'], 'Statuts & vie sociale')
        self.assertNotIn('f-contentieux', [f['id'] for f in stored[second]])

    def test_deleting_a_default_folder_only_affects_one_sci(self):
        first, second = self.two_scis()
        folders = self.state()['settings']['doc_folders_by_sci']
        folders[second] = [f for f in folders[second] if f['id'] != 'f-statuts']
        self.api('settings', {'doc_folders_by_sci': folders})
        stored = self.state()['settings']['doc_folders_by_sci']
        self.assertNotIn('f-statuts', [f['id'] for f in stored[second]])
        self.assertIn('f-statuts', [f['id'] for f in stored[first]])

    def test_folder_order_is_preserved_per_sci(self):
        first, _ = self.two_scis()
        folders = self.state()['settings']['doc_folders_by_sci']
        reordered = list(reversed(folders[first]))
        self.api('settings', {'doc_folders_by_sci': {first: reordered}})
        stored = self.state()['settings']['doc_folders_by_sci']
        self.assertEqual([f['id'] for f in stored[first]],
                         list(reversed([f['id'] for f in app.DEFAULT_DOC_FOLDERS])))

    def test_invalid_folder_settings_are_rejected(self):
        first, _ = self.two_scis()
        for bad in ('Statuts', [1, 2], {first: 'pas-une-liste'}):
            with self.subTest(bad=bad), self.assertRaises(HTTPError) as ctx:
                self.api('settings', {'doc_folders_by_sci': bad})
            self.assertEqual(ctx.exception.code, 400)

    def test_legacy_global_folders_are_migrated_into_every_sci(self):
        first, second = self.two_scis()
        with app.connect() as c:
            preferences = app.settings(c)
            preferences.pop('doc_folders_by_sci', None)
            preferences['doc_folders'] = [{'id': 'f-statuts', 'name': 'Statuts & AG'},
                                          {'id': 'f-perso', 'name': 'Contentieux'}]
            c.execute("UPDATE meta SET value=? WHERE key='settings'", (json.dumps(preferences),))
        folders = self.state()['settings']['doc_folders_by_sci']
        for sci in (first, second):
            names = {f['id']: f['name'] for f in folders[sci]}
            # Le renommage existant est conservé, le dossier personnel est repris.
            self.assertEqual(names['f-statuts'], 'Statuts & AG')
            self.assertEqual(names['f-perso'], 'Contentieux')
            # Les dossiers par défaut absents de l'ancienne liste sont rétablis.
            self.assertIn('f-immobilier', names)

    def test_deleting_a_sci_removes_its_folders(self):
        first, second = self.two_scis()
        self.assertEqual(self.api('delete', {'kind': 'sci', 'id': first,
                                             'confirmation': 'SCI Littoral'})[0], 200)
        folders = self.state()['settings']['doc_folders_by_sci']
        self.assertNotIn(first, folders)
        self.assertIn(second, folders)

    def test_imported_sci_receives_its_folders(self):
        bundle = {'application': 'Dominis', 'version': 1,
                  'scis': [{'id': 'source', 'name': 'SCI Importée'}],
                  'records': [{'id': 'r1', 'kind': 'entries', 'sci': 'source',
                               'label': 'Loyer', 'date': '2023-05-01',
                               'direction': 'Recette', 'category': 'Loyers', 'amount': 800}]}
        payload = {'format': 'json', 'text': json.dumps(bundle), 'mapping': {'source': 'new'}}
        self.assertEqual(self.api('import', payload)[0], 200)
        scis = self.state()['scis']
        self.assertEqual(len(scis), 1)
        folders = self.state()['settings']['doc_folders_by_sci']
        self.assertIn(scis[0]['id'], folders)
        self.assertEqual([f['id'] for f in folders[scis[0]['id']]],
                         [f['id'] for f in app.DEFAULT_DOC_FOLDERS])

    def test_ui_keeps_folders_scoped_to_the_current_sci(self):
        self.assertIn('function sciDocFolders', app.HTML)
        self.assertIn('function docScope()', app.HTML)
        self.assertIn("doc_folders_by_sci", app.HTML)
        self.assertIn('resolveDocFolder(r){\n    let folders=sciDocFolders(r?.sci);', app.HTML)
        # Les compteurs de dossiers ne mélangent plus les sociétés.
        self.assertIn("rows('documents',scoped)", app.HTML)
        self.assertNotIn("function folderDocCount(id){return rows('documents')", app.HTML)
        # Renommer un dossier propose aussi sa suppression, et l'ordre est réglable.
        self.assertIn("$('#manage-folder-delete').onclick=()=>deleteDocFolder(id)", app.HTML)
        self.assertIn('data-folder-move', app.HTML)
        self.assertIn('doc-folder-all', app.HTML)
        self.assertIn('restoreDefaultDocFolders', app.HTML)


class VersionTests(unittest.TestCase):
    def test_application_version_is_v005(self):
        self.assertEqual(app.APP_VERSION, 'v0.0.5')


if __name__ == '__main__':
    unittest.main()
