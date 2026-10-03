"""HTML table span consistency; a warning does not prove an OCR error."""
from html.parser import HTMLParser
class Tables(HTMLParser):
    def __init__(self):
        super().__init__();self.tables=[];self.depth=0;self.rows=None;self.row=None
    def handle_starttag(self,tag,attrs):
        if tag=='table':
            self.depth+=1
            if self.depth==1:self.rows=[]
        if self.depth!=1:return
        if tag=='tr':self.row=[];self.rows.append(self.row)
        elif tag in ('td','th') and self.row is not None:
            attrs=dict(attrs)
            try:rs=int(attrs.get('rowspan','1'));cs=int(attrs.get('colspan','1'))
            except ValueError:rs=cs=-1
            self.row.append((rs,cs))
    def handle_endtag(self,tag):
        if tag=='table':
            if self.depth==1:self.tables.append(self.rows);self.rows=None;self.row=None
            self.depth=max(0,self.depth-1)
        elif tag=='tr':self.row=None
def table_shape_risks(body):
    parser=Tables();parser.feed(body);flags=[]
    for index,rows in enumerate(parser.tables,1):
        carry={};widths=[];invalid=False
        for row in rows:
            occupied=set(carry);cursor=0
            for rs,cs in row:
                if not (1<=rs<=1000 and 1<=cs<=1000):invalid=True;break
                while any(c in occupied for c in range(cursor,cursor+cs)):cursor+=1
                for col in range(cursor,cursor+cs):occupied.add(col);carry[col]=rs
                cursor+=cs
            if occupied:widths.append(max(occupied)+1)
            carry={c:v-1 for c,v in carry.items() if v>1}
        if invalid:flags.append(f'第{index}个HTML表格合并属性特殊或无效，需原图复核')
        elif len(set(widths))>1:flags.append(f'第{index}个HTML表格在计入rowspan/colspan后列数不一致（{sorted(set(widths))}），需原图复核')
    return flags
