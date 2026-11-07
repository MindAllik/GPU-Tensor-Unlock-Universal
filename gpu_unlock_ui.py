#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Universal Console-Styled Desktop GUI for NVIDIA GPU Tensor Unlock (Windows 10 / 11)
Supports 4 languages: English (EN), Russian (RU), Chinese (ZH), and Hindi (HI)."""

from __future__ import annotations

import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

import core_detector
import os
import platform
from i18n_strings import I18N, OS_MISMATCH_MESSAGES
import tensor_benchmark

# Strict Pure Grayscale Console / Industrial Terminal Palette (Zero Blue Tint)
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


class UniversalUnlockApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.lang = "RU"
        self.title(I18N[self.lang]["app_title"])
        self.geometry("1280x880")
        self.minsize(1100, 780)
        self.configure(bg=BG_MAIN)

        self.hw_info: dict[str, Any] = {}
        self.usb_drives: list[dict[str, Any]] = []
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
            t = I18N[self.lang]
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
            self.btn_refresh_usb,
            self.btn_build_usb,
            self.btn_export_folder,
            self.btn_read_report,
            self.btn_cold_shutdown,
            self.btn_run_bench,
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

    def _make_btn(self, parent: tk.Widget, command: Any, accent: bool = False, danger: bool = False) -> tk.Button:
        bg = BTN_ACCENT if accent else ("#6e1c1c" if danger else BTN_BG)
        fg = "#ffffff" if (accent or danger) else FG_PRIMARY
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

        # --- LEFT COLUMN: [01] HARDWARE, [02] DEPENDENCIES, [03] USB BUILDER ---
        self.pnl_hw, self.hdr_hw = self._make_panel(left_col)
        self.pnl_hw.pack(fill="x", pady=(0, 4))

        hw_grid = tk.Frame(self.pnl_hw, bg=BG_PANEL)
        hw_grid.pack(fill="x")
        hw_grid.columnconfigure(1, weight=1)

        self.var_gpu_name = tk.StringVar()
        self.var_die = tk.StringVar(value="UNSUPPORTED")
        self.var_board_id = tk.StringVar()
        self.var_subsys_id = tk.StringVar()
        self.var_bus = tk.StringVar()
        self.var_chip_id = tk.StringVar()
        self.var_vram_min = tk.StringVar()
        self.var_vram_max = tk.StringVar()
        self.var_esp_guid = tk.StringVar()
        self.var_prom_sha = tk.StringVar(value="AUTO")
        self.var_cli_cmd = tk.StringVar(value=core_detector.get_live_cli_verification_command())

        self.hw_labels: dict[str, tk.Label] = {}
        rows_spec = [
            ("lbl_gpu", self.var_gpu_name, "gpu_combo"),
            ("lbl_die", self.var_die, "die_locked"),
            ("lbl_pci", self.var_board_id, self.var_subsys_id),
            ("lbl_bus", self.var_bus, self.var_chip_id),
            ("lbl_vram", self.var_vram_min, self.var_vram_max),
            ("lbl_esp", self.var_esp_guid, None),
            ("lbl_prom_mode", self.var_prom_sha, None),
            ("lbl_cli_cmd", self.var_cli_cmd, "cli_preview"),
        ]
        for r_idx, (lkey, var1, var2) in enumerate(rows_spec):
            lbl = tk.Label(hw_grid, text="", bg=BG_PANEL, fg=FG_MUTED, font=("Consolas", 9), anchor="w")
            lbl.grid(row=r_idx, column=0, sticky="w", pady=1, padx=(0, 8))
            self.hw_labels[lkey] = lbl

            row_f = tk.Frame(hw_grid, bg=BG_PANEL)
            row_f.grid(row=r_idx, column=1, sticky="ew", pady=1)
            if var2 == "gpu_combo":
                # Readonly Combobox so user can switch between real detected GPUs on multi-GPU systems,
                # but cannot type arbitrary fake GPU names or IDs
                self.cb_gpu = ttk.Combobox(row_f, textvariable=var1, state="readonly", style="Console.TCombobox")
                self.cb_gpu.pack(side="left", fill="x", expand=True)
                self.cb_gpu.bind("<<ComboboxSelected>>", self._on_gpu_selected)
            elif var2 == "die_locked":
                # Locked readonly Entry for Die so user cannot mismatch PCI ID and Die!
                e_die = self._make_readonly_entry(row_f, var1, width=12, fg=FG_CYAN)
                e_die.pack(side="left")
                self.lbl_arch_tag = tk.Label(row_f, text="NOT DETECTED", bg=BG_PANEL, fg=FG_AMBER, font=("Consolas", 9, "bold"))
                self.lbl_arch_tag.pack(side="left", padx=8)
            elif var2 == "cli_preview":
                # Transparent CLI command preview field (readonly so user can select/copy and see exact command)
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

        # [02] DEPENDENCIES
        self.pnl_deps, self.hdr_deps = self._make_panel(left_col)
        self.pnl_deps.pack(fill="x", pady=(0, 4))

        deps_grid = tk.Frame(self.pnl_deps, bg=BG_PANEL)
        deps_grid.pack(fill="x")
        deps_grid.columnconfigure(1, weight=1)

        self.lbl_llvm_title = tk.Label(deps_grid, text="", bg=BG_PANEL, fg=FG_MUTED, font=("Consolas", 9), anchor="w")
        self.lbl_llvm_title.grid(row=0, column=0, sticky="w", pady=1, padx=(0, 8))
        self.lbl_llvm_val = tk.Label(deps_grid, text="...", bg=BG_PANEL, fg=FG_GREEN, font=("Consolas", 9, "bold"), anchor="w")
        self.lbl_llvm_val.grid(row=0, column=1, sticky="w", pady=1)

        self.lbl_zst_title = tk.Label(deps_grid, text="", bg=BG_PANEL, fg=FG_MUTED, font=("Consolas", 9), anchor="w")
        self.lbl_zst_title.grid(row=1, column=0, sticky="w", pady=1, padx=(0, 8))
        self.lbl_zst_val = tk.Label(deps_grid, text="...", bg=BG_PANEL, fg=FG_GREEN, font=("Consolas", 9, "bold"), anchor="w")
        self.lbl_zst_val.grid(row=1, column=1, sticky="w", pady=1)

        self.btn_install_deps = self._make_btn(self.pnl_deps, self.action_install_deps)
        self.btn_install_deps.pack(fill="x", pady=(4, 0))

        # [03] BOOTABLE USB BUILDER
        self.pnl_usb, self.hdr_usb = self._make_panel(left_col)
        self.pnl_usb.pack(fill="both", expand=True)

        self.lbl_usb_drive = tk.Label(self.pnl_usb, text="", bg=BG_PANEL, fg=FG_PRIMARY, font=("Consolas", 9, "bold"), anchor="w")
        self.lbl_usb_drive.pack(fill="x", pady=(0, 1))
        self.lbl_usb_note = tk.Label(self.pnl_usb, text="", bg=BG_PANEL, fg=FG_AMBER, font=("Consolas", 8), anchor="w", wraplength=540, justify="left")
        self.lbl_usb_note.pack(fill="x", pady=(0, 3))

        usb_sel_row = tk.Frame(self.pnl_usb, bg=BG_PANEL)
        usb_sel_row.pack(fill="x", pady=(0, 4))
        self.var_usb_target = tk.StringVar(value="")
        self.cb_usb = ttk.Combobox(usb_sel_row, textvariable=self.var_usb_target, state="readonly", style="Console.TCombobox", font=("Consolas", 9))
        self.cb_usb.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self.btn_refresh_usb = self._make_btn(usb_sel_row, self.action_refresh_usb)
        self.btn_refresh_usb.pack(side="left", padx=(2, 0))

        build_row = tk.Frame(self.pnl_usb, bg=BG_PANEL)
        build_row.pack(fill="x", pady=(1, 3))
        build_row.columnconfigure(0, weight=3)
        build_row.columnconfigure(1, weight=2)
        self.btn_build_usb = self._make_btn(build_row, self.action_build_usb, accent=True)
        self.btn_build_usb.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.btn_export_folder = self._make_btn(build_row, self.action_export_folder)
        self.btn_export_folder.grid(row=0, column=1, sticky="ew", padx=(3, 0))

        usb_sub_row = tk.Frame(self.pnl_usb, bg=BG_PANEL)
        usb_sub_row.pack(fill="x")
        usb_sub_row.columnconfigure(0, weight=1)
        usb_sub_row.columnconfigure(1, weight=1)
        self.btn_read_report = self._make_btn(usb_sub_row, self.action_read_report)
        self.btn_read_report.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.btn_cold_shutdown = self._make_btn(usb_sub_row, self.action_cold_shutdown, danger=True)
        self.btn_cold_shutdown.grid(row=0, column=1, sticky="ew", padx=(3, 0))

        # --- RIGHT COLUMN: [04] TENSOR CORE BENCHMARK ---
        self.pnl_bench, self.hdr_bench = self._make_panel(right_col)
        self.pnl_bench.pack(fill="both", expand=True)

        self.lbl_bench_banner = tk.Label(
            self.pnl_bench,
            text="FMLA32 STATUS: READY TO MEASURE",
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

        # Layout-independent Ctrl+C / Ctrl+A bindings (works in both RU and EN Windows keyboard layouts)
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
        t = I18N[code]
        self.title(t["app_title"])
        self.lbl_title.configure(text=t["app_title"])
        self.lbl_subtitle.configure(text=t["subtitle"])
        self.lbl_issues_note.configure(text=t["issues_note"])
        self.lbl_lang.configure(text=t["lang_label"])

        for c, btn in self.lang_btns.items():
            btn.configure(bg=BTN_ACCENT if c == code else BTN_BG, fg="#ffffff" if c == code else FG_PRIMARY)

        self.hdr_hw.configure(text=t["sec_hw"])
        self.hdr_deps.configure(text=t["sec_deps"])
        self.hdr_usb.configure(text=t["sec_usb"])
        self.hdr_bench.configure(text=t["sec_bench"])
        self.hdr_console.configure(text=t["sec_console"])
        self.lbl_drag_hint.configure(text=t["drag_console_hint"])
        self.btn_copy_log.configure(text=t["btn_copy_log"])
        self.log_menu.delete(0, "end")
        self.log_menu.add_command(label=t["ctx_copy_sel"], command=self.action_copy_selected_log)
        self.log_menu.add_command(label=t["ctx_copy_all"], command=self.action_copy_all_log)
        self.log_menu.add_separator()
        self.log_menu.add_command(label=t["ctx_select_all"], command=self.action_select_all_log)

        for lkey, lbl in self.hw_labels.items():
            lbl.configure(text=t[lkey])

        self.btn_rescan.configure(text=t["btn_rescan"])
        self.btn_live_cli.configure(text=t["btn_live_cli"])
        self.lbl_llvm_title.configure(text=t["lbl_llvm"])
        self.lbl_zst_title.configure(text=t["lbl_zst"])
        self.btn_install_deps.configure(text=t["btn_install_deps"])

        self.lbl_usb_drive.configure(text=t["lbl_usb_drive"])
        self.lbl_usb_note.configure(text=t["usb_fat32_note"])
        self.btn_refresh_usb.configure(text=t["btn_refresh_usb"])
        self.btn_build_usb.configure(text=t["btn_build_usb"])
        self.btn_export_folder.configure(text=t["btn_export_folder"])
        self.btn_read_report.configure(text=t["btn_read_report"])
        self.btn_cold_shutdown.configure(text=t["btn_cold_shutdown"])

        self.btn_run_bench.configure(text=t["btn_run_bench"])
        self.btn_save_before.configure(text=t["btn_save_before"])
        self.btn_save_after.configure(text=t["btn_save_after"])
        self.btn_max_pl.configure(text=t["btn_max_pl"])

        self.tree_bench.heading("inst", text=t["col_inst"])
        self.tree_bench.heading("fuse", text=t["col_fuse"])
        self.tree_bench.heading("before", text=t["col_before"])
        self.tree_bench.heading("after", text=t["col_after"])
        self.tree_bench.heading("current", text=t["col_current"])
        self.tree_bench.heading("gain", text=t["col_gain"])
        self._refresh_deps_labels()

    def _refresh_deps_labels(self) -> None:
        if not self.hw_info:
            return
        t = I18N[self.lang]
        info = self.hw_info
        llvm_ok = bool(info.get("clang_path") and info.get("lld_path"))
        self.lbl_llvm_val.configure(
            text=f"{t['status_ok']} ({Path(info['clang_path']).parent})" if llvm_ok else t["status_missing"],
            fg=FG_GREEN if llvm_ok else FG_AMBER,
        )
        zst_ok = bool(info.get("zst_ok"))
        self.lbl_zst_val.configure(
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

    def action_select_all_log(self) -> str:
        self.txt_log.tag_add("sel", "1.0", "end-1c")
        self.txt_log.mark_set("insert", "1.0")
        self.txt_log.see("insert")
        return "break"

    def _on_log_ctrl_key(self, event: tk.Event) -> str | None:
        # Windows VK_C = 67, VK_A = 65, VK_INSERT = 45 (works regardless of RU/EN keyboard layout)
        kc = getattr(event, "keycode", 0)
        ks = (getattr(event, "keysym", "") or "").lower()
        if kc == 67 or ks in ("c", "cyrillic_es", "insert"):
            return self.action_copy_selected_log()
        if kc == 65 or ks in ("a", "cyrillic_ef"):
            return self.action_select_all_log()
        return None

    def _on_log_keypress(self, event: tk.Event) -> str | None:
        # Allow Ctrl shortcuts and navigation keys, block accidental typing/editing in log
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
                # Copy all GPU fields including vbios_version and verification_sources
                for k in (
                    "gpu_name", "gpu_uuid", "pci_bdf", "board_id_hex", "subsystem_id_hex",
                    "segment_hex", "bus_hex", "device_hex", "function_hex", "die_name",
                    "chip_id_hex", "is_ada", "support_tier", "vram_mib", "vram_min_hex",
                    "vram_max_hex", "vbios_version", "power_default_w", "power_min_w",
                    "power_max_w", "verification_sources",
                ):
                    if k in g:
                        self.hw_info[k] = g[k]
                self.var_die.set(g["die_name"])
                self.var_board_id.set(g["board_id_hex"])
                self.var_subsys_id.set(g["subsystem_id_hex"])
                self.var_bus.set(g["bus_hex"])
                self.var_chip_id.set(g["chip_id_hex"])
                self.var_vram_min.set(g["vram_min_hex"])
                self.var_vram_max.set(g["vram_max_hex"])
                self._on_die_changed()
                self._update_power_btn_state()
                self._refresh_benchmark_table()
                break

    def _on_die_changed(self, _event: Any = None) -> None:
        die = self.var_die.get()
        tier = self.hw_info.get("support_tier", "unsupported")
        if die in core_detector.CHIP_BY_PMC:
            chip_id, is_ada = core_detector.CHIP_BY_PMC[die]
            self.var_chip_id.set(f"0x{chip_id:08x}")
            arch_str = "Turing TU10x (2-PLM)" if die.startswith("TU10") else ("Ada Lovelace (4-PLM)" if is_ada else "Ampere GA10x (1-PLM)")
            self.lbl_arch_tag.configure(
                text=f"{arch_str} [{tier}]",
                fg=FG_GREEN if tier == "hardware_tested" else (FG_CYAN if tier == "experimental_simulated" else FG_AMBER),
            )
        else:
            self.lbl_arch_tag.configure(text=f"UNSUPPORTED [{tier}]", fg=FG_RED)

    def action_run_live_cli(self) -> None:
        """Run the transparent live CLI verification command and print raw + parsed numbers in the console."""
        if self.busy:
            return
        self._set_busy(True)

        def _worker() -> None:
            try:
                core_detector.run_live_cli_verification(log_fn=self.log)
            except Exception as exc:
                self.log(f"[ERROR] Live CLI verification failed: {exc}")
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_worker, daemon=True).start()

    def action_rescan_hardware(self) -> None:
        if self.busy:
            return
        self._set_busy(True)
        self.log("[SCAN] Detecting GPU hardware, PCI topology, BitLocker/SecureBoot, and Windows ESP...")

        # Full try/except/finally around background detection so busy is always cleared
        def _worker() -> None:
            info: dict[str, Any] = {}
            drives: list[dict[str, Any]] = []
            err_msg: str | None = None
            try:
                info = core_detector.detect_host_environment()
                drives = core_detector.list_usb_drives()
            except Exception as exc:
                err_msg = str(exc)

            def _apply() -> None:
                try:
                    if err_msg:
                        self.log(f"[ERROR] Hardware scan error: {err_msg}")
                        return
                    self.hw_info = info
                    self.usb_drives = drives
                    gpus = info.get("gpus") or []
                    if gpus:
                        gpu_labels = [f"[{g['index']}] {g['gpu_name']} ({g['pci_bdf']})" for g in gpus]
                        self.cb_gpu["values"] = gpu_labels
                    else:
                        self.cb_gpu["values"] = []

                    self.var_gpu_name.set(info["gpu_name"])
                    self.var_die.set(info["die_name"])
                    self.var_board_id.set(info["board_id_hex"])
                    self.var_subsys_id.set(info["subsystem_id_hex"])
                    self.var_bus.set(info["bus_hex"])
                    self.var_chip_id.set(info["chip_id_hex"])
                    self.var_vram_min.set(info["vram_min_hex"])
                    self.var_vram_max.set(info["vram_max_hex"])
                    self.var_esp_guid.set(info["esp_guid"])
                    self._on_die_changed()
                    self._refresh_benchmark_table()

                    self._refresh_deps_labels()

                    if self.usb_drives:
                        values = [d["display"] for d in self.usb_drives]
                        self.cb_usb["values"] = values
                        self.var_usb_target.set(values[0])
                    else:
                        self.cb_usb["values"] = []
                        self.var_usb_target.set("")

                    if info["gpu_detected"]:
                        self.log(
                            f"[OK] Detected: {info['gpu_name']} | Die={info['die_name']} ({info['support_tier']}) | "
                            f"BDF={info['pci_bdf']} | PCI={info['board_id_hex']} | Subsys={info['subsystem_id_hex']} | "
                            f"VRAM={info['vram_mib']} MiB | ESP={info['esp_guid']} ({info['esp_disk_part']})"
                        )
                    else:
                        self.log("[WARN] No supported NVIDIA Ada/Ampere/Turing GPU detected on this host.")
                    if info.get("esp_ambiguous"):
                        self.log("[WARN] Multiple EFI System Partitions detected; verify the selected ESP GUID before building.")
                    if info.get("bitlocker_protection_on"):
                        self.log("[WARN] BitLocker is active on C:. Suspend BitLocker or keep your 48-digit recovery key ready before changing Secure Boot.")
                finally:
                    self._set_busy(False)

            self.after(0, _apply)

        threading.Thread(target=_worker, daemon=True).start()

    def action_refresh_usb(self) -> None:
        if self.busy:
            return
        self._set_busy(True)

        def _worker() -> None:
            drives = core_detector.list_usb_drives()

            def _apply() -> None:
                try:
                    self.usb_drives = drives
                    if self.usb_drives:
                        values = [d["display"] for d in self.usb_drives]
                        self.cb_usb["values"] = values
                        self.var_usb_target.set(values[0])
                        summary = ", ".join(f"{d['letter']} ({d['filesystem']}, {d['size_gb']} GB)" for d in self.usb_drives)
                        self.log(f"[USB] Detected {len(self.usb_drives)} USB/removable drive(s): {summary}")
                        for d in self.usb_drives:
                            if not d.get("is_fat32"):
                                self.log(f"[WARN] USB drive {d['letter']} is formatted as {d['filesystem']} — format it as FAT32 before building.")
                    else:
                        self.cb_usb["values"] = []
                        self.var_usb_target.set("")
                        self.log("[WARN] No removable USB / FAT32 drives detected. Connect a FAT32 USB flash drive with a drive letter (e.g. D:\\) and click REFRESH DRIVES.")
                finally:
                    self._set_busy(False)

            self.after(0, _apply)

        threading.Thread(target=_worker, daemon=True).start()

    def _get_clean_usb_path(self) -> str:
        raw = self.var_usb_target.get().strip()
        if "[" in raw:
            raw = raw.split("[", 1)[0].strip()
        return raw

    def _collect_profile_cfg(self) -> dict[str, Any]:
        die = self.var_die.get().strip()
        _, is_ada = core_detector.CHIP_BY_PMC.get(die, (0, False))
        return {
            "gpu_name": self.var_gpu_name.get().strip(),
            "die_name": die,
            "is_ada": is_ada,
            "board_id_hex": self.var_board_id.get().strip(),
            "subsystem_id_hex": self.var_subsys_id.get().strip(),
            "segment_hex": self.hw_info.get("segment_hex", "0x0"),
            "bus_hex": self.var_bus.get().strip(),
            "device_hex": self.hw_info.get("device_hex", "0x0"),
            "function_hex": self.hw_info.get("function_hex", "0x0"),
            "chip_id_hex": self.var_chip_id.get().strip(),
            "vram_min_hex": self.var_vram_min.get().strip(),
            "vram_max_hex": self.var_vram_max.get().strip(),
            "esp_guid": self.var_esp_guid.get().strip(),
            "esp_part_num": self.hw_info.get("esp_part_num", 0),
            "prom_sha256": self.var_prom_sha.get().strip() or "AUTO",
            "rom_sha256": "AUTO",
            "unattended_autofire": False,
        }

    def action_install_deps(self) -> None:
        if self.busy:
            return
        self._set_busy(True)

        # Check return codes of pip and winget and verify installation before logging [OK]
        def _worker() -> None:
            try:
                self.log("[INSTALL] Installing Python 'zstandard' module via pip...")
                r_pip = subprocess.run([sys.executable, "-m", "pip", "install", "zstandard"], capture_output=True, text=True)
                if r_pip.returncode != 0:
                    self.log(f"[WARN] pip install zstandard exited with code {r_pip.returncode}: {(r_pip.stderr or r_pip.stdout).strip()}")
                else:
                    self.log("[OK] python-zstandard installed.")

                if not (core_detector.find_llvm_tool("clang") and core_detector.find_llvm_tool("lld-link")):
                    self.log("[INSTALL] Installing LLVM (clang + lld-link) via winget...")
                    r_wg = subprocess.run(
                        ["winget", "install", "-e", "--id", "LLVM.LLVM", "--accept-package-agreements", "--accept-source-agreements"],
                        capture_output=True,
                        text=True,
                    )
                    if r_wg.returncode != 0:
                        self.log(f"[ERROR] winget LLVM install exited with code {r_wg.returncode}: {(r_wg.stderr or r_wg.stdout).strip()}")
                    else:
                        self.log("[OK] LLVM installed via winget.")
            except Exception as exc:
                self.log(f"[ERROR] Dependency install error: {exc}")
            finally:
                self.after(0, lambda: (self._set_busy(False), self.action_rescan_hardware()))

        threading.Thread(target=_worker, daemon=True).start()

    def action_build_usb(self) -> None:
        if self.busy:
            return
        usb_path = self._get_clean_usb_path()
        if not usb_path or usb_path.upper().startswith("C:"):
            messagebox.showerror("Invalid Drive", I18N[self.lang]["err_no_usb"])
            return
        self._run_stage_job(usb_path, target_mode="usb")

    def action_export_folder(self) -> None:
        if self.busy:
            return
        folder = filedialog.askdirectory(title=I18N[self.lang]["btn_export_folder"])
        if not folder:
            return
        self._run_stage_job(folder, target_mode="export")

    def _run_stage_job(self, target_path: str, target_mode: str) -> None:
        cfg = self._collect_profile_cfg()
        try:
            validated_prof = core_detector.validate_target_profile(cfg)
            if not cfg.get("esp_guid") and validated_prof.get("esp_guid"):
                cfg["esp_guid"] = validated_prof["esp_guid"]
                self.var_esp_guid.set(validated_prof["esp_guid"])
        except Exception as exc:
            messagebox.showerror("Invalid Profile", str(exc))
            self.log(f"[ERROR] Profile validation failed: {exc}")
            return

        self._set_busy(True)

        def _worker() -> None:
            try:
                self.log("=" * 72)
                self.log(f"[START] Building UEFI bundle ({target_mode.upper()}) at {target_path} ...")
                staged = core_detector.build_and_stage_usb(cfg, target_path, log_fn=self.log, target_mode=target_mode)
                self.log(f"[SUCCESS] Bundle ready at {staged} (\\EFI\\Boot\\BOOTX64.EFI + \\GPU-UNLOCK\\ASSETS)")
                self.log("=" * 72)
            except Exception as exc:
                self.log(f"[ERROR] Build/stage failed: {exc}")
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_worker, daemon=True).start()

    def action_read_report(self) -> None:
        if self.busy:
            return
        usb_path = self._get_clean_usb_path()
        if not usb_path:
            folder = filedialog.askdirectory(title=I18N[self.lang]["btn_read_report"])
            if not folder:
                return
            usb_path = folder
        expected_prof = {
            "board_id_hex": self.var_board_id.get().strip(),
            "subsystem_id_hex": self.var_subsys_id.get().strip(),
        }
        self._set_busy(True)

        def _worker() -> None:
            try:
                rep = core_detector.read_latest_usb_report(usb_path, expected_profile=expected_prof)
                if not rep.get("found"):
                    self.log(f"[WARN] {rep.get('error')}")
                    return
                self.log("=" * 72)
                self.log(
                    f"[REPORT] Loaded {rep['path']} ({rep['run_name']}, all_runs={rep.get('runs')}) | "
                    f"PROFILE_MATCHED={rep.get('profile_matched')} | VERIFIED_SUCCESS={rep['success']}"
                )
                if rep.get("ss0_line"):
                    self.log(f"  {rep['ss0_line']}")
                if rep.get("ss1_line"):
                    self.log(f"  {rep['ss1_line']}")
                if rep.get("final_line"):
                    self.log(f"  {rep['final_line']}")
                self.log("-" * 72)
                self.log(rep["text"])
            except Exception as exc:
                self.log(f"[ERROR] Failed to read report: {exc}")
            finally:
                self.after(0, lambda: self._set_busy(False))

        threading.Thread(target=_worker, daemon=True).start()

    def action_cold_shutdown(self) -> None:
        if self.busy:
            return
        t = I18N[self.lang]
        if messagebox.askyesno(t["confirm_shutdown_title"], t["confirm_shutdown_msg"]):
            subprocess.Popen(["shutdown", "/s", "/t", "5"])

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
        t = I18N[self.lang]
        uuid_key = str(self.last_bench_result.get("gpu_uuid") or self.last_bench_result.get("pci_bdf") or "").strip()
        existing_per_uuid = ((self.bench_history.get("baselines_by_uuid") or {}).get(uuid_key) or {}).get(slot)
        if existing_per_uuid is not None:
            if not messagebox.askyesno(t["confirm_overwrite_title"], t["confirm_overwrite_msg"].format(slot=slot.upper())):
                return
        self.bench_history = tensor_benchmark.save_benchmark_slot(slot, self.last_bench_result, overwrite=True)
        self._refresh_benchmark_table()
        self.log(f"[OK] Saved current benchmark snapshot to slot '{slot.upper()}' for {uuid_key}.")

    def _snapshot_matches_active_gpu(self, snap: dict[str, Any] | None, active_uuid: str, active_bdf: str) -> bool:
        """Ensure a baseline snapshot belongs to the active GPU before displaying or computing speedup."""
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


def enforce_windows_os_guard() -> None:
    """Block execution of Windows_Launch_UI on Linux/macOS or under Wine with a clear error message."""
    is_wine = bool(os.environ.get("WINEPREFIX") or os.environ.get("WINELOADERNOEXEC"))
    if not sys.platform.startswith("win") or is_wine:
        plat_str = "Wine on Linux" if is_wine else f"{platform.system()} {platform.release()} ({sys.platform})"
        info = OS_MISMATCH_MESSAGES["win_on_non_win"]
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


if __name__ == "__main__":
    enforce_windows_os_guard()
    app = UniversalUnlockApp()
    app.mainloop()
