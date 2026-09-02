"""导入预览分析与合并策略（纯逻辑，可离线测试）。

流程：解析文件 → 分析（来源/数量/重复/异常）→ 用户选策略 → 合并 → 报告。
对应需求文档「导入预览 + 导入策略 + 导入报告」。
"""

from __future__ import annotations

import os
from typing import Dict, List, Sequence, Tuple
from urllib.parse import urlsplit

from .models import Bookmark, normalize_url

STRATEGY_REPLACE = "replace"      # 替换当前列表
STRATEGY_MERGE = "merge"          # 合并到当前列表（URL 相同则跳过新文件里的重复项）
STRATEGY_APPEND = "append"        # 追加到当前列表（不去重）


def detect_source(path: str) -> str:
    """根据扩展名与文件头判断书签来源，用于预览与报告。"""
    low = (path or "").lower()
    if low.endswith(".json"):
        try:
            with open(path, "r", encoding="utf-8") as f:
                head = f.read(2000)
        except OSError:
            return "JSON 文件"
        if '"roots"' in head or "bookmark_bar" in head:
            return "Chrome / Edge 导出的 JSON"
        if '"bookmarks"' in head or '"version"' in head:
            return "Bookmark Tool JSON"
        return "通用 JSON"
    if low.endswith(".csv"):
        return "CSV 表格"
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            head = f.read(1500)
    except OSError:
        return "书签 HTML"
    if "NETSCAPE-Bookmark-file" in head:
        return "浏览器导出的书签 HTML（Chrome / Edge / Firefox 通用格式）"
    return "HTML 文件"


def analyze_incoming(
    bms: Sequence[Bookmark],
    existing: Sequence[Bookmark] | None = None,
) -> Dict[str, int]:
    """对将要导入的书签做统计，供预览对话框展示。

    返回：
      total          总条数
      folders        文件夹数
      empty_url      空 URL 条数
      other_scheme   非 http/https 协议条数（chrome://、javascript: 等）
      int_dup_groups 文件内部「完全重复」组数（归一化后 URL 相同）
      dup_with_existing  与当前列表重复的条数
    """
    total = len(bms)
    folders = len({b.folder for b in bms if b.folder})
    empty_url = sum(1 for b in bms if not (b.url or "").strip())
    other_scheme = 0
    seen: Dict[str, int] = {}
    for b in bms:
        if not b.url:
            continue
        try:
            scheme = urlsplit(b.url).scheme.lower()
        except ValueError:
            scheme = ""
        if scheme and scheme not in ("http", "https"):
            other_scheme += 1
        k = normalize_url(b.url)
        if k:
            seen[k] = seen.get(k, 0) + 1
    int_dup_groups = sum(1 for c in seen.values() if c >= 2)

    dup_with_existing = 0
    if existing:
        ex = {normalize_url(b.url) for b in existing if b.url}
        dup_with_existing = sum(
            1 for b in bms if (b.url and normalize_url(b.url) in ex))
    return {
        "total": total,
        "folders": folders,
        "empty_url": empty_url,
        "other_scheme": other_scheme,
        "int_dup_groups": int_dup_groups,
        "dup_with_existing": dup_with_existing,
    }


def apply_import(
    existing: Sequence[Bookmark],
    incoming: Sequence[Bookmark],
    strategy: str,
) -> Tuple[List[Bookmark], Dict[str, int]]:
    """按策略合并书签，返回 (新列表, 统计)。

    统计：
      added          新增条数
      kept_existing  保留的原有条数
      skipped_dup    因与原有重复而跳过的新条数（仅 merge 时有）
    """
    if strategy == STRATEGY_REPLACE:
        return list(incoming), {"added": len(incoming),
                                "kept_existing": 0, "skipped_dup": 0}

    if strategy == STRATEGY_APPEND:
        merged = list(existing) + list(incoming)
        return merged, {"added": len(incoming),
                        "kept_existing": len(existing), "skipped_dup": 0}

    # merge：URL（归一化）相同的新条目跳过，保留原有的那一条
    seen = {normalize_url(b.url): True for b in existing if b.url}
    kept = list(existing)
    added = 0
    skipped = 0
    for b in incoming:
        k = normalize_url(b.url)
        if k and k in seen:
            skipped += 1
            continue
        kept.append(b)
        added += 1
        if k:
            seen[k] = True
    return kept, {"added": added, "kept_existing": len(existing),
                  "skipped_dup": skipped}
