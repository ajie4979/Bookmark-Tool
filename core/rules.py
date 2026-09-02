"""用户沉淀的域名规则。

人工裁定或复检结果可一键沉淀为规则，下次验证时自动生效——
这是让工具「越用越准」的关键。

规则文件：%LOCALAPPDATA%\\BookmarkTool\\rules.json
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Sequence

from .models import Bookmark, domain_of

ACTION_PROXY = "require_proxy"     # 需要代理才能访问
ACTION_DIRECT = "require_direct"   # 需要直连（站点封境外 IP）
ACTION_SKIP = "skip"               # 跳过检测（内网等）

ACTIONS = {
    ACTION_PROXY: "需要代理访问",
    ACTION_DIRECT: "需要直连访问",
    ACTION_SKIP: "跳过检测",
}


@dataclass
class Rule:
    domain: str
    action: str
    note: str = ""
    ts: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def load_rules(path: str) -> Dict[str, Rule]:
    out: Dict[str, Rule] = {}
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for domain, r in (data or {}).items():
                if isinstance(r, str):          # 兼容简写 {"a.com": "skip"}
                    r = {"action": r}
                out[domain] = Rule(
                    domain=domain,
                    action=r.get("action", ""),
                    note=r.get("note", ""),
                    ts=int(r.get("ts", 0) or 0),
                )
        except Exception:  # noqa: BLE001
            pass
    return out


def save_rules(path: str, rules: Dict[str, Rule]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    data = {d: r.to_dict() for d, r in rules.items()}
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def put_rule(rules: Dict[str, Rule], domain: str, action: str, note: str = ""):
    domain = (domain or "").strip().lower()
    if not domain or action not in ACTIONS:
        return
    rules[domain] = Rule(domain=domain, action=action, note=note, ts=int(time.time()))


def remove_rule(rules: Dict[str, Rule], domain: str):
    rules.pop((domain or "").strip().lower(), None)


def match_rule(domain: str, rules: Dict[str, Rule]) -> Optional[Rule]:
    """域名匹配：先精确匹配，再逐级向上匹配父域名。"""
    domain = (domain or "").strip().lower()
    if not domain or not rules:
        return None
    if domain in rules:
        return rules[domain]
    parts = domain.split(".")
    for i in range(1, len(parts) - 1):
        parent = ".".join(parts[i:])
        if parent in rules:
            return rules[parent]
    return None


def partition_by_rules(
    bookmarks: Sequence[Bookmark],
    rules: Dict[str, Rule],
) -> tuple:
    """按规则把书签分成三组：(跳过组, 需代理组, 需直连组)。

    未命中任何规则的条目不出现在任何组里——它们走默认出口。
    """
    skip, need_proxy, need_direct = [], [], []
    for b in bookmarks:
        r = match_rule(b.domain, rules)
        if not r:
            continue
        if r.action == ACTION_SKIP:
            skip.append(b)
        elif r.action == ACTION_PROXY:
            need_proxy.append(b)
        elif r.action == ACTION_DIRECT:
            need_direct.append(b)
    return skip, need_proxy, need_direct


def apply_skip(skip_list: Sequence[Bookmark]):
    """把命中「跳过」规则的条目标记为已跳过。"""
    from .models import V_SKIPPED, ST_RULE_SKIP
    for b in skip_list:
        b.verdict = V_SKIPPED
        b.subtype = ST_RULE_SKIP
        b.confidence = ""
