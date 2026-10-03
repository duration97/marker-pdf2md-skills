"""Serial, source-checked segment conversion; printed-page review remains separate."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
from page_provenance import source_manifest
from convert_pdf import inspect_pdf

def save(value,path):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(path)

def main():
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):stream.reconfigure(encoding='utf-8',errors='replace')
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('pdf',nargs='+',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--segment-pages',type=int,default=60);p.add_argument('--parallel',type=int,default=1)
    p.add_argument('--reuse-server',action='store_true');p.add_argument('--mode',choices=['balanced','fast'],default='balanced')
    a=p.parse_args()
    if a.segment_pages<=0 or not 1<=a.parallel<=8:
        p.error('--segment-pages must be positive and --parallel must be 1–8')
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=True);state_path=out/'batch_manifest.json'
    state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {'books':[]}
    sentinel=Path.home()/'.cache/datalab/surya/llamacpp_server.json'
    preexisting=json.loads(sentinel.read_text()) if sentinel.exists() else None
    if preexisting:
        import psutil
        try:
            previous_proc=psutil.Process(preexisting.get('pid',0))
            if previous_proc.name().lower()!='llama-server.exe':preexisting=None
        except (psutil.NoSuchProcess,psutil.AccessDenied):preexisting=None
    owned=None
    try:
        for pdf in a.pdf:
            pdf=pdf.resolve(strict=True);source=source_manifest(pdf,inspect_pdf(pdf)['total_pages'])
            book=next((b for b in state['books'] if b['source_sha256']==source['source_sha256']),None)
            if book is None:
                book={**source,'id':source['source_sha256'][:12],'segments':[],'status':'pending'};state['books'].append(book)
            for start in range(0,source['total_pdf_pages'],a.segment_pages):
                end=min(start+a.segment_pages-1,source['total_pdf_pages']-1)
                seg=next((s for s in book['segments'] if s['start_index']==start),None)
                if seg and seg['status']=='converted':
                    report=json.loads(Path(seg['report']).read_text(encoding='utf-8'))
                    rows=json.loads(Path(seg['report']).with_name('page_map.json').read_text(encoding='utf-8'))
                    if report['source_sha256']!=source['source_sha256'] or not Path(report['markdown']).is_file():
                        raise ValueError('Resumed segment source/output does not match')
                    if [r['pdf_page'] for r in rows]!=list(range(start+1,end+2)):
                        raise ValueError('Resumed segment page boundaries do not match')
                    continue
                if seg is None:seg={'start_index':start,'end_index':end};book['segments'].append(seg)
                target=out/book['id']/'segments'/f'pdf-{start+1:04d}-{end+1:04d}';target.parent.mkdir(parents=True,exist_ok=True)
                seg['status']='running';book['status']='running';save(state,state_path)
                env={**os.environ,'PYTHONIOENCODING':'utf-8','SURYA_INFERENCE_PARALLEL':str(a.parallel)}
                if a.reuse_server:env['SURYA_INFERENCE_KEEP_ALIVE']='true'
                command=[sys.executable,str(Path(__file__).with_name('convert_pdf.py')),str(pdf),'--scan-book','--mode',a.mode,'--parallel',str(a.parallel),'--page-range',f'{start}-{end}','--output',str(target),'--timeout','2400']
                print(f"START {pdf.name}: PDF {start+1}-{end+1}",flush=True);began=time.monotonic()
                with target.with_suffix('.wrapper.log').open('w',encoding='utf-8') as log:
                    result=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT)
                if a.reuse_server and preexisting is None and owned is None and sentinel.exists():
                    import psutil
                    data=json.loads(sentinel.read_text());pid=data.get('pid')
                    if pid:
                        proc=psutil.Process(pid)
                        if proc.name().lower()=='llama-server.exe':owned=(pid,proc.create_time())
                seg['seconds']=round(time.monotonic()-began,3)
                reports=sorted(target.rglob('quality_report.json'),key=lambda f:f.stat().st_mtime) if target.exists() else []
                if result.returncode or not reports:
                    seg['status']='failed';book['status']='failed';save(state,state_path);raise RuntimeError(f'Segment failed: {target}')
                report_path=reports[-1];report=json.loads(report_path.read_text(encoding='utf-8'))
                rows=json.loads(report_path.with_name('page_map.json').read_text(encoding='utf-8'))
                if report['source_sha256']!=source['source_sha256'] or [r['pdf_page'] for r in rows]!=list(range(start+1,end+2)):
                    raise ValueError('Converted segment source/page boundaries do not match')
                seg.update(status='converted',report=str(report_path),markdown=report['markdown'],warnings=report['warnings']);save(state,state_path)
                print(f"DONE PDF {start+1}-{end+1}: {seg['seconds']}s",flush=True)
            book['status']='converted';save(state,state_path)
    finally:
        if owned:
            import psutil
            try:
                proc=psutil.Process(owned[0])
                if proc.create_time()==owned[1] and proc.name().lower()=='llama-server.exe':
                    proc.terminate();proc.wait(timeout=15)
                    if sentinel.exists() and json.loads(sentinel.read_text()).get('pid')==owned[0]:sentinel.unlink()
            except psutil.NoSuchProcess:pass
    print('ALL_SEGMENTS_CONVERTED',flush=True)

if __name__=='__main__':main()
