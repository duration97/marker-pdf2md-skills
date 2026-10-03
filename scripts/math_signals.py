"""Structural math review signals; never certify mathematical equivalence."""
from collections import Counter
import html
import re


def math_risks(body, layout=None):
    flags = []
    formulas = re.findall(r'\$\$(.*?)\$\$', body, re.S)
    numbers = []
    for formula in formulas:
        numbers.extend(int(n) for n in re.findall(r'(?:\\(?:tag|quad)\s*\{?\s*)?\((\d{1,3})\)\s*$', formula.strip()))
        if formula.count('{') != formula.count('}'):
            flags.append('公式花括号不配对')
    if any(count > 1 for count in Counter(numbers).values()):
        flags.append('展示公式编号重复')
    if numbers != sorted(numbers):
        flags.append('展示公式编号顺序异常')
    if len(numbers) >= 3 and any(b-a > 1 for a, b in zip(sorted(set(numbers)), sorted(set(numbers))[1:])):
        flags.append('页内展示公式编号跳号（可能漏式）')
    canonical = [re.sub(r'\s|\\(?:quad|qquad)|\\tag\{\d+\}|\(\d+\)\s*$', '', f) for f in formulas]
    if any(count > 1 for f, count in Counter(canonical).items() if len(f) >= 12):
        flags.append('展示公式内容重复')
    if re.search(r'<math\b|<mfrac\b|<msup\b|<msub\b', body, re.I):
        flags.append('残留 HTML/MathML 数学内容，渲染与重复情况需核验')
    if re.search(r'<sup>\s*(?:−|-|&|&lt;|&gt;)', body):
        flags.append('数学符号疑似被错误提升为上标')
    if layout:
        equations = [b for b in layout.get('blocks', []) if b['type'] == 'Equation' and not b.get('ignored')]
        if equations:
            flags.append('含展示公式：上下标、分式、符号和编号须逐式对照原图')
            if len(equations) > len(formulas):
                flags.append('位置证据中的公式块多于 LaTeX 展示公式（可能被扁平化或漏渲染）')
            for equation in equations:
                text = html.unescape(equation.get('text', ''))
                if len(re.findall(r'\(\d{1,3}\)', text)) >= 3:
                    flags.append('单公式块聚集多个编号（文字层或框选可能错位）')
                    break
    return list(dict.fromkeys(flags))
