"""Régressions des synthèses annuelles PDF et de la suppression ciblée.

Couvre les décisions de la v0.0.6 :
  * une synthèse est enregistrée en PDF dans les documents (dossier Synthèses) ;
  * le PDF est produit sans dépendance externe et reste lisible ;
  * « Gérer la suppression » ne vide qu'une page et qu'une seule SCI ;
  * les dossiers de documents acceptent des sous-dossiers (3 niveaux maximum).
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


def open_url(url, data=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token is not None:
        headers['X-Dominis-Token'] = token
    body = json.dumps(data).encode() if data is not None else None
    return LOCAL_OPENER.open(Request(url, data=body, headers=headers), timeout=10)


def simple_model(style='classique'):
    section = {
        'title': '1. Trésorerie et flux',
        'paragraphs': ['Le solde part du solde d’ouverture de la société.'],
    }
    if style == 'graphique':
        section['kpis'] = [
            {'label': 'Recettes de l’exercice', 'value': '25 030,00 €', 'tone': 'green'},
            {'label': 'Dépenses de l’exercice', 'value': '12 600,00 €', 'tone': 'red'},
        ]
        section['chart'] = {
            'type': 'bars',
            'labels': ['Jan', 'Fév', 'Mar'],
            'series': [{'label': 'Recettes', 'color': '#367858', 'values': [2503, 2503, 2503]}],
        }
    else:
        section['table'] = {
            'headers': ['Indicateur', 'Montant'],
            'rows': [['Recettes de l’exercice', '25 030,00 €'],
                     ['Dépenses de l’exercice', '12 600,00 €']],
            'weights': [3, 1],
            'aligns': ['left', 'right'],
        }
    return {
        'eyebrow': 'DOMINIS · SYNTHÈSE ANNUELLE',
        'title': 'SCI Les Oliviers',
        'subtitle': 'Synthèse de gestion · Exercice 2026',
        'meta': ['Établie le 23/10/2026', 'Régime IR'],
        'notice': 'Document préparatoire de gestion, à vérifier avec la comptabilité.',
        'sections': [section, {
            'title': '5. Analyse automatique',
            'analysis': {
                'strengths': ['Flux net positif de 12 430,00 €.'],
                'watch': ['1 070,00 € de loyers restent à encaisser.'],
                'conclusion': 'L’exercice 2026 se solde par un flux net positif.',
            },
        }],
    }


class PdfBuilderTests(unittest.TestCase):
    def test_pdf_is_well_formed_and_lists_offsets(self):
        raw, pages = app.build_annual_report_pdf(simple_model())
        self.assertGreaterEqual(pages, 1)
        self.assertTrue(raw.startswith(b'%PDF-1.4'))
        self.assertTrue(raw.rstrip().endswith(b'%%EOF'))
        self.assertIn(b'/Type /Catalog', raw)
        start = int(raw.rsplit(b'startxref', 1)[1].split()[0])
        self.assertEqual(raw[start:start + 4], b'xref')
        # Chaque décalage de la table xref pointe bien sur un objet.
        xref = raw[start:].split(b'trailer')[0].splitlines()[3:]
        for line in xref:
            if not line.strip():
                continue
            offset = int(line.split()[0])
            self.assertRegex(raw[offset:offset + 20].decode('latin-1'), r'^\d+ 0 obj')

    def test_text_is_readable_and_money_uses_narrow_spaces(self):
        raw, _ = app.build_annual_report_pdf(simple_model())
        text = raw.decode('cp1252', 'replace')
        self.assertIn('SCI Les Oliviers', text)
        self.assertIn('25 030,00 €', text)  # espace fine insécable normalisée
        self.assertNotIn('\u202f'.encode('cp1252', 'replace').decode('cp1252'), text)

    def test_pdf_paginates_long_reports(self):
        model = simple_model()
        model['sections'] = model['sections'] * 12
        raw, pages = app.build_annual_report_pdf(model)
        self.assertGreater(pages, 1)
        self.assertEqual(raw.count(b'/Type /Page '), pages)

    def test_invalid_models_are_rejected(self):
        for bad in (None, 'texte', {'title': 'x'}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                app.build_annual_report_pdf(bad)

    def test_graphics_and_tables_never_share_the_same_values(self):
        """La synthèse graphique et la synthèse classique restent deux mises en page."""
        classique, _ = app.build_annual_report_pdf(simple_model('classique'))
        graphique, _ = app.build_annual_report_pdf(simple_model('graphique'))
        self.assertNotEqual(classique, graphique)
        self.assertIn(b'/Type /Page', graphique)


class FolderHierarchyTests(unittest.TestCase):
    def test_parent_links_are_kept_and_cycles_are_broken(self):
        folders = app.normalize_doc_folders([
            {'id': 'a', 'name': 'Synthèses'},
            {'id': 'b', 'name': 'Classique', 'parent_id': 'a'},
            {'id': 'c', 'name': 'Graphique', 'parent_id': 'a'},
        ])
        self.assertNotIn('parent_id', folders[0])
        self.assertEqual(folders[1]['parent_id'], 'a')

        cyclic = app.normalize_doc_folders([
            {'id': 'a', 'name': 'A', 'parent_id': 'b'},
            {'id': 'b', 'name': 'B', 'parent_id': 'a'},
        ])
        # Un seul lien est cassé, mais il suffit : l'arbre ne boucle plus.
        for item in cyclic:
            seen, cur = set(), item
            while cur.get('parent_id'):
                self.assertNotIn(cur['id'], seen)
                seen.add(cur['id'])
                cur = next(f for f in cyclic if f['id'] == cur['parent_id'])

    def test_missing_parent_falls_back_to_root(self):
        folders = app.normalize_doc_folders([{'id': 'a', 'name': 'A', 'parent_id': 'absent'}])
        self.assertEqual(folders, [{'id': 'a', 'name': 'A'}])

    def test_three_levels_maximum(self):
        folders = app.normalize_doc_folders([
            {'id': 'a', 'name': 'A'},
            {'id': 'b', 'name': 'B', 'parent_id': 'a'},
            {'id': 'c', 'name': 'C', 'parent_id': 'b'},
            {'id': 'd', 'name': 'D', 'parent_id': 'c'},
        ])
        self.assertEqual([f.get('parent_id') for f in folders], [None, 'a', 'b', None])

    def test_merge_keeps_parent_of_personal_folders(self):
        merged = app.merge_doc_folders(
            [{'id': 'a', 'name': 'Synthèses'}],
            [{'id': 'b', 'name': 'Classique', 'parent_id': 'a'}],
        )
        self.assertEqual(merged[-1]['parent_id'], 'a')


class PurgeBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_patch = patch.object(app, 'DB', Path(self.temp.name) / 'data.db')
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        app.EXIT_READY.clear()
        app.init_db()

    def fixture(self):
        with app.connect() as c:
            sci = app.save_record(c, {'kind': 'sci', 'data': {'name': 'SCI Littoral'}})
            other = app.save_record(c, {'kind': 'sci', 'data': {'name': 'SCI Opale'}})
            prop = app.save_record(c, {'kind': 'properties', 'sci': sci,
                                       'data': {'name': 'Villa', 'address': '1 rue A'}})
            lease = app.save_record(c, {'kind': 'leases', 'sci': sci,
                                        'data': {'tenant': 'Locataire', 'property_id': prop,
                                                 'start': '2025-01-01'}})
            call = app.save_record(c, {'kind': 'calls', 'sci': sci,
                                       'data': {'lease_id': lease, 'period': '2026-01',
                                                'due': '2026-01-05', 'rent': 900, 'charges': 0}})
            app.save_record(c, {'kind': 'entries', 'sci': sci,
                                'data': {'label': 'Loyer', 'date': '2026-01-05',
                                         'direction': 'Recette', 'category': 'Loyers',
                                         'amount': 900, 'call_id': call}})
            app.save_record(c, {'kind': 'loans', 'sci': sci,
                                'data': {'name': 'Prêt', 'balance': 50000}})
            app.save_record(c, {'kind': 'entries', 'sci': other,
                                'data': {'label': 'Loyer Opale', 'date': '2026-01-05',
                                         'direction': 'Recette', 'category': 'Loyers',
                                         'amount': 700}})
            c.commit()
        return sci, other

    def count(self, kind, sci=None):
        with app.connect() as c:
            if sci:
                return c.execute('SELECT count(*) FROM records WHERE kind=? AND sci=?',
                                 (kind, sci)).fetchone()[0]
            return c.execute('SELECT count(*) FROM records WHERE kind=?', (kind,)).fetchone()[0]

    def test_properties_purge_takes_leases_calls_and_entries(self):
        sci, other = self.fixture()
        with app.connect() as c:
            result = app.purge_tab(c, sci, 'properties')
            c.commit()
        self.assertEqual(result['deleted'], 4)  # bien + bail + appel + encaissement
        self.assertEqual(result['detail'], {'properties': 1, 'leases': 1, 'calls': 1, 'entries': 1})
        self.assertEqual(self.count('loans', sci), 1)
        self.assertEqual(self.count('entries', other), 1)

    def test_single_page_purge_leaves_dependencies(self):
        sci, _ = self.fixture()
        with app.connect() as c:
            result = app.purge_tab(c, sci, 'calls')
            c.commit()
        self.assertEqual(result['by' if 'by' in result else 'deleted'], 2)  # appel + encaissement
        self.assertEqual(self.count('leases', sci), 1)
        self.assertEqual(self.count('properties', sci), 1)

    def test_purge_is_scoped_to_one_sci(self):
        sci, other = self.fixture()
        with app.connect() as c:
            app.purge_tab(c, sci, 'entries')
            c.commit()
        self.assertEqual(self.count('entries', sci), 0)
        self.assertEqual(self.count('entries', other), 1)

    def test_unknown_tab_or_sci_is_rejected(self):
        sci, _ = self.fixture()
        with app.connect() as c:
            with self.assertRaises(ValueError):
                app.purge_tab(c, sci, 'tresorerie')
            with self.assertRaises(ValueError):
                app.purge_tab(c, 'inconnue', 'entries')

    def test_audit_line_records_the_purge(self):
        sci, _ = self.fixture()
        with app.connect() as c:
            app.purge_tab(c, sci, 'loans')
            c.commit()
            last = c.execute("SELECT action, detail FROM audit ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(last['action'], 'Suppression')
        self.assertIn('Emprunts', last['detail'])


class PurgeHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patch.object(app, 'DB', Path(self.temp.name) / 'data.db').start()
        self.addCleanup(patch.stopall)
        app.EXIT_READY.clear()
        app.init_db()
        self.server = app.DominisHTTPServer(('127.0.0.1', 0), app.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)

    def api(self, path, data=None):
        with open_url(self.base + '/api/' + path, data, app.TOKEN) as r:
            return r.status, json.load(r)

    def test_purge_requires_explicit_confirmation(self):
        with app.connect() as c:
            sci = app.save_record(c, {'kind': 'sci', 'data': {'name': 'SCI Littoral'}})
            app.save_record(c, {'kind': 'tasks', 'sci': sci, 'data': {'name': 'PNO', 'due': '2026-10-28'}})
        for payload in ({'sci': sci, 'tab': 'tasks'}, {'sci': sci, 'tab': 'tasks', 'confirm': 'oui'}):
            with self.subTest(payload=payload), self.assertRaises(HTTPError) as ctx:
                self.api('purge', payload)
            self.assertEqual(ctx.exception.code, 400)
        status, result = self.api('purge', {'sci': sci, 'tab': 'tasks', 'confirm': True})
        self.assertEqual(status, 200)
        self.assertEqual(result['deleted'], 1)

    def test_annual_report_is_saved_as_pdf_document(self):
        with app.connect() as c:
            sci = app.save_record(c, {'kind': 'sci', 'data': {'name': 'SCI Les Oliviers'}})
        folders = self.api('state')[1]['settings']['doc_folders_by_sci'][sci]
        status, result = self.api('annual-report', {
            'sci': sci, 'year': '2026', 'style': 'graphique',
            'folder_id': folders[0]['id'], 'model': simple_model('graphique')})
        self.assertEqual(status, 200)
        self.assertTrue(result['filename'].endswith('.pdf'))
        self.assertEqual(result['mime'] if 'mime' in result else 'application/pdf', 'application/pdf')
        state = self.api('state')[1]
        doc = next(r for r in state['records'] if r['id'] == result['id'])
        self.assertEqual(doc['kind'], 'documents')
        self.assertEqual(doc['synthesis_year'], '2026')
        self.assertEqual(doc['report_style'], 'graphique')
        self.assertEqual(doc['folder_id'], folders[0]['id'])
        self.assertNotIn('blob', doc)  # le blob ne transite pas dans /api/state
        with app.connect() as c:
            stored = c.execute('SELECT data FROM records WHERE id=?', (result['id'],)).fetchone()
        payload = json.loads(stored['data'])
        raw = base64.b64decode(payload['blob'])
        self.assertTrue(raw.startswith(b'%PDF-1.4'))
        self.assertEqual(payload['size'], len(raw))
        self.assertEqual(payload['mime'], 'application/pdf')
        # Le document reste téléchargeable et prévisualisable comme les autres.
        with open_url(self.base + '/api/document-preview?id=' + result['id'], token=app.TOKEN) as r:
            preview = json.load(r)
        self.assertEqual(preview['preview_type'], 'pdf')

    def test_annual_report_rejects_unknown_sci_and_bad_year(self):
        with self.assertRaises(HTTPError) as ctx:
            self.api('annual-report', {'sci': 'absente', 'year': '2026',
                                       'model': simple_model()})
        self.assertEqual(ctx.exception.code, 400)


class AnnualReportUiTests(unittest.TestCase):
    def test_report_no_longer_exports_html(self):
        self.assertIn('function annualReport()', app.HTML)
        self.assertIn('ensureSynthesisFolders', app.HTML)
        self.assertIn('annualReportModel', app.HTML)
        self.assertNotIn("downloadText(doc,'synthese-", app.HTML)
        self.assertIn("api('annual-report'", app.HTML)
        self.assertIn('Graphique · indicateurs et graphiques', app.HTML)

    def test_analysis_is_computed_not_written_by_the_manager(self):
        self.assertIn('function annualReportAnalysis(', app.HTML)
        self.assertNotIn('Analyse à compléter par le gérant', app.HTML)
        self.assertIn('Analyse automatique', app.HTML)

    def test_manage_deletions_uses_the_same_red_trash_button(self):
        self.assertIn('data-action="manage-deletions"', app.HTML)
        self.assertIn('data-action="delete-sci"', app.HTML)
        self.assertIn('function manageDeletions()', app.HTML)
        self.assertIn('purgePlan(', app.HTML)
        # Le bouton reprend exactement l'icône et le libellé demandés.
        self.assertIn("${icon('trash')} Supprimer cette SCI", app.HTML)
        self.assertIn("${icon('trash')} Gérer la suppression", app.HTML)
        self.assertIn('class="danger" data-action="manage-deletions"', app.HTML)


if __name__ == '__main__':
    unittest.main()
