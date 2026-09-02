"""AI 分类客户端（OpenAI 兼容接口，支持任意中转站）。

所有失败都会抛出 AIError，调用方按需降级到本地规则引擎。
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import requests

from .models import Bookmark


class AIError(Exception):
    pass


RE_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str):
    """从模型输出里抠出 JSON，兼容 ```json 围栏与前后废话。"""
    if not text:
        raise AIError("AI 返回内容为空")
    text = text.strip()
    m = RE_FENCE.search(text)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start: end + 1])
        except json.JSONDecodeError as e:
            raise AIError(f"AI 返回的 JSON 无法解析：{e}") from e
    start, end = text.find("["), text.rfind("]")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start: end + 1])
        except json.JSONDecodeError as e:
            raise AIError(f"AI 返回的 JSON 无法解析：{e}") from e
    raise AIError(f"AI 未返回 JSON：{text[:200]}")


def build_endpoint(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return "https://api.openai.com/v1/chat/completions"
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return base + "/chat/completions"
    return base + "/v1/chat/completions"


class AIClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "",
        model: str = "gpt-4o-mini",
        timeout: float = 90.0,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ):
        self.api_key = (api_key or "").strip()
        self.base_url = base_url or ""
        self.model = (model or "gpt-4o-mini").strip()
        self.endpoint = build_endpoint(base_url)
        self.timeout = timeout
        self.max_tokens = max_tokens
        self.temperature = temperature

    def chat_json(self, prompt: str, system: str = "", retries: int = 2):
        if not self.api_key:
            raise AIError("未配置 API Key")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system or "你是书签分类助手，只返回 JSON。"},
                {"role": "user", "content": prompt},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        last: Optional[Exception] = None
        for attempt in range(retries + 1):
            try:
                resp = requests.post(self.endpoint, headers=headers, json=body,
                                     timeout=self.timeout)
                raw = resp.text or ""
                if raw.lstrip()[:20].lower().startswith(("<!doctype html", "<html")):
                    raise AIError("接口返回了 HTML，代理地址可能不正确")
                data = json.loads(raw)
                if not resp.ok:
                    msg = (data.get("error") or {}).get("message") or raw[:200]
                    raise AIError(f"HTTP {resp.status_code}: {msg}")
                content = ((data.get("choices") or [{}])[0]
                           .get("message", {}).get("content", ""))
                return extract_json(content)
            except AIError:
                raise
            except Exception as e:  # noqa: BLE001
                last = e
                if attempt < retries:
                    time.sleep(1.2 * (attempt + 1))
        raise AIError(f"调用 AI 失败：{last}")

    def test_connection(self) -> str:
        """返回一段成功说明，失败抛 AIError。"""
        data = self.chat_json('请只返回：{"ok": true}', system="只返回 JSON。", retries=0)
        return f"连接成功 · 模型 {self.model} · 返回 {json.dumps(data, ensure_ascii=False)[:60]}"

    def classify_batch(
        self,
        items: Sequence[Tuple[int, Bookmark]],
        categories: Sequence[str],
        category_descs: Optional[Dict[str, str]] = None,
    ) -> Dict[int, str]:
        """给一批书签分类，返回 {索引: 分类名}。

        category_descs：分类名 → 一句话边界说明（来自分类体系），帮助模型
        理解每个类别的含与不含，显著降低相邻类别误判。未提供时退化为纯列表。
        """
        descs = category_descs or {}
        cat_list = "\n".join(
            f"- {c}：{descs[c]}" if descs.get(c) else f"- {c}"
            for c in categories
        )
        payload = [
            {"id": i, "title": bm.title[:120], "url": bm.url[:300],
             "old_folder": bm.folder[:80]}
            for i, bm in items
        ]
        prompt = (
            "你是书签分类专家。请把下面每条书签归入给定分类之一。\n\n"
            f"可选分类（必须从中选择，不要自创）：\n{cat_list}\n\n"
            "判断依据优先级：URL 域名 > 标题语义 > 原文件夹。\n"
            "判定要求：\n"
            "- 分类后面的说明是判断边界，优先匹配说明中提到的域名与语义。\n"
            "- confidence 判定标准：high=非常确定；medium=有较充分依据（程序会采纳）；"
            "low=完全无法判断（才交给本地规则）。\n"
            "- 请尽量从给定分类中选出最接近的一个，不要轻易填 low；"
            "即使不完全完美，归入最接近的分类也比留空好。\n"
            "- 避免仅凭 URL 中单个英文片段（如 ai / sd / api / tool）就武断归类，\n"
            "  要结合标题与域名整体判断。\n\n"
            "必须严格返回如下 JSON（不要任何解释文字）：\n"
            '{"results":[{"id":0,"category":"分类名","confidence":"high|medium|low",'
            '"reason":"不超过15字"}]}\n\n'
            f"书签列表：\n{json.dumps(payload, ensure_ascii=False)}"
        )
        data = self.chat_json(prompt)
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise AIError("AI 返回结构缺少 results 数组")

        valid = set(categories)
        out: Dict[int, str] = {}
        for r in results:
            try:
                idx = int(r.get("id"))
            except (TypeError, ValueError):
                continue
            cat = str(r.get("category", "")).strip()
            conf = str(r.get("confidence", "medium")).strip().lower()
            # 低置信结果不采纳：交给本地规则引擎兜底，避免 AI 硬猜引入误分类
            if cat in valid and conf in ("high", "medium"):
                out[idx] = cat
        return out

    def judge_alive_batch(self, items: Sequence[Tuple[int, str, str, int, str, str]]) \
            -> Dict[int, Tuple[str, str]]:
        """判断一批「存疑」页面是否真失效。

        items: [(id, title, url, status_code, text, final_url), ...]
              text 为已抓取的正文摘要，final_url 为重定向后的最终地址
              （用于识别跳转到域名停放/售卖页的情况）。
        返回 {id: (alive, reason)}，alive ∈ {"alive", "dead", "uncertain"}。
        仅发送页面文本与最终地址，不把 URL 交给云端浏览器二次抓取，隐私安全。
        """
        payload = [
            {"id": i, "title": (t or "")[:200], "url": (u or "")[:400],
             "status": s, "text": (x or "")[:1500],
             "final_url": (f or "")[:400]}
            for (i, t, u, s, x, f) in items
        ]
        prompt = (
            "你是网页状态判定助手。下面每条是「程序验证时被判为存疑」的书签页面：\n"
            "它们要么返回了某个 HTTP 状态码，要么返回 200 但程序怀疑内容是错误页。\n"
            "请阅读每条的 标题 / URL / 状态码 / 重定向后的最终地址(final_url) / 正文片段，\n"
            "判断该页面实际是否还能正常访问。\n\n"
            "判定原则：\n"
            "- alive：页面是真实可用的内容页（文章、首页、登录页、后台页等）；\n"
            "  或 反爬/验证码/需登录/地区限制 页（站点确实活着，只是拒绝了程序）；\n"
            "  或 单页应用(SPA)骨架（内容由前端加载，正文短是正常的）；\n"
            "  或 返回 200 的空首页 / 目录页。\n"
            "- dead：页面是错误页 / 占位页 / 域名售卖页 / 「站点已关闭」「页面不存在」\n"
            "  「404」「该内容已被删除」等，或整站关停后的统一提示页；\n"
            "  或 final_url 是域名停放/售卖页（Sedo、Afternic、GoDaddy 停放、抢注页）。\n"
            "- uncertain：正文太少无法判断，或无法确认是活是死。\n"
            "  **拿不准就填 uncertain，不要猜。**\n"
            "注意：403 / 451 / 502 / 504 等状态码本身不能说明失效，必须结合正文与 final_url 判断。\n\n"
            "必须严格返回如下 JSON（不要任何解释文字）：\n"
            '{"results":[{"id":0,"alive":"alive|dead|uncertain",'
            '"reason":"不超过20字的中文理由"}]}\n\n'
            f"待判定页面：\n{json.dumps(payload, ensure_ascii=False)}"
        )
        data = self.chat_json(
            prompt, system="你是网页状态判定助手，只返回 JSON。")
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list):
            raise AIError("AI 返回的 alive 判定结构缺少 results 数组")
        out: Dict[int, Tuple[str, str]] = {}
        for r in results:
            try:
                idx = int(r.get("id"))
            except (TypeError, ValueError):
                continue
            alive = str(r.get("alive", "")).strip().lower()
            if alive not in ("alive", "dead", "uncertain"):
                continue
            reason = str(r.get("reason", "")).strip()[:60]
            out[idx] = (alive, reason)
        return out

    def classify_all(
        self,
        bookmarks: Sequence[Bookmark],
        categories: Sequence[str],
        category_descs: Optional[Dict[str, str]] = None,
        batch_size: int = 25,
        workers: int = 3,
        should_stop: Optional[Callable[[], bool]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[int, int]:
        """并发批量分类，就地写入 bm.category。返回 (成功条数, 失败条数)。

        失败条数含 AI 未返回、以及 AI 自认低置信（confidence=low）的条目——
        这两类都会由调用方用本地规则补齐，避免 AI 硬猜。
        """
        targets = [(i, bm) for i, bm in enumerate(bookmarks) if bm.keep]
        if not targets:
            return 0, 0

        batches = [targets[i: i + batch_size] for i in range(0, len(targets), batch_size)]
        ok = failed = 0
        done = 0

        def run(batch):
            return self.classify_batch(batch, categories, category_descs)

        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            futs = {ex.submit(run, b): b for b in batches}
            for f in as_completed(futs):
                batch = futs[f]
                try:
                    mapping = f.result()
                except Exception:  # noqa: BLE001
                    mapping = {}
                hit = 0
                for idx, cat in mapping.items():
                    if 0 <= idx < len(bookmarks):
                        bookmarks[idx].category = cat
                        hit += 1
                del hit
                ok += len(mapping)
                failed += max(0, len(batch) - len(mapping))
                done += len(batch)
                if on_progress:
                    on_progress(done, len(targets))
                if should_stop and should_stop():
                    for p in futs:
                        p.cancel()
                    break
        return ok, failed
