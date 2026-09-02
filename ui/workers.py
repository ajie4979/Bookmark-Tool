"""后台任务线程：所有耗时操作都跑在这里，避免界面卡死。"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import QThread, Signal

from core.ai import AIClient, AIError
from core.classifier import classify_all
from core.dedupe import deduplicate
from core.models import (
    EXIT_CUSTOM, EXIT_DIRECT, EXIT_SYSTEM, V_DEAD, V_OK, V_SKIPPED,
    V_SUSPECT, V_UNKNOWN, Bookmark,
)
from core.prober import (
    ProbeConfig, collect_for_recheck, mark_uniform_pages, probe_all,
)
from core.rules import apply_skip, match_rule, partition_by_rules


class BaseWorker(QThread):
    progress = Signal(int, int, str)     # done, total, 描述
    log = Signal(str)
    finished_ok = Signal(object)         # 结果对象
    failed = Signal(str)                 # 错误信息

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = False

    def request_stop(self):
        self._stop = True

    def stopped(self) -> bool:
        return self._stop

    def _emit(self, done: int, total: int, msg: str = ""):
        self.progress.emit(int(done), int(total), msg)


class LoadWorker(BaseWorker):
    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self):
        from core import parser
        try:
            self.log.emit(f"正在读取 {self.path}")
            folders, bms = parser.load_bookmarks(self.path)
            self.log.emit(f"解析完成：{len(bms)} 条书签，{len(folders)} 个文件夹")
            self.finished_ok.emit((folders, bms))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"读取失败：{e}")


class DedupeWorker(BaseWorker):
    def __init__(self, bookmarks: List[Bookmark], level: str, threshold: float,
                 parent=None):
        super().__init__(parent)
        self.bookmarks = bookmarks
        self.level = level
        self.threshold = threshold

    def run(self):
        try:
            self._emit(0, 1, "正在比对…")
            removed = deduplicate(self.bookmarks, level=self.level,
                                  title_threshold=self.threshold)
            self._emit(1, 1, "完成")
            self.log.emit(f"去重完成（{self.level}）：标记剔除 {removed} 条")
            self.finished_ok.emit(removed)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"去重失败：{e}")


class ProbeWorker(BaseWorker):
    """多出口验证。

    流程：
      1. 按域名规则分成「跳过 / 需代理 / 需直连」三组
      2. 跳过组直接标记
      3. 需代理组强制走代理出口，需直连组强制走直连出口
      4. 其余走用户配置的默认出口
      5. 每条书签合并结论（乐观合并）
    """

    def __init__(self, bookmarks: List[Bookmark], cfg: dict, rules: dict,
                 only: Optional[List[Bookmark]] = None, parent=None):
        super().__init__(parent)
        self.bookmarks = bookmarks
        self.cfg = cfg
        self.rules = rules or {}
        self.only = only

    def _targets(self):
        if self.only is not None:
            return list(self.only)
        return [b for b in self.bookmarks if b.keep]

    def run(self):
        try:
            from config import make_probe_config
            pcfg = make_probe_config(self.cfg)

            targets = self._targets()
            total = len(targets)
            if total == 0:
                self.log.emit("没有需要验证的条目")
                self.finished_ok.emit({"total": 0})
                return

            # 记录每条书签验证前的结论，完成后用于计算变化（让日志数量对得上）
            self._init_verdict = {id(b): b.effective_verdict for b in targets}
            n_suspect = sum(1 for b in targets if b.effective_verdict == V_SUSPECT)
            n_dead = sum(1 for b in targets if b.effective_verdict == V_DEAD)
            n_unknown = sum(1 for b in targets
                            if b.effective_verdict in (V_UNKNOWN, V_SKIPPED))
            n_ok = sum(1 for b in targets if b.effective_verdict == V_OK)

            skip_group, proxy_group, direct_group = partition_by_rules(
                targets, self.rules)
            rule_hit = {id(b) for b in skip_group + proxy_group + direct_group}
            default_group = [b for b in targets if id(b) not in rule_hit]

            if skip_group:
                apply_skip(skip_group)
                self.log.emit(f"按用户规则跳过 {len(skip_group)} 条")

            # 说明本次验证的构成，避免用户觉得数量对不上
            parts = []
            if n_suspect:
                parts.append(f"{n_suspect} 条存疑复检")
            if n_unknown:
                parts.append(f"{n_unknown} 条首次检测")
            if n_dead:
                parts.append(f"{n_dead} 条已失效重测")
            if n_ok:
                parts.append(f"{n_ok} 条可访问重测")
            detail = "、".join(parts) if parts else "全部书签"
            mode = "复检" if self.only is not None else "验证"
            self.log.emit(
                f"开始{mode} {total} 条（{detail}；出口：{pcfg.exit_profile}，"
                f"{pcfg.workers} 线程，超时 {pcfg.timeout}s）"
            )

            done = 0
            total_left = len(default_group) + len(proxy_group) + len(direct_group)

            def progress(d, t, bm):
                nonlocal done
                done += 1
                self._emit(done, total_left, f"{bm.effective_verdict} · "
                                             f"{bm.display_title(28)}")

            # 默认组：用户配置的出口
            if default_group:
                probe_all(self.bookmarks, pcfg, only=default_group,
                          should_stop=self.stopped, on_progress=progress)

            # 需代理组：强制代理
            if proxy_group and not self._stop:
                from copy import deepcopy
                pcfg_p = deepcopy(pcfg)
                if pcfg_p.exit_profile == EXIT_DIRECT or not pcfg_p.custom_proxy:
                    pcfg_p.exit_profile = EXIT_CUSTOM
                    pcfg_p.custom_proxy = pcfg.custom_proxy or ""
                self.log.emit(f"按规则用代理出口验证 {len(proxy_group)} 条")
                probe_all(self.bookmarks, pcfg_p, only=proxy_group,
                          should_stop=self.stopped, on_progress=progress)

            # 需直连组：强制直连
            if direct_group and not self._stop:
                from copy import deepcopy
                pcfg_d = deepcopy(pcfg)
                pcfg_d.exit_profile = EXIT_DIRECT
                self.log.emit(f"按规则用直连出口验证 {len(direct_group)} 条")
                probe_all(self.bookmarks, pcfg_d, only=direct_group,
                          should_stop=self.stopped, on_progress=progress)

            # 全站统一页面：必须等所有链接都探完才能横向比对——
            # 单条探测时无从判断「同域名是不是只剩一种内容」。
            if not self._stop:
                n_landing = mark_uniform_pages(targets)
                if n_landing:
                    self.log.emit(
                        f"发现 {n_landing} 条「疑似统一页面」：同一域名下多个链接"
                        f"返回了完全相同的内容或跳到了同一个地址，站点多半已关停")

            if self._stop:
                self.log.emit("验证已中止（已得结果保留）")

            self._summarize(targets)
            self.finished_ok.emit(self._stats(targets))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"验证失败：{e}")

    def _stats(self, targets) -> dict:
        s: Dict[str, int] = {"total": len(targets)}
        for b in targets:
            v = b.effective_verdict
            s[v] = s.get(v, 0) + 1
        return s

    def _summarize(self, targets):
        s = self._stats(targets)
        self.log.emit(
            f"验证完成：可访问 {s.get(V_OK, 0)}，"
            f"存疑 {s.get(V_SUSPECT, 0)}（仅超时/无响应），"
            f"已失效 {s.get(V_DEAD, 0)}（页面不存在/域名失效）"
        )
        # 详细变化：按验证前的初始状态分组，让用户看清数量怎么来的
        init = getattr(self, "_init_verdict", {})
        if init:
            suspect_to_ok = suspect_to_dead = suspect_remain = 0
            new_ok = new_dead = new_suspect = 0
            dead_changed = ok_changed = 0
            for b in targets:
                before = init.get(id(b))
                after = b.effective_verdict
                if before == V_SUSPECT:
                    if after == V_OK:
                        suspect_to_ok += 1
                    elif after == V_DEAD:
                        suspect_to_dead += 1
                    else:
                        suspect_remain += 1
                elif before in (V_UNKNOWN, V_SKIPPED):
                    if after == V_OK:
                        new_ok += 1
                    elif after == V_DEAD:
                        new_dead += 1
                    else:
                        new_suspect += 1
                elif before == V_DEAD and after != V_DEAD:
                    dead_changed += 1
                elif before == V_OK and after != V_OK:
                    ok_changed += 1
            if suspect_to_ok or suspect_to_dead or suspect_remain:
                self.log.emit(
                    f"  └ 存疑项结果：{suspect_to_ok} 条转可访问、"
                    f"{suspect_to_dead} 条转失效、{suspect_remain} 条仍存疑")
            if new_ok or new_dead or new_suspect:
                self.log.emit(
                    f"  └ 首次检测结果：{new_ok} 条可访问、"
                    f"{new_dead} 条失效、{new_suspect} 条存疑")
            if dead_changed:
                self.log.emit(f"  └ 已失效重测：{dead_changed} 条结论变化")
            if ok_changed:
                self.log.emit(f"  └ 可访问重测：{ok_changed} 条结论变化")
        suspect = s.get(V_SUSPECT, 0)
        if suspect:
            self.log.emit(
                f"另有 {suspect} 条「存疑」——程序完全连不上（超时/网络不通），"
                f"站点本身多半正常（浏览器能打开）。切换网络出口（直连↔系统代理）后点"
                f"「复检存疑项」再跑一次，或在列表里右键标记为可访问。")


class LocalClassifyWorker(BaseWorker):
    def __init__(self, bookmarks: List[Bookmark], taxonomy: dict, parent=None):
        super().__init__(parent)
        self.bookmarks = bookmarks
        self.taxonomy = taxonomy

    def run(self):
        try:
            self._emit(0, 1, "按规则归类…")
            counts = classify_all(self.bookmarks, self.taxonomy, only_kept=True,
                                  use_ai_results=False)
            self._emit(1, 1, "完成")
            # 完整列出所有有数量的分类（按数量降序），不再只取前 5 个
            ordered = sorted(((k, v) for k, v in counts.items() if v),
                             key=lambda x: -x[1])
            total = sum(v for _, v in ordered)
            detail = "，".join(f"{k} {v}" for k, v in ordered)
            self.log.emit(
                f"本地规则归类完成：共 {total} 条、{len(ordered)} 个分类 —— {detail}")
            self.finished_ok.emit(counts)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"归类失败：{e}")


class AIClassifyWorker(BaseWorker):
    def __init__(self, bookmarks: List[Bookmark], cfg: dict,
                 categories: Sequence[str], category_descs: Optional[dict] = None,
                 taxonomy: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.bookmarks = bookmarks
        self.cfg = cfg
        self.categories = list(categories)
        self.category_descs = dict(category_descs or {})
        self.taxonomy = dict(taxonomy or {})

    def run(self):
        try:
            client = AIClient(
                api_key=self.cfg.get("api_key", ""),
                base_url=self.cfg.get("base_url", ""),
                model=self.cfg.get("model", "gpt-4o-mini"),
                timeout=float(self.cfg.get("ai_timeout", 90)),
            )
            total = sum(1 for b in self.bookmarks if b.keep)
            self.log.emit(f"AI 分类开始：模型 {client.model}，共 {total} 条")

            def on_prog(done, tot):
                self._emit(done, tot, f"AI 已处理 {done}/{tot}")

            ok, failed = client.classify_all(
                self.bookmarks,
                self.categories,
                category_descs=self.category_descs,
                batch_size=int(self.cfg.get("batch_size", 25)),
                workers=int(self.cfg.get("ai_workers", 3)),
                should_stop=self.stopped,
                on_progress=on_prog,
            )
            if failed:
                self.log.emit(
                    f"有 {failed} 条 AI 未返回或低置信，正在用本地规则补齐"
                    f"（仅补未分类项，不覆盖 AI 已分类的结果）…")
                # 只对 AI 未覆盖/低置信导致 category 仍为空的书签做本地规则分类，
                # 绝不全量重分类，避免把 AI 结果覆盖掉
                uncategorized = [b for b in self.bookmarks if b.keep and not b.category]
                if uncategorized:
                    from core.classifier import classify_all
                    classify_all(uncategorized, self.taxonomy,
                                 only_kept=False, use_ai_results=False)
            if self._stop:
                self.log.emit("AI 分类已中止")
            else:
                # 完整分类分布（和本地规则归类同样的格式，不再只报成功条数）
                counts: Dict[str, int] = {}
                for b in self.bookmarks:
                    if b.keep:
                        c = b.category or "其他未分类"
                        counts[c] = counts.get(c, 0) + 1
                ordered = sorted(((k, v) for k, v in counts.items() if v),
                                 key=lambda x: -x[1])
                total = sum(v for _, v in ordered)
                detail = "，".join(f"{k} {v}" for k, v in ordered)
                self.log.emit(
                    f"AI 分类完成：共 {total} 条、{len(ordered)} 个分类 —— {detail}")
            self.finished_ok.emit({"ok": ok, "failed": failed})
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"AI 分类失败：{e}")


class AITestWorker(BaseWorker):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg

    def run(self):
        try:
            client = AIClient(
                api_key=self.cfg.get("api_key", ""),
                base_url=self.cfg.get("base_url", ""),
                model=self.cfg.get("model", "gpt-4o-mini"),
                timeout=float(self.cfg.get("ai_timeout", 60)),
            )
            self._emit(0, 1, "正在测试连接…")
            info = client.test_connection()
            self.finished_ok.emit(info)
        except AIError as e:
            self.failed.emit(str(e))
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"连接失败：{e}")


class AIJudgeWorker(BaseWorker):
    """用 AI 复检「存疑」链接是否真失效（仅发正文文本，不二次抓 URL）。"""

    def __init__(self, bookmarks: List[Bookmark], cfg: dict, parent=None):
        super().__init__(parent)
        self.bookmarks = bookmarks
        self.cfg = cfg

    def run(self):
        try:
            from core import ai_judge
            from core.ai import AIClient

            targets = ai_judge.collect_targets(self.bookmarks)
            # 说明存疑总数和可判定数，避免用户觉得数量对不上
            total_suspect = sum(1 for b in self.bookmarks
                                 if b.effective_verdict == V_SUSPECT)
            no_text = total_suspect - len(targets)
            if no_text:
                self.log.emit(
                    f"AI 复检开始：存疑共 {total_suspect} 条，其中 {len(targets)} 条"
                    f"有正文可判定，{no_text} 条完全连不上无正文已跳过")
            else:
                self.log.emit(f"AI 复检开始：待判定存疑项 {len(targets)} 条")
            if not targets:
                self.finished_ok.emit({"done": 0, "alive": 0, "dead": 0,
                                       "uncertain": 0})
                return
            # 记录本次复检的书签，统计时只算这些，避免多次复检后数字累计
            target_ids = set(id(bm) for _, bm, _ in targets)
            client = AIClient(
                api_key=self.cfg.get("api_key", ""),
                base_url=self.cfg.get("base_url", ""),
                model=self.cfg.get("model", "gpt-4o-mini"),
                timeout=float(self.cfg.get("ai_timeout", 90)),
            )
            done = ai_judge.judge_suspects(
                self.bookmarks, client, self.cfg,
                on_progress=lambda d, t: self._emit(d, t, f"AI 已判定 {d}/{t}"),
                should_stop=self.stopped,
                on_warning=lambda m: self.log.emit(m),
            )
            # 只统计本次 targets 的结果，不把之前复检过的算进来
            alive = dead = uncertain = 0
            for bm in self.bookmarks:
                if id(bm) not in target_ids:
                    continue
                if bm.ai_verdict == "alive":
                    alive += 1
                elif bm.ai_verdict == "dead":
                    dead += 1
                else:
                    uncertain += 1
            if self._stop:
                self.log.emit("AI 复检已中止")
            else:
                msg = f"AI 复检完成：{dead} 条判为失效，{alive} 条判为可访问"
                if uncertain:
                    msg += f"，{uncertain} 条仍存疑"
                self.log.emit(msg)
            self.finished_ok.emit({"done": done, "alive": alive, "dead": dead,
                                   "uncertain": uncertain})
        except AIError as e:
            self.failed.emit(f"AI 复检失败：{e}")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"AI 复检失败：{e}")
