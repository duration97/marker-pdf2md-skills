"""Low-ink scan/OCR inconsistency: review only, never infer a blank page."""
import re
def low_ink_risks(pdf, pages):
    import pypdfium2 as pdfium
    from PIL import Image
    flags=[]
    with pdfium.PdfDocument(str(pdf)) as doc:
        for row in pages:
            body=row['body'];visible=re.sub(r'<[^>]+>', '',body)
            visible=re.sub(r'!\[[^\]]*\]\([^)]*\)','',visible)
            chars=len(re.sub(r'\s','',visible))
            if chars<40:continue
            page=doc[row['pdf_page']-1]
            image=page.render(scale=.6).to_pil().convert('L');page.close()
            # Exclude bindings, page edges, running headers and footer labels.
            crop=image.crop((int(image.width*.10),int(image.height*.16),int(image.width*.90),int(image.height*.86)))
            hist=crop.histogram();fraction=sum(hist[:160])/max(1,sum(hist))
            if fraction<.002:
                flags.append({'pdf_page':row['pdf_page'],'body_dark_pixel_fraction':round(fraction,6),'visible_ocr_chars':chars,'risk':'原扫描正文区域墨迹极少但OCR产生较多文字；须查看原图区分扉页、淡页与错误生成'})
    return flags
