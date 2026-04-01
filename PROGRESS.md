# 当前进度

本文件不再记录已完成事项，只用于发布后的用户反馈收集和下一步开发整理。

## 当前版本说明

- 当前仓库以 Flask + SQLite 为主链路，默认本机运行在 `localhost:8080`
- 最近一次发布前关键验证见 [verification.md](/Users/hao/OCRandTranslation/verification.md)
- 当前维护说明、模块结构、主要函数和代码块说明见 [DEV.md](/Users/hao/OCRandTranslation/DEV.md)

## 用户反馈收集

- 《The Last Man Takes LSD》阅读反馈：存在“同一长段在阅读中疑似重复出现”，待继续定位与修复

## 已确认待开发事项

- 跨页合并链路仍需补防重复策略，避免长段在阅读页重复展示

## 下一步开发

- 在跨页处理链路补一条防重复策略（保持原行为前提下），并用《The Last Man Takes LSD》做回归
- 找一份带真实书签的 PDF，补齐 TOC 前端展示联调
- 继续优化特殊脚注页和乱码页的清洗效果
