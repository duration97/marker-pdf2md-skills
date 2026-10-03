"""Capture positions from the same OCR pass, without changing installed packages."""
import json, os
from pathlib import Path

def install():
    from marker.converters.pdf import PdfConverter
    original = PdfConverter.build_document
    def capture(self, filepath):
        document = original(self, filepath)
        pages = []
        for page in document.pages:
            blocks = []
            for block in page.current_children:
                if block.removed or block.block_type.name in ('Span', 'Line'):
                    continue
                blocks.append({'id': str(block.id), 'type': block.block_type.name,
                               'bbox': block.polygon.bbox, 'text': block.raw_text(document),
                               'ignored': block.ignore_for_output})
            pages.append({'pdf_page': page.page_id + 1, 'bbox': page.polygon.bbox, 'blocks': blocks})
        Path(os.environ['MARKER_LAYOUT_SIDECAR']).write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding='utf-8')
        return document
    PdfConverter.build_document = capture
