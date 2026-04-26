# 数据库瘦身与拆库方案

## 摘要
- 目标定为“直接拆库 + 只保留当前态”。全局只保留轻量目录索引，文档正文、翻译、FNM 当前态搬到 `local_data/user_data/data/documents/{doc_id}/doc.db`；`local_data/user_data/data/catalog.db` 只存文档清单与全局状态。
- 先做一次离线迁移，不保留双写或兼容层。迁移完成后新代码只读新库；旧 `app.db` 只留备份。
- 这次方案同时解决三类问题：写锁竞争、删文档慢、库体积膨胀。当前证据是：`app.db` 约 622MB；`fnm_translation_units` 约 481MB；最大 `translate_runs.task_json` 约 2.1MB；`fnm_runs` 430 条但文档只有 7 个；读链路里的 GET 接口会触发真实写事务。

## 实测基线（2026-04-15）

- 实际主库路径：`local_data/user_data/data/app.db`（仓库根 `app.db` 为空壳 0B）。
- 主库体积：`652,468,224 bytes`（约 622MB）。
- 关键大对象（dbstat）：
  - `fnm_translation_units`: `480,571,392 bytes`
  - `pages`: `57,749,504 bytes`
  - `fnm_body_anchors`: `20,832,256 bytes`
  - `fnm_note_items`: `15,884,288 bytes`
  - `fnm_structure_reviews`: `7,954,432 bytes`
  - `fnm_note_links`: `7,774,208 bytes`
  - `fnm_runs`: `7,147,520 bytes`
- 运行态累积：
  - `documents=7`
  - `fnm_runs=430`（单文档最高 89 条）
  - `fnm_translation_units=46,461`
  - `translate_runs=7`（每文档 1 条）
  - `MAX(LENGTH(translate_runs.task_json))=2,136,736`
- 读链路写入热点（代码扫描，含本轮收敛）：
  - 已清理：`persistence/storage.py::load_pages_from_disk` 的读取修复回写（`replace_pages/remap_book_pages/update_doc_meta`）已移除。
  - 已清理：`GET /`、`GET /input`、`GET /reading` 对 `set_current_doc` 的写入；`GET /reading` 对 `save_entry_cursor` 的写入。
  - 已复核：`/api/doc_processing_status`、`/api/reading_view_state` 在当前实现中为纯读聚合，无写库副作用。

## 关键改动
- 拆分仓储边界：
  - `CatalogRepository` 只管 `documents` 和全局 `app_state/current_doc_id`。
  - `DocumentRepository(doc_id)` 只管当前文档的 `pages / translation_* / fnm_* / glossary / translation_title / translate_state / revisions`。
  - 初始化改成显式启动步骤；去掉 `SQLiteRepository().__init__ -> initialize_database()` 的隐式迁移副作用。
  - 主链初始化默认不再初始化 legacy `app.db`（`initialize_runtime_databases(include_legacy_app_db=False)`）。
- 去掉读路径写库（首批已落地）：
  - `load_pages_from_disk()` 不再做修复性写回；`GET /reading` 不再写 `save_entry_cursor`。
  - `GET /`、`GET /input`、`GET /reading` 不再写 `current_doc_id`。
  - 页码修复/回填改成显式维护任务，剩余 GET/状态接口继续按“纯读无写”收口。
- 重新定义“必须落库”的数据：
  - 必须持久化：OCR 页面正文与脚注、用于 FNM 和导出的最小块级结构、最终译文、人工修订、当前目录与目录偏移、当前 FNM 结构摘要、当前可恢复 checkpoint、当前 glossary。
  - 不再持久化：流式草稿段落、`active_para_indices`、`paragraph_states/errors`、增量 `translation_so_far`、`target_bps`、`target_unit_ids`、doc 级历史 run 列表。
  - `translate_state` 改成单行当前态表，只保留 `phase/resume_bp/current_bp/计数器/失败摘要/model 信息`；`running/stop_requested` 留在进程内存，进程重启后一律按“未运行 + 可恢复”处理。
- 清理和压缩 schema：
  - `documents` 只保留轻量元数据；删除 `toc_json`、`has_pdf`、`status`、`source_pdf_path`。`has_pdf` 改由文件是否存在判定；`status` 当前未驱动业务。
  - `pages` 去掉“列字段 + payload_json 双份存储”。保留列：`book_page/file_idx/img_w/img_h/markdown/footnotes/text_source/print_page_label/is_placeholder`；只把 `blocks/fnBlocks/少量额外 OCR 元数据` 放进精简后的 `ocr_payload_json`。
  - `translation_pages/translation_segments` 去掉 `run_id`；页与段改用 `book_page` 和 `(book_page, segment_index)` 直接寻址。
  - `fnm_runs` 改成单行 `fnm_state`；不再积累 70 到 90 条每文档的重复历史摘要。
  - `fnm_translation_units` 拆成“重载荷”和“轻状态”两层，避免状态更新时重写大 JSON：
    - `fnm_unit_payloads`：`unit_id/source_text/page_segments_json`
    - `fnm_unit_state`：`unit_id/translated_text/status/error_msg/target_ref/updated_at`
  - `page_segments_json` 继续保留当前投影能力，但只放当前投影需要的数据；状态变更时绝不重写它。
  - `segment_revisions` 只记录人工改动；普通模型重译不再自动备份整页旧段落。
- 删除流程重做：
  - 删除文档时只删 `catalog.db` 中该文档行，然后直接删除整个 `documents/{doc_id}/` 目录；由于正文库也在目录里，数据库删除变成文件删除，不再在总库里做大级联。
  - 同时清除该文档的 glossary、translation_title 和任何 doc-scoped state，杜绝 `catalog.app_state` 残留孤儿 key 的情况。
  - 新库启用 `WAL + auto_vacuum=INCREMENTAL`；迁移后旧 `app.db` 做一次 `VACUUM` 或归档，不再继续增长。

## 迁移与接口
- 一次性迁移脚本：
  - 扫描旧 `app.db` 的 `documents`。
  - 为每个 `doc_id` 生成 `documents/{doc_id}/doc.db`，迁移当前 `pages`、当前译文、当前 FNM 结构、当前 glossary、当前 translation_title、当前 translate_state、当前 FNM 摘要。
  - `fnm_runs` 只取每文档最新一条；`translate_runs` 只取每文档最新一条；旧历史不迁移。
  - 迁移时剥离 `pages.payload_json` 中与列重复的键；剥离 `translate_state.task_json` 中可推导的大数组。
- 对外接口和代码边界调整：
  - 新增 `CatalogRepository` 与 `DocumentRepository(doc_db_path)`。
  - 所有 web、translation、FNM 入口先通过 `doc_id` 定位 `doc.db`，不再把所有文档落到同一连接目标。
  - `load_pages_from_disk` 和 `load_entries_from_disk` 只做读取和内存归一化；任何“修复后写回”都改成显式维护命令。
  - 保留现有 HTTP 路由形状，不改前端 contract；变化只在持久化实现和读写时机。

## 测试与验收
- 并发验收：
  - 流式翻译进行中，同时轮询 `/api/doc_processing_status`、`/api/reading_view_state`、`/api/doc/<doc_id>/fnm/status`、打开 `/reading`，日志里不再出现 `database is locked`。
  - 给这些 GET 链路加 SQL 写保护测试，确认不会触发 `INSERT/UPDATE/DELETE/REPLACE`。
- 数据正确性：
  - 迁移前后同一文档的页数、可见页、译文页、人工修订、FNM 章节、脚注、尾注投影一致。
  - 页面编辑历史仍可查看；普通重译不会把 revision 表无限做大。
  - glossary、translation_title 跟随文档迁移，删文档后不留孤儿状态。
- 删除与体积：
  - 删除大文档时只删除对应目录，耗时与该目录文件大小相关，不再与整库总大小线性相关。
  - 新建、重译、重跑 FNM 后，单文档库大小可预期增长；删除文档后磁盘空间直接回收，不依赖总库 `VACUUM`。
- 回归场景：
  - 上传新文档、重解析、手动目录上传、自动视觉目录、标准翻译、FNM 翻译、阅读页跳页、失败恢复、停止翻译后继续、刷新页面后恢复进度。

## 默认假设
- 采用“直接拆库”，不保留双写或旧 schema 兼容层；只提供一次性迁移脚本和旧库备份。
- 采用“只保留当前态”，旧 `fnm_runs/translate_runs` 历史不迁移。
- 流式草稿不落库；刷新时只展示最近已完成页或已完成 unit 的状态，未完成中的段落直接丢弃。
- 当前业务仍保留页编辑历史、目录管理、API usage 展示和 FNM 当前结构摘要。
