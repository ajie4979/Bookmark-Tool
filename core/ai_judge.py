"""AI 复检「存疑」链接是否真失效。

设计要点（隐私 / 成本 / 内网可用）：
- 复用 prober 已经抓取并存好的正文文本（Probe.text），**不二次请求**、
  也**不把 URL 交给云端浏览器**去抓——只把「标题 + 状态码 + 正文片段」
  发给模型判读。这样用户的整库书签不会外泄，且内网地址（程序本地能抓到）
  也能被 AI 判读。
- 只对「存疑」结论调用，其它结论（可访问 / 已失效）不再打扰 AI。
- 默认关闭，需用户在设置里开启并自备 API Key。
"""
from __future__ import annotations

from typing import Callable, List, Optional, Sequence, Tuple

from core.ai import AIClient, AIError
from core.models import (
    CONF_HIGH, CONF_MID, ST_AI_DEAD, ST_AI_OK, V_DEAD, V_OK, V_SUSPECT,
    Bookmark,
)


def collect_targets(bookmarks: Sequence[Bookmark]) -> List[Tuple[int, Bookmark, object]]:
    """筛出「存疑」且已抓到正文文本的条目（无正文的连不上型存疑 AI 也帮不上）。"""
    out = []
    for i, bm in enumerate(bookmarks):
        if bm.effective_verdict != V_SUSPECT:
            continue
        probe = next((p for p in bm.probes if p.text), None)
        if not probe:
            continue
        out.append((i, bm, probe))
    return out


def _apply(bm: Bookmark, alive: str, reason: str) -> str:
    """把 AI 结论写回书签，返回一句话摘要（用于日志）。"""
    bm.ai_verdict = alive
    bm.ai_reason = reason
    if alive == "dead":
        bm.verdict = V_DEAD
        bm.subtype = ST_AI_DEAD
        bm.confidence = CONF_HIGH
        return "判为失效"
    if alive == "alive":
        bm.verdict = V_OK
        bm.subtype = ST_AI_OK
        bm.confidence = CONF_MID
        return "判为可访问"
    return "仍存疑"


def judge_suspects(
    bookmarks: Sequence[Bookmark],
    client: AIClient,
    cfg: dict,
    on_progress: Optional[Callable[[int, int], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    on_warning: Optional[Callable[[str], None]] = None,
) -> int:
    """对全部存疑且有正文的条目调用 AI 判活，结果合并回 verdict。返回处理条数。

    单批 AI 调用失败（如返回空、超时）时记录警告并跳过该批继续处理，
    不再让整次复检因一批失败而全部失败。
    """
    targets = collect_targets(bookmarks)
    if not targets:
        return 0
    batch_size = max(1, int(cfg.get("batch_size", 25)))
    done = 0
    for start in range(0, len(targets), batch_size):
        if should_stop and should_stop():
            break
        chunk = targets[start:start + batch_size]
        items = [
            (idx, bm.title[:200], bm.url[:400], probe.status_code, probe.text,
             probe.final_url)      # final_url 供 AI 识别域名停放/售卖页跳转
            for (idx, bm, probe) in chunk
        ]
        try:
            res = client.judge_alive_batch(items)
        except AIError as e:
            # 单批失败：记录警告，跳过该批，继续处理剩余批次
            if on_warning:
                on_warning(f"⚠ 本批 {len(chunk)} 条 AI 复检失败（{e}），已跳过，继续处理其余")
            done += len(chunk)
            if on_progress:
                on_progress(done, len(targets))
            continue
        for idx, (alive, reason) in res.items():
            if 0 <= idx < len(bookmarks):
                _apply(bookmarks[idx], alive, reason)
        done += len(chunk)
        if on_progress:
            on_progress(done, len(targets))
    return done
