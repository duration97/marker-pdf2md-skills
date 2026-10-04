"""Strict Marker page boundaries and reviewed printed-page mapping (no OCR)."""
import csv
import hashlib
import html
import json
from pathlib import Path
import re
from collections import Counter
import zlib


def repetition_metrics(body):
    """Lossless compression is a review signal, never a deletion rule."""
    visible = html.unescape(re.sub(r'<[^>]+>', ' ', body))
    raw = re.sub(r'\s+', ' ', visible).strip().encode('utf-8')
    rows = [re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', row))).strip()
            for row in re.findall(r'<tr\b[^>]*>(.*?)</tr>', body, re.I | re.S)]
    counts = Counter(row for row in rows if len(row) >= 12)
    return {'visible_bytes': len(raw), 'compression_ratio': round(len(raw) / max(1, len(zlib.compress(raw))), 3),
            'table_rows': len(rows), 'max_repeated_table_row': max(counts.values(), default=0)}


class PageBoundaryError(ValueError):
    pass


def text_risks(body):
    """Review signals only; HTML markup and numbered prefixes are not prose."""
    visible = html.unescape(re.sub(r'<[^>]+>', ' ', body))
    compact = re.sub(r'\s', '', visible)
    flags = []
    metrics = repetition_metrics(body)
    if metrics['visible_bytes'] >= 2000 and metrics['compression_ratio'] >= 6:
        flags.append('异常压缩率（整页重复候选）')
    if metrics['table_rows'] >= 100:
        flags.append('表格行数异常（可能为图片误识）')
    if metrics['max_repeated_table_row'] >= 12:
        flags.append('大量重复表格行')
    for block in re.split(r'\n\s*\n', body):
        bm = repetition_metrics(block)
        if bm['visible_bytes'] >= 1000 and bm['compression_ratio'] >= 8:
            flags.append('局部块异常重复'); break
    refs = Counter(re.findall(r'[①-⑳㉑-㉟㊱-㊿]', visible))
    definitions = {marker for group in re.findall(r'(?:^|\n)\s*((?:[①-⑳㉑-㉟㊱-㊿]\s*)+)\S', visible)
                   for marker in re.findall(r'[①-⑳㉑-㉟㊱-㊿]', group)}
    if any(marker not in definitions for marker in refs):
        flags.append('脚注标记可能缺注释（须原图确认，跨页注可能正常）')
    if len(compact) > 6000:
        flags.append('可见文本异常偏长')
    if re.search(r'(.{10,100}?)\1{5,}', compact):
        flags.append('连续重复文本')
    lines = []
    # Repeated numeric cells/formulas are common in real tables, so compare
    # whole prose lines only outside HTML tables.
    prose = html.unescape(re.sub(r'<[^>]+>', ' ', re.sub(r'<table\b.*?</table>', '\n', body, flags=re.I|re.S)))
    for line in prose.splitlines():
        line = re.sub(r'^\s*[（(][零一二三四五六七八九十百\d]+[）)]\s*', '', line)
        line = re.sub(r'\s', '', line)
        if len(line) >= 10:
            lines.append(line)
    if any(count >= 8 for count in Counter(lines).values()):
        flags.append('大量重复行（含编号变动）')
    # Short title/blank pages can hallucinate several repeated prose lines
    # without reaching the whole-page compression byte threshold.
    repeated_chars = max((len(line) * sum(line in other for other in lines)
                          for line in set(lines) if len(line) >= 15
                          and sum(line in other for other in lines) >= 3), default=0)
    if 0 < len(compact) <= 500 and repeated_chars >= len(compact) * 0.3:
        flags.append('短页重复段落（须原图复核）')
    return flags


def selected_indices(total_pages, page_range=None):
    if not page_range:
        return list(range(total_pages))
    selected = set()
    for part in page_range.split(','):
        bounds = part.strip().split('-')
        try:
            if len(bounds) == 1:
                start = end = int(bounds[0])
            elif len(bounds) == 2:
                start, end = map(int, bounds)
            else:
                raise ValueError()
        except ValueError:
            raise PageBoundaryError('页码范围格式无效；使用从 0 开始的编号，例如 0,5-10')
        if start < 0 or end < start or end >= total_pages:
            raise PageBoundaryError('页码范围超出原 PDF 或倒序')
        selected.update(range(start, end + 1))
    return sorted(selected)


def load_printed_map(path, total_pages):
    """Only an explicitly reviewed map can produce a verified printed page."""
    if not path:
        return {}
    result = {}
    with Path(path).open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        required = {'pdf_page', 'printed_page', 'verified', 'note'}
        if not required.issubset(reader.fieldnames or []):
            raise PageBoundaryError('页码映射 CSV 需要 pdf_page,printed_page,verified,note 四列')
        for row in reader:
            number = int(row['pdf_page'])
            if number < 1 or number > total_pages or number in result:
                raise PageBoundaryError('页码映射含重复或超范围 PDF 页码')
            value = row['verified'].strip().lower()
            if value not in {'true', 'false', '1', '0', 'yes', 'no', ''}:
                raise PageBoundaryError('verified 必须明确为 true/false')
            label, note = row['printed_page'].strip(), row['note'].strip()
            section = (row.get('所属部分') or '').strip()
            verified = value in {'true', '1', 'yes'}
            if verified and (not label or not note):
                raise PageBoundaryError('经核验的印刷页码需要页码文本与核验说明 note；无印刷页可写“无印刷页码”')
            if any(c in label + note + section for c in '\r\n'):
                raise PageBoundaryError('页码、核验说明与所属部分不能跨行')
            result[number] = {'printed_page': label, 'verified': verified, 'note': note,
                              '所属部分': section}
    return result


def source_manifest(pdf, total_pages):
    digest = hashlib.sha256()
    with Path(pdf).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'source_pdf': str(Path(pdf).resolve()), 'source_filename': Path(pdf).name,
            'source_sha256': digest.hexdigest(), 'source_bytes': Path(pdf).stat().st_size,
            'total_pdf_pages': total_pages, 'pdf_page_numbering': '1-based',
            'marker_page_numbering': '0-based', 'ocr_text_status': 'unreviewed'}


def annotate_pages(text, expected_indices, mapping, manifest, output, metadata_indices=None, reading=False):
    """Reject ambiguous boundaries instead of inferring them from output position."""
    markers = list(re.finditer(r'^\{(\d+)\}-{48,}[ \t]*\r?$', text, re.M))
    actual = [int(match[1]) for match in markers]
    if actual != list(expected_indices):
        raise PageBoundaryError(f'无法可靠对应原始页：期望 {list(expected_indices)[:12]}（共 {len(expected_indices)} 页），实际 {actual[:12]}（共 {len(actual)} 页）。原始输出已保留，不按结果顺序猜页码。')
    if markers and text[:markers[0].start()].strip():
        raise PageBoundaryError('第一页标记之前有正文，无法可靠归属页面')
    if metadata_indices is not None and list(metadata_indices) != actual:
        raise PageBoundaryError('Markdown 页面标记与 Marker 元数据页码不一致')
    output = Path(output)
    lines = ['<!-- marker-pdf2md provenance: ' + json.dumps(manifest, ensure_ascii=False).replace('--', '\\u002d\\u002d') + ' -->\n',
             '> 引用定位：PDF 页码从 1 开始；原书印刷页码须单独核验。OCR 文本未经逐页校对。\n\n']
    if reading:
        lines = []
    records, warnings = [], []
    for i, match in enumerate(markers):
        index = int(match[1])
        number = index + 1
        body = text[match.end():markers[i + 1].start() if i + 1 < len(markers) else len(text)].strip()
        printed = mapping.get(number, {'printed_page': '', 'verified': False, 'note': ''})
        label = printed['printed_page']
        section = printed.get('所属部分', '')
        displayed = (label + '（已核验）') if printed['verified'] else ((label + '（候选，待核）') if label else '待核')
        anchor = f'pdf-page-{number:06d}'
        if reading:
            page_label = f'第 {label} 页' if printed['verified'] and label != '无印刷页码' else f'PDF 第 {number} 页，' + ('无印刷页码' if printed['verified'] else '印刷页码待核')
            if section:
                page_label = section + '，' + page_label
            lines += [f'<a id="{anchor}"></a>\n\n', f'〔{html.escape(page_label)}〕\n\n', body + '\n\n']
        else:
            lines += [f'<a id="{anchor}"></a>\n\n',
                      f'## 来源定位：PDF 第 {number} 页｜原书印刷页码：{html.escape(displayed)}\n\n', body + '\n\n']
        record = {'pdf_page': number, 'marker_page_index': index, 'printed_page': label,
                  '所属部分': section,
                  'verified': printed['verified'], 'note': printed['note'], 'anchor': anchor,
                  'text_status': 'unreviewed', 'non_whitespace_chars': len(re.sub(r'\s', '', body))}
        records.append(record)
        if record['non_whitespace_chars'] < 80:
            warnings.append(f'PDF 第 {number} 页文本很少，可能为封面/空白页或 OCR 漏文，需核对')
        risks = text_risks(body)
        if risks:
            warnings.append(f'PDF 第 {number} 页：'+ '、'.join(risks) + '；可能发生 OCR 重复生成或幻觉，须查看原图，不能据此引用')
    fieldnames = ['pdf_page', 'marker_page_index', 'printed_page', '所属部分', 'verified', 'note', 'anchor', 'text_status', 'non_whitespace_chars']
    with (output / 'page_map.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({**record, 'verified': str(record['verified']).lower()})
    (output / 'source_manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'page_map.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    unknown = sum(not row['verified'] for row in records)
    if unknown:
        warnings.append(f'{unknown} 页原书印刷页码未核验；可回查 PDF 位置，不能直接把 PDF 页码当原书页码引用')
    return ''.join(lines), records, warnings
