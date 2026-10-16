"""Import Excel (.xlsx) : tableaux Date / Libellé / Débit / Crédit / Solde.

Le classeur de référence reproduit fidèlement la structure observée dans un
relevé réel (titres, en-tête, solde d'ouverture, mouvements, clôtures
mensuelles et ligne de totaux), sans qu'aucune donnée de exemple ne soit
intégrée à l'application.
"""
import base64
import datetime as dt
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from test_dominis import app

NS_MAIN = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
NS_PKG = 'http://schemas.openxmlformats.org/package/2006/relationships'
NS_OD = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'

MONEY = 1      # style montant (format personnalisé « #,##0.00 € »)
DATE_C = 2     # style date au format personnalisé « dd/mm/yy »
DATE_B = 3     # style date au format intégré 14

HEADER = [(0, 'inline', 'Date'), (1, 'inline', 'Libellé'), (2, 'inline', 'Débit'),
          (3, 'inline', 'Crédit'), (4, 'inline', 'Solde')]


def serial(day):
    return (day - dt.date(1899, 12, 30)).days


def xml_esc(value):
    return (str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            .replace('"', '&quot;'))


def col_ref(i):
    n, letters = i + 1, ''
    while n:
        n, r = divmod(n - 1, 26)
        letters = chr(65 + r) + letters
    return letters


def build_xlsx(sheets, numfmts=None, cell_xfs=None):
    """Construit un .xlsx minimal mais conforme.

    sheets : [(nom, lignes)] — une ligne est None (ligne omise : le trou marque
    une ligne vide) ou une liste de cellules (colonne, type, valeur[, style]).
    Types : 'inline', 'shared', 'n' (numérique), 'iso' (date Excel t="d"),
    'str' (résultat de formule mis en cache).
    """
    numfmts = numfmts or {}
    xfs = cell_xfs or [0]
    shared_list, shared_index, sheet_parts = [], {}, []
    for _name, rows in sheets:
        parts = []
        for rn, cells in enumerate(rows, 1):
            if cells is None:
                continue
            cell_xml = []
            for spec in cells:
                col, kind, value = spec[0], spec[1], spec[2]
                style = spec[3] if len(spec) > 3 else None
                attrs = ' r="%s%d"' % (col_ref(col), rn)
                if kind == 'inline':
                    attrs += ' t="inlineStr"'
                    body = '<is><t xml:space="preserve">%s</t></is>' % xml_esc(value)
                elif kind == 'shared':
                    if value not in shared_index:
                        shared_index[value] = len(shared_list)
                        shared_list.append(value)
                    attrs += ' t="s"'
                    body = '<v>%d</v>' % shared_index[value]
                elif kind == 'n':
                    body = '<v>%s</v>' % repr(float(value))
                elif kind == 'iso':
                    attrs += ' t="d"'
                    body = '<v>%sT00:00:00</v>' % value
                elif kind == 'str':
                    attrs += ' t="str"'
                    body = '<v>%s</v>' % xml_esc(value)
                else:
                    raise AssertionError('type de cellule inconnu : %r' % (kind,))
                if style is not None:
                    attrs += ' s="%d"' % style
                cell_xml.append('<c%s>%s</c>' % (attrs, body))
            parts.append('<row r="%d">%s</row>' % (rn, ''.join(cell_xml)))
        sheet_parts.append(''.join(parts))

    sst = ''
    if shared_list:
        sst = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<sst xmlns="%s" count="%d" uniqueCount="%d">%s</sst>'
               % (NS_MAIN, len(shared_list), len(shared_list),
                  ''.join('<si><t xml:space="preserve">%s</t></si>' % xml_esc(v) for v in shared_list)))

    numfmt_xml = ''
    if numfmts:
        numfmt_xml = '<numFmts count="%d">%s</numFmts>' % (
            len(numfmts),
            ''.join('<numFmt numFmtId="%d" formatCode="%s"/>' % (k, xml_esc(v)) for k, v in numfmts.items()))
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="%s">%s<cellXfs count="%d">%s</cellXfs></styleSheet>'
              % (NS_MAIN, numfmt_xml, len(xfs),
                 ''.join('<xf numFmtId="%d" applyNumberFormat="1"/>' % fid for fid in xfs)))

    workbook_sheets, rel_entries, overrides = [], [], []
    for i, (name, _rows) in enumerate(sheets, 1):
        workbook_sheets.append('<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (xml_esc(name), i, i))
        rel_entries.append('<Relationship Id="rId%d" Type="%s/worksheet" Target="worksheets/sheet%d.xml"/>'
                           % (i, NS_OD, i))
        overrides.append('<Override PartName="/xl/worksheets/sheet%d.xml" '
                         'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                         % i)
    rel_entries.append('<Relationship Id="rId%d" Type="%s/styles" Target="styles.xml"/>' % (len(sheets) + 1, NS_OD))
    if shared_list:
        rel_entries.append('<Relationship Id="rId%d" Type="%s/sharedStrings" Target="sharedStrings.xml"/>'
                           % (len(sheets) + 2, NS_OD))

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        + ''.join(overrides) +
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        + ('<Override PartName="/xl/sharedStrings.xml" '
           'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
           if shared_list else '') +
        '</Types>')
    root_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="%s"><Relationship Id="rId1" Type="%s/officeDocument" '
                 'Target="xl/workbook.xml"/></Relationships>' % (NS_PKG, NS_OD))
    workbook = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="%s" xmlns:r="%s"><sheets>%s</sheets></workbook>'
                % (NS_MAIN, NS_OD, ''.join(workbook_sheets)))
    wb_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               '<Relationships xmlns="%s">%s</Relationships>' % (NS_PKG, ''.join(rel_entries)))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', content_types)
        z.writestr('_rels/.rels', root_rels)
        z.writestr('xl/workbook.xml', workbook)
        z.writestr('xl/_rels/workbook.xml.rels', wb_rels)
        z.writestr('xl/styles.xml', styles)
        if shared_list:
            z.writestr('xl/sharedStrings.xml', sst)
        for i, part in enumerate(sheet_parts, 1):
            z.writestr('xl/worksheets/sheet%d.xml' % i,
                       '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                       '<worksheet xmlns="%s"><sheetData>%s</sheetData></worksheet>' % (NS_MAIN, part))
    return buf.getvalue()


def b64(data):
    return base64.b64encode(data).decode('ascii')


def t(col, value):
    return (col, 'shared', value)


def n(col, value, style=MONEY):
    return (col, 'n', value, style)


def movement(date_s, label, debit=None, credit=None):
    cells = [t(0, date_s), t(1, label)]
    if debit is not None:
        cells.append(n(2, debit))
    if credit is not None:
        cells.append(n(3, credit))
    return cells


def sample_rows():
    """Reproduction stricte du tableau de l'échantillon (structure uniquement)."""
    return [
        [t(0, 'SCI 52 RUE LOUGUET')],
        [t(0, 'BNP PARISBAS 2026')],
        None,
        HEADER,
        [t(0, '31/12/25'), n(4, 32155.66)],
        movement('02/01/26', 'VIREMENT MLE BOUVELET', credit=490.00),
        movement('05/01/26', 'VIREMENT DE MADAME FORSCHLE MICHELE', credit=565.00),
        movement('12/01/26', 'VIREMENT LA MIE DU COIN', credit=690.00),
        movement('05/01/26', 'COMMISSIONS', debit=4.15),
        [t(0, '31/01/26'), n(4, 33896.51)],
        movement('02/02/26', 'VIREMENT M. PIRAS CHRISTOPHER CAUTION', credit=490.00),
        movement('02/02/26', 'VIREMENT M. PIRAS CHRISTOPHER', credit=490.00),
        movement('03/02/26', 'COMMISSIONS', debit=4.15),
        movement('05/02/26', 'VIREMENT DE MADAME FORSCHLE MICHELE', credit=565.00),
        movement('10/02/26', 'VIREMENT LA MIE DU COIN', credit=690.00),
        movement('06/02/26', 'REMBOURSEMENT FACTURE MLE BOUVELET', debit=10.00),
        movement('06/02/26', 'RESTITUTION CAUTION MLE BOUVELET', debit=490.00),
        movement('11/02/26', 'LEROY MERLIN', debit=5.99),
        movement('11/02/26', 'GAUDELOT', debit=12.00),
        movement('11/02/26', 'LEROY MERLIN', debit=62.78),
        [t(0, '28/02/26'), n(2, 584.92), n(3, 2235.00), n(4, 35546.59)],
    ]


def sample_xlsx():
    return build_xlsx([('Relevés', sample_rows())],
                      numfmts={164: '#,##0.00" €"'}, cell_xfs=[0, 164])


def parse(data, fmt='xlsx'):
    return app.parse_import({'format': fmt, 'text': b64(data) if isinstance(data, bytes) else data})


class XlsxParseTests(unittest.TestCase):
    """Lecture des tableaux : classification, regroupement, contrôles, erreurs."""

    def test_sample_from_screenshot_structure(self):
        bundle = parse(sample_xlsx())
        records = bundle['records']
        self.assertEqual(len(records), 14)
        self.assertEqual(bundle['warnings'], [])
        self.assertEqual(len(bundle['scis']), 1)
        source = bundle['scis'][0]
        self.assertEqual(source['name'], 'SCI 52 RUE LOUGUET')
        self.assertEqual(source['opening'], 32155.66)
        self.assertEqual(source['opening_date'], '2025-12-31')
        recettes = [r for r in records if r['direction'] == 'Recette']
        depenses = [r for r in records if r['direction'] == 'Dépense']
        self.assertEqual(len(recettes), 7)
        self.assertEqual(len(depenses), 7)
        self.assertEqual(round(sum(r['amount'] for r in recettes), 2), 3980.00)
        # total annuel : 4,15 € (janvier) + 584,92 € (total de février annoncé en ligne de clôture)
        self.assertEqual(round(sum(r['amount'] for r in depenses), 2), 589.07)
        first = records[0]
        self.assertEqual((first['date'], first['label'], first['direction'], first['amount']),
                         ('2026-01-02', 'VIREMENT MLE BOUVELET', 'Recette', 490.0))
        caution = [r for r in records if r['label'] == 'RESTITUTION CAUTION MLE BOUVELET'][0]
        self.assertEqual((caution['direction'], caution['amount']), ('Dépense', 490.0))
        self.assertTrue(all(len(r['date']) == 10 and r['date'][4] == '-' for r in records))
        self.assertTrue(all(r['sci'] == source['id'] for r in records))
        self.assertTrue(all(r['kind'] == 'entries' for r in records))

    def test_serial_dates_and_french_text_amounts(self):
        rows = [
            [t(0, 'SCI SÉRIAUX')],
            None,
            HEADER,
            [n(0, serial(dt.date(2025, 12, 31)), DATE_C), (4, 'shared', '32\u00a0155,66 €')],
            [n(0, serial(dt.date(2026, 1, 5)), DATE_B), t(1, 'Virement loyer'), (3, 'shared', '490,00 €')],
            [n(0, serial(dt.date(2026, 1, 6)), DATE_C), t(1, 'Commission'), (2, 'shared', '4,15 €')],
            [n(0, serial(dt.date(2026, 1, 31)), DATE_C), (4, 'shared', '32\u202f641,51 €')],
        ]
        bundle = parse(build_xlsx([('Sérial', rows)],
                                  numfmts={164: '#,##0.00" €"', 165: 'dd/mm/yy'},
                                  cell_xfs=[0, 164, 165, 14]))
        self.assertEqual(bundle['warnings'], [])
        records = bundle['records']
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]['date'], '2026-01-05')
        self.assertEqual(records[0]['direction'], 'Recette')
        self.assertEqual(records[0]['amount'], 490.0)
        self.assertEqual(records[1]['date'], '2026-01-06')
        self.assertEqual(records[1]['direction'], 'Dépense')
        self.assertEqual(records[1]['amount'], 4.15)
        self.assertEqual(bundle['scis'][0]['opening'], 32155.66)

    def test_header_variants_repeated_header_category_and_cache(self):
        header = [(0, 'inline', 'DATE'), (1, 'inline', 'LIBELLÉ'), (2, 'inline', 'Débit (€)'),
                  (3, 'inline', 'CRÉDIT'), (4, 'inline', 'Solde (€)'), (5, 'inline', 'Catégorie'),
                  (6, 'inline', 'Référence')]
        rows = [
            [t(0, 'SCI HEADERS')], None, header,
            [t(0, '01/06/26'), t(1, 'Travaux toiture'), n(2, 120.0), t(5, 'Travaux'), t(6, 'FACT-01')],
            header,  # en-tête répété (saut de page)
            [t(0, '02/06/26'), (1, 'str', 'Virement formule'), n(3, 700.0), t(5, 'Loyers')],
            [(0, 'iso', '2026-06-03'), t(1, 'Date ISO native'), n(3, 50.0)],
        ]
        bundle = parse(build_xlsx([('Divers', rows)],
                                  numfmts={164: '#,##0.00" €"'}, cell_xfs=[0, 164]))
        self.assertEqual(bundle['warnings'], [])
        records = bundle['records']
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0]['category'], 'Travaux')
        self.assertEqual(records[1]['label'], 'Virement formule')
        self.assertEqual(records[2]['date'], '2026-06-03')
        self.assertEqual([r['direction'] for r in records], ['Dépense', 'Recette', 'Recette'])

    def test_multiple_tables_and_sheets_grouping(self):
        sheet1 = [
            [t(0, 'SCI ALPHA')], [t(0, 'BNP 2025')], None, HEADER,
            movement('01/03/26', 'Loyer A', credit=100),
            None,
            [t(0, 'SCI ALPHA')], None, HEADER,
            movement('01/04/26', 'Loyer A2', credit=100),
            None,
            [t(0, 'SCI BETA')], None, HEADER,
            [t(0, '01/04/26'), n(4, 700.0)],
            movement('01/05/26', 'Loyer B', credit=50),
        ]
        sheet2 = [
            None,
            HEADER,
            movement('01/06/26', 'Loyer C', credit=60),
        ]
        bundle = parse(build_xlsx([('FEUILLE-UN', sheet1), ('Feuil2', sheet2)],
                                  numfmts={164: '#,##0.00" €"'}, cell_xfs=[0, 164]))
        self.assertEqual(bundle['warnings'], [])
        by_name = {s['name']: s for s in bundle['scis']}
        self.assertEqual(set(by_name), {'SCI ALPHA', 'SCI BETA', 'Tableau 1 · Feuil2'})
        counts = {name: sum(1 for r in bundle['records'] if r['sci'] == sid['id'])
                  for name, sid in by_name.items()}
        self.assertEqual(counts, {'SCI ALPHA': 2, 'SCI BETA': 1, 'Tableau 1 · Feuil2': 1})
        # chaque source reçoit son propre solde d'ouverture, indépendamment des autres
        self.assertEqual(by_name['SCI BETA'].get('opening'), 700.0)
        self.assertEqual(by_name['SCI BETA'].get('opening_date'), '2026-04-01')
        self.assertNotIn('opening', by_name['SCI ALPHA'])

    def test_untitled_continuation_stays_in_same_group(self):
        rows = [
            [t(0, 'SCI SUITE')], None, HEADER,
            movement('01/03/26', 'Loyer 1', credit=100),
            None,
            HEADER,  # tableau sans titre : suite du précédent
            movement('01/04/26', 'Loyer 2', credit=100),
        ]
        bundle = parse(build_xlsx([('Suite', rows)],
                                  numfmts={164: '#,##0.00" €"'}, cell_xfs=[0, 164]))
        self.assertEqual(len(bundle['scis']), 1)
        self.assertEqual(bundle['scis'][0]['name'], 'SCI SUITE')
        self.assertEqual(len(bundle['records']), 2)

    def test_reconciliation_warnings_for_wrong_solde_and_totals(self):
        rows = [
            [t(0, 'SCI ÉCARTS')], None, HEADER,
            [t(0, '01/01/26'), n(4, 1000.0)],
            movement('02/01/26', 'Virement', credit=100),
            [t(0, '31/01/26'), n(2, 50.0), n(3, 100.0), n(4, 1050.0)],  # totaux débit faux, solde faux
            movement('02/02/26', 'Avoir', debit=-10.0),                   # négatif → recette
            [t(0, '03/02/26'), t(1, 'Note sans montant')],                # ignorée
            [t(0, '04/02/26')],                                           # date seule
        ]
        bundle = parse(build_xlsx([('Écarts', rows)],
                                  numfmts={164: '#,##0.00" €"'}, cell_xfs=[0, 164]))
        warnings = bundle['warnings']
        self.assertEqual(len(warnings), 5)
        joined = '\n'.join(warnings)
        self.assertIn('total débit', joined)
        self.assertIn('solde au 31/01/2026', joined)
        self.assertIn('1 100,00 €', joined)
        self.assertIn('sens inversé en Recette', joined)
        self.assertIn('libellé sans montant', joined)
        self.assertIn('date seule', joined)
        records = bundle['records']
        self.assertEqual(len(records), 2)
        avoir = [r for r in records if r['label'] == 'Avoir'][0]
        self.assertEqual((avoir['direction'], avoir['amount']), ('Recette', 10.0))

    def test_tolerates_correct_tallies_without_solde_on_closing_row(self):
        rows = [
            [t(0, 'SCI TOTAUX')], None, HEADER,
            [t(0, '01/01/26'), n(4, 1000.0)],
            movement('05/01/26', 'Loyer', credit=800),
            movement('06/01/26', 'Charge', debit=55.25),
            [t(0, '31/01/26'), n(2, 55.25), n(3, 800.0)],  # totaux exacts, sans solde
            movement('05/02/26', 'Loyer', credit=800),
            [t(0, '28/02/26'), n(4, 2544.75)],  # 1000 + 800 - 55.25 + 800
        ]
        bundle = parse(build_xlsx([('Totaux', rows)],
                                  numfmts={164: '#,##0.00" €"'}, cell_xfs=[0, 164]))
        # seul avertissement : la ligne de totaux de janvier ne porte pas de solde
        self.assertEqual(len(bundle['warnings']), 1)
        self.assertIn('sans solde', bundle['warnings'][0])
        self.assertEqual(len(bundle['records']), 3)

    def test_structural_errors_are_explicit(self):
        cases = [
            # date illisible alors que la ligne porte des montants
            ('date illisible', [[t(0, 'SCI')], None, HEADER,
                                [t(0, '31/02/26'), t(1, 'Achat'), n(2, 10.0)]]),
            # montant à la fois en débit et en crédit
            ('débit et en crédit', [[t(0, 'SCI')], None, HEADER,
                                    [t(0, '01/01/26'), t(1, 'Bizarre'), n(2, 10.0), n(3, 10.0)]]),
            # date manquante sur une ligne de données
            ('date manquante', [[t(0, 'SCI')], None, HEADER,
                                [t(1, 'Sans date'), n(2, 10.0)]]),
            # montant illisible en colonne débit
            ('montant illisible', [[t(0, 'SCI')], None, HEADER,
                                   [t(0, '01/01/26'), t(1, 'Texte'), (2, 'shared', 'N/A')]]),
            # données sans aucune ligne d'en-tête
            ('d’en-tête', [[t(0, '01/01/26'), t(1, 'Orphelin'), n(2, 10.0)]]),
        ]
        for expected, sheet_rows in cases:
            with self.subTest(expected=expected):
                with self.assertRaises(ValueError) as ctx:
                    parse(build_xlsx([('Feuille1', sheet_rows)],
                                     numfmts={164: '#,##0.00" €"'}, cell_xfs=[0, 164]))
                self.assertIn(expected, str(ctx.exception))

    def test_no_table_and_no_operation_errors(self):
        with self.assertRaises(ValueError) as ctx:
            parse(build_xlsx([('Note', [[t(0, 'Juste un titre')]])]))
        self.assertIn('Aucun tableau', str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            parse(build_xlsx([('Vide', [HEADER, [t(0, '31/12/25'), n(4, 10.0)]])]))
        self.assertIn('aucune opération', str(ctx.exception))

    def test_invalid_files_rejected(self):
        for payload, expected in [
            ('', 'absent'),
            (b64(b'ceci n est pas un zip'), 'illisible'),
            (base64.b64encode(b'PK\x03\x04corrompu').decode(), 'illisible'),
        ]:
            with self.subTest(expected=expected):
                with self.assertRaises(ValueError) as ctx:
                    app.parse_import({'format': 'xlsx', 'text': payload})
                self.assertIn(expected, str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            app.parse_import({'format': 'xlsx', 'text': '!!!base64 invalide!!!"'})
        self.assertIn('encodage', str(ctx.exception))

    def test_record_limit(self):
        rows = [HEADER]
        for i in range(app.XLSX_MAX_RECORDS + 1):
            rows.append([(0, 'n', serial(dt.date(2026, 1, 1)) + i % 365), t(1, 'Opération'), (3, 'n', 10.0)])
        with self.assertRaises(ValueError) as ctx:
            parse(build_xlsx([('Géant', rows)]))
        self.assertIn('40 000', str(ctx.exception))


class XlsxImportBundleTests(unittest.TestCase):
    """Intégration : destinations, nouvelle SCI, anti-doublon, garde-fous CSV."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_patch = patch.object(app, 'DB', Path(self.temp.name) / 'data.db')
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        app.EXIT_READY.clear()
        app.init_db()

    def test_import_into_existing_sci_leaves_opening_untouched(self):
        text = b64(sample_xlsx())
        with app.connect() as c:
            sid = app.save_record(c, {'kind': 'sci', 'data': {'name': 'SCI existante', 'address': '1 rue Test'}})
        bundle = app.parse_import({'format': 'xlsx', 'text': text})
        source = bundle['scis'][0]['id']
        with app.connect() as c:
            count = app.import_bundle(c, {'format': 'xlsx', 'text': text, 'mapping': {source: sid}})
            c.commit()
        self.assertEqual(count, 14)
        with app.connect() as c:
            entries = c.execute("SELECT count(*) FROM records WHERE kind='entries' AND sci=?", (sid,)).fetchone()[0]
            self.assertEqual(entries, 14)
            data = json.loads(c.execute('SELECT data FROM scis WHERE id=?', (sid,)).fetchone()[0])
            self.assertNotIn('opening', data)
        # le même fichier vers les mêmes destinations est refusé (empreinte d'import)
        with app.connect() as c:
            with self.assertRaises(ValueError) as ctx:
                app.import_bundle(c, {'format': 'xlsx', 'text': text, 'mapping': {source: sid}})
        self.assertIn('déjà été importé', str(ctx.exception))

    def test_create_new_sci_from_title_with_opening_balance(self):
        text = b64(sample_xlsx())
        bundle = app.parse_import({'format': 'xlsx', 'text': text})
        source = bundle['scis'][0]['id']
        with app.connect() as c:
            count = app.import_bundle(c, {'format': 'xlsx', 'text': text, 'mapping': {source: 'new'}})
            c.commit()
        self.assertEqual(count, 14)
        with app.connect() as c:
            scis = [json.loads(r[0]) for r in c.execute('SELECT data FROM scis')]
        self.assertEqual(len(scis), 1)
        created = scis[0]
        self.assertEqual(created['name'], 'SCI 52 RUE LOUGUET')  # pas de suffixe « (import) »
        self.assertEqual(created['opening'], 32155.66)
        self.assertEqual(created['opening_date'], '2025-12-31')

    def test_unknown_destination_rejected(self):
        text = b64(sample_xlsx())
        bundle = app.parse_import({'format': 'xlsx', 'text': text})
        source = bundle['scis'][0]['id']
        with app.connect() as c:
            with self.assertRaises(ValueError) as ctx:
                app.import_bundle(c, {'format': 'xlsx', 'text': text, 'mapping': {source: 'does-not-exist'}})
        self.assertIn('introuvable', str(ctx.exception))

    def test_csv_still_requires_an_existing_destination(self):
        csv_text = 'date;label;direction;category;amount\n2026-01-01;Loyer;Recette;Loyers;850\n'
        bundle = app.parse_import({'format': 'csv', 'text': csv_text})
        source = bundle['scis'][0]['id']
        with app.connect() as c:
            with self.assertRaises(ValueError) as ctx:
                app.import_bundle(c, {'format': 'csv', 'text': csv_text, 'mapping': {source: 'new'}})
        self.assertIn('SCI existante', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
