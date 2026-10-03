# GitHub 发布与后续更新（入门）

GitHub 用户名是个人主页与仓库地址中的名称；登录邮箱用于登录，不用作仓库路径。`Sign in` 就是登录，`Sign up` 是注册。

本项目地址为 `https://github.com/duration97/marker-pdf2md-skills`，它是一个供 Codex 使用的 PDF 文献转换技能，调用名称为 `$marker-pdf2md-skills`。仓库公开后，别人可以浏览代码、下载 ZIP、提出 Issue，或者 fork 后提交改进。创建仓库与发布版本是两个步骤：仓库存放持续更新的代码；Release 为一个已测试版本提供固定下载入口。此次调用名称调整只提交并推送仓库，不创建新版本，也不修改已有 Release 的下载包；需要新调用名称时使用仓库当前源码。

## 第一次发布的步骤

1. 整理代码、README、依赖说明、许可和测试。检查不含文献全文、运行库、模型、密码与令牌。
2. 在本地初始化 Git，把文件加入暂存区，创建提交。提交表示一次可追踪的代码快照。
3. 用 GitHub CLI 官方设备授权登录。本人在已登录的浏览器打开 `https://github.com/login/device`，输入一次性设备代码并核对 GitHub CLI。密码不交给助手，也不写进命令。
4. 在本人账号下创建公开仓库，将本地提交推送。CLI 例子：`gh repo create marker-pdf2md-skills --public --source . --remote origin --push`。已有本地 README/许可时不要在远端再次创建初始文件。
5. 检查网页上的 README、LICENSE 和代码，检查自动测试。
6. 创建版本标签（如 `v0.1.0`）并发布 Release，说明功能、验证范围与已知限制，提供只含源码的 ZIP 和校验和。

如果仓库名已经存在，先确认其中内容，不直接覆盖。GitHub 官方教程：[将本地代码添加到 GitHub](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)。

## 以后更新

在仓库目录中修改文件并完成测试，再执行：

```powershell
git status
git diff
git add <本次明确要提交的文件>
git commit -m "说明本次改动"
git push
```

`git diff` 让你先看见到底改了什么。不要在文献项目的父目录执行无差别 `git add .`，应在独立代码仓库内操作，并检查暂存文件。

需要固定一个新版本时创建新标签与 Release，不更改已经发布的旧标签。日常修正文档不一定需要立刻发布新版。

## 页面上常用入口

- **Code**：浏览代码；`Download ZIP` 可直接下载。
- **Issues**：反馈错误或提出需求。
- **Pull requests**：查看别人提出的代码修改，阅读检查结果后决定是否合并。
- **Actions**：自动运行的小型测试，不会在本项目默认下载模型或转换你的文献。
- **Releases**：下载固定版本，查看版本说明。
- **Settings**：仓库设置；改名、权限等操作先了解影响。

设备授权完成后通常不用每次重新登录。需要在这台电脑撤销 CLI 登录可用 `gh auth logout --hostname github.com`；也可到 GitHub 账户的应用授权设置撤销 GitHub CLI 权限。
