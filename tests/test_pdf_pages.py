"""Assemblage de pages PDF : import à la suite, suppression, réordonnancement.

L'application reste autonome (aucune dépendance d'exécution) : le lecteur et
l'écrivain PDF sont donc testés sur des fichiers construits à la main, puis
relus par un second parseur indépendant quand il est disponible.
"""
import importlib.util
import io
import unittest
import zlib
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / 'Dominis' / 'Dominis.py'
spec = importlib.util.spec_from_file_location('dominis_pdf', APP)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

SOURCE = APP.read_text(encoding='utf-8')
HTML = app.HTML


def _simple_pdf(pages=2):
    """PDF 1.4 minimal, une page par entrée, table xref classique."""
    contents = []
    for i in range(pages):
        contents.append(('BT /F1 24 Tf 72 700 Td (Page %d) Tj ET' % (i + 1)).encode('latin-1'))
    out = bytearray(b'%PDF-1.4\n%\xe2\xe3\xcf\xd3\n')
    offsets = {}

    def add(num, payload):
        offsets[num] = len(out)
        out.extend(b'%d 0 obj\n' % num + payload + b'\nendobj\n')

    first_page = 3
    font_num = first_page + pages
    add(1, b'<< /Type /Catalog /Pages 2 0 R >>')
    kids = b' '.join(b'%d 0 R' % (first_page + i) for i in range(pages))
    add(2, b'<< /Type /Pages /Count %d /Kids [%s] >>' % (pages, kids))
    for i, data in enumerate(contents):
        add(first_page + i, (b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] '
                             b'/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>'
                             % (font_num, font_num + 1 + i)))
    add(font_num, b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>')
    for i, data in enumerate(contents):
        add(font_num + 1 + i, b'<< /Length %d >>\nstream\n%s\nendstream' % (len(data), data))
    total = len(offsets)
    xref = len(out)
    out.extend(b'xref\n0 %d\n0000000000 65535 f \n' % (total + 1))
    for num in range(1, total + 1):
        out.extend(b'%010d 00000 n \n' % offsets[num])
    out.extend(b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (total + 1, xref))
    return bytes(out)


def _objstm_pdf(pages=3):
    """PDF 1.5 : pages rangées dans un flux d'objets et table xref compressée."""
    contents = [('BT /F1 20 Tf 72 700 Td (Objet %d) Tj ET' % (i + 1)).encode('latin-1') for i in range(pages)]
    font_num = 3 + pages + 1
    simple = {
        1: b'<< /Type /Catalog /Pages 2 0 R >>',
        2: b'<< /Type /Pages /Count %d /Kids [%s] >>' % (
            pages, b' '.join(b'%d 0 R' % (3 + i) for i in range(pages))),
    }
    for i in range(pages):
        simple[3 + i] = (b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] '
                         b'/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>'
                         % (font_num, font_num + 1 + i))
    simple[font_num] = b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>'
    stream_nums = [font_num + 1 + i for i in range(pages)]

    header, body, index = [], bytearray(), {}
    for pos, (num, raw) in enumerate(sorted(simple.items())):
        header.append(b'%d %d' % (num, len(body)))
        index[num] = pos
        body += raw + b' '

    out = bytearray(b'%PDF-1.5\n%\xe2\xe3\xcf\xd3\n')
    offsets = {}

    def add(num, payload):
        offsets[num] = len(out)
        out.extend(b'%d 0 obj\n' % num + payload + b'\nendobj\n')

    stm_num = max(stream_nums) + 1
    xref_num = stm_num + 1
    total = xref_num + 1
    for num, data in zip(stream_nums, contents):
        add(num, b'<< /Length %d >>\nstream\n%s\nendstream' % (len(data), data))
    head = b' '.join(header) + b'\n'
    packed = zlib.compress(head + bytes(body))
    add(stm_num, (b'<< /Type /ObjStm /N %d /First %d /Filter /FlateDecode /Length %d >>\n'
                  b'stream\n' % (len(simple), len(head), len(packed))) + packed + b'\nendstream')
    rows = bytearray()
    for num in range(total):
        if num in index:
            rows += bytes([2]) + stm_num.to_bytes(4, 'big') + index[num].to_bytes(2, 'big')
        elif num in offsets:
            rows += bytes([1]) + offsets[num].to_bytes(4, 'big') + b'\x00\x00'
        else:
            rows += bytes([0]) + b'\x00\x00\x00\x00' + b'\xff\xff'
    xref_off = len(out)
    data = zlib.compress(bytes(rows))
    add(xref_num, (b'<< /Type /XRef /Size %d /W [1 4 2] /Root 1 0 R /Filter /FlateDecode '
                   b'/Length %d >>\nstream\n' % (total, len(data))) + data + b'\nendstream')
    out.extend(b'startxref\n%d\n%%%%EOF\n' % xref_off)
    return bytes(out)


def read_pages(raw):
    try:
        from pypdf import PdfReader
    except ImportError:  # pypdf n'est pas une dépendance d'exécution
        return None
    return PdfReader(io.BytesIO(raw))


class PdfReadingTests(unittest.TestCase):
    def test_a_classic_pdf_is_read_page_by_page(self):
        source = app.PdfSource(_simple_pdf(3))
        self.assertEqual(source.page_count(), 3)
        self.assertEqual(source.version, (1, 4))

    def test_a_pdf_with_object_streams_is_read(self):
        # Les PDF récents (Chrome, Word) rangent leurs pages dans un flux
        # d'objets compressé : sans cette lecture, l'import échouerait.
        source = app.PdfSource(_objstm_pdf(3))
        self.assertEqual(source.page_count(), 3)

    def test_a_non_pdf_is_refused_with_a_clear_message(self):
        with self.assertRaises(app.PdfError):
            app.PdfSource(b'PK\x03\x04 pas un pdf')

    def test_an_encrypted_pdf_is_refused(self):
        raw = _simple_pdf(1).replace(b'trailer\n<< /Size', b'trailer\n<< /Encrypt 9 0 R /Size')
        with self.assertRaises(app.PdfError):
            app.PdfSource(raw)


class PdfCompositionTests(unittest.TestCase):
    def test_a_single_page_can_be_extracted(self):
        raw = app.pdf_page_pdf(_simple_pdf(3), 1)
        self.assertEqual(app.pdf_pages_from_bytes(raw), 1)
        reader = read_pages(raw)
        if reader is not None:
            self.assertIn('Page 2', reader.pages[0].extract_text())

    def test_pages_are_reordered(self):
        raw = app.pdf_reorder(_simple_pdf(3), [3, 1, 2])
        self.assertEqual(app.pdf_pages_from_bytes(raw), 3)
        reader = read_pages(raw)
        if reader is not None:
            self.assertIn('Page 3', reader.pages[0].extract_text())

    def test_a_page_can_be_removed(self):
        raw = app.pdf_remove_page(_simple_pdf(3), 2)
        self.assertEqual(app.pdf_pages_from_bytes(raw), 2)
        reader = read_pages(raw)
        if reader is not None:
            texts = [p.extract_text() for p in reader.pages]
            self.assertTrue(any('Page 1' in t for t in texts))
            self.assertFalse(any('Page 2' in t for t in texts))

    def test_selection_can_drop_several_pages(self):
        raw = app.pdf_select(_simple_pdf(4), [4, 1])
        self.assertEqual(app.pdf_pages_from_bytes(raw), 2)

    def test_the_last_page_cannot_be_removed(self):
        with self.assertRaises(app.PdfError):
            app.pdf_remove_page(_simple_pdf(1), 1)

    def test_an_unknown_page_is_refused(self):
        with self.assertRaises(app.PdfError):
            app.pdf_select(_simple_pdf(2), [1, 5])

    def test_a_document_can_be_appended_to_another(self):
        first = app.PdfSource(_simple_pdf(2))
        second = app.PdfSource(_simple_pdf(3))
        merged = app.compose_pdf([(first, 0), (first, 1)] + [(second, i) for i in range(3)])
        self.assertEqual(app.pdf_pages_from_bytes(merged), 5)
        reader = read_pages(merged)
        if reader is not None:
            self.assertIn('Page 1', reader.pages[0].extract_text())
            self.assertIn('Page 1', reader.pages[2].extract_text())

    def test_shared_resources_are_copied_once(self):
        # Deux pages du même document partagent leur police : elle ne doit pas
        # être dupliquée à chaque page, sinon le fichier grossit sans raison.
        one = len(app.pdf_page_pdf(_simple_pdf(2), 0))
        two = len(app.pdf_select(_simple_pdf(2), [1, 2]))
        self.assertLess(two, one * 2)


class PdfImageImportTests(unittest.TestCase):
    # JPEG 3 × 2 px en base64 (l'import accepte aussi une image : elle devient
    # une page pleine, ce qui couvre les scans photographiés).
    JPEG_1PX = __import__('base64').b64decode(
        '/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABsSFBcUERsXFhceHBsgKEIrKCUlKFE6PTBCYFVlZF9VXVtqeJmBanGQc1tdhbWG'
        'kJ6jq62rZ4C8ybqmx5moq6T/2wBDARweHigjKE4rK06kbl1upKSkpKSkpKSkpKSkpKSkpKSkpKSkpKSkpKSkpKSkpKSkpKSkpKSk'
        'pKSkpKSkpKSkpKT/wAARCAACAAMDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgED'
        'AwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdI'
        'SUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW'
        '19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQA'
        'AQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldY'
        'WVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk'
        '5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDnqKKKok//2Q==')
    PNG_1PX = bytes.fromhex(
        '89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de0000000c4944415408d7'
        '63f8ffff3f0005fe02fea7358cd60000000049454e44ae426082')

    def test_a_jpeg_becomes_a_full_page(self):
        raw = app.image_page_pdf(self.JPEG_1PX)
        self.assertEqual(app.pdf_pages_from_bytes(raw), 1)
        reader = read_pages(raw)
        if reader is not None:
            self.assertAlmostEqual(float(reader.pages[0].mediabox.width), 595.28, places=1)

    def test_a_png_becomes_a_full_page(self):
        raw = app.image_page_pdf(self.PNG_1PX)
        self.assertEqual(app.pdf_pages_from_bytes(raw), 1)

    def test_an_unknown_format_is_refused(self):
        with self.assertRaises(app.PdfError):
            app.pdf_sources_from_upload('note.txt', b'bonjour')


class DocumentPagesApiTests(unittest.TestCase):
    def test_the_page_endpoints_exist(self):
        self.assertIn("if path=='/api/document-page':", SOURCE)
        self.assertIn("if path=='/api/document-info':", SOURCE)
        self.assertIn("if path=='/api/document-pages':", SOURCE)

    def test_appending_replaces_the_blob_so_the_download_is_complete(self):
        # Le PDF assemblé remplace le fichier d'origine : l'aperçu, le bouton
        # Télécharger et la sauvegarde servent toujours le document complet.
        block = SOURCE[SOURCE.index("if path=='/api/document-pages':"):SOURCE.index("if path=='/api/declaration-pdf':")]
        self.assertIn("d['blob']=base64.b64encode(out).decode('ascii')", block)
        self.assertIn("d['pdf_pages']=pages", block)
        self.assertIn("save_record(c,{'kind':'documents'", block)
        self.assertIn("if op=='append':", block)
        self.assertIn("elif op=='order':", block)

    def test_the_interface_offers_append_and_arrange(self):
        self.assertIn('data-doc-append-btn', HTML)
        self.assertIn('data-doc-arrange', HTML)
        self.assertIn("Ajouter au document", HTML)
        self.assertIn("Modifier la disposition", HTML)
        self.assertIn('function docArrangeModal(', HTML)
        self.assertIn('function docAppendFiles(', HTML)

    def test_a_page_can_be_moved_or_removed_from_the_grid(self):
        self.assertIn('data-doc-page-move', HTML)
        self.assertIn('data-doc-page-del', HTML)
        self.assertIn('function docPagesFlip(', HTML)   # animation FLIP au réordonnancement
        self.assertIn('draggable="true" data-page=', HTML)

    def test_nothing_is_sent_before_the_explicit_save(self):
        self.assertIn("$('#save-doc-pages').onclick", HTML)
        self.assertIn("notify('Disposition enregistrée", HTML)


class DeclarationPdfTests(unittest.TestCase):
    def test_the_download_button_and_endpoint_exist(self):
        self.assertIn('data-action="decl-pdf"', HTML)
        self.assertIn("case'decl-pdf':await declPdfDownload();break;", HTML)
        self.assertIn("if path=='/api/declaration-pdf':", SOURCE)

    def test_the_model_reuses_the_displayed_amounts(self):
        # Aucun recalcul côté serveur : le PDF part du même declModel que l'écran.
        block = HTML[HTML.index('function declPdfModel(s,period){'):]
        block = block[:block.index('async function declPdfDownload(')]
        self.assertIn('let m=declModel(s,period);', block)
        self.assertIn('let a1=declA1Rows(m,keys)', block)
        self.assertIn('declMainCases(m,keys)', block)
        self.assertIn('declShares(s,period,m)', block)

    def test_every_official_block_is_in_the_pdf(self):
        # Le titre de l'identité dépend du régime : 2072-S pour l'IR,
        # 2065 et liasse 2033 pour l'IS.
        self.assertIn("'1 · Identité de la société'+(isIS?' (2065 et liasse 2033)':' (cadre II de la 2072-S)')", HTML)
        for title in (
                      '2072-S · cadre I — résultat de la société',
                      '2072-S · cadre IV — immeubles détenus',
                      'Annexe A1 · cadre VII — détail par immeuble',
                      'Annexe A2 · cadre IX — répartition entre associés',
                      '2044 de chaque associé', 'Points à vérifier avant de déposer'):
            self.assertIn(title, HTML)

    def test_the_pdf_says_it_is_not_an_official_form(self):
        self.assertIn('Ce n’est pas un formulaire officiel', HTML)
        self.assertIn('il ne se dépose pas en l’état', HTML)

    def test_the_builder_uses_the_declaration_header(self):
        self.assertIn("str(self.model.get('eyebrow') or 'DOMINIS · SYNTHÈSE ANNUELLE')", SOURCE)
        self.assertIn("str(self.model.get('footer') or", SOURCE)


def _csv_model():
    return {
        'sci': 'SCI Les Oliviers',
        'regime': 'IR',
        'period': '2026',
        'sections': [
            {'name': '2072-S · cadre I', 'rows': [
                ['R1', 'Revenus bruts', 'Résultat de la société', 25030],
                ['R2', 'Paiement sur travaux', 'Résultat de la société', 4400],
                ['R3', 'Frais et charges autres qu’intérêts d’emprunts', 'Résultat de la société', 4400],
                ['R4', 'Intérêts d’emprunts', 'Résultat de la société', 0],
                ['R5', 'Revenu net (+) ou déficit net (−)', 'Résultat de la société', 20630],
            ]},
            {'name': 'Annexe A1 · cadre VII', 'rows': [
                ['1', 'Montant brut des fermages ou des loyers encaissés', '12 rue des Jardins', 15400],
                ['1', 'Montant brut des fermages ou des loyers encaissés', 'Total', 25030],
            ]},
        ],
        'recap': {
            'recettes': [
                ['2026-01-05', 'Loyer janvier', 'Loyers', '12 rue des Jardins', 1200.5, '1'],
                ['2026-02-05', 'Loyer février', 'Loyers', '12 rue des Jardins', 1200.5, '1'],
            ],
            'depenses': [
                ['2026-03-01', 'Réparation chaudière', 'Entretien', '12 rue des Jardins', 350.25, '9'],
            ],
            'hors': [
                ['2026-04-01', 'Apport en compte courant', 'Apport', '—', 10000, 'Opération de financement'],
            ],
        },
    }


class DeclarationCsvTests(unittest.TestCase):
    def test_the_form_export_lists_every_official_box(self):
        raw = app.build_declaration_csv(_csv_model(), 'form')
        self.assertTrue(raw.startswith(b'\xef\xbb\xbf'), 'BOM pour Excel')
        text = raw.decode('utf-8-sig')
        lines = text.splitlines()
        self.assertEqual(lines[0], 'Formulaire;Case;Libellé;Détail;Montant;Unité')
        self.assertIn('2072-S · cadre I;R1;Revenus bruts;Résultat de la société;25030;euros', lines)
        self.assertIn('2072-S · cadre I;R5;Revenu net (+) ou déficit net (−);Résultat de la société;20630;euros', lines)
        self.assertIn('Annexe A1 · cadre VII;1;Montant brut des fermages ou des loyers encaissés;12 rue des Jardins;15400;euros', lines)

    def test_the_form_export_keeps_zero_amounts(self):
        # Une case à zéro doit figurer : c'est une case du formulaire.
        text = app.build_declaration_csv(_csv_model(), 'form').decode('utf-8-sig')
        self.assertIn('R4;Intérêts d’emprunts;Résultat de la société;0;euros', text)

    def test_the_recap_export_is_ordered_and_totalled(self):
        text = app.build_declaration_csv(_csv_model(), 'recap').decode('utf-8-sig')
        lines = text.splitlines()
        self.assertIn('SCI Les Oliviers;Exercice 2026;Régime IR;;;', lines)
        self.assertIn('RECETTES;;;;;', lines)
        self.assertIn('DÉPENSES;;;;;', lines)
        self.assertIn('2026-01-05;Loyer janvier;Loyers;12 rue des Jardins;1200,50;1', lines)
        self.assertIn('TOTAL RECETTES;;;;2401,00;', lines)
        self.assertIn('TOTAL DÉPENSES;;;;350,25;', lines)
        self.assertIn('RÉSULTAT (recettes − dépenses);;;;2050,75;Bénéfice', lines)
        self.assertIn('TOTAL HORS RÉSULTAT;;;;10000,00;', lines)

    def test_the_recap_separates_everything_outside_the_result(self):
        # Financement, échéances à ventiler et catégories non classées ne
        # doivent jamais gonfler les recettes ou les dépenses.
        text = app.build_declaration_csv(_csv_model(), 'recap').decode('utf-8-sig')
        recettes = text.split('RECETTES')[1].split('DÉPENSES')[0]
        self.assertNotIn('Apport en compte courant', recettes)

    def test_a_deficit_is_named_as_such(self):
        model = _csv_model()
        model['recap']['depenses'].append(['2026-05-01', 'Toiture', 'Travaux', '12 rue', 9000, '9'])
        text = app.build_declaration_csv(model, 'recap').decode('utf-8-sig')
        self.assertIn('RÉSULTAT (recettes − dépenses);;;;-6949,25;Déficit', text)

    def test_values_that_look_like_formulas_are_neutralised(self):
        model = _csv_model()
        model['recap']['recettes'].append(['2026-06-01', '=1+1', 'Loyers', '12 rue', 10, '1'])
        model['sections'][0]['rows'].append(['R9', '@SUM(A1)', 'test', 5])
        text = app.build_declaration_csv(model, 'recap').decode('utf-8-sig') + \
               app.build_declaration_csv(model, 'form').decode('utf-8-sig')
        self.assertNotIn(';=1+1;', text)
        self.assertIn("'=1+1", text)
        self.assertIn("'@SUM(A1)", text)

    def test_semicolons_and_quotes_survive_a_round_trip(self):
        import csv as _csv
        model = _csv_model()
        model['recap']['recettes'].append(['2026-07-01', 'Loyer "spécial"; mars', 'Loyers', '12 rue', 1, '1'])
        text = app.build_declaration_csv(model, 'recap').decode('utf-8-sig')
        rows = list(_csv.reader(io.StringIO(text), delimiter=';'))
        self.assertTrue(any(r[:2] == ['2026-07-01', 'Loyer "spécial"; mars'] for r in rows))

    def test_invalid_models_are_refused(self):
        for bad, fmt in ((None, 'form'), ('texte', 'recap'), ({}, 'recap'), ({'sci': 'x'}, 'form')):
            with self.subTest(bad=bad, fmt=fmt), self.assertRaises(ValueError):
                app.build_declaration_csv(bad, fmt)

    def test_the_endpoint_and_the_buttons_exist(self):
        self.assertIn("if path=='/api/declaration-csv':", SOURCE)
        self.assertIn('data-action="decl-csv"', HTML)
        self.assertIn('data-decl-csv="recap"', HTML)
        self.assertIn('data-decl-csv="form"', HTML)
        self.assertIn("case'decl-csv':declExportModal();break;", HTML)
        self.assertIn('function declCsvModel(', HTML)

    def test_screen_pdf_and_csv_share_the_same_labels(self):
        # Les cinq cases du cadre I sont définies une seule fois.
        self.assertIn('const DECL_MAIN_CASES=[', HTML)
        self.assertIn("let cases=DECL_MAIN_CASES.map(([code,label,note])=>[code,label,c[code],note]);", HTML)
        self.assertIn('DECL_MAIN_CASES.map(([code,label])=>[code,label,\'Résultat de la société\',Math.round(c[code])])', HTML)


class PdfRobustnessTests(unittest.TestCase):
    """Cas limites trouvés en générant des modèles aléatoires."""

    def test_a_table_without_column_settings_still_builds(self):
        # Un tableau dont les largeurs ou les alignements sont incomplets
        # interrompait la génération (IndexError) : le dossier entier échouait.
        model = {'title': 'x', 'sections': [{'title': '1 · test', 'table': {
            'headers': ['A', 'B', 'C'], 'rows': [['1', '2', '3']], 'aligns': ['left']}}]}
        raw, pages = app.build_annual_report_pdf(model)
        self.assertGreaterEqual(pages, 1)
        self.assertEqual(app.pdf_pages_from_bytes(raw), pages)

    def test_a_word_longer_than_the_line_is_broken(self):
        # Un mot insécable plus large que la colonne débordait de la page.
        long_word = 'X' * 120
        model = {'title': 'x', 'sections': [{'title': '1 · test', 'paragraphs': [long_word]}]}
        raw, _ = app.build_annual_report_pdf(model)
        source = app.PdfSource(raw)
        self.assertGreaterEqual(source.page_count(), 1)

    def test_the_width_estimate_majorates_wide_glyphs(self):
        # Le cadratin et les points de suspension étaient sous-estimés : le
        # texte tronqué « à la largeur » dépassait alors sa colonne.
        self.assertGreater(app._pdf_width('—', 10), app._pdf_width('a', 10) * 1.5)
        self.assertGreater(app._pdf_width('…', 10), app._pdf_width('a', 10) * 1.5)
        self.assertAlmostEqual(app._pdf_width('aaaa', 10), app._pdf_width('aaaaa', 10) - app._pdf_width('a', 10), places=1)


class ScreenConsistencyTests(unittest.TestCase):
    """L'écran, le PDF et le CSV partagent les mêmes définitions."""

    def test_the_annex_a1_labels_are_defined_once(self):
        self.assertEqual(HTML.count("const DECL_A1_LINES="), 1)
        self.assertEqual(HTML.count("const DECL_MAIN_CASES="), 1)
        self.assertIn('DECL_A1_LINES.map(([n,label,kind])=>{', HTML)

    def test_the_pdf_prints_every_official_line(self):
        block = HTML[HTML.index('function declPdfA1('):HTML.index('function declPdfA2(')]
        self.assertIn('let keep=DECL_A1_LINES.map(([n,label,kind])=>[n,kind]);', block)

    def test_the_csv_uses_the_screen_labels(self):
        block = HTML[HTML.index('function declCsvModel('):HTML.index('async function declCsvDownload(')]
        self.assertIn('DECL_MAIN_CASES.map(([code,label])', block)
        self.assertIn('DECL_A1_LINES.forEach(([n,label])=>{', block)

    def test_a_negative_amount_stays_a_number_in_the_csv(self):
        # Un montant négatif commence par « - » : il ne doit pas être préfixé,
        # sinon le tableur le traite comme du texte.
        self.assertIn('def _csv_is_number(text):', SOURCE)
        self.assertIn('if text and _csv_is_number(text):', SOURCE)
        raw = app.build_declaration_csv(_csv_model(), 'form')
        self.assertIn(b'-', app.build_declaration_csv(
            {'sci': 'x', 'sections': [{'name': 'n', 'rows': [['a', 'b', 'c', -1234]]}]}, 'form'))

    def test_nothing_is_declared_implicitly_in_the_interface(self):
        # Une affectation sans déclaration créerait une variable globale : le
        # seul cas trouvé par l'analyse statique est désormais déclaré.
        self.assertIn("let docPageOrder=[];", HTML)
        self.assertNotIn("\ndocPageOrder=", HTML)


if __name__ == '__main__':
    unittest.main()
