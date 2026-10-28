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


def build_xlsx(sheets, numfmts=None, cell_xfs=None, borders=None, border_xfs=None):
    """Construit un .xlsx minimal mais conforme.

    sheets : [(nom, lignes)] — une ligne est None (ligne omise : le trou marque
    une ligne vide) ou une liste de cellules (colonne, type, valeur[, style[, cache]]).
    Types : 'inline', 'shared', 'n' (numérique), 'iso' (date Excel t="d"),
    'str' (résultat de formule mis en cache), 'f' (formule sans valeur en cache),
    'fc' (formule avec valeur en cache donnée en 5e position).
    borders / border_xfs : styles de bordure (indice de style -> indice de bordure).
    """
    numfmts = numfmts or {}
    xfs = cell_xfs or [0]
    borders = borders or []
    border_xfs = border_xfs or {}
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
                elif kind == 'f':
                    body = '<f>%s</f>' % xml_esc(value)
                elif kind == 'fc':
                    cached = spec[4] if len(spec) > 4 else ''
                    body = '<f>%s</f><v>%s</v>' % (xml_esc(value), '' if cached == '' else repr(float(cached)))
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
    border_xml = ''
    if borders:
        sides = ('left', 'right', 'top', 'bottom')
        border_xml = '<borders count="%d">%s</borders>' % (
            len(borders),
            ''.join('<border>%s</border>' % ''.join('<%s style="thin"/>' % side for side in item if side in sides)
                    for item in borders))
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<styleSheet xmlns="%s">%s%s<cellXfs count="%d">%s</cellXfs></styleSheet>'
              % (NS_MAIN, numfmt_xml, border_xml, len(xfs),
                 ''.join('<xf numFmtId="%d"%s applyNumberFormat="1"/>'
                         % (fid, ' borderId="%d"' % border_xfs.get(i, 0) if border_xfs else '')
                         for i, fid in enumerate(xfs))))

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
        self.assertIn('solde attendu', joined)
        self.assertIn('31/01/2026', joined)
        self.assertIn('1 100,00 €', joined)
        self.assertIn('enregistré en Recette', joined)
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
        self.assertIn('Aucune opération importable', str(ctx.exception))

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
        # La limite de sécurité reste très élevée : le test l'abaisse pour rester rapide.
        with patch.object(app, 'XLSX_MAX_RECORDS', 50):
            rows = [HEADER]
            for i in range(app.XLSX_MAX_RECORDS + 1):
                rows.append([(0, 'n', serial(dt.date(2026, 1, 1)) + i % 365), t(1, 'Opération'), (3, 'n', 10.0)])
            with self.assertRaises(ValueError) as ctx:
                parse(build_xlsx([('Géant', rows)]))
        self.assertIn('50 opérations', str(ctx.exception))
        with patch.object(app, 'XLSX_MAX_RECORDS', 50):
            with self.assertRaises(ValueError) as ctx:
                app.parse_import({'format': 'csv', 'text': 'date;label;direction;category;amount\n' + '\n'.join(
                    '2026-01-0%d;Loyer %d;Recette;Loyers;10' % (i % 9 + 1, i) for i in range(51))})
        self.assertIn('1 et 50 lignes', str(ctx.exception))

    def test_monthly_solde_crediteur_debiteur_blank_rows_and_zero_opening(self):
        header = [t(0, 'Date operation'), t(1, 'Libelle'), t(2, ' Débit '), t(3, ' Crédit '), t(4, ' Solde ')]
        rows = [
            [t(0, 'SCI THEMA Immobilier')],
            [t(0, 'HSBC 2021')],
            header,
            None,  # ligne vide juste sous l'en-tête (ligne 4)
            [t(1, 'Solde Créditeur au 01/07/2021'), n(4, 0.0)],  # ligne 5 : solde nul -> aucun solde initial affiché
            [n(0, serial(dt.date(2021, 7, 29)), DATE_B), t(1, 'Virement Emilie VENIEL'), n(3, 24000.0)],
            [n(0, serial(dt.date(2021, 7, 30)), DATE_B), t(1, 'Virement Arnauld LEE'), n(3, 18000.0)],
            [n(0, serial(dt.date(2021, 7, 30)), DATE_B), t(1, 'Virement Arnauld LEE'), n(3, 6000.0)],
            [t(1, 'Solde Créditeur au 30/07/2021'), n(4, 48000.0)],
            [t(1, 'Solde Créditeur au 31/08/2021')],  # aucun solde affiché -> rien ne doit apparaître
            [n(0, serial(dt.date(2021, 9, 2)), DATE_B), t(1, 'Virement Me Delforge'), n(2, 47500.0)],
            [n(0, serial(dt.date(2021, 9, 3)), DATE_B), t(1, 'Frais virement'), n(2, 4.0)],
            [n(0, serial(dt.date(2021, 9, 17)), DATE_B), t(1, 'AXA'), n(2, 66.28)],
            [t(1, 'Solde Créditeur au 30/09/2021'), n(4, 429.72)],
            [n(0, serial(dt.date(2021, 10, 25)), DATE_B), t(1, 'Remise de chèque N° 0645031'), n(3, 178.0)],
            [n(0, serial(dt.date(2021, 10, 28)), DATE_B), t(1, 'Virement Visite Prest. Assain. Collectif'), n(2, 120.0)],
            [t(1, 'Solde Créditeur au 29/10/2021'), n(4, 487.72)],
            [n(0, serial(dt.date(2021, 11, 10)), DATE_B), t(1, 'Remise de chèque N° 0645032'), n(3, 431.45)],
            [n(0, serial(dt.date(2021, 11, 16)), DATE_B), t(1, 'Virement Eric THOMAS'), n(3, 76.0)],
            [t(1, 'Solde Créditeur au 30/11/2021'), n(4, 995.17)],
            [n(0, serial(dt.date(2021, 12, 16)), DATE_B), t(1, 'Virement Eric THOMAS'), n(3, 76.0)],
            [n(0, serial(dt.date(2021, 12, 29)), DATE_B), t(1, 'Charges Copro'), n(2, 209.68)],
            [t(1, 'Solde Créditeur au 31/12/2021'), n(4, 861.49)],
            None,
        ]
        bundle = parse(build_xlsx([('2021', rows)],
                                  numfmts={164: 'dd/mm/yy;@'},
                                  cell_xfs=[0, 44, 164, 14]))
        self.assertEqual(bundle['warnings'], [])
        self.assertEqual(len(bundle['scis']), 1)
        sci = bundle['scis'][0]
        self.assertEqual(sci['name'], 'SCI THEMA Immobilier')
        self.assertNotIn('opening', sci)
        self.assertEqual(len(bundle['records']), 12)
        net = round(sum((r['amount'] if r['direction'] == 'Recette' else -r['amount']) for r in bundle['records']), 2)
        self.assertEqual(net, 861.49)

    def test_multi_sheet_year_tabs_partial_dates_and_large_tables(self):
        header = [t(0, 'Date operation'), t(1, 'Libelle'), t(2, 'Débit'), t(3, 'Crédit'), t(4, 'Solde')]
        sheet_2021 = [
            [t(0, 'SCI THEMA Immobilier')],
            [t(0, 'HSBC 2021')],
            header,
            None,
            [t(1, 'Solde Créditeur au 01/01/2021'), n(4, 1000.0)],
            [t(0, '15/01'), t(1, 'Loyer Janvier'), n(2, 0.0), n(3, 500.0)],
            [t(0, '28 janvier'), t(1, 'Assurance'), n(2, 100.0), n(3, 0.0)],
            [t(1, 'Solde Créditeur au 31/01/2021'), n(4, 1400.0)],
        ]
        sheet_2022 = [
            [t(0, 'HSBC 2022')],  # sous-titre bancaire seul sur l'onglet 2022
            header,
            [t(1, 'Solde Créditeur au 01/01/2022'), n(4, 1400.0)],
        ]
        running = 1400.0
        for m in range(1, 13):
            for d in range(1, 21):
                amt = 50.0 if d % 2 == 0 else 20.0
                if d % 2 == 0:
                    running = round(running + amt, 2)
                    sheet_2022.append([t(0, f'{d:02d}/{m:02d}'), t(1, f'Opération {m}-{d}'), n(3, amt)])
                else:
                    running = round(running - amt, 2)
                    sheet_2022.append([t(0, f'{d:02d}/{m:02d}'), t(1, f'Charge {m}-{d}'), n(2, amt)])
            sheet_2022.append([t(1, f'Solde Créditeur au 28/{m:02d}/2022'), n(4, running)])
            sheet_2022.append(None)

        bundle = parse(build_xlsx([('2021', sheet_2021), ('2022', sheet_2022)],
                                  numfmts={164: '#,##0.00" €"'}, cell_xfs=[0, 164]))
        self.assertEqual(bundle['warnings'], [])
        self.assertEqual(len(bundle['scis']), 1)
        self.assertEqual(bundle['scis'][0]['name'], 'SCI THEMA Immobilier')
        self.assertEqual(bundle['scis'][0]['opening'], 1000.0)
        self.assertEqual(bundle['scis'][0]['opening_date'], '2021-01-01')
        self.assertEqual(len(bundle['records']), 2 + 12 * 20)
        self.assertEqual(bundle['records'][0]['date'], '2021-01-15')
        self.assertEqual(bundle['records'][1]['date'], '2021-01-28')
        self.assertEqual(bundle['records'][2]['date'], '2022-01-01')

    def test_detailed_error_messages_include_sheet_row_column_and_context(self):
        header = [t(0, 'Date operation'), t(1, 'Libelle'), t(2, 'Débit'), t(3, 'Crédit'), t(4, 'Solde')]
        bad_amount_rows = [
            [t(0, 'SCI ERREUR')],
            header,
            [t(0, '15/07/2021'), t(1, 'Facture plombier'), t(2, '12abc')],
        ]
        with self.assertRaises(ValueError) as ctx:
            parse(build_xlsx([('2021', bad_amount_rows)]))
        msg = str(ctx.exception)
        self.assertIn('Feuille « 2021 »', msg)
        self.assertIn('ligne 3', msg)
        self.assertIn('colonne C (« Débit »)', msg)
        self.assertIn('montant illisible', msg)
        self.assertIn('Facture plombier', msg)

    def test_tabular_csv_and_xlsx_disguised_as_csv(self):
        csv_tabular = (
            'SCI THEMA Immobilier;;;;\n'
            'HSBC 2021;;;;\n'
            'Date operation;Libelle; Débit ; Crédit ; Solde \n'
            ';;;;\n'
            ';Solde Créditeur au 01/07/2021;;;- €\n'
            '29/07/2021;Virement Emilie VENIEL;;24 000,00 €;\n'
            '30/07/2021;Virement Arnauld LEE;;18 000,00 €;\n'
            ';Solde Créditeur au 30/07/2021;;;42 000,00 €\n'
        )
        bundle_csv = app.parse_import({'format': 'csv', 'text': csv_tabular})
        self.assertEqual(bundle_csv['warnings'], [])
        self.assertEqual(len(bundle_csv['scis']), 1)
        self.assertEqual(bundle_csv['scis'][0]['name'], 'SCI THEMA Immobilier')
        self.assertNotIn('opening', bundle_csv['scis'][0])
        self.assertEqual(len(bundle_csv['records']), 2)
        self.assertEqual(bundle_csv['records'][0]['amount'], 24000.0)

        # Fichier .xlsx envoyé avec format='csv' (ex. extension .csv sur une archive .xlsx)
        xlsx_b64 = b64(sample_xlsx())
        bundle_auto = app.parse_import({'format': 'csv', 'text': xlsx_b64})
        self.assertEqual(len(bundle_auto['records']), 14)



def f(col, formula, style=MONEY):
    """Formule sans valeur calculée (fichier produit par un générateur)."""
    return (col, 'f', formula, style)


def fc(col, formula, cached, style=MONEY):
    """Formule avec valeur calculée en cache (fichier produit par Excel)."""
    return (col, 'fc', formula, style, cached)


def boxed(cells):
    """Cellules encadrées : style 4 (bordure sur les quatre côtés)."""
    return [(c[0], c[1], c[2], 4) + tuple(c[4:]) for c in cells]


class XlsxReaderRegressionTests(unittest.TestCase):
    """Défauts réels du lecteur : formules, bordures, en-têtes fusionnés, sens unique.

    La ligne d'en-tête est toujours en ligne 4 (comme dans les classeurs réels
    reproduits par les autres tests) : les formules peuvent donc référencer
    E5/D6/C6 de façon lisible.
    """

    HEAD = [[(0, 'inline', 'SCI TEST')], None, None, HEADER]

    # --- formules -----------------------------------------------------------
    def test_formula_amounts_are_recalculated_when_no_value_is_cached(self):
        rows = self.HEAD + [
            [f(4, '1200+300')],                                        # E5 : 1500
            [t(0, '05/01/26'), t(1, 'Loyer'), f(3, '1000+200'), f(4, 'E5+D6')],
            [t(0, '06/01/26'), t(1, 'Travaux'), f(2, '500*0.5'), f(4, 'E6-C7')],
        ]
        bundle = parse(build_xlsx([('Formules', rows)], numfmts={164: '#,##0.00" €"'},
                                  cell_xfs=[0, 164]))
        self.assertEqual(bundle['scis'][0]['opening'], 1500.0)
        self.assertEqual([(r['label'], r['direction'], r['amount']) for r in bundle['records']],
                         [('Loyer', 'Recette', 1200.0), ('Travaux', 'Dépense', 250.0)])
        # aucun écart de solde : les formules sont recalculées correctement
        self.assertEqual(len(bundle['warnings']), 1)
        self.assertIn('recalculées à l’import', bundle['warnings'][0])
        self.assertEqual(bundle['reconcile'][bundle['scis'][0]['id']]['gap'], 0.0)

    def test_cached_formula_values_are_preferred_and_silent(self):
        rows = self.HEAD + [
            [fc(4, '1200+300', 1500)],
            [t(0, '05/01/26'), t(1, 'Loyer'), fc(3, '1000+200', 1200), fc(4, 'E5+D6', 2700)],
        ]
        bundle = parse(build_xlsx([('Cache', rows)], numfmts={164: '#,##0.00" €"'},
                                  cell_xfs=[0, 164]))
        self.assertEqual(bundle['warnings'], [])
        self.assertEqual(bundle['scis'][0]['opening'], 1500.0)
        self.assertEqual(bundle['records'][0]['amount'], 1200.0)

    def test_unreadable_formula_is_reported_and_never_silently_dropped(self):
        rows = self.HEAD + [
            [t(0, '05/01/26'), t(1, 'Loyer'), n(3, 1200.0),
             f(4, 'VLOOKUP(A5,Feuil2!A1:B9,2,FALSE)')],
            [t(0, '06/01/26'), t(1, 'Travaux'), n(2, 250.0)],
        ]
        bundle = parse(build_xlsx([('Illisible', rows)], numfmts={164: '#,##0.00" €"'},
                                  cell_xfs=[0, 164]))
        joined = '\n'.join(bundle['warnings'])
        self.assertIn('n’a pas de résultat enregistré', joined)
        self.assertIn('→ Ouvrez le classeur dans Excel', joined)
        self.assertIn('VLOOKUP', joined)
        self.assertIn('E5', joined)
        self.assertEqual(len(bundle['records']), 2)

    def test_running_balance_without_opening_line_derives_the_opening(self):
        rows = self.HEAD + [
            [t(0, '05/01/26'), t(1, 'Loyer'), n(3, 1200.0),
             f(4, '1000+SUM($D$5:D5)-SUM($C$5:C5)')],
            [t(0, '03/02/26'), t(1, 'Travaux'), n(2, 250.55),
             f(4, '1000+SUM($D$5:D6)-SUM($C$5:C6)')],
        ]
        bundle = parse(build_xlsx([('Soldes', rows)], numfmts={164: '#,##0.00" €"'},
                                  cell_xfs=[0, 164]))
        sci = bundle['scis'][0]
        self.assertEqual(sci['opening'], 1000.0)
        self.assertEqual(sci['opening_date'], '2026-01-04')
        self.assertTrue(sci.get('opening_derived'))
        self.assertEqual(bundle['reconcile'][sci['id']]['calculated'], 1949.45)

    # --- structure du tableau ----------------------------------------------
    def test_two_line_header_with_merged_group(self):
        rows = [[t(0, 'SCI FUSION')], None,
                [t(0, 'Date'), t(1, 'Libellé'), t(2, 'Montant')],
                [(2, 'inline', 'Débit'), (3, 'inline', 'Crédit'), (4, 'inline', 'Solde')],
                [t(0, '05/01/26'), t(1, 'Loyer'), n(3, 1200.0), n(4, 2200.0)]]
        bundle = parse(build_xlsx([('Fusion', rows)], numfmts={164: '#,##0.00" €"'},
                                  cell_xfs=[0, 164]))
        self.assertEqual([(r['label'], r['direction'], r['amount']) for r in bundle['records']],
                         [('Loyer', 'Recette', 1200.0)])

    def test_single_amount_column_with_direction_column(self):
        header = [t(0, 'Date'), t(1, 'Libellé'), t(2, 'Montant'), t(3, 'Sens')]
        rows = [[t(0, 'SCI SENS')], None, header,
                [t(0, '05/01/26'), t(1, 'Loyer'), n(2, 1200.0), t(3, 'Crédit')],
                [t(0, '06/01/26'), t(1, 'Travaux'), n(2, 250.0), t(3, 'Débit')],
                [t(0, '07/01/26'), t(1, 'Avoir'), n(2, 50.0), t(3, 'Débit')],
                [t(0, '08/01/26'), t(1, 'Remboursement'), n(2, -30.0)]]   # signe = dépense
        bundle = parse(build_xlsx([('Sens', rows)], numfmts={164: '#,##0.00" €"'},
                                  cell_xfs=[0, 164]))
        self.assertEqual(bundle['warnings'], [])
        self.assertEqual([(r['label'], r['direction'], r['amount']) for r in bundle['records']],
                         [('Loyer', 'Recette', 1200.0), ('Travaux', 'Dépense', 250.0),
                          ('Avoir', 'Dépense', 50.0), ('Remboursement', 'Dépense', 30.0)])

    def test_unknown_direction_is_refused(self):
        header = [t(0, 'Date'), t(1, 'Libellé'), t(2, 'Montant'), t(3, 'Sens')]
        rows = [[t(0, 'SCI SENS')], None, header,
                [t(0, '05/01/26'), t(1, 'Loyer'), n(2, 1200.0), t(3, 'Peut-être')]]
        with self.assertRaises(ValueError) as ctx:
            parse(build_xlsx([('Sens', rows)], numfmts={164: '#,##0.00" €"'}, cell_xfs=[0, 164]))
        self.assertIn('sens illisible', str(ctx.exception))

    def test_summary_row_below_the_table_is_never_an_operation(self):
        rows = self.HEAD + [
            [t(0, '05/01/26'), t(1, 'Loyer'), n(3, 1200.0), n(4, 1200.0)],
            [t(0, '06/01/26'), t(1, 'Travaux'), n(2, 200.0), n(4, 1000.0)],
            [t(0, '31/01/26'), t(1, 'Total des dépenses'), n(2, 250.0)],
            [t(0, '31/01/26'), t(1, 'Total des recettes'), n(3, 1200.0)],
        ]
        bundle = parse(build_xlsx([('Recap', rows)], numfmts={164: '#,##0.00" €"'}, cell_xfs=[0, 164]))
        self.assertEqual([(r['label'], r['direction'], r['amount']) for r in bundle['records']],
                         [('Loyer', 'Recette', 1200.0), ('Travaux', 'Dépense', 200.0)])
        joined = '\n'.join(bundle['warnings'])
        self.assertIn('total annoncé 250,00 € en débit', joined)
        self.assertIn('Ligne de synthèse non importée', joined)

    def test_bordered_table_ends_before_the_recap_block(self):
        rows = [[t(0, 'SCI BORDURES')], None, None]
        for line in (HEADER,
                     [t(0, '05/01/26'), t(1, 'Loyer'), n(3, 1200.0), n(4, 1000.0)],
                     [t(0, '06/01/26'), t(1, 'Loyer'), n(3, 1200.0), n(4, 2200.0)]):
            rows.append(boxed(line))
        rows += [None,
                 [(1, 'inline', 'Total des recettes'), (3, 'n', 2400.0)],
                 [(1, 'inline', 'Frais de dossier'), (2, 'n', 293.05)]]   # hors tableau, sans date
        bundle = parse(build_xlsx([('Bordures', rows)], numfmts={164: '#,##0.00" €"'},
                                  cell_xfs=[0, 164, 164, 164, 164],
                                  borders=[[], ['left', 'right', 'top', 'bottom']],
                                  border_xfs={4: 1}))
        self.assertEqual(len(bundle['records']), 2)
        self.assertEqual(bundle['reconcile'][bundle['scis'][0]['id']]['calculated'], 2200.0)
        joined = '\n'.join(bundle['warnings'])
        self.assertIn('hors du tableau', joined)
        self.assertIn('Frais de dossier', joined)

    def test_footer_marker_ends_the_table_without_borders(self):
        rows = self.HEAD + [
            [t(0, '05/01/26'), t(1, 'Loyer'), n(3, 1200.0)],
            [t(0, 'Récapitulatif')],
            [t(0, 'Loyer'), n(3, 1200.0)],
        ]
        bundle = parse(build_xlsx([('Recap', rows)], numfmts={164: '#,##0.00" €"'}, cell_xfs=[0, 164]))
        self.assertEqual(len(bundle['records']), 1)
        self.assertIn('hors du tableau', '\n'.join(bundle['warnings']))

    def test_second_bank_account_of_the_same_sci_is_reported(self):
        first = [[t(0, 'SCI DEUX COMPTES')], None, None, HEADER,
                 [(4, 'n', 1000.0)],
                 [t(0, '05/01/26'), t(1, 'Loyer'), n(3, 1200.0), n(4, 2200.0)]]
        second = [[t(0, 'SCI DEUX COMPTES')], None, None, HEADER,
                  [(4, 'n', 5000.0)],
                  [t(0, '05/02/26'), t(1, 'Intérêts'), n(3, 50.0), n(4, 5050.0)]]
        bundle = parse(build_xlsx([('Compte courant', first), ('Compte épargne', second)],
                                  numfmts={164: '#,##0.00" €"'}, cell_xfs=[0, 164]))
        self.assertEqual(len(bundle['scis']), 1)
        joined = '\n'.join(bundle['warnings'])
        self.assertIn('solde attendu 2 200,00 €', joined)
        self.assertIn('trouvé 5 000,00 €', joined)
        self.assertEqual(bundle['reconcile'][bundle['scis'][0]['id']]['gap'], -2800.0)

    # --- rapprochement ------------------------------------------------------
    def test_reconcile_summary_exposes_the_gap_to_the_import_screen(self):
        rows = self.HEAD + [
            [(4, 'n', 7000.0)],
            [t(0, '05/01/26'), t(1, 'Loyer'), n(3, 1200.0), n(4, 8484.04)],
        ]
        bundle = parse(build_xlsx([('Écart', rows)], numfmts={164: '#,##0.00" €"'}, cell_xfs=[0, 164]))
        rec = bundle['reconcile'][bundle['scis'][0]['id']]
        self.assertEqual(rec['opening'], 7000.0)
        self.assertEqual(rec['last_balance'], 8484.04)
        self.assertEqual(rec['balance_at_last'], 8200.0)
        self.assertEqual(rec['gap'], -284.04)


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
            count = app.import_bundle(c, {'format': 'xlsx', 'text': text, 'mapping': {source: sid}})['count']
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
            count = app.import_bundle(c, {'format': 'xlsx', 'text': text, 'mapping': {source: 'new'}})['count']
            c.commit()
        self.assertEqual(count, 14)
        with app.connect() as c:
            scis = [json.loads(r[0]) for r in c.execute('SELECT data FROM scis')]
        self.assertEqual(len(scis), 1)
        created = scis[0]
        self.assertEqual(created['name'], 'SCI 52 RUE LOUGUET')  # pas de suffixe « (import) »
        self.assertEqual(created['opening'], 32155.66)
        self.assertEqual(created['opening_date'], '2025-12-31')

    def test_corrected_opening_from_the_import_screen_is_applied(self):
        # Le contrôle affiché dans l'écran d'import indique un écart : l'utilisateur
        # corrige le solde d'ouverture avant de confirmer.
        text = b64(sample_xlsx())
        bundle = app.parse_import({'format': 'xlsx', 'text': text})
        source = bundle['scis'][0]['id']
        with app.connect() as c:
            app.import_bundle(c, {'format': 'xlsx', 'text': text, 'mapping': {source: 'new'},
                                  'openings': {source: 30000.00}})
            c.commit()
        with app.connect() as c:
            created = json.loads(c.execute('SELECT data FROM scis').fetchone()[0])
        self.assertEqual(created['opening'], 30000.0)
        self.assertEqual(created['opening_date'], '2025-12-31')

    def test_corrected_opening_makes_the_import_distinct_from_the_first_one(self):
        text = b64(sample_xlsx())
        bundle = app.parse_import({'format': 'xlsx', 'text': text})
        source = bundle['scis'][0]['id']
        with app.connect() as c:
            app.import_bundle(c, {'format': 'xlsx', 'text': text, 'mapping': {source: 'new'}})
            c.commit()
        with app.connect() as c:
            # même fichier, même destination : doublon
            with self.assertRaises(ValueError):
                app.import_bundle(c, {'format': 'xlsx', 'text': text, 'mapping': {source: 'new'}})
            # solde d'ouverture corrigé : ce n'est plus le même import
            count = app.import_bundle(c, {'format': 'xlsx', 'text': text, 'mapping': {source: 'new'},
                                          'openings': {source: 32000.0}})['count']
            c.commit()
        self.assertEqual(count, 14)

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


class XlsxSourceGuardTests(unittest.TestCase):
    """Origine des montants : feuilles de synthèse, titres, doublons, raccordement."""

    HEAD = [[t(0, 'Date'), t(1, 'Libellé'), t(2, 'Débit'), t(3, 'Crédit'), t(4, 'Solde')]]

    def setUp(self):
        # Base temporaire : la suite ne doit jamais écrire dans Dominis/data.db.
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db_patch = patch.object(app, 'DB', Path(self.temp.name) / 'data.db')
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        app.EXIT_READY.clear()
        app.init_db()

    def bundle(self, sheets, **kw):
        kw.setdefault('numfmts', {164: '#,##0.00 €'})
        kw.setdefault('cell_xfs', [0, 164])
        return parse(build_xlsx(sheets, **kw))

    def test_summary_sheet_never_feeds_a_real_sci(self):
        """Une feuille « Synthèse » reprenant le nom de la SCI doublait ses montants."""
        bundle = self.bundle([
            ('SCI THEMA', self.HEAD + [[t(0, '05/03/25'), t(1, 'Loyer'), n(3, 1000.0)]]),
            ('Synthèse', [[t(0, 'SCI THEMA')]] + self.HEAD
             + [[t(0, '31/12/24'), t(1, 'Loyers encaissés'), n(3, 12000.0)]]),
        ])
        self.assertEqual(len(bundle['scis']), 1)
        self.assertEqual(len(bundle['records']), 1)
        joined = '\n'.join(bundle['warnings'])
        self.assertIn('tableau de synthèse', joined)
        self.assertIn('autre nom que', joined)

    def test_workbook_with_only_summary_sheets_is_refused_with_a_hint(self):
        with self.assertRaises(ValueError) as ctx:
            self.bundle([('Synthèse', self.HEAD + [[t(0, '31/12/24'), t(1, 'Loyers encaissés'), n(3, 12000.0)]])])
        message = str(ctx.exception)
        self.assertIn('Aucune opération importable', message)
        self.assertIn('Pistes', message)
        self.assertIn('tableau de synthèse', message)

    def test_control_prefix_in_title_keeps_the_sci_name(self):
        """« Bilan 2024 · SCI THEMA » devenait « Tableau 1 · Feuil1 »."""
        bundle = self.bundle([
            ('2024', [[t(0, 'Bilan 2024 · SCI THEMA')]] + self.HEAD
             + [[t(0, '05/03/24'), t(1, 'Loyer'), n(3, 1000.0)]]),
            ('2025', [[t(0, 'Bilan 2025 · SCI THEMA')]] + self.HEAD
             + [[t(0, '05/03/25'), t(1, 'Loyer'), n(3, 1100.0)]]),
        ])
        self.assertEqual([s['name'] for s in bundle['scis']], ['SCI THEMA'])
        self.assertEqual(len(bundle['records']), 2)

    def test_summary_title_is_not_imported(self):
        with self.assertRaises(ValueError) as ctx:
            self.bundle([('Feuil1', [[t(0, 'Récapitulatif général')]] + self.HEAD
                         + [[t(0, '31/12/24'), t(1, 'Loyers encaissés'), n(3, 12000.0)]])])
        self.assertIn('tableau de synthèse', str(ctx.exception).lower())

    def test_overlapping_files_are_not_counted_twice(self):
        text = b64(sample_xlsx())
        bundle = app.parse_import({'format': 'xlsx', 'text': text})
        source = bundle['scis'][0]['id']
        with app.connect() as c:
            sid = app.save_record(c, {'kind': 'sci', 'data': {'name': 'SCI existante'}})
            first = app.import_bundle(c, {'format': 'xlsx', 'text': text, 'mapping': {source: sid}})
            c.commit()
        self.assertEqual(first['count'], 14)
        # Même contenu, empreinte différente (ouverture différente) : les lignes
        # déjà présentes ne doivent pas être comptées deux fois.
        with app.connect() as c:
            second = app.import_bundle(c, {'format': 'xlsx', 'text': text, 'mapping': {source: sid},
                                           'openings': {source: 32155.66}})
            c.commit()
        self.assertEqual(second['count'], 0)
        self.assertEqual(second['skipped'], 14)
        self.assertTrue(any('déjà présente' in w for w in second['warnings']))
        with app.connect() as c:
            total = c.execute("SELECT count(*) FROM records WHERE kind='entries' AND sci=?", (sid,)).fetchone()[0]
        self.assertEqual(total, 14)

    def test_opening_mismatch_on_existing_sci_is_reported(self):
        sheet = [[t(0, 'SCI TEST')]] + self.HEAD + [[n(4, 1000.0)],
                 [t(0, '05/03/24'), t(1, 'Loyer'), n(3, 1200.0), n(4, 2200.0)]]
        text = b64(build_xlsx([('Relevé', sheet)], numfmts={164: '#,##0.00 €'}, cell_xfs=[0, 164]))
        source = app.parse_import({'format': 'xlsx', 'text': text})['scis'][0]['id']
        with app.connect() as c:
            sid = app.save_record(c, {'kind': 'sci', 'data': {'name': 'SCI TEST', 'opening': 1000.0,
                                                             'opening_date': '2024-01-01'}})
            app.import_bundle(c, {'format': 'xlsx', 'text': text, 'mapping': {source: sid}})
            c.commit()
        sheet2 = [[t(0, 'SCI TEST')]] + self.HEAD + [[n(4, 3000.0)],
                  [t(0, '05/03/25'), t(1, 'Loyer'), n(3, 1200.0), n(4, 4200.0)]]
        text2 = b64(build_xlsx([('Relevé', sheet2)], numfmts={164: '#,##0.00 €'}, cell_xfs=[0, 164]))
        source2 = app.parse_import({'format': 'xlsx', 'text': text2})['scis'][0]['id']
        with app.connect() as c:
            result = app.import_bundle(c, {'format': 'xlsx', 'text': text2,
                                           'mapping': {source2: sid}})
            c.commit()
        joined = '\n'.join(result['warnings'])
        self.assertIn('ne correspond pas au solde', joined)
        self.assertIn('→', joined)


if __name__ == '__main__':
    unittest.main()
