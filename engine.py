#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地文件批量重命名工具 —— 改名规则引擎（纯标准库，无第三方依赖）
被 GUI 版(app.py) 与服务版(server.py) 共用，作为唯一真源。
"""

import os
import re
import json
import uuid
import random
import string
import datetime
import tempfile


def _fmt_num(index, start, step, pad):
    n = start + index * step
    if pad > 0:
        return str(n).zfill(pad)
    return str(n)


def apply_rule(rule, base, ext, index, meta):
    """对单个文件应用一条规则，返回新的 (base, ext)。"""
    rtype = rule.get("type")
    p = rule.get("params", {}) or {}

    # ---- 位置类：作用于 base，保留 ext ----
    if rtype == "prefix":
        base = (p.get("text", "") or "") + base

    elif rtype == "suffix":
        base = base + (p.get("text", "") or "")

    elif rtype == "number":
        num = _fmt_num(index, int(p.get("start", 1) or 1),
                       int(p.get("step", 1) or 1), int(p.get("pad", 3) or 0))
        pos = p.get("pos", "prefix")
        if pos == "prefix":
            base = num + base
        elif pos == "suffix":
            base = base + num
        elif pos == "replace":
            base = num
        elif pos == "template":
            tpl = p.get("template", "{n}_{name}")
            base = tpl.replace("{n}", num).replace("{name}", base)

    elif rtype == "date":
        src = p.get("source", "mtime")
        ts = meta.get("ctime") if src == "ctime" else meta.get("mtime")
        dt = datetime.datetime.fromtimestamp(ts)
        try:
            fmt = p.get("format", "%Y%m%d")
            stamp = dt.strftime(fmt)
        except Exception:
            stamp = dt.strftime("%Y%m%d")
        if p.get("pos", "prefix") == "suffix":
            base = base + stamp
        else:
            base = stamp + base

    elif rtype == "ext":
        new_ext = p.get("ext", "") or ""
        if new_ext and not new_ext.startswith("."):
            new_ext = "." + new_ext
        ext = new_ext

    elif rtype == "random":
        mode = p.get("mode", "alnum")
        length = int(p.get("len", 8) or 8)
        if mode == "uuid":
            rnd = uuid.uuid4().hex
        elif mode == "hex":
            rnd = "".join(random.choice("0123456789abcdef") for _ in range(length))
        else:  # alnum
            chars = string.ascii_letters + string.digits
            rnd = "".join(random.choice(chars) for _ in range(length))
        pos = p.get("pos", "replace")
        if pos == "prefix":
            base = rnd + base
        elif pos == "suffix":
            base = base + rnd
        else:
            base = rnd

    # ---- 文本类：作用域 name / full ----
    elif rtype in ("replace", "case", "strip", "insert", "truncate",
                   "sanitize", "regex"):
        scope = p.get("scope", "full")
        if scope == "full":
            work = base + ext
            is_full = True
        else:
            work = base
            is_full = False

        if rtype == "replace":
            find = p.get("find", "") or ""
            repl = p.get("repl", "") or ""
            if p.get("regex"):
                flags = 0 if p.get("casesens") else re.IGNORECASE
                work = re.sub(find, repl, work, flags=flags)
            else:
                if p.get("casesens"):
                    work = work.replace(find, repl)
                else:
                    work = _ci_replace(work, find, repl)

        elif rtype == "case":
            mode = p.get("mode", "upper")
            if mode == "upper":
                work = work.upper()
            elif mode == "lower":
                work = work.lower()
            elif mode == "title":
                work = work.title()
            elif mode == "capitalize":
                work = work[:1].upper() + work[1:] if work else work
            elif mode == "swapcase":
                work = work.swapcase()

        elif rtype == "strip":
            mode = p.get("mode", "spaces")
            chars = p.get("chars", "") or ""
            if mode == "spaces":
                work = work.strip()
            elif mode == "both":
                work = work.strip(chars)
            elif mode == "leading":
                work = work.lstrip(chars)
            elif mode == "trailing":
                work = work.rstrip(chars)
            elif mode == "all-spaces":
                work = re.sub(r"\s+", "", work)

        elif rtype == "insert":
            text = p.get("text", "") or ""
            at = int(p.get("at", 0) or 0)
            if at < 0:
                at = max(0, len(work) + at)
            work = work[:at] + text + work[at:]

        elif rtype == "truncate":
            if scope == "full":
                work = base + ext
            else:
                work = base
            mx = int(p.get("max", 30) or 30)
            if p.get("fromEnd"):
                work = work[-mx:] if len(work) > mx else work
            else:
                work = work[:mx] if len(work) > mx else work
            if scope == "full":
                base = work[:-len(ext)] if ext and work.endswith(ext) else work
                ext = ext if work.endswith(ext) else ""
                is_full = False

        elif rtype == "sanitize":
            level = p.get("level", "windows")
            spaces_to = p.get("spacesTo", "")
            illegal = set('<>:"/\\|?*') | {chr(c) for c in range(32)}
            out = []
            for ch in work:
                if level == "windows" and ch in illegal:
                    continue
                if level == "linux" and ch in ("/",):
                    continue
                out.append(ch)
            work = "".join(out)
            if spaces_to:
                work = work.replace(" ", spaces_to)
            work = work.strip(". ")
            if not work:
                work = "file"

        elif rtype == "regex":
            pattern = p.get("pattern", "") or ""
            template = p.get("template", r"\g<0>")
            try:
                work = re.sub(pattern, template, work)
            except Exception:
                pass

        if is_full:
            base = work
            ext = ""
        else:
            base = work

    return base, ext


def _ci_replace(text, find, repl):
    """大小写不敏感的精确替换。"""
    if not find:
        return text
    pattern = re.compile(re.escape(find), re.IGNORECASE)
    return pattern.sub(repl, text)


def transform_relative(rel_path, rules, index, meta):
    """对相对路径应用规则流水线，仅改变文件名部分，目录部分保留。"""
    d, fname = os.path.split(rel_path)
    base, ext = os.path.splitext(fname)
    for i, rule in enumerate(rules):
        base, ext = apply_rule(rule, base, ext, index, meta)
    new_fname = base + ext
    return os.path.join(d, new_fname) if d else new_fname


def scan_directory(directory, recursive):
    entries = []
    directory = os.path.abspath(directory)
    if recursive:
        for root, dirs, files in os.walk(directory):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, directory)
                entries.append(_stat_entry(rel, full))
    else:
        try:
            names = sorted(os.listdir(directory))
        except Exception:
            names = []
        for f in names:
            full = os.path.join(directory, f)
            if os.path.isfile(full):
                entries.append(_stat_entry(f, full))
    return entries


def _stat_entry(rel, full):
    st = os.stat(full)
    return {
        "name": rel,
        "size": st.st_size,
        "mtime": st.st_mtime,
        "ctime": st.st_ctime,
    }


def build_preview(directory, recursive, names, rules):
    directory = os.path.abspath(directory)
    mapping = []
    ordered = sorted(names)
    meta_cache = {}
    for idx, rel in enumerate(ordered):
        full = os.path.join(directory, rel)
        if rel not in meta_cache:
            st = os.stat(full)
            meta_cache[rel] = {"mtime": st.st_mtime, "ctime": st.st_ctime}
        new_rel = transform_relative(rel, rules, idx, meta_cache[rel])
        mapping.append({"from": rel, "to": new_rel})
    return mapping


def detect_conflicts(directory, mapping):
    conflicts = {}
    seen = {}
    for m in mapping:
        seen.setdefault(m["to"], []).append(m["from"])
    for to, frm_list in seen.items():
        if len(frm_list) > 1:
            conflicts[to] = frm_list
    from_set = {m["from"] for m in mapping}
    existing_overwrites = []
    for m in mapping:
        target_full = os.path.join(directory, m["to"])
        if (m["to"] not in from_set) and os.path.exists(target_full):
            existing_overwrites.append(m["to"])
    return conflicts, existing_overwrites


def undo_store_dir():
    """撤销备份存放目录（系统用户/临时目录，不污染目标文件夹）。"""
    base = (os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
            or os.environ.get("TEMP") or tempfile.gettempdir())
    d = os.path.join(base, "FileRenamer", "undo")
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except Exception:
        pass
    # 兜底：直接用系统临时目录
    try:
        os.makedirs(tempfile.gettempdir(), exist_ok=True)
    except Exception:
        pass
    return tempfile.gettempdir()


def apply_rename(directory, mapping, allow_overwrite, write_backup=True):
    directory = os.path.abspath(directory)
    conflicts, overwrites = detect_conflicts(directory, mapping)
    if conflicts:
        return {"ok": False, "error": "存在目标名冲突，已阻止操作", "conflicts": conflicts}
    if overwrites and not allow_overwrite:
        return {"ok": False, "error": "部分目标文件已存在，将覆盖现有文件，已阻止",
                "overwrites": overwrites}
    undo_path = None
    if write_backup:
        # 备份写到系统临时目录，绝不写进目标文件夹
        undo = {
            "tool": "file-renamer",
            "dir": directory,
            "created": datetime.datetime.now().isoformat(timespec="seconds"),
            "mapping": [{"from": m["from"], "to": m["to"]} for m in mapping],
        }
        undo_name = "file_renamer_undo_%s.json" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        undo_path = os.path.join(undo_store_dir(), undo_name)
        with open(undo_path, "w", encoding="utf-8") as fh:
            json.dump(undo, fh, ensure_ascii=False, indent=2)

    renamed, skipped = [], []
    for m in mapping:
        src = os.path.join(directory, m["from"])
        dst = os.path.join(directory, m["to"])
        if not os.path.exists(src):
            skipped.append(m["from"])
            continue
        os.rename(src, dst)
        renamed.append({"from": m["from"], "to": m["to"]})
    return {"ok": True, "renamed": renamed, "skipped": skipped, "undo": undo_path}


def undo_rename(directory, mapping):
    directory = os.path.abspath(directory)
    renamed, skipped = [], []
    for m in mapping:
        src = os.path.join(directory, m["from"])
        dst = os.path.join(directory, m["to"])
        if not os.path.exists(src):
            skipped.append(m["from"])
            continue
        os.rename(src, dst)
        renamed.append({"from": m["from"], "to": m["to"]})
    return {"ok": True, "renamed": renamed, "skipped": skipped}
