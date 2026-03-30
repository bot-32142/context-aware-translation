**中文** | [English](README.md)

# 上下文感知翻译（CAT）

CAT 是一个桌面翻译工具，适合翻译长篇小说、书籍、PDF、扫描文档和漫画，并尽量保持人名、术语和上下文一致。

## 适合谁用

- 翻译小说、网文、轻小说
- 翻译需要统一人名、地名、术语的长文档
- 翻译需要先 OCR 的扫描书、PDF 和漫画
- 不想手动拼 Prompt，希望直接用桌面工作流的人

## 为什么用 CAT

- 可以从原文自动构建术语表
- 会随着章节和页数推进持续累积上下文
- 可以先复核 OCR 和术语，再导出结果
- 文本、EPUB、PDF、扫描页、漫画可以用同一套流程处理

## 安装

当前桌面版构建没有签名，所以第一次启动时系统可能会弹出安全提示。

### macOS

- 下载最新的 `.dmg`
- 打开后把 `CAT-UI.app` 拖到 `Applications`
- 从 `Applications` 启动 `CAT-UI.app`
- 如果 macOS 因为开发者无法验证而阻止启动，打开 `系统设置` -> `隐私与安全性`
- 在 `安全性` 区域里为 `CAT-UI.app` 点击 `仍要打开`，然后再确认 `打开`

### Windows

- 下载最新的 `.zip`
- 解压到任意目录
- 运行 `CAT-UI.exe`
- 如果 Windows SmartScreen 提示应用无法识别，点击 `更多信息` -> `仍要运行`

## 快速开始

### 1. 打开 App Settings，开始设置

![设置入口](docs/screenshots/CN/设置.png)

### 2. 运行 Setup Wizard

![设置向导](docs/screenshots/CN/设置向导.png)

### 3. 选择服务商并填入 API key。目前最推荐、也唯一充分验证过的组合是 Gemini + DeepSeek。

![API 配置](docs/screenshots/CN/API配置.png)

### 4. 选择目标语言

![目标语言](docs/screenshots/CN/设置结束.png)

### 5. 新建项目

![新项目](docs/screenshots/CN/新项目.png)

### 6. 按阅读顺序导入文件

![导入](docs/screenshots/CN/导入.png)

### 7. 如果需要，先构建/过滤/审校/翻译术语

![术语](docs/screenshots/CN/术语.png)

### 8. 开始翻译

![翻译](docs/screenshots/CN/翻译.png)

### 9. 导出结果

![导出](docs/screenshots/CN/导出.png)

## 使用前需要知道

- 目前主要测试过的是 `DeepSeek` + `Gemini` 的向导配置路径。
- 其它 provider 和 model 也可能能用，但我没有条件测试大多数模型，所以这里没有验证过。通常需要你自己手动配置连接并调整参数。
- 图片编辑会很烧钱。
- OCR 是尽力而为，复杂版面请先人工复核再导出。
- 如果你希望术语和上下文持续累积，请按阅读顺序导入。
- CAT 还在持续迭代，遇到一些粗糙之处是正常的。

## 支持格式

| 类型 | 导入 | 导出 | 翻译前是否需要 OCR |
| --- | --- | --- | --- |
| 文本 | `.txt`, `.md` | `txt` | 否 |
| PDF | `.pdf` | `epub`, `md` | 是 |
| 扫描书籍 | 图片文件或文件夹 | `epub`, `md` | 是 |
| 漫画 | `.cbz`、图片文件夹 | `cbz` | 是 |
| EPUB | `.epub` | `epub`, `md`, `docx`, `html` | 否，但支持图片 OCR |
