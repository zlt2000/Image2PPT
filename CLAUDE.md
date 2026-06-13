# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 提供在本仓库中工作的指导。

## 项目概述

**DeckWeaver**（又名 Image2PPT）将幻灯片截图或导出的幻灯片图片转换为可编辑的 PowerPoint（.pptx）文件。它使用本地 OCR（PaddleOCR + EasyOCR + Tesseract 交叉验证）和图像处理算法——无需云端多模态 API。文字转为可编辑的 PowerPoint 文本框；图标、Logo、照片和装饰元素转为独立的 PNG 图片对象。

三种使用方式：
1. **Skill/Agent 工具** — Agent 调用 `scripts/convert.py` 处理图片文件夹或单张图片
2. **CLI 工具** — 直接运行 `scripts/convert.py`，零 Token 批量转换
3. **Web 服务** — FastAPI + React 前端，含认证、任务队列和自动更新。Web 相关细节见 `web/README.md`

## 常用命令

### 环境安装

```bash
# 安装 Python 依赖、系统工具（LibreOffice、Poppler、Tesseract）、预下载模型缓存
# 幂等操作，可安全重复执行
bash scripts/bootstrap.sh

# 强制使用 CPU 版本（即使检测到 GPU）：
bash scripts/bootstrap.sh --cpu

# 跳过系统工具安装（受管环境）：
bash scripts/bootstrap.sh --no-system
```

### 一键转换

```bash
# 单张图片、图片文件夹或 PDF：
python scripts/convert.py --source slides/
python scripts/convert.py --source page_01.png
python scripts/convert.py --source deck.pdf --pdf-dpi 300

# 自定义输出目录（默认：output/<name>_<YYYYMMDD>/）：
python scripts/convert.py --source slides/ --work-dir output/my_run
```

### 三步流水线（用于调试 / 迭代）

```bash
RUN="output/demo_$(date +%Y%m%d)"
SRC="slides"

# 1. OCR + 三引擎交叉验证 + 生成复核包
python scripts/ocr/prepare_ocr.py --source-dir "$SRC" --work-dir "$RUN"

# 2. 应用 OCR 修正（已预填充，可无人值守运行）
python scripts/ocr/ocr_review_apply.py --work-dir "$RUN"

# 3. 构建 PPT（擦除 → 资产检测 → 布局 → PPTX → QA → 预览）
python scripts/build_deck.py --source-dir "$SRC" --work-dir "$RUN"
```

### 常用参数

| 参数 | 适用脚本 | 作用 |
|---|---|---|
| `--pages 1,3,8` | convert, prepare_ocr, build_deck | 仅处理指定页码 |
| `--skip-render` | convert, build_deck | 跳过 LibreOffice 预览生成和默认文字校准 |
| `--skip-calibration` | convert, build_deck | 跳过基于预览的字号/位置校准 |
| `--detect-tables` | convert, build_deck | 启用原生表格重建（默认关闭，见架构说明） |
| `--mode text-only` | convert, build_deck | 全页背景 + 可编辑文字覆盖；跳过图标提取（更快） |
| `--icon-review` | convert, build_deck | 导出图标/文字边界判断包供人工复核 |
| `--workers 4` | build_deck | 并行逐页处理（默认自动 = min(核心数, 页数, 8)） |

### 回归测试

```bash
# 运行所有 fixture 对比基线（会复用缓存的流水线输出）：
python tests/runner/runner.py

# 单个 fixture：
python tests/runner/runner.py -k light_cover_hero

# 修改脚本后强制重新跑流水线：
python tests/runner/runner.py --rerun-pipeline

# 将当前分数记录为新基线：
python tests/runner/runner.py --update-baseline
```

报告输出到 `tests/reports/<timestamp>/report.html`，含并排视觉对比和热图。

### Web 服务（开发）

```bash
cp web/.env.example web/.env   # 至少修改 ADMIN_PASSWORD 和 JWT_SECRET
bash web/start.sh              # uvicorn :8000 + vite :5173
bash web/start-prod.sh         # 编译前端 + 单端口 uvicorn
```

## 架构

### 流水线阶段

转换流程由 `scripts/build_deck.py` 编排，分为以下阶段：

```
源图片 (page_NN.*)
    ↓
[阶段 0] OCR: prepare_ocr.py
    - PaddleOCR（热模型，跨页复用）
    - 三引擎交叉验证（EasyOCR + Tesseract）处理低置信度条目
    - 自动清除启发式（零误报的装饰/Logo 误识别移除）
    - 生成带标注的复核图片（可选人工复核）
    ↓
[阶段 1] 逐页流水线: run_pipeline.py（可通过 --workers 并行）
    a. erase_text.py      — 从图片中擦除 OCR 文字，保留图标/Logo
    b. build_inventory.py — cv2 连通域检测 → 资产清单 JSON
    c. inventory_to_layout.py — 生成布局 JSON + 提取资产 PNG
    ↓
[阶段 2] combine_layouts.py — 合并逐页布局为 combined.layout.json
    ↓
[阶段 2b] classify_text_slots.py — 结构性文本槽样式聚类
    ↓
[阶段 3b/3c] calibrate_text_sizes.py + calibrate_text_positions.py
    - 闭环校准：通过 LibreOffice 将 PPTX 渲染为 PDF → PNG，
      与源图对比，调整字号和文本框位置
    ↓
[阶段 3] build_pptx_from_layout.py — 布局 JSON → slides.pptx
    ↓
[阶段 4] inspect_pptx.py — 包级 QA（占位文字、零字节媒体）
    ↓
[阶段 5] render_preview.py — PPTX → PDF → PNG 预览（需 LibreOffice + pdftoppm）
```

`scripts/convert.py` 是用户面向的包装器：规范化源输入（单图、文件夹或 PDF），创建工作目录，然后调用 OCR 步骤和 `build_deck.py`。

### 目录结构

```
scripts/
├── convert.py              # 一键入口
├── build_deck.py           # 五阶段编排器
├── warmup.py               # 预下载模型缓存
├── image_sources.py        # page_NN 图片发现助手
├── fontconfig_helper.py    # macOS Office 雅黑字体发现（供 LibreOffice 使用）
├── text_safety.py          # PPTX XML 安全文本清理
├── ocr/
│   ├── prepare_ocr.py      # PaddleOCR + 交叉验证 + 自动清除 + 标注复核
│   ├── ocr_review_apply.py # 将 corrected_text 合并回 OCR JSON
│   ├── ocr_cross_verify.py # 三引擎共识逻辑
│   ├── ocr_review_autoclear.py # 6 条保守自动清除启发式
│   ├── ocr_paddle.py       # PaddleOCR 结果提取
│   ├── pdf_ingest.py       # PDF → PNG 渲染 + 精确文字层提取
│   └── render_annotated_review.py
├── page/
│   ├── run_pipeline.py     # 逐页编排器（擦除 → 检测 → 布局）
│   ├── erase_text.py       # 文字擦除，保留图标/Logo
│   ├── build_inventory.py  # cv2 组件检测 → 资产清单 JSON
│   ├── inventory_to_layout.py # 清单 → 布局 JSON + 资产提取
│   ├── simple_layout.py    # text-only 模式布局生成器
│   └── _heuristics.py      # 尺度感知启发式助手
├── deck/
│   ├── build_pptx_from_layout.py # 布局 JSON → .pptx（python-pptx）
│   ├── combine_layouts.py  # 合并逐页布局
│   ├── classify_text_slots.py    # 字体/大小/样式聚类 + 传播
│   ├── calibrate_text_sizes.py   # 基于预览的字号闭环校准
│   ├── calibrate_text_positions.py # 基于预览的文字位置校准
│   └── text_finalizers.py  # 对齐 / 大小统一 / 标题居中
├── verify/
│   ├── inspect_pptx.py     # PPTX 包级 QA
│   └── render_preview.py   # PPTX → PDF → PNG（需 LibreOffice + pdftoppm）
├── tables/
│   ├── detect_tables.py    # OCR 网格表格候选检测
│   └── table_recognize.py  # SLANet_plus 结构验证
├── icon/
│   ├── detect.py           # 图标检测启发式
│   └── inpaint.py          # 图标区域修复
├── shared/
│   ├── geometry.py         # 框交集、包含助手
│   ├── bg_sample.py        # 背景色估计
│   └── gpu.py              # GPU 检测 + Paddle 设备选择
└── optional/
    ├── find_template_logos.py
    └── rmbg_postprocess.py # RMBG-1.4 背景移除（可选）
```

### 关键设计决策

- **OCR 模型复用**：`prepare_ocr.py` 一次加载 PaddleOCR 并在同一进程中处理所有页面。启动约 3 秒；识别约 9 秒/页。不要每页单独启动 PaddleOCR。
- **三引擎交叉验证**：低置信度 Paddle 条目通过 EasyOCR + Tesseract 验证。结果分级：🟢 绿色（强共识）、🟡 黄色（弱共识）、🔴 红色（无共识）。`corrected_text` 已预填充，首次运行无需 Agent 介入。
- **纯文字模式**（`--mode text-only`）：跳过资产检测、图标提取、槽位分类和校准。清洁后的页面作为全页背景；OCR 文字作为可编辑框覆盖。更快但图标不可编辑。
- **表格检测默认关闭**：基于 SLANet 的检测器可能将样式化的横幅区域误判为表格。仅当幻灯片包含真正的网格表格时才传 `--detect-tables`。
- **`build_deck.py` 中的并行**：阶段 1（逐页流水线）支持 `ProcessPoolExecutor`（spawn 上下文）。每个 worker 重新导入 cv2/numpy（约 200–400 MB）。上限 8 个 worker 以避免内存抖动。OCR 和校准阶段是串行的。
- **字体假设**：默认 PPTX 字体为 `"Microsoft YaHei"`。Linux 上无 Office 字体时，创建 fontconfig 别名指向文泉驿微米黑（度量兼容）。完整配置见 `web/README.md` "安装 CJK 字体" 一节。
- **PDF 模式**：PyMuPDF 将页面渲染为 PNG 并提取精确文字层（Unicode + 每字 bbox，置信度=1.0），完全跳过 OCR。纯图像 PDF（扫描件）应先转为图片再处理。

### 输出目录结构

```
output/<run>/
├── slides.pptx              # 最终可编辑 PPT
├── qa.json                  # QA 检查报告
├── previews/page-NN.png     # 渲染预览图
├── ocr/
│   ├── page_NN.ocr.json                 # 原始 OCR 检测结果
│   ├── page_NN.ocr_review.json          # 分级复核包 + 建议
│   └── page_NN.ocr_review.annotated.png # 标注复核图
├── inventory/
│   ├── page_NN.clean.png                # 文字擦除后的图片
│   ├── page_NN.inventory.json           # 元素资产清单
│   └── masks/page_NN/v###.mask.png      # 组件遮罩
├── manifests/page_NN.assets.json        # 资产裁剪清单
├── layouts/
│   ├── page_NN.layout.json              # 逐页布局
│   └── combined.layout.json             # 整稿合并布局
├── assets/page_NN/*.png                 # 提取的视觉资产
└── debug/page_NN_*.png                  # 调试可视化
```

### 布局 JSON 格式

`build_pptx_from_layout.py` 消费的中间格式。完整规范见 `references/layout-json.md`。关键元素类型：

- `type: "text"` — 可编辑文本框，含 `box`、`font`、`size`、`color`、`align`、`valign`、`line_spacing`
- `type: "image"` — 提取的 PNG，含 `path`（相对于 `--assets-root`）和 `box`
- `type: "shape"` — 原生 PPT 形状（`rect`、`rounded_rect`、`oval`、`diamond`、`triangle`、`trapezoid`），含 `fill`、`line`、`line_width`、`radius`
- `type: "line"` — 原生线条，含 `points`、`line`、`line_width`、`dash`
- `type: "table"` — 原生 PPT 表格，含 `rows`、`cols`、`col_widths`、`row_heights`、`cells`

元素按列表顺序渲染：背景最先，然后是框/形状，然后是图标，最后是文字。

## 依赖

| 层级 | 文件 | 关键包 |
|---|---|---|
| CLI 流水线 | `requirements.txt`（仓库根） | `python-pptx`、`pillow`、`numpy`、`opencv-python`、`paddleocr>=3`、`paddlex[ocr]`、`easyocr`、`pytesseract`、`onnxruntime`、`huggingface_hub`、`pymupdf` |
| Web 后端 | `web/backend/requirements.txt` | `fastapi`、`uvicorn`、`sqlalchemy`、`passlib`、`bcrypt` |
| 系统工具 | `scripts/bootstrap.sh` | LibreOffice (`soffice`)、Poppler (`pdftoppm`)、Tesseract (`tesseract`) |

`bootstrap.sh` 自动检测 NVIDIA GPU，存在时安装 `paddlepaddle-gpu` + `onnxruntime-gpu`。

## 测试

- 测试是基于指标的回归测试，非简单的通过/失败断言。每个 fixture 获得一个综合质量分（视觉 0.40 + 文字 0.50 + 数量 0.10），与存储的基线对比。
- Fixture 位于 `tests/fixtures/<name>/`，含 `source.png`、`source.html`、`expected.json` 和 `baseline.json`。
- 无基线的新 fixture 报告为 `NEW`，不会报为回归。
- 测试套件复用仓库依赖——无需额外 pip 安装。

## 字体分类器

一个 ResNet-34 ONNX 模型（`models/font_classifier.onnx`，约 20 MB，随仓库发布）为文本框提供字体族推断。它运行滑动窗口裁剪预处理，将文字分类为粗粒度桶（serif、sans-serif、mono、script、display、CJK-sans、CJK-serif）。结果通过 `classify_text_slots.py` 在桶级别传播。

## 注意事项

- 源图片必须命名为 `page_NN.<ext>`，其中 `<ext>` 为以下之一：`.png`、`.jpg`、`.jpeg`、`.webp`、`.bmp`、`.tif`、`.tiff`。`image_sources.py` 强制执行此命名，如果同一页码有多个文件会抛出 `ValueError`。
- `output/` 已加入 `.gitignore`。不要提交生成的文件。
- 修改逐页流水线（`erase_text.py`、`build_inventory.py`、`inventory_to_layout.py`）后，运行 `tests/runner/runner.py --rerun-pipeline` 强制使缓存失效。
- Web 层是完全独立的附加入口——不启动 Web 时 CLI 行为完全一致。所有 Web 运行时状态保存在 `web/data/` 下（已 gitignore）。
