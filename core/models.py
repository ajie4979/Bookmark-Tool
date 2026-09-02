"""书签数据模型与状态词典。

v2.0 核心变化：验证结果从「单状态码」升级为「多次探测 + 结论 + 置信度 + 子类型」，
因为失效不是 URL 的绝对属性，而是「URL × 时刻 × 网络出口」的联合结果。
"""

from dataclasses import dataclass, field
from typing import List, Optional
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, unquote

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "spm", "from", "ref", "ref_src", "referer", "share_token", "share_source",
    "share_medium", "share_plat", "share_session_id", "share_tag", "unique_k",
    "vd_source", "seid", "src", "source", "track", "utm_id", "utm_name",
    "gclid", "fbclid", "mc_cid", "mc_eid", "igshid", "tt_medium", "tt_content",
}

# ---------------------------------------------------------------- 结论
#
# 极简判定（用户口径：能打开网页就正常，打不开才不正常）：
#   · 服务器有任何响应（2xx/3xx/401/403/429/451/5xx，甚至 TLS 回了握手）
#     == 站点活着 == 可访问
#   · 只有「页面确实没了(404/410)」或「域名没了/端口连不上」== 已失效
#   · 完全无响应（超时/网络不通）== 存疑，交给人工决定
V_OK = "可访问"
V_SUSPECT = "存疑"          # 仅「完全连不上（超时/无响应）」才存疑
V_DEAD = "已失效"           # 404/410 / DNS 失败 / 连接失败
V_SKIPPED = "跳过"
V_UNKNOWN = "未检测"

VERDICTS = [V_UNKNOWN, V_OK, V_SUSPECT, V_DEAD, V_SKIPPED]

# 子类型（不单独成列，避免状态爆炸；在 tooltip 与筛选器中展示）
ST_LIMITED = "访问受限"       # 401/403/429
ST_BLOCKED = "地区限制"       # 451
ST_SERVER = "服务端错误"      # 5xx
ST_GATEWAY = "网关错误"       # 502/504：网关或代理层面失败，不能证明站点活着
ST_TIMEOUT = "网络超时"
ST_UNREACHABLE = "无法连接"
ST_TLS = "TLS限制"
ST_SOFT404 = "疑似软404"
ST_LANDING = "疑似统一页面"    # 同域名多个链接内容/跳转完全一致 → 站点多半已关停
ST_CONFLICT = "环境矛盾"      # 不同出口结果不一致
ST_NOTFOUND = "页面不存在"    # 404/410
ST_NODNS = "域名不存在"
ST_MANUAL_OK = "人工标记可访问"
ST_MANUAL_DEAD = "人工标记失效"
ST_RULE_SKIP = "已跳过（用户规则）"
ST_AI_OK = "AI 判可访问"       # AI 读页面正文后判定为真页面
ST_AI_DEAD = "AI 判失效"       # AI 读页面正文后判定为错误/占位/关停页

SUBTYPES = [
    ST_LIMITED, ST_BLOCKED, ST_SERVER, ST_GATEWAY, ST_TIMEOUT, ST_UNREACHABLE,
    ST_TLS, ST_SOFT404, ST_LANDING, ST_CONFLICT, ST_NOTFOUND, ST_NODNS,
    ST_MANUAL_OK, ST_MANUAL_DEAD, ST_RULE_SKIP, ST_AI_OK, ST_AI_DEAD,
]

# 置信度
CONF_HIGH = "高"
CONF_MID = "中"
CONF_LOW = "低"

# 网络出口
EXIT_DIRECT = "直连"
EXIT_SYSTEM = "系统代理"
EXIT_CUSTOM = "自定义代理"

# 人工裁定
OVERRIDE_OK = "ok"
OVERRIDE_DEAD = "dead"

# 视为「确有问题」的结论。存疑不计入——站点本身是活的，只是程序确认不了。
BAD_VERDICTS = {V_DEAD}

STATUS_HINT = {
    V_OK: "服务器有响应（2xx/3xx 或 TLS 握手），站点活着、可访问",
    V_DEAD: "页面确实不存在（404/410）或域名/端口连不上，链接失效",
    V_SUSPECT: "程序完全连不上（超时/无响应），无法确认站点是否活着。"
               "这类多半能在浏览器打开，建议换网络出口复检或手动标记。**存疑≠失效**",
    V_SKIPPED: "chrome:// 等特殊协议，无法也不必检测",
    V_UNKNOWN: "尚未检测",
}

SUBTYPE_HINT = {
    ST_LIMITED: "HTTP 401/403/429，站点拒绝了程序访问",
    ST_BLOCKED: "HTTP 451，因法律或地区原因不可用（换网络环境可能能开）",
    ST_SERVER: "HTTP 5xx，对方服务器故障，多半是临时的",
    ST_GATEWAY: "HTTP 502/504，网关或代理连不上目标站点。走代理时尤其常见——"
                "代理自己连不上也会返回 502，**不能证明站点还活着**，故记为存疑",
    ST_TIMEOUT: "请求超时，站点慢或网络不通",
    ST_UNREACHABLE: "DNS 解析失败或连接被拒（非 TLS）",
    ST_TLS: "程序无法完成 TLS 握手：常见于国密站点、反爬 WAF、代理/网络的 TLS 限制。"
            "**不代表链接失效**——浏览器通常能正常打开。建议换网络出口复检或直接打开确认",
    ST_SOFT404: "返回 200 但页面内容像「页面不存在」",
    ST_LANDING: "同域名下多个不同链接返回完全相同的内容，或全部跳转到同一个地址。"
                "站点多半已关停并做了全站兜底跳转。**单条看不出异常，横向比对才发现**",
    ST_CONFLICT: "不同网络出口结果不一致，说明该站点需要特定网络环境",
    ST_NOTFOUND: "HTTP 404/410",
    ST_NODNS: "域名无法解析，站点多半已关闭",
    ST_MANUAL_OK: "你手动标记为可访问，不会被自动检测覆盖",
    ST_MANUAL_DEAD: "你手动标记为已失效，不会被自动检测覆盖",
    ST_RULE_SKIP: "命中你设置的跳过规则",
    ST_AI_OK: "AI 阅读页面正文后判定为真实可用的页面（原被判为存疑）",
    ST_AI_DEAD: "AI 阅读页面正文后判定为错误页/占位页/站点已关停（原被判为存疑）",
}


def normalize_url(url: str, drop_tracking: bool = True, drop_fragment: bool = True) -> str:
    """归一化 URL，用于去重比对（保留 http/https 差异）。"""
    if not url:
        return ""
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return url.lower()

    scheme = (parts.scheme or "http").lower()
    host = (parts.netloc or "").lower()
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    if host.endswith(":80") and scheme == "http":
        host = host[:-3]
    elif host.endswith(":443") and scheme == "https":
        host = host[:-4]
    # www. 前缀只是别名，归一化掉才能把 www.x.com 与 x.com 视为同一资源
    if host.startswith("www."):
        host = host[4:]

    path = unquote(parts.path or "")
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    if not path:
        path = "/"

    query = parts.query
    if query and drop_tracking:
        pairs = [(k, v) for k, v in parse_qsl(query, keep_blank_values=True)
                 if k.lower() not in TRACKING_PARAMS]
        query = urlencode(pairs)

    fragment = "" if drop_fragment else parts.fragment
    return urlunsplit((scheme, host, path, query, fragment))


def domain_of(url: str) -> str:
    try:
        host = urlsplit(url).netloc.lower()
    except ValueError:
        return ""
    if "@" in host:
        host = host.rsplit("@", 1)[1]
    if ":" in host:
        host = host.split(":", 1)[0]
    return host[4:] if host.startswith("www.") else host


@dataclass
class Probe:
    """一次探测记录。多次探测可并存，新结果叠加而非覆盖。"""
    exit_profile: str = ""      # 直连 / 系统代理 / 自定义代理
    session_id: str = ""
    ts: int = 0
    method: str = ""            # 最终采用的方法：HEAD / GET
    status_code: int = 0
    head_code: int = 0          # HEAD 的原始状态码（若曾降级到 GET，便于排查）
    final_url: str = ""
    soft404: bool = False
    error: str = ""
    elapsed_ms: int = 0
    public_ip: str = ""
    # 以下三项用于「全站统一页面」识别：单条探测看不出异常，
    # 必须把所有结果横向比对才能发现（见 prober.mark_uniform_pages）。
    body_hash: str = ""     # 响应正文 SHA1 前 16 位，仅 2xx 且读取到正文时有值
    body_len: int = 0
    is_spa: bool = False    # 单页应用骨架：所有路由共用一份 index.html，不能算统一错误页
    uniform: bool = False   # 后处理判定：与同域名其它链接内容/跳转完全一致
    text: str = ""         # 响应正文清理后的摘要（前 ~2000 字），供软404识别与 AI 判活复用

    @property
    def ok(self) -> bool:
        """是否真的「打开成功」。

        软 404 / 统一页面虽然状态码是 200，但内容层面已经证明页面不对劲，
        不能算成功。否则 merge_verdict 的①分支（任一出口 ok → 可访问）
        会在这里短路，后面的软 404、统一页面判断永远走不到。
        """
        return (200 <= self.status_code < 400
                and not self.soft404 and not self.uniform)

    def brief(self) -> str:
        if self.error:
            return f"{self.exit_profile} · {self.error}"
        extra = ""
        if self.head_code and self.head_code != self.status_code:
            extra = f"（HEAD {self.head_code} → GET {self.status_code}）"
        return f"{self.exit_profile} · {self.method} {self.status_code}{extra}"


@dataclass
class Bookmark:
    title: str = ""
    url: str = ""
    folder: str = ""
    add_date: int = 0
    icon: str = ""

    # 去重
    dup_group: int = -1
    is_primary: bool = True
    keep: bool = True
    dup_type: str = ""          # 完全一致 / 标准化一致（去重时写入）

    # 验证（v2.0）
    verdict: str = V_UNKNOWN
    subtype: str = ""
    confidence: str = ""
    probes: List[Probe] = field(default_factory=list)
    override: str = ""          # OVERRIDE_OK / OVERRIDE_DEAD
    last_checked: int = 0

    # 界面临时选择状态（勾选列），不持久化、不参与导出/导航生成
    selected: bool = False

    # 归类
    category: str = ""
    category_source: str = ""   # ai / rule / manual

    # AI 判活（仅对存疑项，复用已抓取的正文文本，不二次请求）
    ai_verdict: str = ""        # "" / alive / dead / uncertain
    ai_reason: str = ""

    def __post_init__(self):
        if not self.title:
            self.title = self.url

    # ---------- 派生属性 ----------
    @property
    def norm(self) -> str:
        return normalize_url(self.url)

    @property
    def domain(self) -> str:
        return domain_of(self.url)

    @property
    def effective_verdict(self) -> str:
        """人工裁定优先。"""
        if self.override == OVERRIDE_OK:
            return V_OK
        if self.override == OVERRIDE_DEAD:
            return V_DEAD
        return self.verdict

    @property
    def effective_subtype(self) -> str:
        if self.override == OVERRIDE_OK:
            return ST_MANUAL_OK
        if self.override == OVERRIDE_DEAD:
            return ST_MANUAL_DEAD
        return self.subtype

    @property
    def is_bad(self) -> bool:
        return self.effective_verdict in BAD_VERDICTS

    @property
    def exits(self) -> str:
        """这条书签在哪些出口下探测过。"""
        seen = []
        for p in self.probes:
            if p.exit_profile and p.exit_profile not in seen:
                seen.append(p.exit_profile)
        if not seen:
            return ""
        return "全部" if len(seen) > 1 else seen[0]

    def display_title(self, limit: int = 60) -> str:
        t = " ".join((self.title or "").split())
        return t if len(t) <= limit else t[: limit - 1] + "…"

    def add_probe(self, probe: Probe):
        """同出口的旧探测被替换，不同出口的保留——这是复检能叠加的关键。"""
        self.probes = [p for p in self.probes
                       if p.exit_profile != probe.exit_profile]
        self.probes.append(probe)
        self.last_checked = probe.ts

    def merge_verdict(self):
        """合并多出口探测，给出「能打开就正常 / 打不开才失效」的结论。

        核心原则：只要服务器有任何响应，就说明站点活着 → 可访问；
        只有「页面确实没了(404/410)」或「域名没了/连不上」才算失效；
        完全无响应(超时/网络不通)才留作存疑，由人工决定。
        """
        if self.override:
            return

        probes = [p for p in self.probes if p.exit_profile]
        if not probes:
            self.verdict, self.subtype, self.confidence = V_UNKNOWN, "", ""
            return

        # ① 任一出口真正 2xx/3xx → 可访问（高）
        if any(p.ok for p in probes):
            self.verdict = V_OK
            self.subtype = ST_CONFLICT if any(not p.ok for p in probes) else ""
            self.confidence = CONF_HIGH
            return

        codes = [p.status_code for p in probes if not p.error]
        errors = [p.error for p in probes if p.error]
        soft404 = any(p.soft404 for p in probes)
        landing = any(p.uniform for p in probes)

        # ② 明确「页面不存在」(404/410) → 已失效（高）
        if codes and all(c in (404, 410) for c in codes):
            self.verdict, self.subtype, self.confidence = V_DEAD, ST_NOTFOUND, CONF_HIGH
            return

        # ③ 服务器有响应 = 站点活着 → 可访问（中），仅记录原因
        if codes:
            # 502/504 是**网关/代理层面**的失败，不是目标站点的响应。
            # 走代理时这一点尤其关键：代理连不上目标端口就会返回 502，
            # 若按「5xx = 站点在运行」判成可访问，会把真失效的链接救活成假活链接。
            # 因此 502/504 不计入可访问，降级为存疑交由人工/复检确认。
            if any(c in (502, 504) for c in codes):
                self.verdict, self.subtype, self.confidence = (
                    V_SUSPECT, ST_GATEWAY, CONF_LOW)
                return
            # 软 404：服务器返回 200，内容却明摆着写着「页面不存在」。
            # 此前这里判 V_OK —— 明明检测出来了却报「可访问」，导致这批
            # 假活链接一直藏在「可访问」里、用户完全看不见。改为存疑，
            # 让它们浮到「显示范围 → 仅存疑」里供人工复核。
            if soft404:
                self.verdict, self.subtype, self.confidence = (
                    V_SUSPECT, ST_SOFT404, CONF_MID)
                return

            # 全站统一页面：同域名下多个不同链接返回完全相同的正文，
            # 或全部跳转到同一个地址 —— 站点多半已关停并做了兜底跳转。
            # 这是 prober.mark_uniform_pages() 在全部探测结束后横向比对出来的。
            if landing:
                self.verdict, self.subtype, self.confidence = (
                    V_SUSPECT, ST_LANDING, CONF_MID)
                return

            if any(c in (401, 403, 429) for c in codes):
                sub = ST_LIMITED          # 反爬/需登录，浏览器能开
            elif any(c == 451 for c in codes):
                sub = ST_BLOCKED          # 地区/法律限制
            elif any(500 <= c < 600 for c in codes):
                sub = ST_SERVER           # 服务端临时故障，站点在运行
            else:
                sub = ST_LIMITED
            self.verdict, self.subtype, self.confidence = V_OK, sub, CONF_MID
            return

        # ④ 域名彻底没了 / 端口连不上 → 已失效（高）
        if errors and all("域名无法解析" in e or "连接被拒绝" in e for e in errors):
            sub = ST_NODNS if any("域名无法解析" in e for e in errors) else ST_UNREACHABLE
            self.verdict, self.subtype, self.confidence = V_DEAD, sub, CONF_HIGH
            return

        # ⑤ TLS/证书：服务器回了握手，但 TLS 协商失败。
        #    这只能说明服务器在监听 443，**不能证明页面能正常打开**——
        #    可能是国密站点、反爬 WAF、代理 TLS 限制，也可能是站点已关停
        #    但服务器还在。故降级为「存疑」交由人工确认，而非直接判「可访问」。
        if any(("SSL" in e or "证书" in e or "TLS" in e) for e in errors):
            self.verdict, self.subtype, self.confidence = V_SUSPECT, ST_TLS, CONF_LOW
            return

        # ⑤b 连接重置 / 重定向过多：服务器有响应但主动断开或重定向循环，
        #     典型反爬行为（如 mp.pipix.com 对非浏览器请求直接 RST）。
        #     站点活着，只是拒绝了程序请求 → 可访问（访问受限），浏览器能开。
        if any(("连接重置" in e or "重定向次数过多" in e) for e in errors):
            self.verdict, self.subtype, self.confidence = V_OK, ST_LIMITED, CONF_MID
            return

        # ⑥ 其余：超时 / 无响应 / 其它 → 存疑（低）
        sub = ST_TIMEOUT if any("超时" in e for e in errors) else ST_UNREACHABLE
        self.verdict, self.subtype, self.confidence = V_SUSPECT, sub, CONF_LOW


VERDICT_ORDER_MAP = {
    V_OK: 0, V_UNKNOWN: 1, V_SKIPPED: 2, V_SUSPECT: 3, V_DEAD: 4,
}


def verdict_sort_key(bm: "Bookmark") -> int:
    """表格按结论排序时的优先级：可访问 < 存疑 < 已失效。"""
    return VERDICT_ORDER_MAP.get(bm.effective_verdict, 9)
