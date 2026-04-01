索引页过滤 + 跨章尾注编号冲突修复                                              
                                                                  
 Context                                                                        

 上一轮已实现尾注集合页检测与索引匹配（commit 5e60a65），LSD 和 Biopolitique
 的尾注匹配率从 0%/69% 提升到 100%。现在有两个导出质量问题需要修复：

 问题 1（索引页输出为孤立引用块）：LSD 第 187-190 页是书末索引（如 Afary,
 Janet, 26, 37, 205...），目前原样输出为 >
 引用块，无译文，产生大段孤立引用。这些页应被检测并跳过。

 问题 2（跨章尾注编号冲突）：LSD 和 Biopolitique 均按章重新编号尾注。当前
 Markdown 使用全局 [^n] 命名空间——不同章节的 [^3] 指向同一个定义。LSD 125
 个唯一编号全部受影响；Biopolitique 的 [^3] 出现 20
 次指向同一个定义。需要引入章节前缀消歧。

 修改文件

 - storage.py：新增索引页检测函数，修改 gen_markdown 的尾注标签生成逻辑
 - app.py：在 _build_endnote_data 中调用索引页检测，将结果并入 skip_bps
 - test_sqlite_mainline.py：新增测试

 步骤 1：新增书末索引页检测

 在 storage.py 的 compute_boilerplate_skip_bps（line 971）附近新增函数：

 def detect_book_index_pages(entries: list[dict]) -> set[int]:
     """检测书末索引页（人名/主题索引），返回应跳过的页码集合。"""

 检测规则：
 1. 对每页合并 original 文本，逐行检查是否匹配索引条目模式
 2. 索引条目特征：词条, 数字, 数字, 数字...（逗号分隔的页码列表）
   - 正则：^\s*[A-Za-ZÀ-ÿ][\w\s\-'.]+,\s*\d+(?:\s*[,\-–]\s*\d+)+（词条开头 +
 逗号 + 至少两个数字/范围）
 3. 判定标准：索引行占比 ≥ 40% 且索引条目 ≥ 5
 4. 仅扫描文档后 20% 的页面（索引通常在书末）

 返回检测到的索引页页码集合。

 步骤 2：修改 app.py 调用方

 在 _build_endnote_data 函数（line ~1545）中：

 def _build_endnote_data(entries, toc_depth_map):
     # ...现有逻辑...
     # 新增：检测书末索引页
     index_page_bps = detect_book_index_pages(entries)
     endnote_bps = {bp for bps in endnote_page_map.values() for bp in bps}
     return endnote_index, endnote_bps | index_page_bps

 这样索引页会与尾注页一起被加入 skip 集合，不输出正文内容。需要在 app.py
 顶部追加导入 detect_book_index_pages。

 步骤 3：跨章尾注编号消歧——gen_markdown 改动

 核心思路：当多个章节的尾注索引存在重叠编号时，为 [^n] 标签添加章节前缀
 [^ch{cidx}-{n}]，同时对正文中对应的内联引用做同步替换。

 在 gen_markdown 中（line ~1620 起的尾注匹配块），具体改动：

 3a. 预判是否需要消歧

 在 gen_markdown 函数入口（line ~1555 附近），在开始遍历 entries
 之前，预先计算：

 # 检测是否存在跨章节编号重叠
 _endnote_needs_prefix = False
 if endnote_index:
     all_nums_by_chapter = {k: set(v.keys()) for k, v in endnote_index.items()
 if k is not None}
     seen_nums: set[int] = set()
     for nums in all_nums_by_chapter.values():
         if seen_nums & nums:
             _endnote_needs_prefix = True
             break
         seen_nums |= nums

 3b. 生成带前缀的标签

 在尾注匹配块（line ~1622-1670），当 _endnote_needs_prefix 为 True 且
 note_scope_key 不为 None（即章节尾注）时：

 if _endnote_needs_prefix and note_scope_key is not None:
     prefixed_label = f"ch{note_scope_key}-{lbl}"
 else:
     prefixed_label = lbl

 用 prefixed_label 替代原来的 lbl 作为 note_def 的 label。

 3c. 正文内联引用同步替换

 匹配成功后，需要将当前段落的 orig 和 tr 中的 [^{lbl}] 替换为
 [^{prefixed_label}]：

 if prefixed_label != lbl:
     orig = orig.replace(f"[^{lbl}]", f"[^{prefixed_label}]")
     tr = tr.replace(f"[^{lbl}]", f"[^{prefixed_label}]")

 注意：需要在构建 md_lines（_append_blockquote /
 _append_paragraph）之前完成替换。当前代码结构是先做尾注匹配、再输出段落，所以
 需要将段落输出移到尾注匹配之后（目前已经是这个顺序，无需调整）。

 但有一个问题：当前代码的 orig/tr 变量在尾注匹配之前就已经赋值了（line
 1602-1607），尾注匹配在 line 1622-1670，段落输出在 line
 1671+。所以只需在尾注匹配块内部收集需要替换的 {lbl -> prefixed_label}
 映射，然后在匹配块结束后、段落输出之前，对 orig 和 tr 做批量替换即可。

 3d. 尾注定义输出

 chapter_endnotes 和 book_endnotes 的输出逻辑（line 1768-1799）不需要改动，因为
  note_def["label"] 已经是 prefixed_label，[^ch{n}-{num}]: 格式是合法的
 Obsidian 脚注定义。

 步骤 4：测试验证

 自动化测试（test_sqlite_mainline.py）

 1. 索引页检测测试：构造含索引条目格式的 entries，验证 detect_book_index_pages
 返回正确的页码集合
 2. 消歧标签测试：构造两个章节的 endnote_index（编号 1-5 重叠），传入
 gen_markdown，验证输出中不存在重复的 [^n]: 定义，且内联引用 [^ch0-1] 与定义
 [^ch0-1]: 一一对应

 真实数据验证

 用 LSD 和 Biopolitique 的实际数据库运行导出，检查：
 1. LSD 第 187-190 页不再输出为引用块
 2. LSD 输出中每个 [^ch{n}-{m}] 引用都有对应定义
 3. Biopolitique 输出中跨章重复编号正确消歧

 边界情况

 - 无章节重叠：如果所有章节编号互不重叠，_endnote_needs_prefix 为
 False，标签保持原样 [^n]，行为与当前完全一致
 - 全书尾注（chapter_index=None）：不加前缀，保持 [^n]
 - 索引页检测误报：仅扫描后 20% 页面 + 要求高比例索引条目，误报概率极低
 - 非拉丁文索引：当前正则仅匹配拉丁字母开头的索引条目，适用于本项目的法语/英语
 文献
