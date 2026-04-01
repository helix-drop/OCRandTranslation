# 外文文献阅读器

在本机运行的外文文献阅读工具。上传 PDF 或图片后，调用 PaddleOCR 解析版面、用大模型翻译，在阅读页对照查看原文与译文。

适合"边读边翻、边核对原文"的使用方式，不需要部署服务器，也不需要数据库配置。

## 开始前需要准备

1. **Python 3.10 或更高版本**
2. **PaddleOCR 令牌** — 在 [aistudio.baidu.com](https://aistudio.baidu.com) 注册后获取
3. **翻译模型 API Key**，二选一：
   - Qwen（DashScope）— 在 [dashscope.aliyun.com](https://dashscope.aliyun.com) 获取
   - DeepSeek — 在 [platform.deepseek.com](https://platform.deepseek.com) 获取

## 快速上手

### 第 1 步：启动程序

macOS / Linux：

```bash
./start_managed.sh
```

Windows 10 / 11（PowerShell）：

```powershell
.\start_managed.ps1
```

Windows（双击）：

```
start_managed.bat
```

首次启动会自动创建虚拟环境、安装依赖，比后续启动慢一些，属于正常现象。启动完成后脚本会尝试自动打开浏览器。

### 第 2 步：填 API Key

在设置页依次填入：

1. `PaddleOCR 令牌`
2. `DashScope API Key` 或 `DeepSeek API Key`（填其中一个即可）

保存后回到首页。

### 第 3 步：上传 PDF，开始阅读

1. 在首页上传 PDF 或图片
2. 等待 OCR 解析完成
3. 点击"从 p.1 开始读"进入阅读页
4. 按需开启左侧 PDF 对照面板

阅读页会逐页显示原文引用块和译文。翻到还没翻译的页时会自动触发翻译，等几秒即可。

## 阅读页能做什么

| 功能 | 说明 |
|---|---|
| 对照阅读 | 左侧 PDF 原文 + 右侧译文，面板宽度可拖拽 |
| 跳页翻译 | 从指定页开始翻译，无需从头等 |
| 目录跳转 | 导入目录后按章节导航（见进阶功能） |
| 导出 Markdown | 导出整本书或选中章节（见进阶功能） |

## 进阶功能

以下功能可按需使用，不影响基本阅读。

### 术语词典

为每份文档维护一份术语对照表，翻译和重译时自动命中。

**批量导入**：在首页文档卡片点击「词典与目录」，上传 `.xlsx` 或 `.csv` 文件：

| 第一列 | 第二列 |
|---|---|
| 源语言术语（如法语原文） | 中文译文 |

支持追加（同名术语以新值覆盖）和覆盖（清空后全量写入）两种模式。首行含"术语""term"等表头字样时自动跳过。

CSV 示例：

```
raison,理性
monomanie,偏执狂
Esquirol,艾斯基洛尔
```

**逐条管理**：进入设置页，滚动到"术语词典"区域，可逐条添加、编辑和删除。

### 书籍目录导航

适合书籍类 PDF，导入目录后阅读页工具栏会出现「目录」下拉，可按章节跳转，当前所在章节自动高亮。

**自动提取**：上传 PDF 后系统会自动尝试：
1. 读取 PDF 内置书签（大多数正式出版的电子书都有）
2. 若无书签，扫描前 30% 的页面寻找目录页超链接

**手动导入**：自动结果不理想时，在首页「词典与目录」上传三列 `.xlsx` 或 `.csv`：

| 第一列 | 第二列 | 第三列 |
|---|---|---|
| 章节标题 | 层级深度（整数） | 原书印刷页码 |

深度约定：`0` = 章，`1` = 节，`2` = 小节。

CSV 示例：

```
第一章 引言,0,1
1.1 研究背景,1,3
1.2 研究方法,1,7
第二章 文献综述,0,12
```

**页码偏移校准**：书籍 PDF 通常有封面等无页码的前置页，导致印刷页码与 PDF 页序不一致。导入目录后系统会尝试自动校准；也可在「词典与目录」弹窗、阅读页目录下拉底部或设置页手动调整。

> 偏移含义：原书第 1 印刷页对应 PDF 的第几页（1-based）。例如封面占 3 页，则填 4。

### 导出 Markdown

在阅读页工具栏点击「导出」，可下载 Markdown 文件。

**格式约定**

- **原文**：用 `> ` 引用块包裹
- **译文**：紧跟原文后的普通段落
- **脚注**：优先导出为 Obsidian 标准脚注 `[^label]` / `[^label]: ...`，定义就近放在对应段落后；高置信尾注分流到 `## 本章尾注` 或 `## 全书尾注`；编号无法解析时保留为 `[脚注] ...` 普通文本块
- **标题**：`#` 数量由目录层级决定（depth=0 → `#`，depth=1 → `##`，以此类推）；无目录时退化为 OCR 识别的字体层级

**按章节选择导出**

导出弹窗会列出所有顶级章节及其页码范围，默认全选。取消勾选部分章节后只导出选中内容。未提取到目录时直接导出全书。

**省略非主体页**

勾选「省略非主体页（版权/广告/重复封面）」后，会自动过滤前置版式页以及前几页中高度相似的重复封面内容。与章节选择导出可叠加使用。

### 自定义翻译模型

在设置页「翻译模型」区域展开「自定义模型」，填写 Provider、模型 ID 和 Base URL（按需）后保存，再点击「启用此自定义模型」。

支持三类：
- `Qwen`：复用 DashScope API Key
- `DeepSeek`：复用 DeepSeek API Key
- `OpenAI Compatible`：需单独填写 Base URL 和专用 API Key

### 段内并发翻译

设置页「翻译性能」里可开启段内并发翻译，单页同时翻译多个段落，速度更快。默认关闭；并发上限由你设置（1–10），数值越高越容易触发限流或超时，建议从低值开始调。

## 手动启动

如果不想用启动脚本，也可以手动执行：

macOS / Linux：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 app.py
```

Windows PowerShell：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

启动后访问 `http://localhost:8080`。

## 数据存放位置

所有用户数据保存在项目目录的 `local_data/` 下，不写入系统级目录：

- `local_data/user_data/config.json` — API Key、模型偏好、术语表等设置
- `local_data/user_data/data/app.db` — SQLite 主库（文档、页面、翻译结果）
- `local_data/user_data/data/documents/{doc_id}/source.pdf` — 每份文档的 PDF 副本
- `local_data/user_data/data/documents/{doc_id}/toc_source.xlsx` 或 `.csv` — 当前目录文件（如有）

这些内容默认不会提交到 Git 仓库。

## 常见问题

**浏览器没有自动打开**

手动访问 `http://localhost:8080`。

**页面提示缺少 Key**

进入设置页，填入 PaddleOCR 令牌和至少一个翻译模型 Key 后保存。

**上传后一直没结果**

检查：PaddleOCR 令牌是否正确、当前网络能否访问外部 API、PDF 是否损坏或过大。

**想停止程序**

在启动程序的终端窗口按 `Ctrl + C`。

## 相关文档

- [DEV.md](DEV.md) — 开发架构与技术说明
- [PROGRESS.md](PROGRESS.md) — 用户反馈与开发计划
- [verification.md](verification.md) — 已执行的验证记录
