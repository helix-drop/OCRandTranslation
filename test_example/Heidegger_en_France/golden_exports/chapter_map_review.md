# 切分审阅 — Heidegger_en_France

完成 21 个章节（含 7 个 Epilogue）；首/末视觉通过 21/21 + 21/21；待确认 0 项。

## Offset 基线

- **primary_offset**: -1 (fileIdx 7 ↔ printed 8)，视觉对照 ✓
- **段**：[0,6]=front_matter（无label）；[7,598]=body（offset -1）

## 空页插页记录（12个，全部视觉确认）

| fileIdx | printed | 性质 |
|---------|---------|------|
| 53 | 54 | 空白页（Ch1→Ch2过渡，Ch2从printed p55开始） |
| 79 | 80 | 空白页（Ch2内，Ch2仍至printed p79） |
| 111 | 112 | 空白页（Ch3→Ch4过渡，Ch4从printed p113开始） |
| 231 | 232 | 空白页（Epilogue II→Ch7过渡，Ch7从printed p233开始） |
| 273 | 274 | 空白页（Epilogue III内，Ch8从printed p275开始） |
| 315 | 316 | 空白页（Epilogue IV末页后，Ch9从printed p317开始） |
| 345 | 346 | 空白页（Epilogue V末页后，Ch10从printed p347开始） |
| 443 | 444 | 空白页（Epilogue VII末页后，Ch12从printed p445开始） |
| 499 | 500 | 空白页（Ch12末页后，Conclusion从printed p501开始） |
| 541 | 542 | 空白页（Conclusion末页后，Bibliographie从printed p543开始） |
| 585 | 586 | 空白页（Index部分过渡） |
| 0 | 1 | 空白/图版页（封面系列） |
| 1 | 2 | 空白/图版页 |
| 2 | 3 | 图版页（Heidegger en France标题页） |
| 23 | 24 | 图版页（isFigurePage） |

## 章节映射表

| # | 章名 | 印刷页 | fileIdx | 视觉首 | 视觉末 | 备注 |
|---|------|--------|---------|--------|--------|------|
| 0 | Introduction | 7–23 | 6–22 | ✓ | ✓ | |
| 1 | Premiers passages du Rhin | 25–54 | 24–53 | ✓ | ✓ | |
| 2 | La bombe Sartre | 55–80 | 54–79 | ✓ | ✓ | printed p79页眉确认 |
| 3 | Les fascinations de l'après-guerre | 81–112 | 80–111 | ✓ | ✓ | printed p112空页 |
| 4 | L'humanisme dans les turbulences | 113–134 | 112–133 | ✓ | ✓ | |
| 5 | L'embellie des années 1950 | 135–178 | 134–177 | ✓ | ✓ | |
| E-I | Épilogue I | 179–184 | 178–183 | ✓ | ✓ | |
| 6 | Polémiques renouvelées, déplacements inédits | 185–223 | 184–222 | ✓ | ✓ | |
| E-II | Épilogue II | 224–232 | 223–231 | ✓ | ✓ | printed p232空页 |
| 7 | Dissémination ou recomposition? | 233–268 | 232–267 | ✓ | ✓ | printed p233章节首页 |
| E-III | Épilogue III | 269–274 | 268–273 | ✓ | ✓ | |
| 8 | Mort et transfiguration? | 275–309 | 274–308 | ✓ | ✓ | |
| E-IV | Épilogue IV | 310–316 | 309–315 | ✓ | ✓ | printed p315空页 |
| 9 | La lettre et l'esprit | 317–342 | 316–341 | ✓ | ✓ | printed p317章节首页 |
| E-V | Épilogue V | 343–346 | 342–345 | ✓ | ✓ | |
| 10 | Le retour du refoulé? | 347–385 | 346–384 | ✓ | ✓ | |
| E-VI | Épilogue VI | 386–390 | 385–389 | ✓ | ✓ | |
| 11 | Entre érudition et techno-science | 391–438 | 390–437 | ✓ | ✓ | printed p391章节首页 |
| E-VII | Épilogue VII | 439–444 | 438–443 | ✓ | ✓ | |
| 12 | La croisée des chemins | 445–500 | 444–499 | ✓ | ✓ | printed p445章节首页 |
| 13 | Conclusion | 501–540 | 500–539 | ✓ | ✓ | printed p500章节首页 |
| BM | Bibliographie + Index | 543–598 | 541–598 | — | — | |

## 待审清单

**无待审项，直接交付。**

## 尾注说明

本书为脚注书（footnote，非endnote），脚注散布在各章正文页下方。fnm_real_test_modules.json 记录了27个脚注区域，覆盖全部正文章节。每章脚注范围已由fnm系统记录于 note_region_detection.region_rows，build阶段可直接引用。
