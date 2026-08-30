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
    ) -> Dict[int, str]:
        """给一批书签分类，返回 {索引: 分类名}。"""
        cat_list = "\n".join(f"- {c}" for c in categories)
        payload = [
            {"id": i, "title": bm.title[:120], "url": bm.url[:300],
             "old_folder": bm.folder[:80]}
            for i, bm in items
        ]
        prompt = (
            "你是书签分类专家。请把下面每条书签归入给定分类之一。\n\n"
            f"可选分类（必须从中选择，不要自创）：\n{cat_list}\n\n"
            "判断依据优先级：URL 域名 > 标题语义 > 原文件夹。\n"
            "必须严格返回如下 JSON（不要任何解释文字）：\n"
            '{"results":[{"id":0,"category":"分类名","reason":"不超过15字"}]}\n\n'
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
            if cat in valid:
                out[idx] = cat
        return out

    def classify_all(
        self,
        bookmarks: Sequence[Bookmark],
        categories: Sequence[str],
        batch_size: int = 25,
        workers: int = 3,
        should_stop: Optional[Callable[[], bool]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[int, int]:
        """并发批量分类，就地写入 bm.category。返回 (成功条数, 失败条数)。"""
        targets = [(i, bm) for i, bm in enumerate(bookmarks) if bm.keep]
        if not targets:
            return 0, 0

        batches = [targets[i: i + batch_size] for i in range(0, len(targets), batch_size)]
        ok = failed = 0
        done = 0

        def run(batch):
            return self.classify_batch(batch, categories)

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
