# fnm_re_rs — FNM_RE Rust 重写

## 构建

```bash
cd fnm_re_rs
cargo build
```

## PDFium 依赖（Vision LLM）

G1+（`sup_recovery/pdf_render.rs`）使用 pdfium-render crate 渲染 PDF 页面供 Vision LLM 调用。
运行时需要 PDFium 二进制库：

- **macOS (Homebrew)**: `brew install pdfium`
- **Linux**: 从 https://github.com/bblanchon/pdfium-binaries/releases 下载对应架构包，解压后将 libpdfium.so 放入 `LD_LIBRARY_PATH`
- **Windows**: 同上，将 pdfium.dll 放入 `PATH`

pdfium-render 优先加载系统库（`bind_to_system_library`），失败时尝试同目录加载。
对应的测试用 `#[ignore]` 标记，需要 PDFium 二进制 + 测试 PDF 才能运行。:

## 测试

```bash
cargo test --all
```

## Parity 测试

parity 测试用 Python 同名函数的输出作为 ground truth，确保 Rust 实现与 Python 行为完全一致。

### 生成 parity fixture

```bash
python tools/gen_parity_fixtures.py
```

fixture JSON 写入 `fnm-core/tests/fixtures/`，Rust 端 `cargo test` 读取这些 JSON 文件。

### 运行 parity 测试

```bash
cd fnm_re_rs
cargo test --test '*'  # 运行所有集成测试
```

## 代码质量

```bash
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test --all
```

## Crate 结构

| Crate | 用途 |
|---|---|
| `fnm-core` | 基础设施层：类型、数据结构、共享工具、DB 访问 |
| `fnm-phase1` | (待实现) 页面角色 + 章节边界 |
| `fnm-phase2` | (待实现) note_kind 分类 + note_mode 聚合 |
| `fnm-phase3` | (待实现) body anchor 检测 + link 匹配 |
| `fnm-phase4` | (待实现) 引用注入 + 翻译单元 |
| `fnm-phase5` | (待实现) 章 markdown 合并 |
| `fnm-phase6` | (待实现) 导出审计 |
