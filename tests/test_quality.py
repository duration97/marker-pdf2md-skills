"""Small authored PDFs exercise observable provenance and routing behavior."""
import io
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from pdf_triage import inspect_pdf
from math_signals import math_risks
from install_runtime import validate_members
from page_provenance import PageBoundaryError, selected_indices, text_risks
from table_signals import table_shape_risks


def make_pdf(path, page_specs):
    """Generate simple test pages ourselves; no external books or fixtures."""
    objects = [b'', b'', b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Type /XObject /Subtype /Image /Width 1 /Height 1 /ColorSpace /DeviceRGB /BitsPerComponent 8 /Length 3 >>\nstream\n\xff\xff\xff\nendstream']
    kids = []
    for spec in page_specs:
        number = len(objects)+1
        kids.append(f'{number} 0 R')
        mode = '3 Tr' if spec.get('hidden') else '0 Tr'
        content = f'BT /F1 12 Tf {mode} 40 500 Td ({spec.get("text", "")}) Tj ET\n'.encode()
        if spec.get('image'):
            content += b'q 600 0 0 800 0 0 cm /Im1 Do Q\n'
        if spec.get('paths'):
            content += b'20 20 m 580 20 l S\n' * 15
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 800] /Resources << /Font << /F1 3 0 R >> /XObject << /Im1 4 0 R >> >> /Contents {number+1} 0 R >>'.encode())
        objects.append(b'<< /Length '+str(len(content)).encode()+b' >>\nstream\n'+content+b'endstream')
    objects[0] = b'<< /Type /Catalog /Pages 2 0 R >>'
    objects[1] = f'<< /Type /Pages /Count {len(kids)} /Kids [{" ".join(kids)}] >>'.encode()
    output = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f'{index} 0 obj\n'.encode()+obj+b'\nendobj\n')
    xref = len(output)
    output.extend(f'xref\n0 {len(offsets)}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        output.extend(f'{offset:010d} 00000 n \n'.encode())
    output.extend(f'trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode())
    path.write_bytes(output)


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pdf = Path(self.temp.name) / 'authored.pdf'

    def test_native_prose_can_be_candidate_without_claiming_accuracy(self):
        make_pdf(self.pdf, [{'text': 'Ordinary visible prose with sufficient letters to support inspection.'}])
        report = inspect_pdf(self.pdf)
        self.assertEqual(report['fast_candidates'], [1])
        self.assertEqual(report['pages'][0]['text_accuracy'], 'unreviewed')

    def test_scan_with_hidden_ocr_is_not_mistaken_for_native_prose(self):
        make_pdf(self.pdf, [{'image': True, 'hidden': True, 'text': 'A long searchable OCR layer is still not proof of correct printed content.'}])
        report = inspect_pdf(self.pdf)
        self.assertTrue(report['all_selected_pages_scan'])
        self.assertEqual(report['fast_candidates'], [])
        self.assertIn('invisible_text_layer', report['pages'][0]['reasons'])

    def test_mixed_book_does_not_force_ocr_on_every_page(self):
        make_pdf(self.pdf, [{'image': True}, {'text': 'A genuinely authored digital paragraph with many readable letters.'}])
        report = inspect_pdf(self.pdf)
        self.assertFalse(report['all_selected_pages_scan'])
        self.assertTrue(report['pages'][0]['scan_candidate'])
        self.assertFalse(report['pages'][1]['scan_candidate'])

    def test_subset_keeps_original_page_numbers(self):
        make_pdf(self.pdf, [{'image': True}, {'text': 'Ordinary visible prose with sufficient letters to support inspection.'}, {'paths': True}])
        report = inspect_pdf(self.pdf, '1-2')
        self.assertEqual([p['pdf_page'] for p in report['pages']], [2, 3])
        self.assertIn('vector_diagram_table_or_math', report['pages'][1]['reasons'])

    def test_equation_representation_and_order_anomalies_surface(self):
        body = '$$x=2 \\quad (15)$$\n$$y=3 \\quad (13)$$\n<math><msup>x</msup></math>'
        flags = math_risks(body, {'blocks': [{'type': 'Equation', 'text': '(1)(2)(3)', 'ignored': False}]})
        self.assertTrue(any('顺序异常' in flag for flag in flags))
        self.assertTrue(any('MathML' in flag for flag in flags))
        self.assertTrue(any('多个编号' in flag for flag in flags))

    def test_math_validation_is_required_even_when_no_structural_error(self):
        flags = math_risks('$$x=2$$', {'blocks': [{'type': 'Equation', 'text': 'x=2', 'ignored': False}]})
        self.assertTrue(any('须逐式' in flag for flag in flags))

    def test_repeated_newspaper_table_is_flagged_without_deletion(self):
        body = '<table>' + '<tr><td>Repeated newspaper image text from an OCR failure</td></tr>'*76 + '</table>'
        self.assertTrue(any('重复' in flag for flag in text_risks(body)))

    def test_rowspan_is_not_reported_as_ragged_table(self):
        body = '<table><tr><td rowspan="2">A</td><td>B</td></tr><tr><td>C</td></tr></table>'
        self.assertEqual(table_shape_risks(body), [])

    def test_invalid_page_range_rejected(self):
        with self.assertRaises((PageBoundaryError, ValueError)):
            selected_indices(3, '3')

    def test_runtime_zip_traversal_rejected(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('../outside.dll', 'untrusted')
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            with self.assertRaises(ValueError):
                validate_members(archive)


if __name__ == '__main__':
    unittest.main()
