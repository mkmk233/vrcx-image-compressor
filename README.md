# VRC 截图压图工具（AVIF / WebP / JPG）

一款专为 **VRChat 用户**设计的批量图片压缩转换工具，暗色左右分栏 GUI。

**核心场景**：在 VRCX 运行时，VRChat 拍下的照片会把当时的**房间名、房间 ID、玩家名等情景信息**写进 PNG 的元数据里。普通压缩/转换软件只搬运像素、丢弃元数据——转完的图片就像失忆了一样，只剩画面。本工具在压缩的同时**逐项保留这些元数据**，并在保留元数据的基础上提供**无损 / 有损、色度子采样**等完整的压缩选项。

界面为**左右分栏**暗色布局：左列是文件添加区（添加文件/文件夹、清空列表）与转换设置区（输出格式、编码模式、画质滑条、色度子采样、编码速度、并行数、元数据/透明通道/覆盖复选框、输出目录），可滚动；右列是固定的转换进度区（进度条 + 实时日志），始终可见无需滚动。详见下方参数说明。

## 为什么转完会"丢信息"：PNG 元数据说明

VRChat 截图默认是 PNG。PNG 不止存像素，还能在文件内部挂多种元数据块（chunk），VRC 用户最关心的三样都在里面：

| 元数据 | 在 PNG 中的位置 | VRC 场景下的内容 |
|--------|----------------|------------------|
| **XMP** | `iTXt` 文本块（键名 `XML:com.adobe.xmp`） | VRCX 会把截图时的**房间名、房间 ID、创建者、玩家列表**等以 `vrchat:Description` 命名空间写进 XMP |
| **EXIF** | 标准 EXIF 块 | 拍摄时间、相机参数等（多数截图含） |
| **ICC** | `iCCP` 色彩块 | 色彩配置文件，决定颜色显示是否准确 |

**为什么常规工具会丢**：JPEG/WebP/AVIF 的容器结构与 PNG 完全不同（没有 chunk 体系），转码工具必须"主动翻译"元数据到目标格式的对应位置（AVIF 的 `meta` 盒子、JPEG 的 APP1 段等）。大多数压缩软件图省事，转码时只处理像素，把 XMP/EXIF/ICC 一律扔掉——所以压完的图在 VRCX / 图库浏览时不再显示房间与玩家信息。

**本工具的处理方式**：
- 读取阶段按上表从 PNG 各块中取出 XMP、EXIF、ICC（XMP 支持从 `iTXt` 的 `XML:com.adobe.xmp` 键读取）
- 写入阶段**逐项翻译**到目标格式：AVIF 写 `meta` 盒子、WebP 写 XMP/EXIF 块、JPG 写 APP1/APP2 段，格式间行为一致
- 对非 PNG 输入（JPG/BMP 等），同样从源文件中读取并搬运已有元数据
- 界面里**"保留元数据"**复选框可一键关闭：关闭时会显式剥离 ICC（防止 Pillow 隐式回写），做到真正干净的"无信息"输出，适合分享不想要房间信息的图

在完整保留元数据的基础上，工具再叠加压缩能力：见下方格式对比与参数说明。

## 功能

- **输入**：PNG / JPG / BMP / WebP / TIFF / GIF / PPM 等常见格式
- **输出**：AVIF、WebP、JPG（JPG 晚于前两者，优先保证 AVIF/WebP 的压缩率与兼容性）
- **元数据保留**：XMP（含 VRCX 写入的 `vrchat:Description` 房间/玩家信息）、EXIF、ICC 色彩配置文件，跨格式逐项搬运
- **多进程并行**：`ProcessPoolExecutor` + spawn，自动按 CPU 分配编码线程
- **透明通道**：AVIF/WebP 可保留；JPG 会合并为不透明
- **画质与无损**：独立于压缩质量的无损编码模式，逐步压缩参数可调
- **覆盖/自动命名去冲突**：同名文件自动加序号，或选择覆盖

## 格式对比（关键差异）

同一个 VRChat 截图作为源时（PNG ≈ 100%，数值按常见截图近似）：

| 格式 | 模式 | 无损模式 | 位精确 | 典型体积 | 说明 |
|------|------|----------|--------|----------|------|
| AVIF | 有损 | 支持 `lossless` | **否**（±3 取整误差） | ~10–30% | 兼容性一般，视觉无损 |
| AVIF | 无损 | `quality=100 + 4:4:4` | 否（±3） | ~60–85% | YUV 域无损，灰度图位精确 |
| WebP | 有损 | `lossless + exact` | — | ~30–50% | 兼容性好 |
| WebP | 无损 | `lossless + exact` | **是** | ~85–98% | 含 alpha，逐像素无损 |
| JPG  | 有损 | 无 | — | ~5–15% | 兼容性最好，无透明通道 |

> **关于无损的说明**：Pillow 的 AVIF 编码器将色彩矩阵硬编码为 BT601，RGB→YUV→RGB 存在取整误差（±3 以内），因此 AVIF 无损是**视觉无损而非逐像素无损**。需要位精确无损请使用 **WebP 无损**模式；灰度图为**位精确**。JPG 没有真无损模式。

## 使用

1. `pip install -r requirements.txt`
2. `python pngtoavif.py`
3. 添加文件 → 选择输出格式与编码模式 → 开始转换

### 界面参数

- **输出格式**：AVIF / WebP / JPG
- **编码模式**：有损 / 无损（JPG 自动禁用无损）
- **画质**：1–100（有损模式；无损时禁用）
- **色度子采样**：4:2:0 / 4:2:2 / 4:4:4（AVIF 有损与 JPG；4:4:4 不压缩色彩通道，避免彩色边缘发糊，适合文字/UI 截图）
- **编码速度**：1（极致压缩，慢）–10（极速）；AVIF aom speed、WebP method
- **并行数**：1–16 进程
- **保留元数据**、**保留透明通道**、**覆盖同名文件**

## 打包为单文件 exe

```bash
pyinstaller --onefile --windowed --icon=app.ico --name AVIFBatchConverter pngtoavif.py
```

产物位于 `dist/AVIFBatchConverter.exe`。多进程启动使用 spawn，PyInstaller 已有 `mp.freeze_support()` 保护。

## 技术说明

- 元数据注入：EXIF / XMP 通过 Pillow 原生 `exif` / `xmp` 参数写入；AVIF 接受 str 型 XMP，WebP / JPG 需要 UTF-8 bytes。JPG 的 EXIF 需补 `Exif\0\0` 头。
- 剥离元数据时显式传空 ICC 以防 Pillow 回退读取源 IMG 的 ICC。
- 速度映射：`avif_speed(effort)=effort-1`（0 最慢最好），`webp_method(effort)` 线性映射到 method 0–6。
- 界面：标题栏通过 Windows API（DwmSetWindowAttribute 深色模式 + 自定义标题栏颜色）染暗为内容区同色系，避免系统灰色标题栏与深色内容割裂；左右分栏——左列设置可滚动，右列转换进度始终可见。

## 依赖

- Pillow（AVIF / WebP / JPEG 编码插件，Pillow 12.3 起自带 libavif + aom）
- customtkinter（GUI）

## License

MIT
