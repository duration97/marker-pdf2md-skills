"""Find positional reading-order conflicts; never silently rearrange source text."""
import html
import re

CONTENT_TYPES = {'Text', 'SectionHeader', 'Title', 'ListItem', 'Equation', 'Caption', 'Footnote', 'Table'}
NOTE_PREFIX = re.compile(r'^(?:[①-⑳㉑-㉟㊱-㊿*†‡]|\[?\d{1,3}[\].、)）\s])')


def compact(text):
    return re.sub(r'[^\w]', '', html.unescape(re.sub(r'<[^>]*>', '', text)))


def reading_order_risks(body, page):
    flags = []
    rendered = compact(body)
    matched = []
    for block in page.get('blocks', []):
        if block.get('ignored') or block['type'] not in CONTENT_TYPES:
            continue
        text = html.unescape(block.get('text', '')).strip()
        if block['type'] == 'Footnote' and text and not NOTE_PREFIX.match(text):
            flags.append('脚注块开头未识别到常见注号（可能为编码杂字，须原图核对）')
        snippet = compact(text)[:24]
        if len(snippet) < 12 or rendered.count(snippet) != 1:
            continue
        matched.append({'bbox': block['bbox'], 'position': rendered.index(snippet)})
    if len(matched) < 2:
        return list(dict.fromkeys(flags))
    # Vertical whitespace separates complete layout regions; inside each band,
    # left-column paragraphs may legitimately end below right-column starts.
    bands = []
    for item in sorted(matched, key=lambda b: b['bbox'][1]):
        start, end = item['bbox'][1], item['bbox'][3]
        if not bands or start > bands[-1]['end'] + 10:
            bands.append({'end': end, 'items': [item]})
        else:
            bands[-1]['end'] = max(bands[-1]['end'], end)
            bands[-1]['items'].append(item)
    positions = [[b['position'] for b in band['items']] for band in bands]
    if any(max(upper) > min(lower) for upper, lower in zip(positions, positions[1:])):
        flags.append('上下版面区域顺序冲突（跨栏标题/摘要或同页续文可能错位）')
    bounds = page['bbox']
    middle = (bounds[0] + bounds[2])/2
    margin = (bounds[2]-bounds[0])*.025
    for band in bands:
        left = [b['position'] for b in band['items'] if b['bbox'][2] <= middle+margin]
        right = [b['position'] for b in band['items'] if b['bbox'][0] >= middle-margin]
        if left and right and max(left) > min(right):
            flags.append('两栏顺序冲突候选（须确认是否左栏后接右栏）')
    return list(dict.fromkeys(flags))
