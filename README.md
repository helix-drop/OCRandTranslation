# 外文文献阅读器

一个在本机运行的外文文献阅读工具：

- 上传 PDF 或图片
- 调用 PaddleOCR 解析版面
- 用 Qwen / DeepSeek 翻译
- 在阅读页对照查看 PDF 原文、译文和脚注

适合“边读边翻、边核对原文”的使用方式，不需要部署服务器，也不需要数据库配置。

## 先准备什么

开始前只需要准备两样：

1. Python 3.10 或更高版本
2. 可用的 API Key
   - `PaddleOCR 令牌`
   - `Qwen（DashScope）API Key` 或 `DeepSeek API Key`

## 新手最快上手

### 第 1 步：启动程序

macOS / Linux：

```bash
./start.sh
```

Windows 10 / 11：

```powershell
.\start.ps1
```

如果 PowerShell 不方便，也可以直接双击：

```bat
start.bat
```

这些启动脚本会自动完成下面几件事：

1. 首次创建 `.venv` 虚拟环境
2. 安装或更新依赖
3. 启动程序
4. 尝试打开浏览器到 `http://localhost:8080`

### 第 2 步：填 API Key

打开浏览器后：

1. 进入“设置”
2. 填入 `PaddleOCR 令牌`
3. 再填入一个翻译模型的 Key
   - 要么填 `DashScope API Key`
   - 要么填 `DeepSeek API Key`
4. 保存设置

### 第 3 步：上传 PDF 开始读

回到首页后：

1. 上传 PDF 或图片
2. 等待 OCR 解析完成
3. 点击“从 p.1 开始读”或“继续读”
4. 在阅读页里按需要开启 PDF 原文对照

## 如果你想手动启动

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 app.py
```

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

如果你的系统没有 `py`，也可以把第一行改成：

```powershell
python -m venv .venv
```

## 你会看到什么

程序默认运行在：

```text
http://localhost:8080
```

首页主要有三件事：

1. 上传文档
2. 进入设置填写 Key
3. 继续当前文档阅读

阅读页主要有这些能力：

- 逐页阅读译文
- 查看原文和脚注
- 开启左侧 PDF 对照
- 拖拽 PDF 面板宽度
- 从指定页开始翻译
- 导出 Markdown

## 数据放在哪里

所有用户数据都保存在项目目录下的 `local_data/`，不会写到系统级目录：

- `local_data/user_data/config.json`
  保存 API Key、模型偏好、术语表和部分阅读设置
- `local_data/user_data/data/app.db`
  SQLite 主库，保存文档、页面、翻译状态和结果
- `local_data/user_data/data/documents/{doc_id}/source.pdf`
  每份文档的 PDF 副本

这些内容默认不会提交到 Git 仓库。

## 常见问题

### 1. 浏览器没有自动打开

手动访问：

```text
http://localhost:8080
```

### 2. 页面提示缺少 Key

去“设置”页先保存：

- `PaddleOCR 令牌`
- 一个可用的翻译模型 Key

### 3. 第一次启动比较慢

这是正常现象。首次启动会创建虚拟环境并安装依赖，通常会比后续启动慢很多。

### 4. 上传后一直没结果

先检查：

1. `PaddleOCR 令牌` 是否正确
2. 当前网络是否能访问外部 API
3. PDF 是否损坏或过大

### 5. 想停止程序

在启动程序的那个终端窗口里按 `Ctrl + C` 即可。

## 相关说明

- 更稳定的开发说明见 [DEV.md](DEV.md)
- 当前进度和最近结论见 [PROGRESS.md](PROGRESS.md)
- 已执行过的验证见 [verification.md](verification.md)
