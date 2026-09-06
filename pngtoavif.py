# -*- coding: utf-8 -*-
"""AVIF / WebP / JPG batch converter with a compact modern GUI."""

import os
import threading
import multiprocessing as mp
from tkinter import filedialog, messagebox
from concurrent.futures import ProcessPoolExecutor, as_completed
from queue import Queue, Empty
from datetime import datetime

import customtkinter as ctk
from PIL import Image

APP_NAME = "AVIF / WebP / JPG Converter"
APP_VER = "5.0"

INPUT_EXTS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff", ".tif",
    ".gif", ".ppm", ".pgm", ".pbm", ".pnm",
}

# 统一深色系：整体底色、卡片、控件用同一色温(偏冷灰蓝)，不再混黑
BG = "#16181d"        # 窗口内容区底色
SURFACE = "#1f232b"   # 卡片
SURFACE2 = "#282d37"  # 控件/输入框
SURFACE3 = "#333945"  # 悬停/激活
ACCENT = "#7c6ff0"
ACCENT_HOVER = "#9488ff"
TEXT = "#eef1f7"
TEXT_DIM = "#9aa2b5"
OK = "#5ec98f"
ERR = "#e06c75"
SUBSAMPLINGS = ("4:2:0", "4:2:2", "4:4:4")

# 速度 1-10 映射：AVIF 用 aom speed(0 最慢最好)，WebP 用 method(6 最慢最好)，JPEG 编码极快无此概念
def avif_speed(effort):
    return max(0, min(10, effort - 1))

def webp_method(effort):
    return max(0, min(6, 6 - (effort - 1) * 6 // 9))

JPEG_SUBSAMPLING = {"4:4:4": 0, "4:2:2": 1, "4:2:0": 2}

def _extract_meta(img):
    xmp = img.info.get("XML:com.adobe.xmp") or img.info.get("xmp")
    desc = img.info.get("Description")
    if isinstance(xmp, bytes):
        xmp = xmp.decode("utf-8", "ignore")
    if desc is not None and not isinstance(desc, str):
        desc = str(desc)
    return xmp, desc

def _build_xmp(xmp, desc):
    if not xmp and not desc:
        return None
    if xmp:
        core = xmp
        for tail in ("</rdf:RDF>\n</x:xmpmeta>", "</rdf:RDF>\r\n</x:xmpmeta>",
                     "</rdf:RDF></x:xmpmeta>", "</rdf:RDF>"):
            if core.rstrip().endswith(tail):
                core = core.rstrip()[:-len(tail)].rstrip()
                break
        parts = [core]
    else:
        parts = ['<x:xmpmeta xmlns:x="adobe:ns:meta/">',
                 '  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">']
    if desc:
        esc = desc.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts += ['  <rdf:Description xmlns:vrchat="https://vrchat.com/ns/xmp/1.0/">',
                  "    <vrchat:Description>" + esc + "</vrchat:Description>",
                  "  </rdf:Description>"]
    parts += ["</rdf:RDF>", "</x:xmpmeta>"]
    return "\n".join(parts)

def convert_one(args):
    (src, dst, fmt, lossless, quality, subsampling, effort, max_threads,
     keep_meta, keep_alpha) = args
    try:
        src_size = os.path.getsize(src)
        with Image.open(src) as im:
            has_alpha = getattr(im, "has_transparency_data", False) or im.mode == "RGBA"
            if fmt == "JPG" or not (keep_alpha and has_alpha):
                # JPG 不支持透明通道，或用户选择不保留 -> 展平
                target = "L" if im.mode == "L" else "RGB"
            elif im.mode in ("RGB", "RGBA"):
                target = "RGBA"
            elif im.mode == "L":
                target = "L"
            else:
                target = "RGB"
            frame = im if im.mode == target else im.convert(target)

            if fmt == "AVIF":
                kwargs = {
                    "speed": avif_speed(effort),
                    "max_threads": max_threads,
                }
                if lossless:
                    # YUV 域无损：视觉无损；灰度(4:0:0)为位精确
                    kwargs.update(quality=100,
                                  subsampling="4:0:0" if frame.mode == "L" else "4:4:4",
                                  advanced={"lossless": "1"})
                else:
                    kwargs.update(quality=quality,
                                  subsampling="4:0:0" if frame.mode == "L" else subsampling)
            elif fmt == "JPEG":
                kwargs = {
                    "quality": quality,
                    "subsampling": JPEG_SUBSAMPLING[subsampling],
                    "optimize": True,
                    "progressive": True,
                }
            else:
                method = webp_method(effort)
                if lossless:
                    kwargs = {"lossless": True, "exact": True, "quality": 100,
                              "method": method}
                else:
                    kwargs = {"lossless": False, "quality": quality, "method": method}

            if keep_meta:
                xmp, desc = _extract_meta(im)
                full_xmp = _build_xmp(xmp, desc)
                if full_xmp:
                    # AVIF 接受 str，WebP/JPEG 需要 bytes
                    kwargs["xmp"] = full_xmp if fmt == "AVIF" else full_xmp.encode("utf-8")
                try:
                    exif = im.info.get("exif")
                    if not exif:
                        exifobj = im.getexif()
                        exif = exifobj.tobytes() if exifobj else None
                    if exif:
                        if fmt == "JPG":
                            # JPEG 的 EXIF 必须带 Exif\0\0 头，否则写出无效数据
                            if not exif.startswith(b"Exif\x00\x00"):
                                exif = b"Exif\x00\x00" + exif
                        kwargs["exif"] = exif
                except Exception:
                    pass
                if "icc_profile" in im.info:
                    kwargs["icc_profile"] = im.info["icc_profile"]
            else:
                # Pillow 保存端会回退读取 im.info 里的 ICC，显式置空才能真正剥离
                kwargs["icc_profile"] = b""
            save_fmt = "JPEG" if fmt == "JPG" else fmt
            frame.save(dst, format=save_fmt, **kwargs)
        return True, src, dst, src_size, os.path.getsize(dst), "OK"
    except Exception as exc:
        try:
            if os.path.exists(dst):
                os.remove(dst)
        except Exception:
            pass
        return False, src, dst, os.path.getsize(src) if os.path.exists(src) else 0, 0, str(exc)

def _threads_for_workers(workers):
    cpu = os.cpu_count() or 8
    return max(1, min(4, cpu // max(1, workers)))

def center_window(win, width, height):
    screen_w = win.winfo_screenwidth()
    screen_h = win.winfo_screenheight()
    x = max(0, (screen_w - width) // 2)
    y = max(0, (screen_h - height) // 2)
    win.geometry(f"{width}x{height}+{x}+{y}")


def _apply_dark_titlebar(win):
    """染暗 Windows 标题栏，使标题栏颜色匹配内容区深色色板，消除割裂感。"""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        dwmapi = ctypes.windll.dwmapi
        # Tk 窗口实际 HWND 是其子窗口的父窗口
        hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()

        def set_attr(attr, value, vtype):
            try:
                v = vtype(value)
                return dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
            except Exception:
                return -1

        TRUE = ctypes.c_int(1)
        # 深色标题栏 (Win10 2004+ = 20，旧版 = 19)
        for attr in (20, 19):
            if set_attr(attr, 1, ctypes.c_int) == 0:
                break
        # 标题栏文字/按钮用浅色（随深色模式）
        set_attr(20, 1, ctypes.c_int)
        # 自定义标题栏背景色与边框色，匹配 BG 色板（ABGR 十六进制）
        # RGB(BG) = #16181d
        caption_color = 0x1D1816  # 0x00BBGGRR
        set_attr(35, caption_color, ctypes.c_int)  # DWMWA_CAPTION_COLOR
        set_attr(34, caption_color, ctypes.c_int)  # DWMWA_BORDER_COLOR
    except Exception:
        pass

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("AVIF / WebP / JPG 批量转换器")
        self.minsize(900, 700)
        self.configure(fg_color=BG)
        center_window(self, 1020, 780)
        try:
            icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")
            if os.path.exists(icon):
                self.iconbitmap(icon)
        except Exception:
            pass
        _apply_dark_titlebar(self)

        self.files = []
        self.out_dir = ""
        self.running = False
        self.queue = Queue()
        self.start_time = None
        self.ok_count = 0
        self.fail_count = 0
        self.total_in = 0
        self.total_out = 0
        cpu = os.cpu_count() or 8
        self.workers = max(1, min(8, cpu // 2))

        self.title_font = ctk.CTkFont(family="Microsoft YaHei UI", size=22, weight="bold")
        self.card_font = ctk.CTkFont(family="Microsoft YaHei UI", size=14, weight="bold")
        self.normal_font = ctk.CTkFont(family="Microsoft YaHei UI", size=13)
        self.small_font = ctk.CTkFont(family="Microsoft YaHei UI", size=12)
        self.mono_font = ctk.CTkFont(family="Consolas", size=12)

        self._build_ui()
        # 布局完成后强制按设定尺寸显示，避免被滚动区内高内容撑大窗口
        self._clamp_window_size()
        self._clamp_loop()
        self.after(80, self._drain_queue)

    def _clamp_window_size(self):
        """强制窗口保持在设定尺寸，阻止 CTkScrollableFrame 的内容高度撑破窗口。"""
        try:
            self.update_idletasks()
            w, h = 1020, 820
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            h = min(h, sh - 80)
            self.geometry(f"{w}x{h}+{max(0, (sw - w)//2)}+{max(0, (sh - h)//2-20)}")
        except Exception:
            pass

    def _clamp_loop(self):
        """期间反复约束窗口尺寸，抵消内容撑大带来的抖动。"""
        self._clamp_window_size()
        self.after(120, self._clamp_loop)

    def _card(self, parent):
        return ctk.CTkFrame(parent, corner_radius=16, fg_color=SURFACE,
                            border_width=1, border_color=SURFACE3)

    def _ghost_button(self, parent, text, command, width=118):
        return ctk.CTkButton(parent, text=text, command=command, width=width, height=36,
                             corner_radius=10, font=self.normal_font, fg_color=SURFACE2,
                             hover_color=SURFACE3, text_color=TEXT)

    def _seg(self, parent, values, command, width=0):
        kwargs = dict(values=list(values), command=command, font=self.normal_font,
                      height=34, selected_color=ACCENT, selected_hover_color=ACCENT_HOVER,
                      unselected_color=SURFACE2, unselected_hover_color=SURFACE3,
                      fg_color=SURFACE2)
        if width:
            kwargs["width"] = width
        return ctk.CTkSegmentedButton(parent, **kwargs)

    def _build_ui(self):
        # 左右两列：col0=设置(可滚)  col1=进度(固定)  row1=footer(横跨)
        self.grid_columnconfigure(0, weight=1)      # 左列占剩余宽度
        self.grid_columnconfigure(1, weight=0)      # 右列固定宽度
        self.grid_rowconfigure(0, weight=1)          # 内容区占用剩余高度
        self.grid_rowconfigure(1, weight=0)          # footer 固定

        # Footer first so the start button cannot be pushed off-screen.
        foot = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=84)
        foot.grid(row=1, column=0, columnspan=2, sticky="nsew")
        foot.grid_propagate(False)
        inner = ctk.CTkFrame(foot, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=22, pady=16)
        self.start_btn_bottom = ctk.CTkButton(
            inner, text="开始转换", command=self.start, font=self.card_font,
            height=48, width=200, corner_radius=14, fg_color=ACCENT,
            hover_color=ACCENT_HOVER, text_color="#ffffff",
        )
        self.start_btn_bottom.pack(side="left")
        self._ghost_button(inner, "打开输出目录", self.open_out, width=148).pack(side="left", padx=10)
        self.hint = ctk.CTkLabel(inner, text="先添加文件，再点开始转换。", font=self.small_font, text_color=TEXT_DIM)
        self.hint.pack(side="right")

        # 左列：标题 + 输入 + 设置，放进滚动区（内容多时可滚）
        wrap_host = ctk.CTkFrame(self, fg_color="transparent")
        wrap_host.grid(row=0, column=0, sticky="nsew", padx=(22, 8), pady=(16, 4))
        wrap_host.grid_propagate(False)
        wrap = ctk.CTkScrollableFrame(wrap_host, fg_color="transparent", corner_radius=0)
        wrap.pack(fill="both", expand=True)
        self._wrap = wrap
        self._wrap_host = wrap_host  # 供滚动状态复用

        head = ctk.CTkFrame(wrap, fg_color="transparent")
        head.pack(fill="x", pady=(0, 12))
        ctk.CTkLabel(head, text="AVIF / WebP / JPG 批量转换器", font=self.title_font, text_color=TEXT).pack(side="left")
        self.badge = ctk.CTkLabel(head, text=f"{self.workers} 进程 · 智能线程",
                                  font=self.small_font, text_color=TEXT_DIM)
        self.badge.pack(side="right")

        input_card = self._card(wrap)
        input_card.pack(fill="x", pady=(0, 12))
        c1 = ctk.CTkFrame(input_card, fg_color="transparent")
        c1.pack(fill="x", padx=16, pady=14)
        row1 = ctk.CTkFrame(c1, fg_color="transparent")
        row1.pack(fill="x")
        ctk.CTkLabel(row1, text="输入文件", font=self.card_font, text_color=TEXT).pack(side="left")
        self.count_var = ctk.StringVar(value="0 个文件")
        ctk.CTkLabel(row1, textvariable=self.count_var, font=self.small_font,
                     text_color=TEXT_DIM).pack(side="right")
        btnrow = ctk.CTkFrame(c1, fg_color="transparent")
        btnrow.pack(fill="x", pady=(10, 10))
        self._ghost_button(btnrow, "添加文件", self.add_files).pack(side="left")
        self._ghost_button(btnrow, "添加文件夹", self.add_folder, width=132).pack(side="left", padx=8)
        self._ghost_button(btnrow, "清空列表", self.clear_files).pack(side="left")
        self._ghost_button(btnrow, "打开输出目录", self.open_out, width=128).pack(side="left", padx=8)
        self.start_btn = ctk.CTkButton(
            btnrow, text="开始转换", command=self.start, font=self.card_font,
            height=40, width=148, corner_radius=12, fg_color=ACCENT,
            hover_color=ACCENT_HOVER, text_color="#ffffff",
        )
        self.start_btn.pack(side="left", padx=(12, 0))
        self.file_list = ctk.CTkTextbox(c1, height=86, corner_radius=12, fg_color=SURFACE2,
                                        text_color=TEXT_DIM, font=self.mono_font)
        self.file_list.pack(fill="x")
        self.file_list.insert("1.0", "尚未添加文件。\n")
        self.file_list.configure(state="disabled")

        setting_card = self._card(wrap)
        setting_card.pack(fill="x", pady=(0, 12))
        c2 = ctk.CTkFrame(setting_card, fg_color="transparent")
        c2.pack(fill="x", padx=16, pady=14)
        ctk.CTkLabel(c2, text="转换设置", font=self.card_font, text_color=TEXT).pack(anchor="w")

        # 格式与编码模式
        fmtrow = ctk.CTkFrame(c2, fg_color="transparent")
        fmtrow.pack(fill="x", pady=(10, 6))
        ctk.CTkLabel(fmtrow, text="输出格式", font=self.normal_font, text_color=TEXT).pack(side="left")
        self.fmt_var = ctk.StringVar(value="AVIF")
        self.fmt_seg = self._seg(fmtrow, ("AVIF", "WebP", "JPG"), self._on_format, width=300)
        self.fmt_seg.set("AVIF")
        self.fmt_seg.pack(side="left", padx=12)
        ctk.CTkLabel(fmtrow, text="编码模式", font=self.normal_font, text_color=TEXT).pack(side="left", padx=(24, 0))
        self.lossless_var = ctk.BooleanVar(value=False)
        self.mode_seg = self._seg(fmtrow, ("有损", "无损"), self._on_mode, width=160)
        self.mode_seg.set("有损")
        self.mode_seg.pack(side="left", padx=12)

        qhead = ctk.CTkFrame(c2, fg_color="transparent")
        qhead.pack(fill="x", pady=(10, 6))
        ctk.CTkLabel(qhead, text="画质（有损模式）", font=self.normal_font, text_color=TEXT).pack(side="left")
        self.q_label = ctk.CTkLabel(qhead, text="40 · 推荐均衡", font=self.normal_font, text_color=ACCENT_HOVER)
        self.q_label.pack(side="right")

        qrow = ctk.CTkFrame(c2, fg_color="transparent")
        qrow.pack(fill="x")
        ctk.CTkLabel(qrow, text="更小文件", font=self.small_font, text_color=TEXT_DIM).pack(side="left")
        self.q_var = ctk.IntVar(value=40)
        self.q_slider = ctk.CTkSlider(qrow, from_=1, to=100, number_of_steps=99,
                                      command=self._on_quality, progress_color=ACCENT,
                                      button_color=ACCENT, button_hover_color=ACCENT_HOVER)
        self.q_slider.set(40)
        self.q_slider.pack(side="left", fill="x", expand=True, padx=12)
        ctk.CTkLabel(qrow, text="更高画质", font=self.small_font, text_color=TEXT_DIM).pack(side="left")
        ctk.CTkLabel(c2, text="往右：画质更高、文件更大。往左：体积更小。",
                     font=self.small_font, text_color=TEXT_DIM).pack(anchor="w", pady=(6, 8))

        # 色度子采样（仅 AVIF 有损显示）
        self.subs_row = ctk.CTkFrame(c2, fg_color="transparent")
        ctk.CTkLabel(self.subs_row, text="色度子采样", font=self.normal_font, text_color=TEXT).pack(side="left")
        self.subs_var = ctk.StringVar(value="4:2:0")
        self.subs_seg = self._seg(self.subs_row, SUBSAMPLINGS, self._on_subsampling, width=240)
        self.subs_seg.set("4:2:0")
        self.subs_seg.pack(side="left", padx=12)
        self.subs_hint = ctk.CTkLabel(c2, text="4:2:0 体积最小；4:2:2 兼顾；4:4:4 无色彩压缩，可消除放大后的彩色边缘发糊。",
                                      font=self.small_font, text_color=TEXT_DIM)
        self.subs_hint.pack(anchor="w", padx=(0, 0), pady=(2, 0))

        # 速度（1 最慢·压缩最好，10 最快）
        effrow = ctk.CTkFrame(c2, fg_color="transparent")
        effrow.pack(fill="x", pady=(2, 8))
        ctk.CTkLabel(effrow, text="编码速度", font=self.normal_font, text_color=TEXT).pack(side="left")
        ctk.CTkLabel(effrow, text="极致压缩", font=self.small_font, text_color=TEXT_DIM).pack(side="left", padx=(12, 0))
        self.effort_var = ctk.IntVar(value=8)
        self.eff_slider = ctk.CTkSlider(effrow, from_=1, to=10, number_of_steps=9, width=200,
                                        command=self._on_effort, progress_color=ACCENT,
                                        button_color=ACCENT, button_hover_color=ACCENT_HOVER)
        self.eff_slider.set(8)
        self.eff_slider.pack(side="left", padx=10)
        ctk.CTkLabel(effrow, text="极速", font=self.small_font, text_color=TEXT_DIM).pack(side="left")
        self.eff_label = ctk.CTkLabel(effrow, text="", font=self.small_font, text_color=TEXT_DIM)
        self.eff_label.pack(side="left", padx=12)

        opt1 = ctk.CTkFrame(c2, fg_color="transparent")
        opt1.pack(fill="x", pady=(2, 8))
        ctk.CTkLabel(opt1, text="并行数", font=self.normal_font, text_color=TEXT).pack(side="left")
        self.worker_var = ctk.IntVar(value=self.workers)
        self.worker_slider = ctk.CTkSlider(opt1, from_=1, to=16, number_of_steps=15, width=180,
                                           command=self._on_workers, progress_color=ACCENT,
                                           button_color=ACCENT, button_hover_color=ACCENT_HOVER)
        self.worker_slider.set(self.workers)
        self.worker_slider.pack(side="left", padx=12)
        self.worker_label = ctk.CTkLabel(opt1, text=str(self.workers), font=self.normal_font, text_color=TEXT)
        self.worker_label.pack(side="left")
        self.thread_label = ctk.CTkLabel(opt1, text=self._thread_summary(),
                                          font=self.small_font, text_color=TEXT_DIM)
        self.thread_label.pack(side="left", padx=(24, 0))

        opt3 = ctk.CTkFrame(c2, fg_color="transparent")
        opt3.pack(fill="x", pady=(2, 8))
        self.meta_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opt3, text="保留元数据（VRCX / EXIF / XMP / ICC）", variable=self.meta_var,
                        font=self.normal_font, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                        checkmark_color="#ffffff").pack(side="left")
        self.alpha_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opt3, text="保留透明通道", variable=self.alpha_var, font=self.normal_font,
                        fg_color=ACCENT, hover_color=ACCENT_HOVER, checkmark_color="#ffffff").pack(side="left", padx=18)
        self.overwrite_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(opt3, text="覆盖同名文件", variable=self.overwrite_var, font=self.normal_font,
                        fg_color=ACCENT, hover_color=ACCENT_HOVER, checkmark_color="#ffffff").pack(side="left")

        self.mode_hint = ctk.CTkLabel(c2, text="", font=self.small_font, text_color=TEXT_DIM,
                                      wraplength=880, justify="left")
        self.mode_hint.pack(anchor="w", pady=(0, 8))

        outrow = ctk.CTkFrame(c2, fg_color="transparent")
        outrow.pack(fill="x")
        ctk.CTkLabel(outrow, text="输出目录", font=self.normal_font, text_color=TEXT).pack(side="left")
        self.out_var = ctk.StringVar(value="与源文件相同")
        ctk.CTkEntry(outrow, textvariable=self.out_var, height=34, corner_radius=10,
                     fg_color=SURFACE2, border_color="#2b3144", font=self.normal_font).pack(
            side="left", fill="x", expand=True, padx=12)
        self._ghost_button(outrow, "浏览", self.choose_out, width=86).pack(side="left")

        # 右列：转换进度固定在右侧独立一列，始终可见（不需要滚动）
        progress_card = self._card(self)
        progress_card.configure(width=360)
        progress_card.grid(row=0, column=1, sticky="nsew", padx=(8, 22), pady=(16, 4))
        progress_card.grid_propagate(False)
        c3 = ctk.CTkFrame(progress_card, fg_color="transparent")
        c3.pack(fill="both", expand=True, padx=16, pady=14)
        prowt = ctk.CTkFrame(c3, fg_color="transparent")
        prowt.pack(fill="x")
        ctk.CTkLabel(prowt, text="转换进度", font=self.card_font, text_color=TEXT).pack(side="left")
        self.status_var = ctk.StringVar(value="就绪")
        ctk.CTkLabel(prowt, textvariable=self.status_var, font=self.small_font, text_color=TEXT_DIM).pack(side="right")
        self.progress = ctk.CTkProgressBar(c3, progress_color=ACCENT, height=10)
        self.progress.set(0)
        self.progress.pack(fill="x", pady=(12, 12))
        self.log = ctk.CTkTextbox(c3, corner_radius=12, fg_color=SURFACE2, text_color=TEXT_DIM, font=self.mono_font)
        self.log.tag_config("ok", foreground=OK)
        self.log.tag_config("err", foreground=ERR)
        self.log.tag_config("accent", foreground=ACCENT_HOVER)
        self.log.tag_config("info", foreground=TEXT_DIM)
        self.log.pack(fill="both", expand=True)

        self._sync_mode_ui()

    def _thread_summary(self):
        threads = _threads_for_workers(self.workers)
        return f"{self.workers} x {threads} 编码线程"

    def _on_quality(self, value):
        q = int(float(value))
        if q <= 20:
            desc = "极小体积"
        elif q <= 35:
            desc = "省空间"
        elif q <= 55:
            desc = "推荐均衡"
        elif q <= 75:
            desc = "高画质"
        elif q <= 90:
            desc = "极高画质"
        else:
            desc = "顶级画质"
        self.q_label.configure(text=f"{q} · {desc}")
        self.q_var.set(q)

    def _on_workers(self, value):
        self.workers = int(float(value))
        self.worker_var.set(self.workers)
        self.worker_label.configure(text=str(self.workers))
        self.thread_label.configure(text=self._thread_summary())
        self.badge.configure(text=f"{self.workers} 进程 · 智能线程")

    def _on_format(self, value):
        self.fmt_var.set(value)
        if value == "JPG" and self.lossless_var.get():
            # JPEG 无真无损模式，切回有损
            self.lossless_var.set(False)
            self.mode_seg.set("有损")
        self._sync_mode_ui()

    def _on_mode(self, value):
        self.lossless_var.set(value == "无损")
        self._sync_mode_ui()

    def _on_subsampling(self, value):
        self.subs_var.set(value)

    def _on_effort(self, value):
        self.effort_var.set(int(float(value)))
        self._update_effort_label()

    def _update_effort_label(self):
        effort = self.effort_var.get()
        fmt = self.fmt_var.get()
        if fmt == "AVIF":
            self.eff_label.configure(text=f"aom speed {avif_speed(effort)}")
        elif fmt == "JPG":
            self.eff_label.configure(text="JPEG 编码极快")
        else:
            self.eff_label.configure(text=f"method {webp_method(effort)}")

    def _sync_mode_ui(self):
        fmt = self.fmt_var.get()
        lossless = self.lossless_var.get()
        if fmt == "JPG":
            self.mode_seg.configure(state="disabled")
        else:
            self.mode_seg.configure(state="normal")
        if lossless:
            self.q_slider.configure(state="disabled")
            self.q_label.configure(text="无损模式，画质不适用")
        else:
            self.q_slider.configure(state="normal")
            self._on_quality(self.q_slider.get())
        # 子采样：AVIF 有损与 JPG 支持
        if fmt in ("AVIF", "JPG") and not lossless:
            self.subs_row.pack(fill="x", pady=(2, 8), before=self.eff_slider.master)
            self.subs_hint.pack(anchor="w", padx=(0, 0), pady=(2, 8), before=self.eff_slider.master)
        else:
            self.subs_row.pack_forget()
            self.subs_hint.pack_forget()
        if fmt == "AVIF":
            hint = ("AVIF 无损：YUV 域无损编码，视觉无损（RGB 像素存在 ±3 以内取整误差，灰度图为位精确），"
                    "体积通常为 PNG 的 60–85%。") if lossless else \
                   "AVIF 有损：建议画质 ≥80 时搭配 4:4:4 子采样，可消除放大后的彩色边缘发糊。"
        elif fmt == "JPG":
            hint = "JPG：仅支持有损（渐进式 + 霍夫曼优化），透明通道会合并为不透明，兼容性最好；画质 ≥95 后体积增长很快。"
        else:
            hint = ("WebP 无损：逐像素位精确还原（含透明通道），体积通常为 PNG 的 85–98%。"
                    ) if lossless else \
                   "WebP 有损：固定 4:2:0 色度采样，兼容性最好。"
        self.mode_hint.configure(text=hint)
        self._update_effort_label()

    def add_files(self):
        paths = filedialog.askopenfilenames(title="选择图片", filetypes=[
            ("图片", "*.png *.jpg *.jpeg *.bmp *.webp *.tiff *.tif *.gif *.ppm *.pnm"),
            ("所有文件", "*.*"),
        ])
        self._add_paths(paths)

    def add_folder(self):
        folder = filedialog.askdirectory(title="选择文件夹（含子目录）")
        if not folder:
            return
        found = []
        for root, _, files in os.walk(folder):
            for name in files:
                path = os.path.join(root, name)
                if os.path.splitext(name)[1].lower() in INPUT_EXTS:
                    found.append(path)
        self._add_paths(sorted(found))

    def _add_paths(self, paths):
        existing = set(self.files)
        added = 0
        for path in paths:
            path = os.path.abspath(path)
            if os.path.isfile(path) and path not in existing and os.path.splitext(path)[1].lower() in INPUT_EXTS:
                self.files.append(path)
                existing.add(path)
                added += 1
        self._refresh()
        self._log(f"已添加 {added} 个文件，当前 {len(self.files)} 个。", "info")

    def clear_files(self):
        self.files.clear()
        self._refresh()
        self._log("已清空文件列表。", "info")

    def _refresh(self):
        self.count_var.set(f"{len(self.files)} 个文件")
        self.file_list.configure(state="normal")
        self.file_list.delete("1.0", "end")
        if not self.files:
            self.file_list.insert("1.0", "尚未添加文件。\n")
        else:
            for path in self.files:
                self.file_list.insert("end", os.path.basename(path) + "\n")
        self.file_list.configure(state="disabled")

    def choose_out(self):
        folder = filedialog.askdirectory(title="选择输出目录")
        if folder:
            self.out_dir = folder
            self.out_var.set(folder)

    def open_out(self):
        folder = self.out_dir or (os.path.dirname(self.files[0]) if self.files else "")
        if folder and os.path.isdir(folder):
            os.startfile(folder)

    def start(self):
        if self.running or not self.files:
            if not self.files:
                messagebox.showinfo("AVIF / WebP / JPG 批量转换器", "请先添加文件。")
            return
        fmt = self.fmt_var.get()
        lossless = self.lossless_var.get()
        quality = self.q_var.get()
        subsampling = self.subs_var.get()
        effort = self.effort_var.get()
        workers = self.workers
        threads = _threads_for_workers(workers)
        keep_meta = self.meta_var.get()
        keep_alpha = self.alpha_var.get()
        overwrite = self.overwrite_var.get()
        ext = {"AVIF": ".avif", "WebP": ".webp", "JPG": ".jpg"}[fmt]
        tasks = []
        for src in self.files:
            base = os.path.splitext(os.path.basename(src))[0]
            dst_dir = self.out_dir or os.path.dirname(src)
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(dst_dir, base + ext)
            if os.path.exists(dst) and not overwrite:
                seq = 1
                while os.path.exists(os.path.join(dst_dir, f"{base}_{seq}{ext}")):
                    seq += 1
                dst = os.path.join(dst_dir, f"{base}_{seq}{ext}")
            tasks.append((src, dst, fmt, lossless, quality, subsampling, effort,
                          threads, keep_meta, keep_alpha))
        self.running = True
        self.ok_count = 0
        self.fail_count = 0
        self.total_in = 0
        self.total_out = 0
        self.start_time = datetime.now()
        self.progress.set(0)
        self.status_var.set(f"准备转换 {len(tasks)} 个文件")
        self.start_btn.configure(state="disabled", text="转换中...")
        if hasattr(self, "start_btn_bottom"):
            self.start_btn_bottom.configure(state="disabled", text="转换中...")
        mode_text = "无损" if lossless else f"有损 q{quality} {subsampling if fmt != 'WebP' else ''}".strip()
        self._log(f"开始转换：{len(tasks)} 个文件 -> {fmt}（{mode_text}），{workers} 进程 x {threads} 线程。", "accent")
        threading.Thread(target=self._worker, args=(tasks,), daemon=True).start()

    def _worker(self, tasks):
        try:
            context = mp.get_context("spawn")
            with ProcessPoolExecutor(max_workers=self.workers, mp_context=context) as pool:
                futures = {pool.submit(convert_one, task): task for task in tasks}
                for index, future in enumerate(as_completed(futures), 1):
                    try:
                        result = future.result()
                    except Exception as exc:
                        task = futures[future]
                        result = (False, task[0], task[1], 0, 0, f"进程异常：{exc}")
                    self.queue.put(("file", index, result))
            self.queue.put(("done", None))
        except Exception as exc:
            self.queue.put(("fatal", str(exc)))

    def _drain_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                kind = item[0]
                if kind == "file":
                    _, index, result = item
                    ok, src, dst, src_size, dst_size, message = result
                    name = os.path.basename(src)
                    self.total_in += src_size
                    if ok:
                        self.ok_count += 1
                        self.total_out += dst_size
                        ratio = dst_size / src_size * 100 if src_size else 0
                        self._log(f"[{index:02d}] {name} -> {dst_size/1024:.0f} KB ({ratio:.1f}%)", "ok")
                    else:
                        self.fail_count += 1
                        self._log(f"[{index:02d}] {name} 转换失败：{message}", "err")
                    total = len(self.files)
                    self.progress.set(index / total if total else 0)
                    self.status_var.set(f"{index}/{total} · 成功 {self.ok_count} · 失败 {self.fail_count}")
                elif kind == "done":
                    elapsed = (datetime.now() - self.start_time).total_seconds()
                    in_mb = self.total_in / 1048576
                    out_mb = self.total_out / 1048576
                    ratio = self.total_out / self.total_in * 100 if self.total_in else 0
                    rate = self.ok_count / elapsed if elapsed else 0
                    self._log(
                        f"完成：成功 {self.ok_count}，失败 {self.fail_count}；"
                        f"{in_mb:.2f} MB -> {out_mb:.2f} MB ({ratio:.1f}%)；"
                        f"耗时 {elapsed:.1f} 秒，{rate:.1f} 张/秒。",
                        "accent",
                    )
                    self.status_var.set("转换完成")
                    self.running = False
                    self.start_btn.configure(state="normal", text="开始转换")
                    if hasattr(self, "start_btn_bottom"):
                        self.start_btn_bottom.configure(state="normal", text="开始转换")
                elif kind == "fatal":
                    self._log(f"转换任务中断：{item[1]}", "err")
                    self.status_var.set("出错")
                    self.running = False
                    self.start_btn.configure(state="normal", text="开始转换")
                    if hasattr(self, "start_btn_bottom"):
                        self.start_btn_bottom.configure(state="normal", text="开始转换")
        except Empty:
            pass
        self.after(80, self._drain_queue)

    def _log(self, message, tag="info"):
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

def main():
    mp.freeze_support()
    app = App()
    app.mainloop()

if __name__ == "__main__":
    main()
