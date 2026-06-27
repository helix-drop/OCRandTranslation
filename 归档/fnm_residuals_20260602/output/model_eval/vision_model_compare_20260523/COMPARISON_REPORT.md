# FNM 视觉模型同样本能力对比

- 日期：2026-05-23
- 本轮新跑模型：`gemini-3.1-flash-lite`、`glm-4.6v`
- 参照模型：同日已跑的 `glm-4.6v-flashx`
- 比较方式：三模型使用同一组页面截图、同一跨页/尾注 prompt；目录比较统一采用仓库 `pipeline/visual_toc/vision.py` 的 organization prompt
- 隔离约束：实验未调用写 DB 或覆盖视觉目录 bundle 的主链入口；全部产物仅写入 `output/model_eval/`

## 任务基线

| 任务 | 真实样本 | 必须正确的事实 |
|---|---|---|
| 跨页长脚注 | `Biopolitics` 原书 p.44-p.45 | p.44 的 `* M. Foucault passe...` 在 p.45 页底继续；续文之后 p.45 另起一条 `* M. Foucault ajoute...` |
| 尾注区域 | `Goldstein` 原书 p.331-p.332 | `Notes` 区起点；p.331 有编号 1、2；p.332 以编号 3 开始，不是 2 的续文 |
| 英文目录 | `Goldstein` 目录 1 页 | `Notes 331` 是尾注容器；`Note on Sources 399` 与 `Index 403` 为 back matter；Introduction 是 chapter |
| 法文目录 | `Biopolitics` 目录 5 页 | 12 条 `Leçon` 在 `COURS` 下；`RÉSUMÉ` / `SITUATION` 是 post-body；`INDICES` 为 back matter |

## 能力核对

| 任务 | Gemini 3.1 Flash Lite | GLM-4.6V | GLM-4.6V-FlashX |
|---|---|---|---|
| 跨页长脚注 | **部分通过**：准确指出真正续文开头，但 `new_footnote_definitions=[]`，未结构化记录后续新的 `*` 定义 | **部分通过**：识别续注存在并列出新的 `* M. Foucault ajoute...`，但续文引文为空且证据将续注位置误称为“页顶/正文” | **失败**：将第二页新的 `* M. Foucault ajoute...` 当作前条续文 |
| 尾注区域与编号 | **通过**：判为 `endnotes_region`，抽出 1、2，并正确判断第二页从 3 起 | **通过**：判为 `endnotes_region`，抽出 1、2，并正确判断第二页从 3 起 | **失败**：能判断区域，但 `page1_note_markers=[]` |
| Goldstein 自动视觉目录 | **部分通过且最接近可用**：`endnotes_summary.present=true`、Notes=331、Introduction=chapter 均正确；但 `items` 中仍把 `Notes` 写作 `back_matter`，存在内部冲突 | **失败**：条目把 `Notes` 写成 `endnotes`，但 `endnotes_summary.present=false`，关键汇总事实反向 | **失败**：`Notes` 判为 `back_matter` 且 `endnotes_summary.present=false`，并误判 Introduction |
| Biopolitics 自动视觉目录 | **通过**：核心层级、页码、post-body 与 indices 均符合基线 | **基本通过**：主体层级与 post-body 正确；索引子项以 `section` 输出，需规范化确认 | **通过核心结构**：主体层级与 post-body 正确 |

## 时延与令牌

单位为单次真实请求的秒数；令牌数为 API 返回的 `total_tokens`。

| 任务 | Gemini 3.1 Flash Lite | GLM-4.6V | GLM-4.6V-FlashX |
|---|---:|---:|---:|
| 跨页脚注 | 24.295 s / 2785 | 17.071 s / 3434 | 7.005 s / 3209 |
| 尾注区域 | 11.144 s / 2607 | 9.253 s / 3411 | 2.404 s / 3393 |
| Goldstein 目录 | 4.626 s / 2930 | 25.176 s / 2768 | 10.906 s / 3083 |
| Biopolitics 目录 | 15.429 s / 7569 | 32.420 s / 5296 | 14.196 s / 5437 |
| 合计 | **55.494 s / 15891** | **83.920 s / 14909** | **34.511 s / 15122** |

## 结论

### 1. 当前应保留 Gemini 作为自动视觉目录主模型

在最影响 Phase 1/2 事实分类的 Goldstein 目录样本中，只有 Gemini 正确返回了 `endnotes_summary.present=true` 和 `container_title=Notes`。虽然它仍把 `Notes` 条目的 `role_hint` 写成 `back_matter`，但关键汇总信号正确，且该矛盾可以由结构校验直接拦截或归一化；另两个 GLM 模型则直接丢失尾注容器汇总事实。

### 2. GLM-4.6V 不适合作为 Gemini 的直接替代

`glm-4.6v` 比 FlashX 明显改善了局部页面识别：尾注编号能抽出，跨页脚注能看到新定义。但是它在 Goldstein 目录中仍出现“条目识别为 endnotes、汇总却说不存在 endnotes”的冲突，而且本次四项总耗时最高。因此它不能直接承担自动视觉目录的权威输出。

### 3. FlashX 可以作为低成本预筛，但不能写入分类事实

FlashX 的速度最快；对 Biopolitics 目录的主体结构也能读出。但它在两项注释关键任务上出现实质错误，不能决定尾注容器、note item 或跨页脚注拼接。

### 4. 跨页脚注拼接不应仅依赖任何一个本轮模型的一次响应

三模型中没有一个完整满足“识别旧脚注续文 + 同页新脚注定义并结构化输出”的要求。该能力需要程序级约束：

- 页面下缘已有未闭合注释、下一页同一注释区开头无 marker 时，才允许建立续接候选。
- 下一页出现新的 marker 时必须保留为独立定义，不得被续接吞并。
- 模型只生成候选与证据；最终拼接必须通过 marker 分段与区域位置校验。

## 使用建议

| 场景 | 建议模型 | 门禁 |
|---|---|---|
| 自动视觉目录权威提取 | `gemini-3.1-flash-lite` | 校验 `endnotes_summary` 与条目角色自洽；不自洽则阻塞或复核 |
| 廉价页面候选扫描 | `glm-4.6v-flashx` | 只选页，不写入 `note_kind` / link / 目录事实 |
| 尾注页局部确认备选 | `glm-4.6v` 或 Gemini | 必须校验编号序列和章节边界 |
| 跨页脚注拼接 | 无单模型可直接放行 | 规则校验 + 需要时二次视觉复核 |

## 产物路径

- Gemini 请求/响应：`gemini-3.1-flash-lite/`
- GLM-4.6V 请求/响应：`glm-4.6v/`
- FlashX 原始实验与截图：`../glm_4_6v_flashx_20260523/`

## 边缘情况

- 本轮样本覆盖真实英文尾注目录、真实法文多页目录和一处跨页脚注，但不等同于全书实批。
- 各模型均可能受 prompt 细节影响；本次目录结论已经统一为仓库 production prompt，跨页与尾注也使用同一请求文本，因此适合横向比较。
- 本轮没有测试价格和并发吞吐，只记录单次调用时延与返回质量；模型成本选型仍需结合官方计费与更大样本评测。
