"""书签去重。

支持三档严格度：
  严格   —— 仅归一化后完全相同的 URL
  标准   —— 严格 + 同域名同路径（忽略 http/https、忽略查询串差异）
  宽松   —— 标准 + 同域名下标题高度相似（相似度阈值可配）
"""

from __future__ import annotations

import difflib
import re
from collections import defaultdict
from typing import Dict, Iterable, List, Sequence
from urllib.parse import urlsplit, urlunsplit

from .models import (
    V_DEAD, V_OK, V_SKIPPED, V_SUSPECT, V_UNKNOWN,
    Bookmark, domain_of, normalize_url,
)

LEVEL_STRICT = "严格"
LEVEL_NORMAL = "标准"
LEVEL_LOOSE = "宽松"

LEVELS = [LEVEL_STRICT, LEVEL_NORMAL, LEVEL_LOOSE]


def _key_strict(bm: Bookmark) -> str:
    return bm.norm


def _key_noscheme(bm: Bookmark) -> str:
    k = bm.norm
    for scheme in ("https://", "http://"):
        if k.startswith(scheme):
            return k[len(scheme):]
    return k


def _key_path(bm: Bookmark) -> str:
    try:
        parts = urlsplit(bm.url)
    except ValueError:
        return bm.url
    path = parts.path or "/"
    for tail in ("/index.html", "/index.htm", "/index.php", "/default.aspx"):
        if path.lower().endswith(tail):
            path = path[: -len(tail)] or "/"
            break
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    # 用 domain_of 取主机，自动抹平 www. / 端口 / 用户@ 差异
    return f"{domain_of(bm.url)}|{path}"


# ----------------------------------------------------------------- 标题相似度
# 宽松去重靠「同域名 + 标题像」判定重复。原始标题常带站点后缀/标点噪声，
# 直接比对 SequenceMatcher 容易漏。这里先做轻量归一化，再用「字符二元组集合
# 相似度」补强（对增删词、调序都更稳），比单纯整串 ratio 更准。
_NOISE_RE = re.compile(
    r"[\s\u3000]+|"                      # 空白
    r"[\[\]【】()（）{}<>《》·•·:：;；·\-_=+~～!！?？。、,.，,/`|｜…]+|"  # 标点
    r"^(官网|官方网站|首页|home)$|"       # 整体站点标识
    r"(官网|官方网站|首页|-{1,2}.*|_.*)$"  # 尾部站点标识/分隔符后内容
)


def _norm_title(t: str) -> str:
    t = (t or "").lower()
    return _NOISE_RE.sub("", t)


def _bigram_set(s: str) -> set:
    return {s[i:i + 2] for i in range(len(s) - 1)} or {s}


def _title_sim(a: str, b: str) -> float:
    a, b = _norm_title(a), _norm_title(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:        # 一个是另一个去掉站点后缀后的前缀
        return 0.95
    seq = difflib.SequenceMatcher(None, a, b).ratio()
    A, B = _bigram_set(a), _bigram_set(b)
    jacc = len(A & B) / len(A | B) if (A | B) else 0.0
    return max(seq, jacc)


class _Union:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def find_duplicate_groups(
    bookmarks: Sequence[Bookmark],
    level: str = LEVEL_NORMAL,
    title_threshold: float = 0.92,
) -> List[List[int]]:
    """返回重复组，每组是书签索引列表（长度 > 1 才算重复）。"""
    n = len(bookmarks)
    uf = _Union(n)
    buckets: Dict[str, List[int]] = defaultdict(list)

    for i, bm in enumerate(bookmarks):
        buckets["s:" + _key_strict(bm)].append(i)
    if level in (LEVEL_NORMAL, LEVEL_LOOSE):
        for i, bm in enumerate(bookmarks):
            buckets["n:" + _key_noscheme(bm)].append(i)
            buckets["p:" + _key_path(bm)].append(i)

    for _, idxs in buckets.items():
        for j in range(1, len(idxs)):
            uf.union(idxs[0], idxs[j])

    if level == LEVEL_LOOSE:
        by_domain: Dict[str, List[int]] = defaultdict(list)
        for i, bm in enumerate(bookmarks):
            by_domain[bm.domain].append(i)
        for _, idxs in by_domain.items():
            if len(idxs) < 2 or len(idxs) > 400:
                continue
            for a in range(len(idxs)):
                for b in range(a + 1, len(idxs)):
                    ta = bookmarks[idxs[a]].title
                    tb = bookmarks[idxs[b]].title
                    if not ta or not tb:
                        continue
                    if _title_sim(ta, tb) >= title_threshold:
                        uf.union(idxs[a], idxs[b])

    groups: Dict[int, List[int]] = defaultdict(list)
    for i in range(n):
        groups[uf.find(i)].append(i)
    return [g for g in groups.values() if len(g) > 1]


def pick_primary(group: List[int], bookmarks: Sequence[Bookmark], prefer_folder: str = "") -> int:
    """在重复组中挑选保留项。

    优先级（数值越小越优先）：
      1) 站点活着（可访问 > 存疑/未检测 > 已失效）
      2) 有真实标题（而不是只剩一个 URL 当标题）
      3) 命中用户偏好的原文件夹
      4) 添加时间更早
      5) 标题更长（信息更完整）
    """
    v_rank = {V_OK: 0, V_SUSPECT: 1, V_UNKNOWN: 1, V_SKIPPED: 1, V_DEAD: 2}

    def score(i: int):
        bm = bookmarks[i]
        verdict = bm.effective_verdict
        live = v_rank.get(verdict, 1)
        real_title = 1 if (bm.title and bm.title != bm.url) else 0
        folder_bonus = 0 if (prefer_folder and bm.folder.startswith(prefer_folder)) else 1
        return (live, -real_title, folder_bonus, bm.add_date, -len(bm.title or ""))

    return min(group, key=score)


def deduplicate(
    bookmarks: Sequence[Bookmark],
    level: str = LEVEL_NORMAL,
    title_threshold: float = 0.92,
) -> int:
    """就地标记重复项：主条目 keep=True，其余 keep=False。返回被标记剔除的条数。"""
    for bm in bookmarks:
        bm.keep = True
        bm.dup_group = -1
        bm.is_primary = True

    groups = find_duplicate_groups(bookmarks, level=level, title_threshold=title_threshold)
    removed = 0
    for gid, group in enumerate(groups):
        primary = pick_primary(group, bookmarks)
        for i in group:
            bm = bookmarks[i]
            bm.dup_group = gid
            bm.is_primary = i == primary
            if i != primary:
                bm.keep = False
                removed += 1
    return removed
