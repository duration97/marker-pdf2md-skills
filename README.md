# marker-pdf2md

面向学术写作与文献整理的本地 PDF → Markdown 技能。以 Marker 为转换引擎，重点处理扫描书、中文史料和学术论文，保留公式、表格、图片以及原 PDF 页面定位，并为印刷页码核验提供独立记录。

**质量优先，速度其次。** 本工具生成便于检索、校对和引用的工作文本，不承诺 OCR、公式或表格逐项正确。正式引用须对照原 PDF；PDF 第几页与书上印的页码分别记录。

## 能做什么

- 每页保留稳定锚点，严格检查漏页、重页、乱序和非零起始页段的对应关系。
- 阅读版 MD 使用简洁页标；日志、来源哈希、页码映射和质量报告放在旁文件。
- 逐页检查文字层、不可见 OCR 层、整页扫描图、数学符号和复杂矢量内容。普通文字页可利用原生文字层；复杂页保留精细识别。
- 检查异常压缩率、连续重复、重复表格行、表格列宽、图注/脚注遗漏及淡扫描页与 OCR 字量不一致。
- 检查展示公式重复、编号错序、残留 MathML、位置证据与公式输出不一致。没有报警也不代表公式正确。
- 保留原始输出与修改记录，分段处理并支持核对后续传，可复用本次启动的本地推理服务。

## 安装

需要 Python 3.10 或更高版本。依赖较多，首次安装与模型下载需要网络。已有可用环境可复用；不要为使用本技能自动升级整个 Python 环境。

```powershell
git clone https://github.com/duration97/marker-pdf2md.git
cd marker-pdf2md
# 先按你的硬件安装合适的 PyTorch，参照其官方安装说明。
python -m pip install -r requirements.txt
python scripts/convert_pdf.py --check
```

[PyTorch 安装说明](https://pytorch.org/get-started/locally/)。本次验证使用 Marker 2.0.0、Surya 0.22.1、PDFium 5.10.1；依赖版本变更后应先用代表页回归验证。

Windows x64 可按需安装可选的原生 Vulkan 推理运行库：

```powershell
python scripts/install_runtime.py
python scripts/install_runtime.py --check
```

下载器只在明确运行时联网，使用固定官方 llama.cpp 发布地址与 SHA-256；完整保留配套 DLL 和供应商许可。不覆写已有运行库。已安装者可用 PATH、`LLAMA_CPP_BINARY` 或 `--llama-server` 指定 `llama-server`。其他平台请使用 [llama.cpp 官方构建](https://github.com/ggml-org/llama.cpp/releases)，本下载器仅支持 Windows x64。

模型权重由安装的 Surya 按其版本下载到模型缓存，不在本仓库。首次运行需额外空间与下载时间。若网络需代理，按本地网络配置设置当前进程的 `HTTPS_PROXY`；不把密码或令牌写进仓库。

作为 Codex 技能使用时，将此目录放入你配置的技能目录，例如 `~/.codex/skills/marker-pdf2md`。重载技能后可调用 `$marker-pdf2md`；也可以直接运行以下脚本，不必依赖 Codex。

## 转换

```powershell
# 不加载识别模型，先逐页检查
python scripts/convert_pdf.py "book.pdf" --inspect
python scripts/pdf_triage.py "book.pdf" --output "routing.json"

# 质量优先的阅读版；输出目录自行指定
python scripts/convert_pdf.py "book.pdf" --scan-book --reading --output "raw-md/book"

# 原 PDF 第 4–6 页（参数从 0 开始）；适合代表页试验和局部修复
python scripts/convert_pdf.py "paper.pdf" --page-range "3-5" --expect-math --reading --output "sample"

# 已发现文字层错位时，对特定页做一次针对性的完整 OCR
python scripts/convert_pdf.py "paper.pdf" --page-range "3-5" --force-ocr --expect-math --reading --output "repair"
```

默认 `balanced` 使用 Marker 自身的文字提取与 OCR 修复逻辑。存在文字层不意味着一定要整页 OCR；混合文献不会因为几个抽样页像扫描件就强制全书 OCR。数学识别和图片提取保持开启。

`routing.json` 的 `native_text_fast_candidate` 是快速模式候选，**不是已核验结论**。对普通文字章节核对代表页后，可以用 `--mode fast --page-range "..."` 转换相应原页段；公式、表格、复杂布局保留 `balanced`。本版没有未经核验就把所有可复制文字页自动切换为 fast。详见 [质量与速度](references/performance.md) 和 [文字层与公式核验](references/text-and-math.md)。

多个明确指定的文献可用 `scripts/batch_convert.py`；完整选项执行 `--help`，流程见 [分段转换](references/batch-workflow.md)。默认串行；`--parallel` 提高前须同时比较质量和显存。

## 输出与引用

```text
output/
  book.md                 阅读文本：页标与原 PDF 锚点
  images/                 相对路径引用的图片
  raw/                    Marker 原始结果，便于回查
  page_map.csv/json       PDF 页码与核验后的印刷页码
  source_manifest.json    来源与 SHA-256
  layout_evidence.json    本次识别的块类型、位置、文字
  quality_report.json     风险提示与核验状态
  preflight.json          逐页文字层/扫描特征
  command.json            实际执行参数
  marker_stdout/stderr.log
```

已有输出时创建新的运行子目录，保留旧文件。原 PDF 不修改。页码映射 CSV 可通过 `--page-map` 传入，格式见 [引用与页码](references/citation-quality.md)。印刷页码未经原图核对时明确标为待核；不从固定偏移量推断。重号、缺页或不可辨页码如实记录，不自动补造。

## 电脑配置

| 项目 | 说明 |
|---|---|
| 已实测 | Windows x64、Python 3.13、NVIDIA RTX 3500 Ada 12 GB、原生 Vulkan 后端 |
| 建议起点 | 16 GB 以上内存、SSD；复杂扫描书建议独立 GPU，8–12 GB 显存作为试验起点，具体能否运行取决于模型、分辨率和并行度 |
| 磁盘 | 仓库本身很小；Python/Torch、运行库、模型缓存及文献输出需另计，安装前建议预留至少 10 GB，并观察实际占用 |
| CPU / Apple / Linux | 上游提供相应支持；本项目尚未在这些环境完成真实 OCR 验证，不作为已测兼容性或最低配置承诺 |
| 首次运行 | 安装、模型下载与加载较慢；不计入稳定转换速度 |

“8 GB 显存”或“16 GB 内存”是试验建议，不是所有书都能运行的保证。显存不足时先降低并行度与页段大小。更换设备后先试典型页，不以牺牲公式、图表与脚注换速度。

一次同页集、同模式的 20 页扫描样本测试中，提高本地推理并行度后耗时从 319.4 秒降为 246.2 秒，约减少 22.9%。其中一页的识别问题在两组都存在，所以速度数字不等于准确率。本数字包含该次转换过程，不包含人工校对；其他文献表现会不同。

## 验证与限制

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

测试使用自行生成的微型 PDF，不附书籍或论文全文。自动测试验证页面对应、混合文字层路由、重复风险、公式结构提示和下载解压边界，不能验证任意文献识别准确率。

真实公式论文试验发现：文字层看似完整时仍可出现混排；完整 OCR 能改善结构，但仍会把 `fg` 识成 `gg`、`F` 识成 `f`，需要逐式核验。公式正确性与印刷页码、正文校对是不同的状态。本技能不承诺“无损转换”或“公式全部准确”。

## 许可、参与和发布

本仓库原创代码与文档采用 [Apache-2.0](LICENSE)。Marker、Surya、llama.cpp 及模型权重分别遵循自身许可；请阅读 [第三方说明](THIRD_PARTY_NOTICES.md)，开源代码许可不扩大模型商用权利。

欢迎提交可公开共享的最小复现、页码/公式问题和改进建议。请避免提交有版权限制的整本文献、私人路径、登录令牌或模型文件。见 [贡献说明](CONTRIBUTING.md)。初次发布与后续更新步骤见 [GitHub 发布教程](docs/publishing.md)。
