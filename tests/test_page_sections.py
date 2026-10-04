"""Authored pagination examples; no OCR or private documents required."""
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from page_provenance import PageBoundaryError, annotate_pages, load_printed_map


class PageSectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def mapping(self, rows, sections=True):
        path = self.root / 'reviewed.csv'
        fields = ['pdf_page', 'printed_page', 'verified', 'note']
        if sections:
            fields.append('所属部分')
        with path.open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        return load_printed_map(path, 20)

    def render(self, indices, mapping, bodies=None):
        bodies = bodies or ['Authored example paragraph.'] * len(indices)
        raw = ''.join('{' + str(i) + '}' + '-' * 48 + '\n\n' + b + '\n\n'
                      for i, b in zip(indices, bodies))
        return annotate_pages(raw, indices, mapping, {}, self.root,
                              metadata_indices=indices, reading=True)

    def test_legacy_four_columns_keep_old_labels(self):
        mapping = self.mapping([dict(pdf_page=5, printed_page='1', verified='true',
                                     note='Reviewed authored page')], sections=False)
        text, records, _ = self.render([4], mapping)
        self.assertIn('〔第 1 页〕', text)
        self.assertNotIn('来源定位', text)
        self.assertEqual(records[0]['所属部分'], '')

    def test_independent_numbering_and_subset_survive_round_trip(self):
        mapping = self.mapping([
            dict(pdf_page=5, printed_page='1', verified='true', note='Reviewed heading', 所属部分='编辑说明'),
            dict(pdf_page=7, printed_page='1', verified='true', note='Reviewed heading', 所属部分='目录')])
        text, records, _ = self.render([4, 6], mapping)
        self.assertIn('〔编辑说明，第 1 页〕', text)
        self.assertIn('〔目录，第 1 页〕', text)
        self.assertEqual([r['anchor'] for r in records], ['pdf-page-000005', 'pdf-page-000007'])
        self.assertEqual([r['text_status'] for r in records], ['unreviewed', 'unreviewed'])
        exported = load_printed_map(self.root / 'page_map.csv', 20)
        self.assertEqual(exported, mapping)
        self.assertEqual(json.loads((self.root / 'page_map.json').read_text(encoding='utf-8')), records)

    def test_heading_alone_does_not_infer_section_or_printed_number(self):
        text, records, _ = self.render([6], {}, ['目录\n\n1'])
        self.assertIn('〔PDF 第 7 页，印刷页码待核〕', text)
        self.assertEqual(records[0]['所属部分'], '')
        self.assertEqual(records[0]['printed_page'], '')
        self.assertFalse(records[0]['verified'])

    def test_confirmed_section_does_not_verify_candidate_number(self):
        mapping = self.mapping([dict(pdf_page=7, printed_page='iv', verified='false',
                                     note='Unclear footer', 所属部分='前言')])
        text, records, _ = self.render([6], mapping)
        self.assertIn('〔前言，PDF 第 7 页，印刷页码待核〕', text)
        self.assertNotIn('第 iv 页', text)
        self.assertEqual(records[0]['printed_page'], 'iv')
        self.assertFalse(records[0]['verified'])

    def test_multiline_section_is_rejected(self):
        with self.assertRaises(PageBoundaryError):
            self.mapping([dict(pdf_page=7, printed_page='1', verified='true',
                               note='Reviewed footer', 所属部分='目录\n正文')])

    def test_section_text_is_escaped_in_md_but_preserved_in_mapping(self):
        section = '目录 <旧版&新版>'
        mapping = self.mapping([dict(pdf_page=7, printed_page='1', verified='true',
                                     note='Reviewed footer', 所属部分=section)])
        text, records, _ = self.render([6], mapping)
        self.assertIn('〔目录 &lt;旧版&amp;新版&gt;，第 1 页〕', text)
        self.assertEqual(records[0]['所属部分'], section)


if __name__ == '__main__':
    unittest.main()
