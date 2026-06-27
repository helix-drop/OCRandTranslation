# GLM-4.6V-FlashX FNM 视觉能力抽样评测

- 日期：2026-05-23
- 模型请求与返回：`glm-4.6v-flashx`
- 调用方式：智谱 OpenAI-compatible chat completions，图片以 data URL 输入，`thinking.type=disabled`
- 隔离约束：未调用会写回 DB/目录 bundle 的 `run_auto_visual_toc_for_doc()`；仅在本目录保存图片、请求和响应
- 官方说明基线：GLM-4.6V-FlashX 为 GLM-4.6V 系列中的轻量高速视觉模型，文档列示 9B 参数、128K 上下文，支持图片与文件输入

## 样本与任务

| 任务 | 样本页面 | 已知事实 / 判定基线 |
|---|---|---|
| 跨页脚注捕获 | `Biopolitics` 原书 p.44-p.45，PDF `fileIdx=57,58` | p.44 页底的 `* M. Foucault passe...` 长脚注在 p.45 页底上半部分继续；p.45 随后另有新的 `* M. Foucault ajoute...` 脚注 |
| 尾注区域捕获 | `Goldstein` 原书 p.331-p.332，PDF `fileIdx=347,348` | p.331 标题 `Notes`，含 `Introduction` 下的编号尾注 1、2；p.332 继续编号 3 起 |
| 自动视觉目录（英文单页） | `Goldstein` 手动目录 PDF 全部 1 页 | `Notes 331` 是尾注容器；`Note on Sources 399`、`Index 403` 是 back matter；I/II 是容器，Introduction 是正文 chapter |
| 自动视觉目录（法文多页） | `Biopolitics` 手动目录 PDF 全部 5 页 | `COURS, ANNÉE 1978-1979` 下有 12 条 `Leçon`；`RÉSUMÉ DU COURS` 与 `SITUATION DES COURS` 是 post-body；`INDICES` 是 back matter 容器 |

目录任务首次使用了简化 prompt；发现其示例字段会诱发枚举字符串复读后，已使用仓库 `pipeline/visual_toc/vision.py` 的 organization prompt 原规则重跑。下方目录结论仅依据 production prompt 响应。

## 结果

| 能力 | 响应表现 | 判定 |
|---|---|---|
| 找到普通脚注定义 | 在 Biopolitics p.44 正确识别 `* M. Foucault passe...` 为页底脚注 | 可用作候选提示 |
| 识别脚注跨页续文 | 判断存在 p.44 → p.45 跨页续文，但把 p.45 新的 `* M. Foucault ajoute...` 当成续文证据，漏掉页顶真正的无 marker 续段 | 不通过，不能自动落库 |
| 判断尾注区域 | 正确将 Goldstein p.331-p.332 总体分类为 `endnotes_region`，看到了 `Notes` 标题 | 可用于粗筛 |
| 抽取尾注定义 | p.331 明显可见编号 `1.`、`2.`，响应的 `page1_note_markers` 却为空 | 不通过，不能承担 note item 抽取 |
| 英文自动视觉目录 | 抽出主要目录文字和页码，但把 `Notes 331` 标为 `back_matter`，并返回 `endnotes_summary.present=false`；把 `Introduction` 标为 `front_matter`；输出非法 `role_hint=part` | 不通过，会直接误导 Phase 1/2 |
| 法文自动视觉目录 | 12 条课程章节、`RÉSUMÉ`/`SITUATION`、索引层次基本正确；未发现该书存在独立尾注容器，`endnotes_summary=false` 合理 | 单书通过，不足以单独放行模型 |

## 结论

`GLM-4.6V-FlashX` 在本次抽样中适合做**廉价候选扫描或人工复核提示**，暂不能替换当前对 FNM 关键决策负责的视觉模型：

1. 它能读出明显的页面类型和大量目录文本。
2. 它在流程关键的排他判断上不稳定：将“续注文本”和“下一条新脚注”混淆；目录已读到 `Notes 331` 却未将其定为尾注容器。
3. 按当前树枝状条件原则，`note_kind` 与尾注容器属于上游分类事实，不能让存在上述错误的模型直接写入 Phase 1/2 产物。

合理使用方式是将其放在非权威层：

- 用于扫描可能包含脚注/尾注/目录的页面，降低高价模型调用量。
- 对其结果增加严格结构校验：枚举值是否合法、目录中出现 `Notes/Endnotes` 时 `endnotes_summary` 是否自洽、续注判定是否与新 marker 冲突。
- 凡涉及尾注容器确认、跨页注释拼接、最终目录结构的页面，仍由更可靠模型或人工复核确认。

## 产物索引

| 产物 | 文件 |
|---|---|
| 跨页脚注响应 | `footnote_cross_page_biopolitics_response.json` |
| 尾注区域响应 | `endnotes_region_goldstein_response.json` |
| Goldstein production prompt 目录响应 | `visual_toc_goldstein_production_prompt_response.json` |
| Biopolitics production prompt 目录响应 | `visual_toc_biopolitics_production_prompt_response.json` |
| 对应请求与页面截图 | 本目录下 `*_request.json` 与 `*.png` |

## 边缘情况

- 本次只验证两本现有真实书样本，尚未覆盖目录页严重倾斜、双栏目录、符号脚注与数字尾注混排、低清扫描页。
- 响应中 `confidence` 被输出为 `0.0`，因此不能把模型自报置信度作为自动放行依据。
- 本次未将模型加入仓库配置，也未执行会持久化目录或 note records 的主链；结论只针对视觉识别能力抽样。
