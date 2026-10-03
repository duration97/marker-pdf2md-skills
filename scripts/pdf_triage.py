"""Conservative per-page routing evidence. Text presence is not text accuracy."""
import argparse
import json
import re
from pathlib import Path

MATH = re.compile(r'[α-ωΑ-Ω∑∏∫√∞≤≥≠±∂∇]|[A-Za-z][_^]|\\(?:frac|sum|int)')


def inspect_pdf(pdf, page_range=None):
    import pypdfium2 as pdfium
    import pypdfium2.raw as raw
    from page_provenance import selected_indices
    pages = []
    with pdfium.PdfDocument(str(pdf)) as doc:
        count = len(doc)
        selected = selected_indices(count, page_range)
        for index in selected:
            page = doc[index]
            try:
                tp = page.get_textpage()
                try:
                    text = tp.get_text_range()
                finally:
                    tp.close()
                area = max(1, page.get_width() * page.get_height())
                image_area = 0.0
                paths = hidden = text_objects = 0
                for obj in page.get_objects():
                    if obj.type == raw.FPDF_PAGEOBJ_IMAGE:
                        left, bottom, right, top = obj.get_bounds()
                        image_area = max(image_area, max(0, right-left) * max(0, top-bottom) / area)
                    elif obj.type == raw.FPDF_PAGEOBJ_PATH:
                        paths += 1
                    elif obj.type == raw.FPDF_PAGEOBJ_TEXT:
                        text_objects += 1
                        if raw.FPDFTextObj_GetTextRenderMode(obj) in (3, 7):
                            hidden += 1
                compact = re.sub(r'\s', '', text)
                bad = sum(c == '\ufffd' or '\ue000' <= c <= '\uf8ff' or (ord(c) < 32 and not c.isspace()) for c in text)
                reasons = []
                if len(compact) < 40:
                    reasons.append('little_or_no_text')
                if image_area >= .65:
                    reasons.append('page_size_raster_image')
                elif image_area >= .025:
                    reasons.append('illustration_or_mixed_content')
                if hidden:
                    reasons.append('invisible_text_layer')
                if bad / max(1, len(compact)) > .01:
                    reasons.append('suspicious_character_encoding')
                if MATH.search(text):
                    reasons.append('math_symbols')
                if paths >= 12:
                    reasons.append('vector_diagram_table_or_math')
                scan = image_area >= .65 or (len(compact) < 20 and image_area >= .20)
                pages.append({'pdf_page': index+1, 'page_index': index,
                              'text_chars': len(compact), 'largest_image_area_fraction': round(min(1, image_area), 4),
                              'invisible_text_objects': hidden, 'text_objects': text_objects,
                              'path_objects': paths, 'scan_candidate': scan,
                              'route': 'balanced_required' if reasons else 'native_text_fast_candidate',
                              'reasons': reasons,
                              'text_accuracy': 'unreviewed'})
            finally:
                page.close()
    samples = [pages[i] for i in sorted(set((0, len(pages)//4, len(pages)//2, 3*len(pages)//4, len(pages)-1)))]
    return {'total_pages': count, 'requested_pages': len(selected), 'page_range': page_range,
            'samples': samples, 'pages': pages,
            'likely_scan': sum(p['scan_candidate'] for p in pages) / len(pages) >= .8,
            'all_selected_pages_scan': all(p['scan_candidate'] for p in pages),
            'fast_candidates': [p['pdf_page'] for p in pages if p['route'] == 'native_text_fast_candidate'],
            'routing_policy': 'Use native text within balanced by default; fast candidates require representative source review.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', type=Path)
    parser.add_argument('--page-range')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = json.dumps(inspect_pdf(args.pdf, args.page_range), ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(result, encoding='utf-8')
    else:
        print(result)
