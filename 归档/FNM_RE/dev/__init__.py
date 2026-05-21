"""FNM 开发者模式：单阶段运行、Gate、诊断、快照。

# 分层定位

`FNM_RE.dev` **不属于** FNM_RE 的核心分层（shared → stages → modules → app）。
它是 **app 层的调试客户端**，与 `web/dev_routes.py`、CLI 工具同级：

```
shared → stages → modules → app  ← FNM_RE 内部分层（严格单向）
                              ↑
                          dev/ (FNM_RE.dev)    ← 外部客户端，可调用 app
                              ↑
                       web/dev_routes.py        ← 调用 dev/
                       tests/unit/test_dev_*    ← 调用 dev/
```

**允许的依赖方向**：
- dev/ 可以依赖 shared/stages/modules/app（它需要驱动整个 pipeline）
- dev/ 内部模块之间可以互相依赖

**禁止的依赖方向**：
- 任何 shared/stages/modules/app 文件**不得**导入 dev/
  （已审计，目前没有违反）

如果以后需要严格分层，把整个 dev/ 包移到项目根级 `dev/` 或 `scripts/dev/`
即可——只需要更新 web/dev_routes.py 和测试文件中的 import 路径。
"""
