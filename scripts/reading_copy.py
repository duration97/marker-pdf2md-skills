"""Apply explicitly reviewed deletions; preserve raw OCR and log every change."""
import re, json, argparse
from pathlib import Path

def apply_reviewed(body, decisions):
    changes = []
    for decision in decisions:
        before, after = decision['before'], decision.get('after', '')
        if not decision.get('original_image_reviewed') or not decision.get('reason'):
            raise ValueError('Every deletion/replacement needs original-image review and a reason')
        if not before or body.count(before) != decision.get('count', 1):
            raise ValueError('Reviewed text no longer uniquely matches this page')
        body = body.replace(before, after)
        changes.append(decision)
    return body, changes

def layout_risks(body, page):
    visible = re.sub(r'\s+', '', re.sub(r'<[^>]+>', '', body))
    flags = []
    for block in page.get('blocks', []):
        if block['type'] in ('Caption', 'Footnote') and block.get('text', '').strip():
            text = re.sub(r'\s+', '', block['text'])
            if len(text) >= 8 and text[:8] not in visible:
                flags.append(f"{block['type']}内容可能在渲染中丢失：{text[:40]}")
    return flags

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('pages', type=Path, help='JSON list of pdf_page,body records')
    p.add_argument('review', type=Path, help='JSON keyed by PDF page, each value a list of reviewed edits')
    p.add_argument('output', type=Path)
    a=p.parse_args()
    rows=json.loads(a.pages.read_text(encoding='utf-8'))
    review=json.loads(a.review.read_text(encoding='utf-8')); logs=[]
    for row in rows:
        row['body'], edits=apply_reviewed(row['body'],review.get(str(row['pdf_page']),[]))
        logs += [{'pdf_page':row['pdf_page'],**edit} for edit in edits]
    if a.output.exists():raise FileExistsError(a.output)
    a.output.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    a.output.with_suffix('.changes.json').write_text(json.dumps(logs,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
