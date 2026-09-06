# AVIF / WebP / JPG 批量转换器

一款带暗色现代 GUI 的批量图片转换工具，专为 **VRChat 截图/贴图** 场景优化。多进程并行编码，保留元数据，按需选择无损或高压缩率有损编码。

界面包含：文件添加区（添加文件/文件夹、清空列表）、转换设置区（输出格式、编码模式、画质滑条、色度子采样、编码速度、并行数、元数据/透明通道/覆盖复选框、输出目录）、实时进度与日志区。详见下方参数说明。

## 功能

- **输入**：PNG / JPG / BMP / WebP / TIFF / GIF / PPM 等常见格式
- **输出**：AVIF、WebP、JPG（JPG 晚于前两者，优先保证 AVIF/WebP 的压缩率与兼容性）
- **元数据保留**：EXIF、XMP（含 VRCX 写入 XMP 的 `vrchat:Description`）、ICC 色彩配置文件
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
- **色度子采样**：4:2:0 / 4:2:2 / 4:4:4（AVIF 有损与 JPG；4:4:4 消除彩色边缘发糊）
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

## 依赖

- Pillow（AVIF / WebP / JPEG 编码插件，Pillow 12.3 起自带 libavif + aom）
- customtkinter（GUI）
- pywinstyles（Win11 云母/亚克力外观）

## License

MIT
