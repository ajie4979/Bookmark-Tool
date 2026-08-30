"""后台任务线程：所有耗时操作都跑在这里，避免界面卡死。"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import QThread, Signal

from core.ai import AIClient, AIError
from core.classifier import classify_all
from core.dedupe import deduplicate
from core.models import (
    EXIT_CUSTOM, EXIT_DIRECT, EXIT_SYSTEM, V_DEAD, V_OK, V_SUSPECT,
    Bookmark,
)
from core.prober import ProbeConfig, collect_for_recheck, probe_all
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

            skip_group, proxy_group, direct_group = partition_by_rules(
                targets, self.rules)
            rule_hit = {id(b) for b in skip_group + proxy_group + direct_group}
            default_group = [b for b in targets if id(b) not in rule_hit]

            if skip_group:
                apply_skip(skip_group)
                self.log.emit(f"按用户规则跳过 {len(skip_group)} 条")

            self.log.emit(
                f"开始验证 {total} 条（出口：{pcfg.exit_profile}，"
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
            top = sorted(counts.items(), key=lambda x: -x[1])[:5]
            self.log.emit("本地规则归类完成：" +
                          "，".join(f"{k} {v}" for k, v in top))
            self.finished_ok.emit(counts)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(f"归类失败：{e}")


class AIClassifyWorker(BaseWorker):
    def __init__(self, bookmarks: List[Bookmark], cfg: dict,
                 categories: Sequence[str], parent=None):
        super().__init__(parent)
        self.bookmarks = bookmarks
        self.cfg = cfg
        self.categories = list(categories)

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
                batch_size=int(self.cfg.get("batch_size", 25)),
                workers=int(self.cfg.get("ai_workers", 3)),
                should_stop=self.stopped,
                on_progress=on_prog,
            )
            if failed:
                self.log.emit(f"有 {failed} 条 AI 未返回结果，稍后可用本地规则补齐")
            if self._stop:
                self.log.emit("AI 分类已中止")
            else:
                self.log.emit(f"AI 分类完成：成功 {ok} 条")
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
