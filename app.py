#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地文件批量重命名工具 —— 原生 GUI 版（tkinter，独立运行，不开浏览器）
改名引擎复用 engine.py，与浏览器服务版共用同一套逻辑。
打包: pyinstaller --noconsole --onefile --name FileRenamerGUI app.py
"""

import os
import sys
import json
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from engine import (scan_directory, build_preview, detect_conflicts,
                    apply_rename, undo_rename, undo_store_dir)


# ===================== 规则定义（与 engine.apply_rule 参数一致） =====================
RULE_DEFS = {
    "prefix":   {"label": "加前缀", "params": [
        {"k": "text", "t": "text", "label": "文字", "ph": "如 IMG_"}]},
    "suffix":   {"label": "加后缀", "params": [
        {"k": "text", "t": "text", "label": "文字", "ph": "如 _final"}]},
    "number":   {"label": "序号编号", "params": [
        {"k": "start", "t": "int", "label": "起始", "def": 1},
        {"k": "step", "t": "int", "label": "步长", "def": 1},
        {"k": "pad", "t": "int", "label": "补零位数", "def": 3},
        {"k": "pos", "t": "select", "label": "位置",
         "options": [("prefix", "前缀"), ("suffix", "后缀"), ("replace", "替换原名"), ("template", "模板")], "def": "prefix"},
        {"k": "template", "t": "text", "label": "模板({n}序号 {name}原名)", "ph": "{n}_{name}", "show_if": ("pos", "template")}]},
    "date":     {"label": "日期戳", "params": [
        {"k": "source", "t": "select", "label": "时间来源", "options": [("mtime", "修改时间"), ("ctime", "创建时间")], "def": "mtime"},
        {"k": "format", "t": "text", "label": "格式", "ph": "%Y%m%d 或 %Y-%m-%d", "def": "%Y%m%d"},
        {"k": "pos", "t": "select", "label": "位置", "options": [("prefix", "前缀"), ("suffix", "后缀")], "def": "prefix"}]},
    "ext":      {"label": "改扩展名", "params": [
        {"k": "ext", "t": "text", "label": "新扩展名(可带点)", "ph": "png"}]},
    "random":   {"label": "随机/UUID命名", "params": [
        {"k": "mode", "t": "select", "label": "类型", "options": [("uuid", "UUID"), ("hex", "十六进制"), ("alnum", "字母数字")], "def": "uuid"},
        {"k": "len", "t": "int", "label": "长度(hex/alnum)", "def": 8},
        {"k": "pos", "t": "select", "label": "位置", "options": [("replace", "替换原名"), ("prefix", "前缀"), ("suffix", "后缀")], "def": "replace"}]},
    "replace":  {"label": "查找替换", "params": [
        {"k": "find", "t": "text", "label": "查找", "ph": "要找的文字"},
        {"k": "repl", "t": "text", "label": "替换为", "ph": "新文字"},
        {"k": "regex", "t": "check", "label": "正则"},
        {"k": "casesens", "t": "check", "label": "区分大小写"},
        {"k": "scope", "t": "select", "label": "作用域", "options": [("full", "含扩展名"), ("name", "仅文件名")], "def": "full"}]},
    "case":     {"label": "大小写转换", "params": [
        {"k": "mode", "t": "select", "label": "方式", "options": [("upper", "全大写"), ("lower", "全小写"), ("title", "首字母大写"), ("capitalize", "句首大写"), ("swapcase", "反转")], "def": "upper"},
        {"k": "scope", "t": "select", "label": "作用域", "options": [("full", "含扩展名"), ("name", "仅文件名")], "def": "full"}]},
    "strip":    {"label": "去除字符", "params": [
        {"k": "mode", "t": "select", "label": "方式", "options": [("spaces", "两端空格"), ("leading", "左侧"), ("trailing", "右侧"), ("both", "两端指定字符"), ("all-spaces", "所有空白")], "def": "spaces"},
        {"k": "chars", "t": "text", "label": "字符(两端指定时用)", "ph": "_-", "show_if": ("mode", "both")}]},
    "insert":   {"label": "插入文字", "params": [
        {"k": "text", "t": "text", "label": "文字", "ph": "插入内容"},
        {"k": "at", "t": "int", "label": "位置(负=从末尾)", "def": 0},
        {"k": "scope", "t": "select", "label": "作用域", "options": [("name", "仅文件名"), ("full", "含扩展名")], "def": "name"}]},
    "truncate": {"label": "按长度截断", "params": [
        {"k": "max", "t": "int", "label": "最大长度", "def": 30},
        {"k": "fromEnd", "t": "check", "label": "从末尾截取"},
        {"k": "scope", "t": "select", "label": "作用域", "options": [("name", "仅文件名"), ("full", "含扩展名")], "def": "name"}]},
    "sanitize": {"label": "文件名净化", "params": [
        {"k": "level", "t": "select", "label": "规则", "options": [("windows", "Windows非法字符"), ("linux", "Linux非法字符(/)")], "def": "windows"},
        {"k": "spacesTo", "t": "text", "label": "空格替换为(留空不替换)", "ph": "_"}]},
    "regex":    {"label": "正则重命名(捕获组)", "params": [
        {"k": "pattern", "t": "text", "label": "正则", "ph": "img_(\\d+)\\.png"},
        {"k": "template", "t": "text", "label": "模板", "ph": "photo_$1.jpg"}]},
}


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("本地文件批量重命名工具")
        self.root.geometry("940x720")

        self.dir_var = tk.StringVar()
        self.recur_var = tk.BooleanVar(value=False)
        self.allow_var = tk.BooleanVar(value=False)
        self.backup_var = tk.BooleanVar(value=True)  # 是否生成撤销备份
        self.last_undo = None    # 最近一次操作的撤销备份路径
        self.files = []          # 扫描结果
        self.selected = set()    # 勾选的文件名集合
        self.rules = []          # [{type, params:{...}}]
        self.mapping = []        # 最近一次预览结果

        self._build_top()
        self._build_rules()
        self._build_files()
        self._build_actions()
        self._build_undo()
        self._build_warn()
        self._build_status()

        self.render_rules()
        self.set_status("填入文件夹路径后点「扫描」。所有操作仅在本机进行。")

    # ---------------- 顶部：文件夹 ----------------
    def _build_top(self):
        f = ttk.LabelFrame(self.root, text="1. 选择文件夹")
        f.pack(fill="x", padx=10, pady=6)
        row = ttk.Frame(f)
        row.pack(fill="x", padx=6, pady=6)
        ttk.Label(row, text="文件夹:").pack(side="left")
        ttk.Entry(row, textvariable=self.dir_var, width=62).pack(side="left", padx=6)
        ttk.Button(row, text="浏览...", command=self.browse_dir).pack(side="left")
        ttk.Checkbutton(row, text="包含子文件夹", variable=self.recur_var,
                        command=self.on_rule_changed).pack(side="left", padx=8)
        ttk.Button(row, text="扫描", command=self.scan).pack(side="left")

    def browse_dir(self):
        d = filedialog.askdirectory(title="选择要处理的文件夹")
        if d:
            self.dir_var.set(d)
            self.scan()

    # ---------------- 规则 ----------------
    def _build_rules(self):
        f = ttk.LabelFrame(self.root, text="2. 改名规则（可叠加，从上到下依次执行）")
        f.pack(fill="x", padx=10, pady=6)
        row = ttk.Frame(f)
        row.pack(fill="x", padx=6, pady=4)
        self.rule_type = ttk.Combobox(row, state="readonly", width=16)
        self.rule_type["values"] = [v["label"] for v in RULE_DEFS.values()]
        self.rule_type.current(0)
        self.rule_type.pack(side="left")
        ttk.Button(row, text="+ 添加规则", command=self.add_rule).pack(side="left", padx=6)
        ttk.Button(row, text="清空", command=self.clear_rules).pack(side="left")

        # 可滚动的规则卡片区
        cf = ttk.Frame(f)
        cf.pack(fill="both", expand=True, padx=6, pady=4)
        self.rules_canvas = tk.Canvas(cf, height=190)
        self.rules_canvas.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(cf, orient="vertical", command=self.rules_canvas.yview)
        sb.pack(side="right", fill="y")
        self.rules_canvas.configure(yscrollcommand=sb.set)
        self.rules_inner = ttk.Frame(self.rules_canvas)
        self.rules_canvas.create_window((0, 0), window=self.rules_inner, anchor="nw")
        self.rules_inner.bind("<Configure>",
            lambda e: self.rules_canvas.configure(scrollregion=self.rules_canvas.bbox("all")))

    def _type_by_label(self, label):
        for k, v in RULE_DEFS.items():
            if v["label"] == label:
                return k
        return None

    def add_rule(self):
        tkey = self._type_by_label(self.rule_type.get())
        if not tkey:
            return
        defn = RULE_DEFS[tkey]
        params = {}
        for p in defn["params"]:
            if p["t"] == "check":
                params[p["k"]] = False
            elif "def" in p:
                params[p["k"]] = p["def"]
            elif p["t"] == "int":
                params[p["k"]] = 0
            else:
                params[p["k"]] = ""
        self.rules.append({"type": tkey, "params": params})
        self.render_rules()
        self.on_rule_changed()

    def clear_rules(self):
        self.rules = []
        self.render_rules()
        self.on_rule_changed()

    def render_rules(self):
        for w in self.rules_inner.winfo_children():
            w.destroy()
        for i, rule in enumerate(self.rules):
            self._build_rule_card(rule, i)
        self.rules_canvas.configure(scrollregion=self.rules_canvas.bbox("all"))

    def _build_rule_card(self, rule, index):
        defn = RULE_DEFS[rule["type"]]
        card = ttk.LabelFrame(self.rules_inner, text="%d. %s" % (index + 1, defn["label"]))
        card.pack(fill="x", padx=2, pady=3)
        body = ttk.Frame(card)
        body.pack(fill="x", padx=6, pady=4)
        dependent = {}  # show_if 依赖控件

        def refresh_show_if():
            for k, widget in dependent.items():
                cond_key, cond_val = k
                cur = rule["params"].get(cond_key)
                widget.pack() if cur == cond_val else widget.pack_forget()

        for p in defn["params"]:
            sub = ttk.Frame(body)
            sub.pack(side="left", padx=8, pady=2)
            ttk.Label(sub, text=p["label"]).pack(anchor="w")
            w = self._make_param_widget(sub, rule, p)
            if "show_if" in p:
                dependent[tuple(p["show_if"])] = sub
        refresh_show_if()

        ttk.Button(card, text="删除", width=6,
                   command=lambda r=rule: self.remove_rule(r)).pack(side="right", padx=6, pady=4)

    def _make_param_widget(self, parent, rule, p):
        k = p["k"]
        t = p["t"]
        if t == "text":
            var = tk.StringVar(value=rule["params"].get(k, ""))
            var.trace_add("write", lambda *a: (rule["params"].__setitem__(k, var.get()), self.on_rule_changed()))
            e = ttk.Entry(parent, textvariable=var, width=16)
            if p.get("ph"):
                e.insert(0, "")
            e.pack()
            return e
        if t == "int":
            var = tk.IntVar(value=rule["params"].get(k, 0))
            var.trace_add("write", lambda *a: (rule["params"].__setitem__(k, var.get()), self.on_rule_changed()))
            e = ttk.Entry(parent, textvariable=var, width=8)
            e.pack()
            return e
        if t == "check":
            var = tk.BooleanVar(value=bool(rule["params"].get(k, False)))
            var.trace_add("write", lambda *a: (rule["params"].__setitem__(k, var.get()), self.on_rule_changed()))
            c = ttk.Checkbutton(parent, variable=var)
            c.pack()
            return c
        if t == "select":
            opts = p["options"]
            disp = [d for _, d in opts]
            m = {d: v for v, d in opts}
            var = tk.StringVar(value=m.get(rule["params"].get(k), disp[0]))
            cb = ttk.Combobox(parent, values=disp, state="readonly", width=12)
            cb.set(var.get())
            def on_sel(ev=None, cb=cb, m=m, k=k):
                v = m.get(cb.get(), cb.get())
                rule["params"][k] = v
                self.on_rule_changed()
            cb.bind("<<ComboboxSelected>>", on_sel)
            cb.pack()
            return cb
        return None

    def remove_rule(self, rule):
        if rule in self.rules:
            self.rules.remove(rule)
        self.render_rules()
        self.on_rule_changed()

    # ---------------- 文件列表 ----------------
    def _build_files(self):
        f = ttk.LabelFrame(self.root, text="3. 文件列表（勾选要处理的，默认全选）")
        f.pack(fill="x", padx=10, pady=6)
        row = ttk.Frame(f)
        row.pack(fill="x", padx=6, pady=2)
        ttk.Button(row, text="全选", command=lambda: self.select_all(True)).pack(side="left")
        ttk.Button(row, text="全不选", command=lambda: self.select_all(False)).pack(side="left", padx=6)
        cf = ttk.Frame(f)
        cf.pack(fill="both", expand=True, padx=6, pady=4)
        self.tree = ttk.Treeview(cf, columns=("sel", "cur", "new"), show="headings", height=10)
        self.tree.heading("sel", text="")
        self.tree.heading("cur", text="当前名称")
        self.tree.heading("new", text="改名后（预览）")
        self.tree.column("sel", width=28, anchor="center")
        self.tree.column("cur", width=380, anchor="w")
        self.tree.column("new", width=380, anchor="w")
        self.tree.tag_configure("conflict", foreground="#c0392b")
        self.tree.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(cf, orient="vertical", command=self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Button-1>", self.on_tree_click)

    def on_tree_click(self, ev):
        item = self.tree.identify_row(ev.y)
        if not item:
            return
        if item in self.selected:
            self.selected.discard(item)
        else:
            self.selected.add(item)
        self.update_sel_column()
        self.on_rule_changed()

    def update_sel_column(self):
        for name in self.tree.get_children():
            self.tree.set(name, "sel", "☑" if name in self.selected else "")

    def select_all(self, val):
        self.selected = set(f["name"] for f in self.files) if val else set()
        self.update_sel_column()
        self.on_rule_changed()

    # ---------------- 操作 ----------------
    def _build_actions(self):
        f = ttk.Frame(self.root)
        f.pack(fill="x", padx=10, pady=4)
        ttk.Button(f, text="预览改名效果", command=self.refresh_preview).pack(side="left")
        ttk.Button(f, text="应用改名", command=self.do_apply).pack(side="left", padx=8)
        ttk.Button(f, text="撤销上一步", command=self.do_undo_last).pack(side="left", padx=8)
        ttk.Checkbutton(f, text="允许覆盖已存在文件", variable=self.allow_var).pack(side="left", padx=8)
        ttk.Checkbutton(f, text="生成撤销备份", variable=self.backup_var).pack(side="left", padx=8)

    def _build_undo(self):
        f = ttk.LabelFrame(self.root, text="4. 撤销（备份存于系统临时目录，不污染目标文件夹）")
        f.pack(fill="x", padx=10, pady=6)
        row = ttk.Frame(f)
        row.pack(fill="x", padx=6, pady=6)
        self.undo_dir = tk.StringVar(value=undo_store_dir())
        ttk.Entry(row, textvariable=self.undo_dir, width=50).pack(side="left", padx=6)
        ttk.Button(row, text="选择备份文件...", command=self.browse_undo).pack(side="left", padx=4)
        ttk.Button(row, text="撤销还原", command=self.do_undo).pack(side="left", padx=4)
        ttk.Label(row, text="（也可直接点上方「撤销上一步」）").pack(side="left", padx=6)

    def browse_undo(self):
        p = filedialog.askopenfilename(title="选择撤销备份", filetypes=[("JSON", "*.json")])
        if p:
            self.undo_dir.set(p)

    def _build_warn(self):
        self.warn_var = tk.StringVar()
        self.warn_lbl = ttk.Label(self.root, textvariable=self.warn_var, foreground="#c0392b", wraplength=900)
        self.warn_lbl.pack(fill="x", padx=12, pady=2)

    def _build_status(self):
        self.status_var = tk.StringVar()
        ttk.Label(self.root, textvariable=self.status_var, foreground="#555",
                  relief="sunken", anchor="w").pack(side="bottom", fill="x")

    def set_status(self, msg, err=False):
        self.status_var.set(msg)
        # 状态栏颜色
        for child in self.root.winfo_children():
            if isinstance(child, ttk.Label) and child.cget("relief") == "sunken":
                child.configure(foreground="#c0392b" if err else "#555")

    # ---------------- 核心逻辑 ----------------
    def scan(self):
        d = self.dir_var.get().strip()
        if not d or not os.path.isdir(d):
            messagebox.showerror("提示", "文件夹路径无效，请检查后重试。")
            return
        self.files = scan_directory(d, self.recur_var.get())
        self.selected = set(f["name"] for f in self.files)
        self.tree.delete(*self.tree.get_children())
        for f in self.files:
            self.tree.insert("", "end", iid=f["name"], values=("☑", f["name"], "—"))
        self.set_status("扫描完成，共 %d 个文件。" % len(self.files))
        self.on_rule_changed()

    def _current_preview(self):
        d = self.dir_var.get().strip()
        if not d or not os.path.isdir(d):
            return None
        names = [n for n in self.selected]
        if not names:
            return None
        mapping = build_preview(d, self.recur_var.get(), names, self.rules)
        conflicts, overwrites = detect_conflicts(os.path.abspath(d), mapping)
        return mapping, conflicts, overwrites

    def on_rule_changed(self):
        self.refresh_preview()

    def refresh_preview(self):
        res = self._current_preview()
        if res is None:
            return
        mapping, conflicts, overwrites = res
        self.mapping = mapping
        m = {x["from"]: x["to"] for x in mapping}
        conflict_targets = set(conflicts.keys())
        for f in self.files:
            new = m.get(f["name"], "—")
            self.tree.set(f["name"], "new", new)
            if new in conflict_targets:
                self.tree.item(f["name"], tags=("conflict",))
            else:
                self.tree.item(f["name"], tags=())
        # 提示
        warns = []
        if conflicts:
            lines = ["⚠ 目标名冲突（会阻止应用）："]
            for to, frm in conflicts.items():
                lines.append("  %s  ←  %s" % (to, "、".join(frm)))
            warns.append("\n".join(lines))
        if overwrites:
            warns.append("⚠ 会覆盖已存在文件：\n  " + "\n  ".join(overwrites) +
                         "\n（勾选「允许覆盖」后可继续）")
        self.warn_var.set("\n\n".join(warns))
        if not warns:
            self.set_status("预览已更新，无冲突。")

    def do_apply(self):
        res = self._current_preview()
        if res is None:
            messagebox.showerror("提示", "请先扫描并勾选文件。")
            return
        mapping, conflicts, overwrites = res
        if conflicts:
            messagebox.showerror("存在冲突", "有多个文件会改成同名，已阻止。请调整规则。")
            return
        if overwrites and not self.allow_var.get():
            messagebox.showerror("会覆盖文件", "部分目标文件已存在。如确认要覆盖，请勾选「允许覆盖已存在文件」。")
            return
        d = self.dir_var.get().strip()
        r = apply_rename(d, mapping, self.allow_var.get(), self.backup_var.get())
        if not r["ok"]:
            messagebox.showerror("失败", r.get("error", "未知错误"))
            return
        skipped = len(r.get("skipped", []))
        self.last_undo = r.get("undo")
        if self.last_undo:
            msg = ("已改名 %d 个文件%s。\n撤销备份已存于系统临时目录，可点「撤销上一步」还原。"
                   % (len(r["renamed"]),
                      ("，跳过 %d 个（源不存在）" % skipped if skipped else "")))
        else:
            msg = ("已改名 %d 个文件%s。\n（未生成撤销备份）"
                   % (len(r["renamed"]),
                      ("，跳过 %d 个（源不存在）" % skipped if skipped else "")))
        messagebox.showinfo("完成", msg)
        self.scan()

    def do_undo_last(self):
        """撤销上一步：直接用内存中记录的备份路径还原，无需手动找文件。"""
        p = self.last_undo
        if not p or not os.path.isfile(p):
            messagebox.showinfo("提示", "没有可撤销的上一步操作（或备份已丢失）。")
            return
        self._run_undo(p)

    def do_undo(self):
        """手动选择备份文件还原（支持外部/移动过的备份）。"""
        p = self.undo_dir.get().strip()
        if not os.path.isfile(p):
            messagebox.showerror("提示", "请选择有效的撤销备份 JSON 文件。")
            return
        self._run_undo(p)

    def _run_undo(self, p):
        try:
            undo = json.load(open(p, encoding="utf-8"))
        except Exception:
            messagebox.showerror("提示", "JSON 解析失败。")
            return
        # 撤销目录以备份内记录的为准（不再依赖备份文件所在位置）
        d = undo.get("dir") or os.path.dirname(os.path.abspath(p))
        rev = [{"from": m["to"], "to": m["from"]} for m in undo.get("mapping", [])]
        r = undo_rename(d, rev)
        if not r["ok"]:
            messagebox.showerror("失败", r.get("error", "未知错误"))
            return
        messagebox.showinfo("完成", "已还原 %d 个文件。" % len(r["renamed"]))
        if p == self.last_undo:
            self.last_undo = None
        # 若当前文件夹与之相同则刷新
        if os.path.abspath(self.dir_var.get().strip()) == os.path.abspath(d):
            self.scan()


def main():
    try:
        root = tk.Tk()
    except Exception as e:
        sys.stderr.write("无法初始化图形界面: %s\n" % e)
        return
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
