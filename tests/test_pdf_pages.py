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


if __name__ == '__main__':
    unittest.main()
