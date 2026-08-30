"""多出口可达性验证引擎（v2.0 核心）。

设计要点见 docs/设计文档.md 第 5 章。核心思想：

  失效不是 URL 的绝对属性，而是「URL × 时刻 × 网络出口」的联合结果。
  因此每条书签保留多次探测记录（probes），切换网络复检时新结果**叠加**而非覆盖，
  最终用「乐观合并」判定：任一出口能通即判可访问。

单次探测内部走降级链：
  HEAD（完整浏览器头）→ GET（只读 64KB）→ 软404检测 → 换 UA / 关 SSL 重试
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence
from urllib.parse import urlsplit

import requests
import urllib3
from requests.adapters import HTTPAdapter

from .models import (
    EXIT_CUSTOM, EXIT_DIRECT, EXIT_SYSTEM, V_DEAD, V_OK, V_SKIPPED,
    V_SUSPECT, V_UNKNOWN, Bookmark, Probe, domain_of,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
try:
    import warnings
    warnings.filterwarnings("ignore", category=urllib3.exceptions.InsecureRequestWarning)
except Exception:  # noqa: BLE001
    pass

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
ALT_UA = (
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
)

SKIP_SCHEMES = {
    "javascript", "chrome", "edge", "about", "moz-extension",
    "chrome-extension", "edge-extension", "data", "blob", "view-source",
}

BODY_LIMIT = 65536          # 软 404 检测只读前 64KB

SOFT404_PATTERNS = [
    r"页面不存在", r"内容已删除", r"资源已下线", r"找不到该页面",
    r"该页面已被删除", r"您访问的页面", r"页面已失效", r"内容不存在",
    r"page not found", r"\b404\b.{0,20}not found",
    r"no longer available", r"this (page|content) (has been )?removed",
    r"couldn'?t find (that|this) page", r"page you requested",
]
RE_SOFT404 = re.compile("|".join(SOFT404_PATTERNS), re.I)
RE_TAG = re.compile(r"<[^>]+>")
RE_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def browser_headers(user_agent: str = DEFAULT_UA) -> dict:
    """模拟真实 Chrome 的完整请求头，降低被 WAF 拦截的概率。

    实测提示：对 Cloudflare 的 JS 挑战无效，但仍能改善一部分误判。
    """
    return {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                  "image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Connection": "keep-alive",
    }


# ---------------------------------------------------------------- 节流
_domain_lock = threading.Lock()
_domain_next: Dict[str, float] = {}


def _throttle(domain: str, delay: float):
    """同域名最小访问间隔，避免瞬间打出几十个请求被封。

    在锁内预约时间槽，在锁外等待——不阻塞其它域名。
    """
    if delay <= 0 or not domain:
        return
    with _domain_lock:
        now = time.monotonic()
        earliest = _domain_next.get(domain, 0.0)
        wait = max(0.0, earliest - now)
        _domain_next[domain] = max(now, earliest) + delay
    if wait > 0:
        time.sleep(min(wait, 3.0))


def reset_throttle():
    with _domain_lock:
        _domain_next.clear()


# ---------------------------------------------------------------- 配置
@dataclass
class ProbeConfig:
    exit_profile: str = EXIT_SYSTEM
    custom_proxy: str = ""
    workers: int = 32
    timeout: float = 8.0
    retries: int = 1
    verify_ssl: bool = False
    domain_delay: float = 0.1        # 秒
    enable_fallback: bool = True     # HEAD 失败降级 GET
    enable_soft404: bool = True
    record_public_ip: bool = False
    user_agent: str = DEFAULT_UA


def resolve_proxies(cfg: ProbeConfig) -> Optional[dict]:
    """把出口配置翻译成 requests 的 proxies 参数。"""
    if cfg.exit_profile == EXIT_DIRECT:
        return {"http": "", "https": ""}
    if cfg.exit_profile == EXIT_CUSTOM and cfg.custom_proxy:
        p = cfg.custom_proxy.strip()
        if p and "://" not in p:
            p = "http://" + p
        return {"http": p, "https": p}
    return None                       # 系统代理：交给 requests 的环境变量逻辑


_local = threading.local()


def _session(cfg: ProbeConfig) -> requests.Session:
    s = getattr(_local, "session", None)
    if s is None:
        size = max(4, min(cfg.workers, 64))
        s = requests.Session()
        s.trust_env = cfg.exit_profile == EXIT_SYSTEM
        adapter = HTTPAdapter(pool_connections=size, pool_maxsize=size, max_retries=0)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        _local.session = s
        _local.cfg_key = None
    return s


def detect_public_ip(cfg: ProbeConfig, timeout: float = 4.0) -> str:
    """查询当前出口的公网 IP，用于事后追溯「这批结果是在什么网络下测的」。"""
    proxies = resolve_proxies(cfg)
    for url in ("https://myip.ipip.net", "https://api.ipify.org?format=text"):
        try:
            r = requests.get(url, timeout=timeout, proxies=proxies,
                             headers={"User-Agent": "curl/8.0"})
            if r.ok:
                return " ".join(r.text.split())[:60]
        except Exception:  # noqa: BLE001
            continue
    return ""


# ---------------------------------------------------------------- 软 404
def _looks_like_soft404(body: str) -> bool:
    """命中失效特征词，且（正文很短 或 标题含 404）才判定，避免正文提到 404 就误杀。"""
    if not body:
        return False
    text = RE_TAG.sub(" ", body[:BODY_LIMIT])
    text = " ".join(text.split())
    if not RE_SOFT404.search(text):
        return False
    if len(text) < 3072:
        return True
    m = RE_TITLE.search(body[:BODY_LIMIT])
    if m:
        title = " ".join(RE_TAG.sub(" ", m.group(1)).split())
        if RE_SOFT404.search(title):
            return True
    return False


# ---------------------------------------------------------------- 单次探测
def probe_one(
    bm: Bookmark,
    cfg: ProbeConfig,
    session_id: str = "",
    public_ip: str = "",
    skip_scheme_ok: bool = True,
) -> Probe:
    """对单条书签做一次完整探测（含降级链），返回 Probe。"""
    ts = int(time.time())
    p = Probe(exit_profile=cfg.exit_profile, session_id=session_id,
              ts=ts, public_ip=public_ip)

    try:
        scheme = urlsplit(bm.url).scheme.lower()
    except ValueError:
        p.error = "URL 格式非法"
        return p

    if scheme in SKIP_SCHEMES or scheme == "file":
        p.error = "本地或特殊协议，跳过"
        p.status_code = 0
        return p
    if scheme not in ("http", "https"):
        p.error = f"不支持的协议 {scheme}"
        return p

    domain = domain_of(bm.url)
    sess = _session(cfg)
    proxies = resolve_proxies(cfg)
    t0 = time.monotonic()

    last_err = ""
    for attempt in range(cfg.retries + 1):
        _throttle(domain, cfg.domain_delay)
        try:
            headers = browser_headers(cfg.user_agent if attempt == 0 else ALT_UA)
            verify = cfg.verify_ssl

            resp = sess.head(bm.url, headers=headers, timeout=cfg.timeout,
                             allow_redirects=True, proxies=proxies, verify=verify)
            code = resp.status_code
            p.method = "HEAD"
            final_url = resp.url

            # 降级到 GET 复核。
            #
            # 关键：绝不能只凭 HEAD 的 404 就判死。很多站点（尤其是经过 CDN 的
            # 国内站）根本没正确实现 HEAD，会直接返回 404，而 GET 是正常的 200。
            # 实测样例：yige.baidu.com / chat.baidu.com / arc.tencent.com
            # 都是 HEAD=404、GET=200。
            # 因此这里对**所有** 4xx/5xx 都用 GET 复核一遍。
            need_body = cfg.enable_soft404 and 200 <= code < 300
            need_recheck = (code == 0 or code >= 400) and cfg.enable_fallback
            if need_recheck or need_body:
                resp = sess.get(bm.url, headers=headers, timeout=cfg.timeout,
                                allow_redirects=True, stream=True,
                                proxies=proxies, verify=verify)
                try:
                    body = resp.raw.read(BODY_LIMIT, decode_content=True) \
                        if resp.raw else b""
                except Exception:  # noqa: BLE001
                    body = b""
                finally:
                    resp.close()
                p.head_code = code          # 保留 HEAD 的原始结果，便于排查
                code = resp.status_code
                final_url = resp.url
                p.method = "GET"
                if cfg.enable_soft404 and 200 <= code < 300:
                    try:
                        text = body.decode(resp.encoding or "utf-8", "replace")
                    except Exception:  # noqa: BLE001
                        text = ""
                    p.soft404 = _looks_like_soft404(text)

            p.status_code = code
            p.final_url = str(final_url or bm.url)
            p.elapsed_ms = int((time.monotonic() - t0) * 1000)
            return p

        except requests.exceptions.Timeout:
            last_err = "请求超时"
        except requests.exceptions.SSLError:
            if cfg.verify_ssl and attempt < cfg.retries:
                cfg.verify_ssl = False     # 证书问题，重试时放宽
                last_err = "SSL 证书错误，重试"
                continue
            last_err = "SSL 证书错误"
            break
        except requests.exceptions.TooManyRedirects:
            last_err = "重定向次数过多"
            break
        except requests.exceptions.ProxyError:
            last_err = "代理连接失败"
        except requests.exceptions.ConnectionError as e:
            msg = str(e).lower()
            if any(k in msg for k in ("getaddrinfo", "name or service not known",
                                      "nodename nor servname", "name resolution")):
                last_err = "域名无法解析"
                break
            if "refused" in msg:
                last_err = "连接被拒绝"
                break
            last_err = "连接失败"
        except Exception as e:  # noqa: BLE001
            last_err = type(e).__name__
            break

        if attempt < cfg.retries:
            time.sleep(0.4 * (attempt + 1))

    p.error = last_err or "未知错误"
    p.elapsed_ms = int((time.monotonic() - t0) * 1000)
    return p


# ---------------------------------------------------------------- 批量
def probe_all(
    bookmarks: Sequence[Bookmark],
    cfg: ProbeConfig,
    only_kept: bool = True,
    only: Optional[Sequence[Bookmark]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[int, int, Bookmark], None]] = None,
) -> Dict[str, int]:
    """并发探测一批书签，就地写入 probes 并合并结论。

    only: 指定只探测这些条目（复检时用）；否则按 only_kept 过滤。
    """
    if only is not None:
        targets = list(only)
    else:
        targets = [b for b in bookmarks if b.keep or not only_kept]

    total = len(targets)
    stats: Dict[str, int] = {"total": total, "skipped": 0}
    if total == 0:
        return stats

    session_id = uuid.uuid4().hex[:8]
    public_ip = detect_public_ip(cfg) if cfg.record_public_ip else ""

    done = 0
    lock = threading.Lock()

    def run(bm: Bookmark):
        nonlocal done
        if should_stop and should_stop():
            return
        probe = probe_one(bm, cfg, session_id=session_id, public_ip=public_ip)
        bm.add_probe(probe)
        bm.merge_verdict()
        with lock:
            done += 1
            cur = done
            v = bm.effective_verdict
            stats[v] = stats.get(v, 0) + 1
            if probe.error and "跳过" in probe.error:
                stats["skipped"] += 1
        if on_progress:
            on_progress(cur, total, bm)

    reset_throttle()
    with ThreadPoolExecutor(max_workers=max(1, cfg.workers)) as ex:
        futs = [ex.submit(run, bm) for bm in targets]
        for f in as_completed(futs):
            if should_stop and should_stop():
                for p in futs:
                    p.cancel()
                break
            try:
                f.result()
            except Exception:  # noqa: BLE001
                pass

    return stats


# ---------------------------------------------------------------- 复检
def collect_for_recheck(bookmarks: Sequence[Bookmark],
                        also_dead: bool = True) -> List[Bookmark]:
    """收集需要复检的条目：所有存疑项，以及（可选）已失效项。"""
    out = []
    for b in bookmarks:
        if not b.keep or b.override:
            continue
        v = b.verdict
        if v == V_SUSPECT or (also_dead and v == V_DEAD) or v == V_UNKNOWN:
            out.append(b)
    return out
