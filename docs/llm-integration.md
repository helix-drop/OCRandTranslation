# LLM / VLM 接入架构文档

这份文档记录当前仓库保留的模型调用边界。已剥离的脚注/尾注结构化项目在 `/Users/hao/FEnoteTransToMD`，不属于本仓库主链。

## 调用点

| 角色 | 文件 | 统一调用入口 | 模型类型 |
|---|---|---|---|
| 视觉目录解析 | [pipeline/visual_toc/vision.py](../pipeline/visual_toc/vision.py) | `_call_vision_json` | VLM |
| 标准翻译 | [translation/translator.py](../translation/translator.py) | `_call_openai_chat` / `_call_openai_mt` / `_stream_openai_chat` / `_stream_openai_mt` | Text LLM / MT |

不要在这些入口之外直接调用模型 API。新增调用点必须先复用现有 provider 异常分类、JSON 解析、token 统计和日志路径。

## 共享原则

1. **极简上下文**：视觉目录按小批页面处理；翻译按段落处理，不把整本书塞进一次请求。
2. **控制面剥离**：视觉模型输出结构化 JSON；翻译模型只处理待译文本。
3. **闭环校验**：视觉目录结果必须经过结构过滤；翻译结果必须经过术语检查和任务状态记录。
4. **异常分类统一**：模型异常必须走 `translation/translator.py` 的 provider 异常分类，不裸吞错误。

## 视觉目录

视觉目录负责从 PDF 候选页里识别目录条目，供阅读页目录导航和导出章节选择使用。

相关模块：

- `pipeline/visual_toc/vision.py`
- `pipeline/visual_toc/organization.py`
- `pipeline/visual_toc/runtime.py`
- `pipeline/visual_toc/scan_plan.py`
- `pipeline/visual_toc/manual_inputs.py`
- `persistence/storage_toc.py`

输出必须落到当前文档的数据目录和 SQLite 状态里，不能绕过仓储直接改页面内容。

## 标准翻译

标准翻译由 `translation/` 任务链负责：

- `translation/translate_launch.py` 启动任务
- `translation/translate_runtime.py` 管理状态
- `translation/translate_worker_common.py` 执行页面翻译
- `translation/translator.py` 负责真实模型请求

翻译链路需要继续保护：

- 术语词典命中检查
- 流式草稿状态
- 失败页和部分失败页记录
- 停止/继续任务后的 resume 位置

## 新增模型调用 checklist

- 是否复用了现有 provider 配置和模型池解析。
- 是否有明确输入/输出契约。
- 是否记录了失败路径和用户可见错误。
- 是否能在无模型 key、限流、额度不足、网络失败时给出可解释结果。
- 是否有对应单测或集成烟雾测试。
