"""Netscape / Chrome / Edge / Firefox 书签文件的解析与导出。

导出的书签文件是标准的 Netscape 格式（<!DOCTYPE NETSCAPE-Bookmark-file-1>），
可被所有主流浏览器重新导入。
"""

from __future__ import annotations

import csv
import html
import json
import re
import time
from collections import OrderedDict
from typing import Dict, Iterable, List, Tuple

from .models import Bookmark

RE_H3 = re.compile(r"<H3[^>]*>(.*?)</H3>", re.I | re.S)
RE_A = re.compile(
    r"<A\s+([^>]*?)>(.*?)</A>",
    re.I | re.S,
)
RE_ATTR = re.compile(r"""([A-Z_][A-Z0-9_-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""", re.I)


def _attrs(attr_text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in RE_ATTR.finditer(attr_text):
        key = m.group(1).upper()
        val = m.group(2) if m.group(2) is not None else (
            m.group(3) if m.group(3) is not None else (m.group(4) or "")
        )
        out[key] = html.unescape(val)
    return out


def parse_netscape(text: str, keep_icons: bool = False) -> Tuple[List[str], List[Bookmark]]:
    """解析 Netscape 书签文件文本。

    返回 (文件夹路径列表, 书签列表)。文件夹路径形如 "AI相关/中转站"。
    """
    folders: List[str] = []
    bookmarks: List[Bookmark] = []
    stack: List[str] = []

    # 逐行处理，标准导出文件是严格逐行的
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        upper = line.upper()

        if upper.startswith("</DL>"):
            if stack:
                stack.pop()
            continue

        m3 = RE_H3.search(line)
        if m3 and "<H3" in upper:
            name = html.unescape(re.sub(r"<[^>]+>", "", m3.group(1))).strip()
            if not name:
                name = "未命名文件夹"
            stack.append(name)
            folders.append("/".join(stack))
            continue

        ma = RE_A.search(line)
        if ma and "<A" in upper:
            a = _attrs(ma.group(1))
            url = a.get("HREF", "").strip()
            if not url:
                continue
            title = html.unescape(re.sub(r"<[^>]+>", "", ma.group(2))).strip()
            try:
                add_date = int(a.get("ADD_DATE", "0") or 0)
            except ValueError:
                add_date = 0
            icon = a.get("ICON", "") if keep_icons else ""
            bookmarks.append(
                Bookmark(
                    title=title or url,
                    url=url,
                    folder="/".join(stack),
                    add_date=add_date,
                    icon=icon,
                )
            )
            continue

    return folders, bookmarks


def load_bookmarks(path: str, keep_icons: bool = False) -> Tuple[List[str], List[Bookmark]]:
    """根据扩展名自动选择解析方式，支持 .html / .json / .csv。"""
    low = path.lower()
    if low.endswith(".json"):
        return load_json(path)
    if low.endswith(".csv"):
        return load_csv(path)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    return parse_netscape(text, keep_icons=keep_icons)


def load_json(path: str) -> Tuple[List[str], List[Bookmark]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    items = data.get("bookmarks", data) if isinstance(data, dict) else data
    folders: List[str] = []
    bms: List[Bookmark] = []
    for it in items:
        bm = Bookmark(
            title=it.get("title", ""),
            url=it.get("url", ""),
            folder=it.get("folder", ""),
            add_date=int(it.get("add_date", 0) or 0),
            category=it.get("category", ""),
        )
        if bm.folder and bm.folder not in folders:
            folders.append(bm.folder)
        bms.append(bm)
    return folders, bms


def load_csv(path: str) -> Tuple[List[str], List[Bookmark]]:
    folders: List[str] = []
    bms: List[Bookmark] = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            url = (row.get("url") or row.get("URL") or "").strip()
            if not url:
                continue
            folder = (row.get("folder") or "").strip()
            if folder and folder not in folders:
                folders.append(folder)
            bms.append(Bookmark(title=(row.get("title") or url).strip(), url=url, folder=folder))
    return folders, bms


def _new_node():
    return {"__children__": OrderedDict(), "__items__": []}


def _build_tree(bookmarks: Iterable[Bookmark]):
    """把扁平的书签列表还原成嵌套结构。"""
    root = _new_node()

    def node_of(path: str):
        cur = root
        if path:
            for part in path.split("/"):
                part = part.strip()
                if not part:
                    continue
                cur = cur["__children__"].setdefault(part, _new_node())
        return cur

    for bm in bookmarks:
        node_of(bm.folder)["__items__"].append(bm)
    return root


def _emit(children, items, out: List[str], depth: int, with_icons: bool, now: int):
    pad = "    " * depth
    for name, sub in children.items():
        out.append(f'{pad}<DT><H3 ADD_DATE="{now}">{html.escape(name)}</H3>')
        out.append(f"{pad}<DL><p>")
        _emit(sub["__children__"], sub["__items__"], out, depth + 1, with_icons, now)
        out.append(f"{pad}</DL><p>")
    for bm in items:
        icon = f' ICON="{bm.icon}"' if (with_icons and bm.icon) else ""
        out.append(
            f'{pad}<DT><A HREF="{html.escape(bm.url, quote=True)}"'
            f' ADD_DATE="{int(bm.add_date or now)}"{icon}>'
            f"{html.escape(bm.title)}</A>"
        )


def export_netscape(bookmarks: Iterable[Bookmark], path: str, with_icons: bool = False) -> int:
    """导出为浏览器可直接导入的 Netscape 书签文件，返回写入条数。"""
    bms = list(bookmarks)
    root = _build_tree(bms)
    now = int(time.time())
    out: List[str] = [
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>",
        "<!-- This is an automatically generated file.",
        "     It will be read and overwritten.",
        "     DO NOT EDIT! -->",
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
        "<TITLE>Bookmarks</TITLE>",
        "<H1>Bookmarks</H1>",
        "<DL><p>",
    ]
    _emit(root["__children__"], root["__items__"], out, 1, with_icons, now)
    out.append("</DL><p>")

    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    return len(bms)


def export_by_category(bookmarks: Iterable[Bookmark], path: str,
                       with_icons: bool = False) -> int:
    """按新分类体系导出：把每条书签的 folder 临时替换为 category。"""
    bms = list(bookmarks)
    staged = []
    for b in bms:
        staged.append(
            Bookmark(title=b.title, url=b.url, folder=b.category or "未分类",
                     add_date=b.add_date, icon=b.icon)
        )
    return export_netscape(staged, path, with_icons=with_icons)


def export_json(bookmarks: Iterable[Bookmark], path: str) -> int:
    data = [
        {
            "title": b.title,
            "url": b.url,
            "folder": b.folder,
            "category": b.category,
            "add_date": b.add_date,
            "verdict": b.effective_verdict,
            "subtype": b.effective_subtype,
            "confidence": b.confidence,
            "last_checked": b.last_checked,
        }
        for b in bookmarks
    ]
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump({"version": 2, "count": len(data), "bookmarks": data},
                  f, ensure_ascii=False, indent=2)
    return len(data)


def export_csv(bookmarks: Iterable[Bookmark], path: str) -> int:
    n = 0
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["title", "url", "folder", "category",
                    "verdict", "subtype", "confidence", "add_date"])
        for b in bookmarks:
            w.writerow([b.title, b.url, b.folder, b.category,
                        b.effective_verdict, b.effective_subtype,
                        b.confidence, b.add_date])
            n += 1
    return n
