#!/usr/bin/env python3
"""Run the installed Marker CLI, preserving raw output and reporting quality hints."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime
from urllib.parse import unquote, urlsplit
import uuid
import time
import unicodedata
from page_provenance import (PageBoundaryError, selected_indices, load_printed_map,
                             source_manifest, annotate_pages)
from reading_copy import layout_risks

# Load the official console entry point in THIS Python, avoiding another Conda env's CLI.
BOOTSTRAP = '''
import os
import importlib
from importlib.metadata import distribution
if os.environ.get('MARKER_LAYOUT_SIDECAR'):
    import sys
    sys.path.insert(0, os.environ['MARKER_SKILL_SCRIPTS'])
    import layout_capture
    layout_capture.install()
# Some Surya releases probe exited servers with os.kill(pid, 0). On Windows,
# 0 is CTRL_C_EVENT, not a Unix liveness probe: it can interrupt the caller.
# Replace only Surya's server-stop helper in this CLI process, never package files.
if os.name == 'nt':
    try:
        spawn = importlib.import_module('surya.inference.backends.spawn')
        import psutil
        def stop_native_server(pid, name):
            try:
                proc = psutil.Process(pid)
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except psutil.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=10)
            except psutil.NoSuchProcess:
                pass
            except psutil.Error as exc:
                spawn.logger.warning('Failed to stop %s (pid %s): %s', name, pid, exc)
        if hasattr(spawn, '_stop_process'):
            spawn._stop_process = stop_native_server
    except ImportError:
        pass
entrypoint = next(e for e in distribution('marker-pdf').entry_points
                  if e.group == 'console_scripts' and e.name == 'marker_single')
entrypoint.load()()
'''


def run(command, timeout=None):
    return subprocess.run(command, shell=False, capture_output=True,
                          encoding='utf-8', errors='replace', timeout=timeout,
                          env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})


def classify(message):
    text = message.lower()
    groups = [
        ('权限问题', ('permission denied', 'access is denied', 'permissionerror')),
        ('内存不足', ('out of memory', 'memoryerror', 'cannot allocate')),
        ('模型下载或网络问题', ('huggingface', 'connectionerror', 'ssl', 'timed out', 'connection refused')),
        ('OCR 本地推理后端缺失或异常', ('llama-server', 'llamacpp', 'vllm', 'docker', 'inference server')),
        ('PDF 损坏、加密或格式不受支持', ('pdfium', 'invalid pdf', 'password', 'encrypted', 'failed to load document')),
        ('Python 环境或依赖问题', ('modulenotfounderror', 'importerror', 'no module named', 'dll load', 'no matching distribution')),
        ('输出路径问题', ('no such file', 'not a directory', 'filename too long')),
    ]
    return next((name for name, words in groups if any(w in text for w in words)),
                '未能自动归类；请查看保存的日志')


def marker_help(install=False):
    try:
        version = importlib.metadata.version('marker-pdf')
    except importlib.metadata.PackageNotFoundError:
        if not install:
            raise RuntimeError('Marker 未安装。使用当前 Python 安装：python -m pip install -U marker-pdf；或添加 --install-if-missing。')
        print('当前环境缺少 Marker，安装一次 marker-pdf……', file=sys.stderr)
        proc = run([sys.executable, '-m', 'pip', 'install', '-U', 'marker-pdf'])
        if proc.returncode:
            print((proc.stderr or proc.stdout)[-4000:], file=sys.stderr)
            raise RuntimeError('Marker 安装失败：' + classify(proc.stderr + proc.stdout))
        version = importlib.metadata.version('marker-pdf')
    command = [sys.executable, '-c', BOOTSTRAP]
    proc = run(command + ['--help'], timeout=120)
    if proc.returncode:
        print((proc.stderr or proc.stdout)[-4000:], file=sys.stderr)
        raise RuntimeError('Marker --help 失败：' + classify(proc.stderr + proc.stdout) + '。先检查当前解释器和用户 site-packages 是否可访问；已安装包在沙箱中不可见时，不要重复安装。')
    return command, proc.stdout + proc.stderr, version


def supported(help_text, flag):
    return bool(re.search(re.escape(flag) + r'(?![\w-])', help_text))


def boolean_option(help_text, flag):
    # New releases expose some tri-state settings as BOOLEAN values, not flags.
    match = re.search(r'^\s*' + re.escape(flag) + r'(?![\w-])([^\n]*)', help_text, re.M)
    return [flag, 'true'] if match and re.search(r'\bBOOLEAN\b', match[1]) else [flag]


def configure_backend(binary=None):
    try:
        dist = importlib.metadata.distribution('surya-ocr')
        settings = Path(dist.locate_file('surya/settings.py')).read_text(encoding='utf-8')
    except (importlib.metadata.PackageNotFoundError, OSError):
        return {'backend': 'installed Marker defaults'}
    if 'SURYA_INFERENCE_BACKEND' not in settings or 'LLAMA_CPP_BINARY' not in settings:
        return {'backend': 'installed Marker defaults'}
    if os.environ.get('SURYA_INFERENCE_URL'):
        return {'backend': 'user-configured external endpoint'}
    root = Path(__file__).resolve().parents[1]
    candidate = str(binary.expanduser().resolve()) if binary else os.environ.get('LLAMA_CPP_BINARY')
    if not candidate:
        found = shutil.which('llama-server')
        bundled = list((root / 'runtime').rglob('llama-server.exe')) if (root / 'runtime').exists() else []
        candidate = found or (str(bundled[0]) if len(bundled) == 1 else None)
    if not candidate or not (Path(candidate).is_file() or shutil.which(candidate)):
        raise RuntimeError('此版 Marker OCR 需要本地 llama-server。未找到无 Docker 后端；从 llama.cpp 官方 releases 安装，或传 --llama-server "路径"。')
    os.environ['SURYA_INFERENCE_BACKEND'] = 'llamacpp'
    os.environ['LLAMA_CPP_BINARY'] = candidate
    os.environ.setdefault('SURYA_INFERENCE_PARALLEL', '1')
    cached = {}
    # Reuse complete cached GGUF pairs without an unnecessary remote HEAD request.
    # Never override a user-pinned path or guess the model repository/version.
    if not any(os.environ.get(k) for k in ('SURYA_GGUF_LOCAL_MODEL_PATH', 'SURYA_GGUF_LOCAL_MMPROJ_PATH')):
        names = ['SURYA_GGUF_REPO', 'SURYA_GGUF_MODEL_FILE', 'SURYA_GGUF_MMPROJ_FILE']
        defaults = [re.search(r'^\s*' + name + r':\s*str\s*=\s*[\"\x27]([^\"\x27]+)', settings, re.M) for name in names]
        values = [os.environ.get(name) or (m[1] if m else None) for name, m in zip(names, defaults)]
        if all(values):
            try:
                from huggingface_hub import hf_hub_download
                paths = [hf_hub_download(repo_id=values[0], filename=name, local_files_only=True) for name in values[1:]]
                if all(Path(p).is_file() and Path(p).stat().st_size > 0 for p in paths):
                    cached = dict(zip(['SURYA_GGUF_LOCAL_MODEL_PATH', 'SURYA_GGUF_LOCAL_MMPROJ_PATH'], paths))
                    os.environ.update(cached)
            except (ImportError, OSError, ValueError):
                pass  # Incomplete cache: let the official backend resolve/download.
    return {'backend': 'llamacpp', 'binary': candidate,
            'parallel': os.environ['SURYA_INFERENCE_PARALLEL'], 'cached_gguf_paths': cached}


def inspect_pdf(pdf, page_range=None):
    from pdf_triage import inspect_pdf as triage
    return triage(pdf, page_range)


def run_logged(command, output, timeout=None):
    stdout_path, stderr_path = output / 'marker_stdout.log', output / 'marker_stderr.log'
    with stdout_path.open('w', encoding='utf-8') as out, stderr_path.open('w', encoding='utf-8') as err:
        # Surya's Windows cleanup probes with os.kill(pid, 0), which can send a
        # console control event. Isolate the CLI so that event cannot interrupt us.
        proc = subprocess.Popen(command, shell=False, stdout=out, stderr=err,
                                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0,
                                env={**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUNBUFFERED': '1'})
        try:
            code = proc.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            # Terminate only this invocation and its descendants, never other jobs.
            try:
                import psutil
                children = psutil.Process(proc.pid).children(recursive=True)
                for child in reversed(children):
                    try:
                        child.terminate()
                    except psutil.Error:
                        pass
            except Exception:
                pass
            proc.terminate()
            proc.wait()
            raise RuntimeError('转换超时或被中断；已有输出与实时日志保留于 ' + str(output))
    return subprocess.CompletedProcess(command, code,
        stdout_path.read_text(encoding='utf-8', errors='replace'),
        stderr_path.read_text(encoding='utf-8', errors='replace'))


def local_asset(reference, base, raw):
    """Only resolve existing local images inside this invocation's raw output."""
    parts = urlsplit(reference.replace('\\', '/'))
    if parts.scheme not in ('', 'file') or parts.netloc:
        return None
    candidate = Path(unquote(parts.path))
    if not candidate.is_absolute():
        candidate = base / candidate
    candidate = candidate.resolve()
    if candidate.is_relative_to(raw.resolve()) and candidate.is_file():
        return candidate
    return None


def normalize(markdown, raw, final_dir):
    text = markdown.read_text(encoding='utf-8-sig')
    image_dir = final_dir / 'images'
    image_dir.mkdir()
    copied = {}
    warnings = []

    def replace(reference):
        asset = local_asset(reference, markdown.parent, raw)
        if asset is None:
            if not reference.startswith(('https://', 'http://', 'data:')):
                warnings.append('图片引用无法解析：' + reference)
            return reference
        if asset not in copied:
            name = f'{len(copied) + 1:04d}_' + asset.name
            shutil.copy2(asset, image_dir / name)
            from urllib.parse import quote
            copied[asset] = 'images/' + quote(name)
        return copied[asset]

    # Marker emits inline Markdown images; also handle HTML images.
    text = re.sub(r'(!\[[^\]\n]*\]\()(<[^>]+>|[^\s)]+)([^)\n]*\))',
                  lambda m: m[1] + replace(m[2].strip('<>')) + m[3], text)
    text = re.sub(r'(<img\b[^>]*\bsrc=[\"\x27])([^\"\x27]+)([\"\x27])',
                  lambda m: m[1] + replace(m[2]) + m[3], text, flags=re.I)
    target = final_dir / markdown.name
    target.write_text(text, encoding='utf-8')
    return target, text, copied, warnings


def quality(text, images, expect_math, expect_images):
    warnings = []
    body = re.sub(r'!\[[^\]]*\]\([^)]*\)|<[^>]+>', '', text).strip()
    if not body:
        warnings.append('没有检测到正文文本')
    elif len(body) < 200:
        warnings.append('正文少于 200 字符；短 PDF 可能正常，请核对是否漏页')
    if len(text.encode('utf-8')) < 100:
        warnings.append('Markdown 文件非常小，可能近乎空文件')
    if text.count('\ufffd') > 5 or sum(not c.isprintable() and c not in '\n\r\t' and unicodedata.category(c) != 'Zs' for c in text) > 10:
        warnings.append('检测到较多替换字符或控制字符，可能存在乱码')
    if expect_math and not re.search(r'\$[^$]+\$|\\(?:frac|sum|int|begin|alpha|beta)\b|\\\[', text):
        warnings.append('预期存在数学公式，但未检测到美元符号定界公式或常见 LaTeX 结构')
    if expect_images and not images:
        warnings.append('预期有图片，但没有解析到本地图片 assets')
    if not images:
        warnings.append('未提取到可引用图片；无图片的 PDF 可能正常')
    suspicious_dates = re.findall(r'\d{4}年\d{1,2}年\d{1,2}日', text)
    if suspicious_dates:
        warnings.append('异常日期，可能为原书印刷问题或 OCR 误识，需核对原页，不自动改写：' + '、'.join(suspicious_dates[:5]))
    return warnings


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pdf', nargs='?')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--check', action='store_true', help='Check installed CLI without converting')
    parser.add_argument('--install-if-missing', action='store_true')
    parser.add_argument('--force-ocr', action='store_true')
    parser.add_argument('--expect-math', action='store_true')
    parser.add_argument('--expect-images', action='store_true')
    parser.add_argument('--page-range', help='Marker zero-based page range; validated against CLI help')
    parser.add_argument('--scan-book', action='store_true', help='Inspect text layer, enable OCR for likely scans, and preserve page separators')
    parser.add_argument('--inspect', action='store_true', help='Inspect PDF page count/text layer without converting')
    parser.add_argument('--llama-server', type=Path, help='Native llama.cpp binary, used by newer Surya releases')
    parser.add_argument('--mode', choices=['balanced', 'fast'], default='balanced')
    parser.add_argument('--parallel', type=int, choices=range(1,9), help='Native inference slots; benchmark quality and memory before raising')
    parser.add_argument('--reading', action='store_true', help='Clean reading MD; engineering provenance stays in sidecars')
    parser.add_argument('--page-map', type=Path, help='Reviewed printed-page CSV; pdf_page uses 1-based original PDF pages')
    parser.add_argument('--timeout', type=float, help='Maximum conversion seconds; preserve logs on timeout')
    args = parser.parse_args()
    if args.check and args.inspect:
        parser.error('--check 与 --inspect 不能同时使用')
    if not args.check and not args.pdf:
        parser.error('需要 PDF 路径或 --check')
    try:
        pdf = None
        if not args.check:
            pdf = Path(args.pdf).expanduser().resolve(strict=True)
            if not pdf.is_file() or pdf.suffix.lower() != '.pdf':
                raise ValueError('输入必须为存在的 PDF 文件')
            with pdf.open('rb') as handle:
                if b'%PDF-' not in handle.read(1024):
                    raise ValueError('未检测到 PDF 文件头，输入可能损坏')
        # PDF inspection does not require a working OCR CLI.
        if args.inspect:
            print(json.dumps(inspect_pdf(pdf, args.page_range), ensure_ascii=False, indent=2))
            return 0
        command, help_text, version = marker_help(args.install_if_missing)
        if args.check:
            print(f'Python: {sys.executable}\nmarker-pdf: {version}\n{help_text}')
            return 0
        profile = inspect_pdf(pdf, args.page_range)
        printed_map = load_printed_map(args.page_map, profile['total_pages'])
        manifest = source_manifest(pdf, profile['total_pages'])
        if args.parallel:
            os.environ['SURYA_INFERENCE_PARALLEL'] = str(args.parallel)
        backend = configure_backend(args.llama_server)
        if args.scan_book and profile['all_selected_pages_scan']:
            args.force_ocr = True
        flags = ['--output_dir', '--output_format', '--paginate_output']
        if args.force_ocr:
            flags.append('--force_ocr')
        if args.page_range:
            flags.append('--page_range')
        if args.mode:
            flags.append('--mode')
        missing = [flag for flag in flags if not supported(help_text, flag)]
        if missing:
            raise RuntimeError('当前 CLI 不支持所需参数：' + ', '.join(missing))
        output = (args.output.expanduser().resolve() if args.output else
                  pdf.parent / (pdf.stem + '_marker'))
        if output == pdf or (output.exists() and not output.is_dir()):
            raise ValueError('输出路径必须是目录，且不能为输入 PDF')
        output.mkdir(parents=True, exist_ok=True)
        # Reserve a fresh folder: no stale Markdown, overwrites, or destructive cleanup.
        if any(output.iterdir()):
            output = output / ('run_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
            output.mkdir()
        raw = output / 'raw'
        raw.mkdir()
        os.environ['MARKER_LAYOUT_SIDECAR'] = str(output / 'layout_evidence.json')
        os.environ['MARKER_SKILL_SCRIPTS'] = str(Path(__file__).resolve().parent)
        (output / 'marker_help.txt').write_text(help_text, encoding='utf-8')
        (output / 'preflight.json').write_text(json.dumps({'pdf': profile, 'runtime': backend}, ensure_ascii=False, indent=2), encoding='utf-8')
        command += [str(pdf), '--output_dir', str(raw), '--output_format', 'markdown']
        if supported(help_text, '--ocr_inline_math'):
            command += boolean_option(help_text, '--ocr_inline_math')
        if args.force_ocr:
            command += boolean_option(help_text, '--force_ocr')
        if args.page_range:
            command += ['--page_range', args.page_range]
        if args.mode:
            command += ['--mode', args.mode]
        if args.scan_book and supported(help_text, '--html_tables_in_markdown'):
            # Preserve merged cells; the Markdown grid renderer may overflow or
            # shift columns on historical multi-level tables.
            command += boolean_option(help_text, '--html_tables_in_markdown')
        command += boolean_option(help_text, '--paginate_output')
        if args.scan_book and supported(help_text, '--keep_pagefooter_in_output'):
            # Scanned directories/continuations can be mistaken for footers.
            command += boolean_option(help_text, '--keep_pagefooter_in_output')
        if args.scan_book and supported(help_text, '--keep_pageheader_in_output'):
            command += boolean_option(help_text, '--keep_pageheader_in_output')
        (output / 'command.json').write_text(json.dumps(command, ensure_ascii=False, indent=2), encoding='utf-8')
        print('正在转换；首次运行可能下载模型。输出：' + str(output), file=sys.stderr)
        started = time.monotonic()
        proc = run_logged(command, output, args.timeout)
        elapsed = time.monotonic() - started
        if proc.returncode:
            print('Marker 失败：' + classify(proc.stderr + proc.stdout), file=sys.stderr)
            print((proc.stderr or proc.stdout)[-2500:], file=sys.stderr)
            print('原 PDF 和已有输出已保留；日志：' + str(output), file=sys.stderr)
            return 4
        candidates = sorted(raw.rglob('*.md'))
        if len(candidates) != 1:
            print(f'应生成一个 Markdown，实际找到 {len(candidates)} 个；原始输出保留于 {raw}', file=sys.stderr)
            return 5
        # Validate provenance BEFORE exposing a final Markdown. Raw output stays intact.
        original_text = candidates[0].read_text(encoding='utf-8-sig')
        metadata_path = candidates[0].with_name(candidates[0].stem + '_meta.json')
        metadata = {}
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
        metadata_ids = [p['page_id'] for p in metadata.get('page_stats', [])] or None
        annotated, page_records, provenance_warnings = annotate_pages(
            original_text, selected_indices(profile['total_pages'], args.page_range),
            printed_map, manifest, output, metadata_ids)
        target, text, images, warnings = normalize(candidates[0], raw, output)
        # Rewrite image references first, then use the same validated page boundaries.
        annotated, page_records, _ = annotate_pages(
            text, selected_indices(profile['total_pages'], args.page_range),
            printed_map, manifest, output, metadata_ids, reading=args.reading)
        target.write_text(annotated, encoding='utf-8')
        warnings += provenance_warnings + quality(text, images, args.expect_math, args.expect_images)
        chunks = re.split(r'^\{\d+\}-{48,}[^\n]*\n', text, flags=re.M)[1:]
        layout_path = output / 'layout_evidence.json'
        layout = []
        if layout_path.exists():
            layout = json.loads(layout_path.read_text(encoding='utf-8'))
            if [p['pdf_page'] for p in layout] != [p['pdf_page'] for p in page_records]:
                raise PageBoundaryError('位置证据与原PDF页码不一致')
            for body, page in zip(chunks, layout):
                warnings += [f"PDF 第 {page['pdf_page']} 页：{risk}" for risk in layout_risks(body,page)]
        scan_findings=[]
        from table_signals import table_shape_risks
        table_findings=[]
        for row,body in zip(page_records,chunks):
            flags=table_shape_risks(body)
            if flags:table_findings.append({'pdf_page':row['pdf_page'],'risks':flags})
        warnings += [f"PDF 第 {item['pdf_page']} 页：{risk}" for item in table_findings for risk in item['risks']]
        from math_signals import math_risks
        layout_by_page = {p['pdf_page']: p for p in layout}
        math_findings = []
        for row, body in zip(page_records, chunks):
            flags = math_risks(body, layout_by_page.get(row['pdf_page']))
            if flags:
                math_findings.append({'pdf_page': row['pdf_page'], 'risks': flags})
        warnings += [f"PDF 第 {item['pdf_page']} 页：{risk}" for item in math_findings for risk in item['risks']]
        from reading_order_signals import reading_order_risks
        reading_findings = []
        for row, body in zip(page_records, chunks):
            page = layout_by_page.get(row['pdf_page'])
            flags = reading_order_risks(body, page) if page else []
            if flags:
                reading_findings.append({'pdf_page': row['pdf_page'], 'risks': flags})
        warnings += [f"PDF 第 {item['pdf_page']} 页：{risk}" for item in reading_findings for risk in item['risks']]
        if args.mode == 'fast' and any(p['route'] == 'balanced_required' for p in profile['pages']):
            warnings.append('fast 模式包含复杂或扫描页；该结果须与 balanced 和原页对照，不能直接当作质量验证通过')
        if args.scan_book:
            from scan_signals import low_ink_risks
            scanned = {p['pdf_page'] for p in profile['pages'] if p['scan_candidate']}
            scan_findings=low_ink_risks(pdf,[{'pdf_page':row['pdf_page'],'body':body} for row,body in zip(page_records,chunks) if row['pdf_page'] in scanned])
            warnings += [f"PDF 第 {item['pdf_page']} 页：{item['risk']}" for item in scan_findings]
        page_stats = []
        metadata_path = candidates[0].with_name(candidates[0].stem + '_meta.json')
        if metadata_path.exists():
            try:
                metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
                page_stats = [{'page_index': p.get('page_id'), 'text_extraction_method': p.get('text_extraction_method')}
                              for p in metadata.get('page_stats', [])]
                if page_stats and len(page_stats) != profile['requested_pages']:
                    warnings.append('Marker 元数据页数与请求页数不一致，可能漏页')
            except (ValueError, TypeError, AttributeError):
                warnings.append('无法解析 Marker 页面元数据，未能核对页数')
        if args.scan_book and profile['likely_scan'] and len(re.sub(r'\s', '', text)) < profile['requested_pages'] * 100:
            warnings.append('扫描书每页平均少于 100 非空白字符，可能漏识别；空白/封面页可能正常')
        # OCR service may fail while Marker still exits 0; surface that explicitly.
        if re.search(r'\b(error|failed|exception|traceback)\b', proc.stderr + proc.stdout, re.I):
            warnings.append('Marker 日志含 error/failed/exception，需核对是否存在 OCR 失败或漏页')
        if re.search(r'Overflow in columns|rows:\s*\d+\s*>=', proc.stderr + proc.stdout, re.I):
            warnings.append('表格渲染发生行列越界，可能错列或截断合并单元格；须回查表格原图，不可直接引用数值')
        warnings = list(dict.fromkeys(warnings))
        report = {'input': str(pdf), 'markdown': str(target), 'python': sys.executable,
                  'marker_version': version, 'bytes': target.stat().st_size,
                  'images': len(images), 'warnings': warnings,
                  'preflight': profile, 'runtime': backend,
                  'page_stats': page_stats,
                  'scan_text_inconsistencies': scan_findings,
                  'table_shape_inconsistencies': table_findings,
                  'math_review_signals': math_findings,
                  'math_accuracy_status': 'unreviewed',
                  'reading_order_signals': reading_findings,
                  'source_sha256': manifest['source_sha256'],
                  'conversion_seconds': round(elapsed, 3),
                  'seconds_per_page': round(elapsed / profile['requested_pages'], 3),
                  'page_boundaries_verified': True,
                  'printed_page_mapping_complete': all(p['verified'] for p in page_records),
                  'ocr_text_status': 'unreviewed',
                  'review_required': '公式正确性、表格、阅读顺序、脚注和参考文献仍需抽查'}
        (output / 'quality_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        if not text.strip():
            print('Marker 输出为空。输出和日志已保留：' + str(output), file=sys.stderr)
            return 5
        if warnings:
            print('Marker 转换成功，但结果可能存在以下问题……\n- ' + '\n- '.join(warnings), file=sys.stderr)
        print(str(target))
        return 0
    except PageBoundaryError as exc:
        print('页码对应校验失败：' + str(exc), file=sys.stderr)
        return 6
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except (OSError, ValueError, UnicodeError) as exc:
        print(f'输入、路径或结果处理失败：{exc}。原 PDF 与已有输出不会删除。', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
