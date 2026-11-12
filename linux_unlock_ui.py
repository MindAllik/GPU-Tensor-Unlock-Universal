#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Linux Console-Styled Desktop GUI for NVIDIA GPU Tensor Unlock (Kernel Module gpu_unlock.ko)
Supports 4 languages: English (EN), Russian (RU), Chinese (ZH), and Hindi (HI)."""

from __future__ import annotations

import platform
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

import core_detector
from i18n_strings import I18N_LINUX, OS_MISMATCH_MESSAGES
import linux_backend
import tensor_benchmark

# Strict Pure Grayscale Console / Industrial Terminal Palette (Zero Blue Tint: R == G == B)
BG_MAIN = "#121212"
BG_PANEL = "#1c1c1c"
BG_INPUT = "#0a0a0a"
BORDER_COL = "#333333"
FG_PRIMARY = "#e6e6e6"
FG_MUTED = "#999999"
FG_GREEN = "#3fb950"
FG_AMBER = "#d29922"
FG_RED = "#f85149"
FG_CYAN = "#d4d4d4"
BTN_BG = "#262626"
BTN_ACTIVE = "#3a3a3a"
BTN_ACCENT = "#383838"


def enforce_linux_os_guard() -> None:
    """Block execution of Linux_Launch_UI on Windows or macOS with a clear error dialog and console message."""
    if not sys.platform.startswith("linux"):
        plat_str = f"{platform.system()} {platform.release()} ({sys.platform})"
        info = OS_MISMATCH_MESSAGES["linux_on_non_linux"]
        title = info["title"]
        msg = info["msg"].format(platform=plat_str)
        sys.stderr.write("\n" + "=" * 76 + "\n" + msg + "\n" + "=" * 76 + "\n")
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(title, msg)
            root.destroy()
        except Exception:
            pass
        raise SystemExit(2)


class LinuxUnlockApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.lang = "RU"
        self.title(I18N_LINUX[self.lang]["app_title"])
        self.geometry("1280x880")
        self.minsize(1100, 780)
        self.configure(bg=BG_MAIN)

        self.hw_info: dict[str, Any] = {}
        self.last_bench_result: dict[str, Any] | None = None
        self.bench_history: dict[str, Any] = tensor_benchmark.load_benchmark_history()
        self.busy = False

        self.protocol("WM_DELETE_WINDOW", self._on_close_window)
        self._setup_styles()
        self._build_layout()
        self._apply_language(self.lang)
        self.after(60, self._ensure_initial_pane_layout)
        self.after(150, self.action_rescan_hardware)

    def _on_close_window(self) -> None:
        if self.busy:
            t = I18N_LINUX[self.lang]
            messagebox.showwarning(t["busy_close_title"], t["busy_close_msg"])
            return
        self.destroy()

    def _set_busy(self, state: bool) -> None:
        self.busy = state
        btn_state = "disabled" if state else "normal"
        for b in (
            self.btn_rescan,
            self.btn_live_cli,
            self.btn_install_deps,
            self.btn_apply_unlock,
            self.btn_read_dmesg,
            self.btn_unload_mod,
            self.btn_run_bench,
            self.btn_probe_rm,
            self.btn_save_before,
            self.btn_save_after,
            self.btn_max_pl,
        ):
            try:
                b.configure(state=btn_state)
            except Exception:
                pass
        if not state:
            self._update_power_btn_state()

    def _update_power_btn_state(self) -> None:
        has_pl = bool(
            self.hw_info.get("gpu_uuid")
            and (self.hw_info.get("power_max_w") or 0) > 0
            and (self.hw_info.get("power_min_w") or 0) > 0
        )
        try:
            self.btn_max_pl.configure(state="normal" if (has_pl and not self.busy) else "disabled")
        except Exception:
            pass

    def _setup_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Console.Treeview",
            background=BG_INPUT,
            foreground=FG_PRIMARY,
            fieldbackground=BG_INPUT,
            borderwidth=1,
            relief="solid",
            rowheight=23,
            font=("Consolas", 10),
        )
        style.configure(
            "Console.Treeview.Heading",
            background=BTN_BG,
            foreground=FG_CYAN,
            borderwidth=1,
            font=("Consolas", 9, "bold"),
        )
        style.map(
            "Console.Treeview",
            background=[("selected", "#333333")],
            foreground=[("selected", "#ffffff")],
        )
        self.option_add("*TCombobox*Listbox*Background", BG_INPUT)
        self.option_add("*TCombobox*Listbox*Foreground", FG_PRIMARY)
        self.option_add("*TCombobox*Listbox*selectBackground", BTN_ACCENT)
        self.option_add("*TCombobox*Listbox*selectForeground", "#ffffff")
        self.option_add("*TCombobox*Listbox*Font", ("Consolas", 9))

        style.configure(
            "Console.TCombobox",
            fieldbackground=BG_INPUT,
            background=BTN_BG,
            foreground=FG_PRIMARY,
            selectbackground=BG_INPUT,
            selectforeground=FG_PRIMARY,
            bordercolor=BORDER_COL,
            lightcolor=BORDER_COL,
            darkcolor=BORDER_COL,
            arrowcolor=FG_CYAN,
        )
        style.map(
            "Console.TCombobox",
            fieldbackground=[("readonly", BG_INPUT), ("disabled", BG_INPUT), ("!disabled", BG_INPUT), ("active", BG_INPUT), ("focus", BG_INPUT)],
            background=[("readonly", BTN_BG), ("disabled", BTN_BG), ("!disabled", BTN_BG), ("active", BTN_ACTIVE)],
            foreground=[("readonly", FG_PRIMARY), ("disabled", FG_PRIMARY), ("!disabled", FG_PRIMARY), ("active", FG_PRIMARY)],
            selectbackground=[("readonly", BG_INPUT), ("disabled", BG_INPUT), ("!disabled", BG_INPUT)],
            selectforeground=[("readonly", FG_PRIMARY), ("disabled", FG_PRIMARY), ("!disabled", FG_PRIMARY)],
            arrowcolor=[("readonly", FG_CYAN), ("disabled", FG_MUTED), ("!disabled", FG_CYAN)],
        )

        style.configure(
            "Console.Vertical.TScrollbar",
            background=BTN_ACCENT,
            troughcolor=BG_PANEL,
            bordercolor=BORDER_COL,
            lightcolor=BTN_ACCENT,
            darkcolor=BTN_ACCENT,
            arrowcolor=FG_MUTED,
            gripcount=0,
            relief="flat",
            borderwidth=1,
            width=14,
        )
        style.map(
            "Console.Vertical.TScrollbar",
            background=[("pressed", "#555555"), ("active", "#4a4a4a"), ("!disabled", BTN_ACCENT), ("disabled", BG_PANEL)],
            arrowcolor=[("pressed", "#ffffff"), ("active", FG_PRIMARY), ("!disabled", FG_MUTED), ("disabled", BG_PANEL)],
            troughcolor=[("!disabled", BG_PANEL), ("disabled", BG_PANEL)],
        )

    def _make_panel(self, parent: tk.Widget) -> tuple[tk.Frame, tk.Label]:
        outer = tk.Frame(parent, bg=BG_PANEL, highlightbackground=BORDER_COL, highlightthickness=1, padx=10, pady=5)
        hdr = tk.Label(outer, text="", bg=BG_PANEL, fg=FG_CYAN, font=("Consolas", 10, "bold"), anchor="w")
        hdr.pack(fill="x", pady=(0, 4))
        return outer, hdr

    def _make_btn(self, parent: tk.Widget, command: Any, accent: bool = False) -> tk.Button:
        bg = BTN_ACCENT if accent else BTN_BG
        fg = "#ffffff" if accent else FG_PRIMARY
        return tk.Button(
            parent,
            text="",
            command=command,
            bg=bg,
            fg=fg,
            activebackground=BTN_ACTIVE,
            activeforeground="#ffffff",
            disabledforeground=FG_MUTED,
            relief="flat",
            bd=1,
            highlightbackground=BORDER_COL,
            highlightthickness=1,
            padx=10,
            pady=3,
            cursor="hand2",
            font=("Consolas", 9, "bold"),
        )

    def _make_readonly_entry(self, parent: tk.Widget, var: tk.StringVar, width: int | None = None, fg: str = FG_PRIMARY) -> tk.Entry:
        kw: dict[str, Any] = {
            "textvariable": var,
            "state": "readonly",
            "readonlybackground": BG_INPUT,
            "fg": fg,
            "relief": "flat",
            "highlightbackground": BORDER_COL,
            "highlightthickness": 1,
            "font": ("Consolas", 9),
        }
        if width is not None:
            kw["width"] = width
        return tk.Entry(parent, **kw)

    def _build_layout(self) -> None:
        top_bar = tk.Frame(self, bg=BG_PANEL, highlightbackground=BORDER_COL, highlightthickness=1, padx=14, pady=6)
        top_bar.pack(fill="x", padx=10, pady=(8, 4))

        title_box = tk.Frame(top_bar, bg=BG_PANEL)
        title_box.pack(side="left", fill="x", expand=True)
        self.lbl_title = tk.Label(title_box, text="", bg=BG_PANEL, fg=FG_PRIMARY, font=("Consolas", 13, "bold"), anchor="w")
        self.lbl_title.pack(fill="x")
        self.lbl_subtitle = tk.Label(title_box, text="", bg=BG_PANEL, fg=FG_MUTED, font=("Consolas", 9), anchor="w")
        self.lbl_subtitle.pack(fill="x")
        self.lbl_issues_note = tk.Label(title_box, text="", bg=BG_PANEL, fg=FG_AMBER, font=("Consolas", 8, "bold"), anchor="w")
        self.lbl_issues_note.pack(fill="x", pady=(1, 0))

        lang_box = tk.Frame(top_bar, bg=BG_PANEL)
        lang_box.pack(side="right")
        self.lbl_lang = tk.Label(lang_box, text="LANG:", bg=BG_PANEL, fg=FG_MUTED, font=("Consolas", 9, "bold"))
        self.lbl_lang.pack(side="left", padx=(0, 6))
        self.lang_btns: dict[str, tk.Button] = {}
        for code, label in (("EN", "EN"), ("RU", "RU"), ("ZH", "中文"), ("HI", "हिन्दी")):
            b = tk.Button(
                lang_box,
                text=f"[{label}]",
                command=lambda c=code: self._apply_language(c),
                bg=BTN_BG,
                fg=FG_PRIMARY,
                activebackground=BTN_ACTIVE,
                relief="flat",
                padx=8,
                pady=3,
                cursor="hand2",
                font=("Consolas", 9, "bold"),
            )
            b.pack(side="left", padx=2)
            self.lang_btns[code] = b

        self.main_paned = tk.PanedWindow(
            self,
            orient="vertical",
            bg=BORDER_COL,
            sashwidth=7,
            sashrelief="raised",
            sashpad=1,
            bd=0,
            opaqueresize=True,
        )
        self.main_paned.pack(fill="both", expand=True, padx=10, pady=(4, 10))

        mid_frame = tk.Frame(self.main_paned, bg=BG_MAIN)
        mid_frame.columnconfigure(0, weight=11)
        mid_frame.columnconfigure(1, weight=13)
        mid_frame.rowconfigure(0, weight=1)
        self.main_paned.add(mid_frame, minsize=465, stretch="always")

        left_col = tk.Frame(mid_frame, bg=BG_MAIN)
        left_col.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        self.left_col = left_col

        right_col = tk.Frame(mid_frame, bg=BG_MAIN)
        right_col.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        self.right_col = right_col

        # --- LEFT COLUMN: [01] LINUX HARDWARE, [02] KERNEL BUILD ENV, [03] MODULE EXECUTION ---
        self.pnl_hw, self.hdr_hw = self._make_panel(left_col)
        self.pnl_hw.pack(fill="x", pady=(0, 4))

        hw_grid = tk.Frame(self.pnl_hw, bg=BG_PANEL)
        hw_grid.pack(fill="x")
        hw_grid.columnconfigure(1, weight=1)

        self.var_gpu_name = tk.StringVar()
        self.var_die = tk.StringVar(value="UNSUPPORTED")
        self.var_board_id = tk.StringVar()
        self.var_subsys_id = tk.StringVar()
        self.var_bdf = tk.StringVar()
        self.var_bound_drv = tk.StringVar()
        self.var_vram_info = tk.StringVar()
        self.var_pl_info = tk.StringVar()
        self.var_kernel_distro = tk.StringVar()
        self.var_modprobe_cmd = tk.StringVar()
        self.var_cli_cmd = tk.StringVar(value=linux_backend.get_linux_live_cli_command())

        self.hw_labels: dict[str, tk.Label] = {}
        rows_spec = [
            ("lbl_gpu", self.var_gpu_name, "gpu_combo"),
            ("lbl_die", self.var_die, "die_locked"),
            ("lbl_pci", self.var_board_id, self.var_subsys_id),
            ("lbl_bus", self.var_bdf, self.var_bound_drv),
            ("lbl_vram", self.var_vram_info, self.var_pl_info),
            ("lbl_kernel_distro", self.var_kernel_distro, None),
            ("lbl_boot_opt", self.var_modprobe_cmd, "cli_preview"),
            ("lbl_cli_cmd", self.var_cli_cmd, "cli_preview"),
        ]
        for r_idx, (lkey, var1, var2) in enumerate(rows_spec):
            lbl = tk.Label(hw_grid, text="", bg=BG_PANEL, fg=FG_MUTED, font=("Consolas", 9), anchor="w")
            lbl.grid(row=r_idx, column=0, sticky="w", pady=1, padx=(0, 8))
            self.hw_labels[lkey] = lbl

            row_f = tk.Frame(hw_grid, bg=BG_PANEL)
            row_f.grid(row=r_idx, column=1, sticky="ew", pady=1)
            if var2 == "gpu_combo":
                self.cb_gpu = ttk.Combobox(row_f, textvariable=var1, state="readonly", style="Console.TCombobox")
                self.cb_gpu.pack(side="left", fill="x", expand=True)
                self.cb_gpu.bind("<<ComboboxSelected>>", self._on_gpu_selected)
            elif var2 == "die_locked":
                e_die = self._make_readonly_entry(row_f, var1, width=12, fg=FG_CYAN)
                e_die.pack(side="left")
                self.lbl_arch_tag = tk.Label(row_f, text="NOT DETECTED", bg=BG_PANEL, fg=FG_AMBER, font=("Consolas", 9, "bold"))
                self.lbl_arch_tag.pack(side="left", padx=8)
            elif var2 == "cli_preview":
                e_cli = self._make_readonly_entry(row_f, var1, fg=FG_CYAN)
                e_cli.pack(side="left", fill="x", expand=True)
            elif isinstance(var2, tk.StringVar):
                e1 = self._make_readonly_entry(row_f, var1, width=16)
                e1.pack(side="left", padx=(0, 6))
                e2 = self._make_readonly_entry(row_f, var2, width=16)
                e2.pack(side="left")
            else:
                e1 = self._make_readonly_entry(row_f, var1)
                e1.pack(side="left", fill="x", expand=True)

        hw_btn_row = tk.Frame(self.pnl_hw, bg=BG_PANEL)
        hw_btn_row.pack(fill="x", pady=(4, 0))
        hw_btn_row.columnconfigure(0, weight=1)
        hw_btn_row.columnconfigure(1, weight=2)
        self.btn_rescan = self._make_btn(hw_btn_row, self.action_rescan_hardware)
        self.btn_rescan.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.btn_live_cli = self._make_btn(hw_btn_row, self.action_run_live_cli, accent=True)
        self.btn_live_cli.grid(row=0, column=1, sticky="ew", padx=(3, 0))

        # [02] KERNEL BUILD ENVIRONMENT (HEADERS / DKMS / ZSTD)
        self.pnl_deps, self.hdr_deps = self._make_panel(left_col)
        self.pnl_deps.pack(fill="x", pady=(0, 4))

        deps_grid = tk.Frame(self.pnl_deps, bg=BG_PANEL)
        deps_grid.pack(fill="x")
        deps_grid.columnconfigure(1, weight=1)

        self.lbl_headers_title = tk.Label(deps_grid, text="", bg=BG_PANEL, fg=FG_MUTED, font=("Consolas", 9), anchor="w")
        self.lbl_headers_title.grid(row=0, column=0, sticky="w", pady=1, padx=(0, 8))
        self.lbl_headers_val = tk.Label(deps_grid, text="...", bg=BG_PANEL, fg=FG_GREEN, font=("Consolas", 9, "bold"), anchor="w")
        self.lbl_headers_val.grid(row=0, column=1, sticky="w", pady=1)

        self.lbl_dkms_title = tk.Label(deps_grid, text="", bg=BG_PANEL, fg=FG_MUTED, font=("Consolas", 9), anchor="w")
        self.lbl_dkms_title.grid(row=1, column=0, sticky="w", pady=1, padx=(0, 8))
        self.lbl_dkms_val = tk.Label(deps_grid, text="...", bg=BG_PANEL, fg=FG_GREEN, font=("Consolas", 9, "bold"), anchor="w")
        self.lbl_dkms_val.grid(row=1, column=1, sticky="w", pady=1)

        self.lbl_initramfs_title = tk.Label(deps_grid, text="", bg=BG_PANEL, fg=FG_MUTED, font=("Consolas", 9), anchor="w")
        self.lbl_initramfs_title.grid(row=2, column=0, sticky="w", pady=1, padx=(0, 8))
        self.lbl_initramfs_val = tk.Label(deps_grid, text="...", bg=BG_PANEL, fg=FG_GREEN, font=("Consolas", 9, "bold"), anchor="w")
        self.lbl_initramfs_val.grid(row=2, column=1, sticky="w", pady=1)

        self.btn_install_deps = self._make_btn(self.pnl_deps, self.action_install_deps)
        self.btn_install_deps.pack(fill="x", pady=(4, 0))

        # [03] KERNEL MODULE (GPU_UNLOCK.KO) & FIRMWARE EXECUTION
        self.pnl_dkms, self.hdr_dkms = self._make_panel(left_col)
        self.pnl_dkms.pack(fill="both", expand=True)

        self.lbl_fw_state = tk.Label(self.pnl_dkms, text="", bg=BG_PANEL, fg=FG_PRIMARY, font=("Consolas", 9, "bold"), anchor="w")
        self.lbl_fw_state.pack(fill="x", pady=(0, 2))
        self.lbl_mod_state = tk.Label(self.pnl_dkms, text="", bg=BG_PANEL, fg=FG_CYAN, font=("Consolas", 9), anchor="w")
        self.lbl_mod_state.pack(fill="x", pady=(0, 3))
        self.lbl_linux_note = tk.Label(
            self.pnl_dkms, text="", bg=BG_PANEL, fg=FG_AMBER, font=("Consolas", 8),
            anchor="w", wraplength=540, justify="left",
        )
        self.lbl_linux_note.pack(fill="x", pady=(0, 3))

        self.btn_apply_unlock = self._make_btn(self.pnl_dkms, self.action_apply_unlock, accent=True)
        self.btn_apply_unlock.pack(fill="x", pady=(1, 3))

        sub_row = tk.Frame(self.pnl_dkms, bg=BG_PANEL)
        sub_row.pack(fill="x")
        sub_row.columnconfigure(0, weight=1)
        sub_row.columnconfigure(1, weight=1)
        self.btn_read_dmesg = self._make_btn(sub_row, self.action_read_dmesg)
        self.btn_read_dmesg.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.btn_unload_mod = self._make_btn(sub_row, self.action_unload_mod)
        self.btn_unload_mod.grid(row=0, column=1, sticky="ew", padx=(3, 0))

        # --- RIGHT COLUMN: [04] TENSOR CORE BENCHMARK & RM SELECTOR PROBE ---
        self.pnl_bench, self.hdr_bench = self._make_panel(right_col)
        self.pnl_bench.pack(fill="both", expand=True)

        self.lbl_bench_banner = tk.Label(
            self.pnl_bench,
            text="FMLA32 STATUS: READY TO MEASURE (CUDA PTX / RM IOCTL 0x20801230)",
            bg=BG_INPUT,
            fg=FG_AMBER,
            font=("Consolas", 10, "bold"),
            pady=6,
            padx=8,
            anchor="w",
            highlightbackground=BORDER_COL,
            highlightthickness=1,
        )
        self.lbl_bench_banner.pack(fill="x", pady=(0, 6))

        cols = ("inst", "fuse", "before", "after", "current", "gain")
        self.tree_bench = ttk.Treeview(self.pnl_bench, columns=cols, show="headings", style="Console.Treeview", height=7)
        self.tree_bench.column("inst", width=230, anchor="w")
        self.tree_bench.column("fuse", width=65, anchor="center")
        self.tree_bench.column("before", width=105, anchor="e")
        self.tree_bench.column("after", width=105, anchor="e")
        self.tree_bench.column("current", width=105, anchor="e")
        self.tree_bench.column("gain", width=100, anchor="e")
        self.tree_bench.pack(fill="both", expand=True, pady=(0, 6))

        bench_btn_row1 = tk.Frame(self.pnl_bench, bg=BG_PANEL)
        bench_btn_row1.pack(fill="x", pady=(0, 4))
        self.btn_run_bench = self._make_btn(bench_btn_row1, self.action_run_benchmark, accent=True)
        self.btn_run_bench.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.btn_probe_rm = self._make_btn(bench_btn_row1, self.action_probe_rm_rates)
        self.btn_probe_rm.pack(side="left", padx=(0, 4))
        self.btn_max_pl = self._make_btn(bench_btn_row1, self.action_set_max_power)
        self.btn_max_pl.pack(side="left")

        bench_btn_row2 = tk.Frame(self.pnl_bench, bg=BG_PANEL)
        bench_btn_row2.pack(fill="x")
        bench_btn_row2.columnconfigure(0, weight=1)
        bench_btn_row2.columnconfigure(1, weight=1)
        self.btn_save_before = self._make_btn(bench_btn_row2, lambda: self.action_save_slot("before"))
        self.btn_save_before.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.btn_save_after = self._make_btn(bench_btn_row2, lambda: self.action_save_slot("after"))
        self.btn_save_after.grid(row=0, column=1, sticky="ew", padx=(3, 0))

        # --- BOTTOM FULL-WIDTH CONSOLE LOG (DRAGGABLE TOP BORDER VIA PANEDWINDOW) ---
        self.pnl_console = tk.Frame(self.main_paned, bg=BG_PANEL, highlightbackground=BORDER_COL, highlightthickness=1, padx=10, pady=8)
        self.main_paned.add(self.pnl_console, minsize=105, stretch="never")

        console_hdr_bar = tk.Frame(self.pnl_console, bg=BG_PANEL)
        console_hdr_bar.pack(fill="x", pady=(0, 6))
        self.hdr_console = tk.Label(console_hdr_bar, text="", bg=BG_PANEL, fg=FG_CYAN, font=("Consolas", 10, "bold"), anchor="w")
        self.hdr_console.pack(side="left")

        self.btn_copy_log = tk.Button(
            console_hdr_bar,
            text="",
            command=self.action_copy_all_log,
            bg=BTN_BG,
            fg=FG_PRIMARY,
            activebackground=BTN_ACTIVE,
            activeforeground="#ffffff",
            relief="flat",
            bd=1,
            highlightbackground=BORDER_COL,
            highlightthickness=1,
            padx=8,
            pady=2,
            cursor="hand2",
            font=("Consolas", 8, "bold"),
        )
        self.btn_copy_log.pack(side="right")

        self.btn_copy_md_report = tk.Button(
            console_hdr_bar,
            text="",
            command=self.action_copy_markdown_report,
            bg=BTN_ACCENT,
            fg="#ffffff",
            activebackground=BTN_ACTIVE,
            activeforeground="#ffffff",
            relief="flat",
            bd=1,
            highlightbackground=BORDER_COL,
            highlightthickness=1,
            padx=8,
            pady=2,
            cursor="hand2",
            font=("Consolas", 8, "bold"),
        )
        self.btn_copy_md_report.pack(side="right", padx=(0, 6))

        self.lbl_drag_hint = tk.Label(console_hdr_bar, text="", bg=BG_PANEL, fg=FG_MUTED, font=("Consolas", 8), anchor="e")
        self.lbl_drag_hint.pack(side="right", padx=(8, 10))

        log_frame = tk.Frame(self.pnl_console, bg=BG_INPUT, highlightbackground=BORDER_COL, highlightthickness=1)
        log_frame.pack(fill="both", expand=True)

        self.txt_log = tk.Text(
            log_frame,
            bg=BG_INPUT,
            fg=FG_PRIMARY,
            insertbackground=FG_PRIMARY,
            selectbackground=BTN_ACCENT,
            selectforeground="#ffffff",
            relief="flat",
            height=6,
            font=("Consolas", 9),
            wrap="none",
            exportselection=True,
        )
        sb_y = ttk.Scrollbar(log_frame, orient="vertical", command=self.txt_log.yview, style="Console.Vertical.TScrollbar")
        self.txt_log.configure(yscrollcommand=sb_y.set)
        sb_y.pack(side="right", fill="y")
        self.txt_log.pack(side="left", fill="both", expand=True, padx=6, pady=4)

        self.txt_log.bind("<Control-KeyPress>", self._on_log_ctrl_key)
        self.txt_log.bind("<Control-c>", lambda _e: self.action_copy_selected_log())
        self.txt_log.bind("<Control-C>", lambda _e: self.action_copy_selected_log())
        self.txt_log.bind("<Control-Insert>", lambda _e: self.action_copy_selected_log())
        self.txt_log.bind("<Control-a>", lambda _e: self.action_select_all_log())
        self.txt_log.bind("<Control-A>", lambda _e: self.action_select_all_log())
        self.txt_log.bind("<KeyPress>", self._on_log_keypress)

        self.log_menu = tk.Menu(self, tearoff=0, bg=BG_PANEL, fg=FG_PRIMARY, activebackground=BTN_ACTIVE, activeforeground="#ffffff", font=("Consolas", 9))
        self.txt_log.bind("<Button-3>", self._show_log_context_menu)

        self._refresh_benchmark_table()

    def _ensure_initial_pane_layout(self) -> None:
        """Ensure the top pane (Sections [01]-[04]) is tall enough on startup so bottom buttons in [03] are never clipped."""
        try:
            self.update_idletasks()
            req_h = max(self.left_col.winfo_reqheight(), self.right_col.winfo_reqheight()) + 10
            paned_h = self.main_paned.winfo_height()
            if paned_h > 200:
                target_y = min(req_h, max(465, paned_h - 115))
                self.main_paned.sash_place(0, 0, target_y)
        except Exception:
            pass

    def _apply_language(self, code: str) -> None:
        self.lang = code
        t = I18N_LINUX[code]
        self.title(t["app_title"])
        self.lbl_title.configure(text=t["app_title"])
        self.lbl_subtitle.configure(text=t["subtitle"])
        self.lbl_issues_note.configure(text=t["issues_note"])
        self.lbl_lang.configure(text=t["lang_label"])

        for c, btn in self.lang_btns.items():
            btn.configure(bg=BTN_ACCENT if c == code else BTN_BG, fg="#ffffff" if c == code else FG_PRIMARY)

        self.hdr_hw.configure(text=t["sec_hw"])
        self.hdr_deps.configure(text=t["sec_deps"])
        self.hdr_dkms.configure(text=t["sec_dkms"])
        self.hdr_bench.configure(text=t["sec_bench"])
        self.hdr_console.configure(text=t["sec_console"])
        self.lbl_drag_hint.configure(text=t["drag_console_hint"])
        self.btn_copy_log.configure(text=t["btn_copy_log"])
        self.btn_copy_md_report.configure(text=t["btn_copy_md_report"])

        self.log_menu.delete(0, "end")
        self.log_menu.add_command(label=t["ctx_copy_sel"], command=self.action_copy_selected_log)
        self.log_menu.add_command(label=t["ctx_copy_all"], command=self.action_copy_all_log)
        self.log_menu.add_command(label=t["ctx_copy_md"], command=self.action_copy_markdown_report)
        self.log_menu.add_separator()
        self.log_menu.add_command(label=t["ctx_select_all"], command=self.action_select_all_log)

        for lkey, lbl in self.hw_labels.items():
            lbl.configure(text=t[lkey])

        self.btn_rescan.configure(text=t["btn_rescan"])
        self.btn_live_cli.configure(text=t["btn_live_cli"])
        self.lbl_headers_title.configure(text=t["lbl_headers"])
        self.lbl_dkms_title.configure(text=t["lbl_dkms"])
        self.lbl_initramfs_title.configure(text=t["lbl_initramfs"])
        self.btn_install_deps.configure(text=t["btn_install_deps"])

        self.lbl_linux_note.configure(text=t["linux_boot_note"])
        self.btn_apply_unlock.configure(text=t["btn_apply_unlock"])
        self.btn_read_dmesg.configure(text=t["btn_read_dmesg"])
        self.btn_unload_mod.configure(text=t["btn_unload_mod"])

        self.btn_run_bench.configure(text=t["btn_run_bench"])
        self.btn_probe_rm.configure(text=t["btn_probe_rm"])
        self.btn_save_before.configure(text=t["btn_save_before"])
        self.btn_save_after.configure(text=t["btn_save_after"])
        self.btn_max_pl.configure(text=t["btn_max_pl"])

        self.tree_bench.heading("inst", text=t["col_inst"])
        self.tree_bench.heading("fuse", text=t["col_fuse"])
        self.tree_bench.heading("before", text=t["col_before"])
        self.tree_bench.heading("after", text=t["col_after"])
        self.tree_bench.heading("current", text=t["col_current"])
        self.tree_bench.heading("gain", text=t["col_gain"])
        self._refresh_install_state_labels()
        self._refresh_deps_labels()

    def _refresh_deps_labels(self) -> None:
        if not self.hw_info:
            return
        t = I18N_LINUX[self.lang]
        info = self.hw_info
        hdr_ok = bool(info.get("headers_ok"))
        self.lbl_headers_val.configure(
            text=f"{t['status_ok']} ({info.get('headers_path')})" if hdr_ok else f"{t['status_missing']} ({info.get('headers_path')})",
            fg=FG_GREEN if hdr_ok else FG_AMBER,
        )
        dkms_ok = bool(info.get("dkms_toolchain_ok"))
        self.lbl_dkms_val.configure(
            text=f"{t['status_ok']} (dkms + {info.get('cc_path')})" if dkms_ok else t["status_missing"],
            fg=FG_GREEN if dkms_ok else FG_AMBER,
        )
        zst_ok = bool(info.get("zst_ok"))
        self.lbl_initramfs_val.configure(
            text=f"{t['status_ok']} ({info.get('zst_method')})" if zst_ok else t["status_missing"],
            fg=FG_GREEN if zst_ok else FG_AMBER,
        )

    def log(self, msg: str) -> None:
        def _append() -> None:
            self.txt_log.insert("end", msg + "\n")
            self.txt_log.see("end")
        self.after(0, _append)

    def _copy_text_to_clipboard(self, text: str) -> None:
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update_idletasks()

    def action_copy_selected_log(self) -> str:
        try:
            sel = self.txt_log.get("sel.first", "sel.last")
        except tk.TclError:
            sel = self.txt_log.get("1.0", "end-1c")
        self._copy_text_to_clipboard(sel)
        return "break"

    def action_copy_all_log(self) -> str:
        full_text = self.txt_log.get("1.0", "end-1c")
        self._copy_text_to_clipboard(full_text)
        return "break"

    def action_copy_markdown_report(self) -> str:
        log_text = self.txt_log.get("1.0", "end-1c")
        bench_rows = [tuple(self.tree_bench.item(item, "values")) for item in self.tree_bench.get_children()]
        banner_txt = str(self.lbl_bench_banner.cget("text") or "")
        md_text = core_detector.format_markdown_report(
            self.hw_info,
            bench_rows,
            log_text,
            platform_mode="linux",
            bench_banner=banner_txt,
        )
        self._copy_text_to_clipboard(md_text)
        t = I18N_LINUX[self.lang]
        self.log(t["md_copied_log"].format(n=len(md_text)))
        return "break"

    def action_select_all_log(self) -> str:
        self.txt_log.tag_add("sel", "1.0", "end-1c")
        self.txt_log.mark_set("insert", "1.0")
        self.txt_log.see("insert")
        return "break"

    def _on_log_ctrl_key(self, event: tk.Event) -> str | None:
        kc = getattr(event, "keycode", 0)
        ks = (getattr(event, "keysym", "") or "").lower()
        if kc in (54, 67) or ks in ("c", "cyrillic_es", "insert"):
            return self.action_copy_selected_log()
        if kc in (38, 65) or ks in ("a", "cyrillic_ef"):
            return self.action_select_all_log()
        return None

    def _on_log_keypress(self, event: tk.Event) -> str | None:
        if (getattr(event, "state", 0) & 0x4) != 0:
            return self._on_log_ctrl_key(event)
        if getattr(event, "keysym", "") in ("Up", "Down", "Left", "Right", "Prior", "Next", "Home", "End", "Shift_L", "Shift_R", "Control_L", "Control_R"):
            return None
        return "break"

    def _show_log_context_menu(self, event: tk.Event) -> None:
        try:
            self.txt_log.focus_set()
            self.log_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.log_menu.grab_release()

    def _on_gpu_selected(self, _event: Any = None) -> None:
        sel = self.var_gpu_name.get()
        gpus = self.hw_info.get("gpus") or []
        for g in gpus:
            label = f"[{g['index']}] {g['gpu_name']} ({g['pci_bdf']})"
            if sel == label or sel == g["gpu_name"]:
                for k in (
                    "gpu_name", "gpu_uuid", "pci_bdf", "board_id_hex", "subsystem_id_hex",
                    "segment_hex", "bus_hex", "device_hex", "function_hex", "die_name",
                    "chip_id_hex", "is_ada", "is_mobile", "support_tier", "vram_mib", "vram_min_hex",
                    "vram_max_hex", "vbios_version", "power_default_w", "power_min_w",
                    "power_max_w", "bound_driver", "linux_boot_option", "linux_modprobe_cmd", "verification_sources",
                ):
                    if k in g:
                        self.hw_info[k] = g[k]
                self._populate_gpu_fields()
                self._update_power_btn_state()
                self._refresh_benchmark_table()
                break

    def _populate_gpu_fields(self) -> None:
        info = self.hw_info
        self.var_die.set(info.get("die_name", "UNSUPPORTED"))
        self.var_board_id.set(info.get("board_id_hex", ""))
        self.var_subsys_id.set(info.get("subsystem_id_hex", ""))
        self.var_bdf.set(info.get("pci_bdf", ""))
        self.var_bound_drv.set(f"drv:{info.get('bound_driver', 'unknown')}")
        vram_mib = info.get("vram_mib") or 0
        self.var_vram_info.set(f"{vram_mib} MiB" if vram_mib else "N/A")
        p_def = info.get("power_default_w") or 0.0
        p_max = info.get("power_max_w") or 0.0
        self.var_pl_info.set(f"{p_def}W / Max {p_max}W" if p_max > 0 else f"VBIOS {info.get('vbios_version', 'N/A')}")
        self.var_modprobe_cmd.set(info.get("linux_modprobe_cmd", "UNSUPPORTED"))

        die = self.var_die.get()
        tier = info.get("support_tier", "unsupported")
        if die in core_detector.CHIP_BY_PMC:
            _, is_ada = core_detector.CHIP_BY_PMC[die]
            arch_str = "Turing TU10x (2-PLM)" if die.startswith("TU10") else ("Ada Lovelace (4-PLM)" if is_ada else "Ampere GA10x (1-PLM)")
            self.lbl_arch_tag.configure(
                text=f"{arch_str} [{tier}]",
                fg=FG_GREEN if tier == "hardware_tested" else (FG_CYAN if tier == "experimental_simulated" else FG_AMBER),
            )
        else:
            self.lbl_arch_tag.configure(text=f"UNSUPPORTED [{tier}]", fg=FG_RED)

    def _refresh_install_state_labels(self) -> None:
        t = I18N_LINUX[self.lang]
        inst = self.hw_info.get("install_state") or {}
        fw_ok = bool(inst.get("firmware_installed"))
        fw_cnt = inst.get("firmware_count", "0/14")
        self.lbl_fw_state.configure(
            text=f"{t['lbl_fw_state']} {'VERIFIED [OK]' if fw_ok else 'NOT STAGED'} ({fw_cnt} files)",
            fg=FG_GREEN if fw_ok else FG_AMBER,
        )
        dkms_ok = bool(inst.get("dkms_src_installed"))
        ko_ok = bool(inst.get("ko_installed_for_running_kernel"))
        loaded = bool(inst.get("module_loaded"))
        self.lbl_mod_state.configure(
            text=(
                f"{t['lbl_mod_state']} DKMS={'OK' if dkms_ok else 'NO'} | "
                f"gpu_unlock.ko={'BUILT' if ko_ok else 'NOT BUILT'} | "
                f"lsmod={'LOADED [ACTIVE]' if loaded else 'UNLOADED'}"
            ),
            fg=FG_GREEN if (ko_ok or loaded) else FG_CYAN,
        )

    def action_rescan_hardware(self) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self.log("[SCAN] Detecting GPU hardware via Linux sysfs (/sys/bus/pci/devices), lspci, NVML, CUDA, and checking kernel build environment...")

        def _worker() -> None:
            info: dict[str, Any] = {}
            err_msg: str | None = None
            try:
                info = linux_backend.detect_linux_environment()
            except Exception as exc:
                err_msg = str(exc)

            def _apply() -> None:
                try:
                    if err_msg:
                        self.log(f"[ERROR] Linux environment scan error: {err_msg}")
                        return
                    self.hw_info = info
                    gpus = info.get("gpus") or []
                    if gpus:
                        self.cb_gpu["values"] = [f"[{g['index']}] {g['gpu_name']} ({g['pci_bdf']})" for g in gpus]
                    else:
                        self.cb_gpu["values"] = []

                    self.var_gpu_name.set(info.get("gpu_name", "NOT DETECTED"))
                    self.var_kernel_distro.set(f"{info.get('kernel_release')} // {info.get('distro_pretty')}")
                    self._populate_gpu_fields()
                    self._refresh_install_state_labels()
                    self._refresh_benchmark_table()

                    self._refresh_deps_labels()

                    if info.get("gpu_detected"):
                        self.log(
                            f"[OK] [v{core_detector.APP_VERSION}] Detected: {info['gpu_name']} | Die={info['die_name']} ({info['support_tier']}) | "
                            f"BDF={info['pci_bdf']} | PCI={info['board_id_hex']} | Subsys={info['subsystem_id_hex']} | "
                            f"Driver={info.get('bound_driver')} | Sources={', '.join(info.get('verification_sources', []))}"
                        )
                        self.log(f"[OK] Module Command: {info.get('linux_modprobe_cmd')}")
                    else:
                        self.log("[WARN] No supported NVIDIA Ada/Ampere/Turing GPU detected on this Linux host.")
                finally:
                    self._set_busy(False)

            self.after(0, _apply)

        threading.Thread(target=_worker, daemon=True).start()

    def action_run_live_cli(self) -> None:
        if self.busy:
            return
        self._set_busy(True)

        def _worker() -> None:
            try:
                linux_backend.run_linux_live_cli_verification(log_fn=self.log)
            except Exception as exc:
                self.log(f"[ERROR] Live CLI verification failed: {exc}")
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_worker, daemon=True).start()

    def action_install_deps(self) -> None:
        if self.busy:
            return
        self._set_busy(True)
        fam = self.hw_info.get("distro_family", "debian")
        krel = self.hw_info.get("kernel_release")
        dep_cmd = linux_backend.get_distro_deps_command(fam, krel)

        def _worker() -> None:
            try:
                self.log("=" * 72)
                self.log(f"[DEPS] Installing Linux kernel headers, DKMS, compiler, and zstd for {fam}...")
                self.log(f"[CMD] {dep_cmd}")
                clean_cmd = dep_cmd[5:].strip() if dep_cmd.startswith("sudo ") else dep_cmd
                rc = linux_backend._run_privileged_shell(clean_cmd, self.log)
                if rc == 0:
                    self.log("[OK] Linux build dependencies installed.")
                else:
                    self.log(f"[WARN] Dependency installation exited with code {rc}.")
            except Exception as exc:
                self.log(f"[ERROR] Failed to install dependencies: {exc}")
            finally:
                self.after(0, lambda: (self._set_busy(False), self.action_rescan_hardware()))

        threading.Thread(target=_worker, daemon=True).start()

    def action_apply_unlock(self) -> None:
        if self.busy:
            return
        self._set_busy(True)

        def _worker() -> None:
            try:
                self.log("=" * 72)
                self.log("[START] Building NVIDIA 610.43.03 firmware assets, compiling gpu_unlock.ko, and executing modprobe...")
                res = linux_backend.build_and_apply_linux_unlock(self.hw_info, log_fn=self.log)
                if res["returncode"] == 0:
                    self.log(f"[SUCCESS] Executed: {res['modprobe_cmd']}")
                    rep = linux_backend.read_linux_kernel_log(expected_bdf=self.var_bdf.get().strip() or None)
                    if rep.get("found"):
                        for key in ("entry_line", "payload_line", "ss0_line", "ss1_line", "flr_line", "final_line"):
                            if rep.get(key):
                                self.log(f"  {rep[key]}")
                else:
                    self.log(f"[INFO] Firmware assets staged at {res['assets_dir']}. Run the printed command with sudo if needed.")
                self.log("=" * 72)
            except Exception as exc:
                self.log(f"[ERROR] Apply unlock failed: {exc}")
            finally:
                self.after(0, lambda: (self._set_busy(False), self.action_rescan_hardware()))

        threading.Thread(target=_worker, daemon=True).start()

    def action_read_dmesg(self) -> None:
        if self.busy:
            return
        self._set_busy(True)
        expected_bdf = self.var_bdf.get().strip() or None

        def _worker() -> None:
            try:
                rep = linux_backend.read_linux_kernel_log(expected_bdf=expected_bdf)
                self.log("=" * 72)
                if not rep.get("found"):
                    self.log(f"[WARN] {rep.get('error')}")
                    return
                self.log(f"[DMESG] BDF={expected_bdf or 'all'} | VERIFIED_UNLOCKED={rep['unlocked']}")
                for key in ("entry_line", "payload_line", "ss0_line", "ss1_line", "flr_line", "final_line"):
                    if rep.get(key):
                        self.log(f"  {rep[key]}")
                self.log("-" * 72)
                self.log(rep["text"])
            except Exception as exc:
                self.log(f"[ERROR] Failed to read dmesg: {exc}")
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_worker, daemon=True).start()

    def action_unload_mod(self) -> None:
        if self.busy:
            return
        self._set_busy(True)

        def _worker() -> None:
            try:
                linux_backend.unload_linux_unlock_module(log_fn=self.log)
            except Exception as exc:
                self.log(f"[ERROR] Failed to unload gpu_unlock.ko: {exc}")
            finally:
                self.after(0, lambda: (self._set_busy(False), self.action_rescan_hardware()))

        threading.Thread(target=_worker, daemon=True).start()

    def action_probe_rm_rates(self) -> None:
        if self.busy:
            return
        gpu_uuid = str(self.hw_info.get("gpu_uuid") or "").strip()
        self._set_busy(True)

        def _worker() -> None:
            try:
                res = linux_backend.query_sm_issue_rates_live(gpu_uuid, log_fn=self.log)
                fmla32 = (res.get("rates") or {}).get("fmla32")
                if fmla32 == 0:
                    self.after(
                        0,
                        lambda: self.lbl_bench_banner.configure(
                            text=f"{self.hw_info.get('gpu_name', 'GPU')} // RM IOCTL 0x20801230: FMLA32 = 0 [FULL RATE UNLOCKED]",
                            fg=FG_GREEN,
                        ),
                    )
                elif fmla32 == 1:
                    self.after(
                        0,
                        lambda: self.lbl_bench_banner.configure(
                            text=f"{self.hw_info.get('gpu_name', 'GPU')} // RM IOCTL 0x20801230: FMLA32 = 1 [STOCK HALF RATE]",
                            fg=FG_AMBER,
                        ),
                    )
            except Exception as exc:
                self.log(f"[ERROR] RM ioctl probe failed: {exc}")
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_worker, daemon=True).start()

    def action_set_max_power(self) -> None:
        if self.busy:
            return
        gpu_uuid = str(self.hw_info.get("gpu_uuid") or "").strip()
        max_w = float(self.hw_info.get("power_max_w") or 0.0)
        min_w = float(self.hw_info.get("power_min_w") or 0.0)
        if not gpu_uuid or max_w <= 0:
            self.log("[ERROR] Cannot set power limit: no verified GPU UUID or VBIOS max power constraint available.")
            return
        self._set_busy(True)

        def _worker() -> None:
            try:
                res = core_detector.set_gpu_power_limit(gpu_uuid, max_w, min_w, max_w, log_fn=self.log)
                self.log(
                    f"[OK] Power limit verified via hardware readback: {res['readback_watts']} W "
                    f"(requested {res['target_watts']} W) for {res['gpu_uuid']}"
                )
            except Exception as exc:
                self.log(f"[ERROR] Failed to set power limit: {exc}")
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_worker, daemon=True).start()

    def action_run_benchmark(self) -> None:
        if self.busy:
            return
        self._set_busy(True)
        target_bdf = self.hw_info.get("pci_bdf") or None
        target_uuid = self.hw_info.get("gpu_uuid") or None

        def _worker() -> None:
            try:
                self.log("[BENCH] Starting CUDA PTX JIT Tensor Core throughput benchmark...")
                res = tensor_benchmark.run_tensor_benchmark(
                    log_fn=self.log,
                    target_bdf=target_bdf,
                    target_uuid=target_uuid,
                )
                self.last_bench_result = res
                if res.get("correctness_verified"):
                    self.bench_history = tensor_benchmark.record_benchmark_run(res)
                self.after(0, self._refresh_benchmark_table)
                self.log(f"[BENCH] Completed: {res['status_text']} (FP16/FP32 ratio = {res['f16_to_f32_ratio']})")
            except Exception as exc:
                self.log(f"[ERROR] Benchmark failed: {exc}")
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_worker, daemon=True).start()

    def action_save_slot(self, slot: str) -> None:
        if not self.last_bench_result:
            self.log("[WARN] Run the live benchmark first before saving a snapshot.")
            return
        t = I18N_LINUX[self.lang]
        uuid_key = str(self.last_bench_result.get("gpu_uuid") or self.last_bench_result.get("pci_bdf") or "").strip()
        existing_per_uuid = ((self.bench_history.get("baselines_by_uuid") or {}).get(uuid_key) or {}).get(slot)
        if existing_per_uuid is not None:
            if not messagebox.askyesno(t["confirm_overwrite_title"], t["confirm_overwrite_msg"].format(slot=slot.upper())):
                return
        self.bench_history = tensor_benchmark.save_benchmark_slot(slot, self.last_bench_result, overwrite=True)
        self._refresh_benchmark_table()
        self.log(f"[OK] Saved current benchmark snapshot to slot '{slot.upper()}' for {uuid_key}.")

    def _snapshot_matches_active_gpu(self, snap: dict[str, Any] | None, active_uuid: str, active_bdf: str) -> bool:
        if not isinstance(snap, dict):
            return False
        s_uuid = str(snap.get("gpu_uuid") or "").strip()
        s_bdf = str(snap.get("pci_bdf") or "").strip().lower()
        if active_uuid and s_uuid:
            return s_uuid.lower() == active_uuid.lower()
        if active_bdf and s_bdf:
            return s_bdf == active_bdf.lower()
        return not active_uuid and not active_bdf

    def _refresh_benchmark_table(self) -> None:
        for item in self.tree_bench.get_children():
            self.tree_bench.delete(item)

        active_uuid = str((self.last_bench_result or {}).get("gpu_uuid") or self.hw_info.get("gpu_uuid") or "").strip()
        active_bdf = str((self.last_bench_result or {}).get("pci_bdf") or self.hw_info.get("pci_bdf") or "").strip()
        lookup_key = active_uuid or active_bdf

        per_uuid = (self.bench_history.get("baselines_by_uuid") or {}).get(lookup_key) if lookup_key else None
        before_snap = (per_uuid or {}).get("before")
        after_snap = (per_uuid or {}).get("after")

        if before_snap is None and self._snapshot_matches_active_gpu(self.bench_history.get("before"), active_uuid, active_bdf):
            before_snap = self.bench_history.get("before")
        if after_snap is None and self._snapshot_matches_active_gpu(self.bench_history.get("after"), active_uuid, active_bdf):
            after_snap = self.bench_history.get("after")

        before_metrics = (before_snap or {}).get("metrics") or {}
        after_metrics = (after_snap or {}).get("metrics") or {}

        curr_snap = self.last_bench_result if self._snapshot_matches_active_gpu(self.last_bench_result, active_uuid, active_bdf) else None
        curr_metrics = (curr_snap or {}).get("metrics") or {}

        if curr_snap:
            status_code = curr_snap.get("status", "UNKNOWN")
            color = FG_GREEN if status_code == "MEASURED_UNLOCKED" else (FG_AMBER if status_code == "MEASURED_THROTTLED" else FG_RED)
            self.lbl_bench_banner.configure(
                text=f"{curr_snap['gpu_name']} // {curr_snap['status_text']} [Ratio: {curr_snap['f16_to_f32_ratio']}]",
                fg=color,
            )

        rows = [
            ("f16_acc_f16", "FP16 -> FP16 (FMLA16)", "FMLA16", "TFLOP/s"),
            ("f16_acc_f32", "FP16 -> FP32 (FMLA32)", "FMLA32", "TFLOP/s"),
            ("bf16_acc_f32", "BF16 -> FP32 (FMLA32)", "FMLA32", "TFLOP/s"),
            ("tf32_acc_f32", "TF32 -> FP32 (FMLA32)", "FMLA32", "TFLOP/s"),
            ("fp8_e4m3_acc_f32", "FP8 E4M3 -> FP32 (FMLA32)", "FMLA32", "TFLOP/s"),
            ("s8_acc_s32", "INT8 -> INT32 (IMLA1)", "IMLA1", "TOP/s"),
            ("scalar_ffma_f32", "Scalar FP32 (CUDA FFMA)", "FFMA", "TFLOP/s"),
        ]
        for key, default_label, fuse, unit in rows:
            b_val = (before_metrics.get(key) or {}).get("median") or (before_metrics.get(key) or {}).get("best")
            a_val = (after_metrics.get(key) or {}).get("median") or (after_metrics.get(key) or {}).get("best")
            c_val = (curr_metrics.get(key) or {}).get("median") or (curr_metrics.get(key) or {}).get("best")

            b_str = f"{b_val:.2f} {unit}" if isinstance(b_val, (int, float)) else "—"
            a_str = f"{a_val:.2f} {unit}" if isinstance(a_val, (int, float)) else "—"
            c_str = f"{c_val:.2f} {unit}" if isinstance(c_val, (int, float)) else "—"

            gain_str = "—"
            ref_after = a_val if isinstance(a_val, (int, float)) else c_val
            if isinstance(b_val, (int, float)) and isinstance(ref_after, (int, float)) and b_val > 0:
                mult = ref_after / b_val
                pct = (mult - 1.0) * 100.0
                gain_str = f"{mult:.2f}x ({pct:+.1f}%)"

            self.tree_bench.insert("", "end", values=(default_label, fuse, b_str, a_str, c_str, gain_str))


if __name__ == "__main__":
    enforce_linux_os_guard()
    app = LinuxUnlockApp()
    app.mainloop()
