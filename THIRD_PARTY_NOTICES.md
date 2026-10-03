# 第三方组件与模型

本仓库不打包第三方推理二进制、模型权重或文献。下面记录集成所涉及的许可边界；实际使用须查看所下载版本的完整许可。

| 组件 | 上游许可 / 来源 | 本项目的处理 |
|---|---|---|
| Marker | [Apache-2.0](https://github.com/datalab-to/marker/blob/master/LICENSE)、[README](https://github.com/datalab-to/marker/blob/master/README.md) | 通过已安装的官方 CLI 调用；不捆绑源码 |
| Surya 代码 | [Apache-2.0](https://github.com/datalab-to/surya/blob/master/LICENSE)、[README](https://github.com/datalab-to/surya/blob/master/README.md) | 使用其本地推理后端；适配只在本次子进程中生效 |
| Surya / Marker 模型权重 | 上游 README 所说明的修改版 AI Pubs OpenRAIL-M | 模型独立缓存；不是本仓库 Apache-2.0 许可的对象 |
| llama.cpp | [MIT](https://github.com/ggml-org/llama.cpp/blob/master/LICENSE) | 可选固定官方发布包，校验 SHA-256，保留供应商文件 |
| LLVM OpenMP 等运行库组件 | 具体随发行包附带的许可 | 保留完整下载包中的许可和配套库，不以本仓库许可重新许可 |
| PyTorch、PDFium/Python 绑定、Pillow、psutil | 各自安装包及上游许可 | 通过依赖安装，未重打包；部署/分发完整环境时还须遵守其许可 |

上游目前将模型权重许可描述为允许研究、个人使用和融资/营收低于 500 万美元的初创企业使用；超出范围的商业用途应核对当时的模型条款，并向上游确认或取得商业许可。此说明仅帮助定位条款，不能替代具体权重版本的完整许可。

固定的可选 Windows x64 Vulkan 运行库为 llama.cpp `b11344`：

- 来源：https://github.com/ggml-org/llama.cpp/releases/download/b11344/llama-b11344-bin-win-vulkan-x64.zip
- SHA-256：`f561d5af233f802bd0605ff281fd204fba162dfaf09032a361e244ad292ba397`

若以后更换发布版本，必须同时核对来源、完整文件、许可与校验和，再更新下载器并重新验证。
