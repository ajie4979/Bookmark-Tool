"""核心模块冒烟测试。

全部离线：解析 → 去重 → 分类 → 导航页 → 导出回读 → 乐观合并 → 域名规则。
使用 tests/sample_bookmarks.html 合成样本，不依赖真实书签数据，不发网络请求。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import classifier, navgen, parser, rules as rules_mod  # noqa: E402
from core.classifier import (  # noqa: E402
    DEFAULT_CATEGORY, DEFAULT_TAXONOMY, classify_one, load_taxonomy,
)
from core.dedupe import LEVEL_LOOSE, LEVEL_NORMAL, LEVEL_STRICT, deduplicate  # noqa: E402
from core.models import (  # noqa: E402
    CONF_LOW, CONF_MID, EXIT_DIRECT, EXIT_SYSTEM, STATUS_HINT, ST_AI_DEAD,
    ST_AI_OK, ST_LANDING, ST_LIMITED, ST_SOFT404, ST_TLS, SUBTYPE_HINT,
    V_DEAD, V_OK, V_SUSPECT, V_UNKNOWN, Bookmark, Probe,
    normalize_url,
)

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "tests", "sample_bookmarks.html")
TMP = os.path.join(HERE, "_tmp_test_out")

results = []


def check(name, fn):
    try:
        info = fn()
        results.append(("通过", name, info or ""))
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        results.append(("失败", name, f"{type(e).__name__}: {e}"))


def t_parse():
    folders, bms = parser.load_bookmarks(SRC)
    assert len(bms) >= 30, f"样本解析数量异常：{len(bms)}"
    return f"{len(bms)} 条 / {len(folders)} 个文件夹"


def t_normalize():
    a = normalize_url("https://Example.COM/a/?utm_source=x&b=1#top")
    b = normalize_url("https://example.com/a?b=1")
    assert a == b, f"{a} != {b}"
    return a


def t_dedupe():
    _, bms = parser.load_bookmarks(SRC)
    deduplicate(bms, LEVEL_STRICT)
    strict = sum(1 for x in bms if not x.keep)
    deduplicate(bms, LEVEL_NORMAL)
    normal = sum(1 for x in bms if not x.keep)
    assert normal >= strict >= 1, f"严格 {strict} / 标准 {normal}"
    return f"严格剔除 {strict}，标准剔除 {normal}"


def t_classify():
    _, bms = parser.load_bookmarks(SRC)
    deduplicate(bms, LEVEL_NORMAL)
    tax = classifier.load_taxonomy("")
    counts = classifier.classify_all(bms, tax, only_kept=True)
    assert len(counts) >= 5, f"分类数过少：{len(counts)}"
    return f"{len(counts)} 个分类，未分类 {counts.get('其他未分类', 0)} 条"


def t_nav():
    _, bms = parser.load_bookmarks(SRC)
    deduplicate(bms, LEVEL_NORMAL)
    os.makedirs(TMP, exist_ok=True)
    p = os.path.join(TMP, "nav.html")
    n = navgen.generate_nav(bms, p, title="测试导航")
    assert os.path.getsize(p) > 5000
    return f"{n} 条 / {os.path.getsize(p)//1024} KB"


def t_export_roundtrip():
    _, bms = parser.load_bookmarks(SRC)
    os.makedirs(TMP, exist_ok=True)
    a = os.path.join(TMP, "a.html")
    b = os.path.join(TMP, "b.json")
    parser.export_netscape(bms, a)
    parser.export_json(bms, b)
    _, r1 = parser.load_bookmarks(a)
    _, r2 = parser.load_bookmarks(b)
    assert len(r1) == len(bms) == len(r2), f"{len(bms)}/{len(r1)}/{len(r2)}"
    return f"HTML {len(r1)} 条，JSON {len(r2)} 条"


# ---------------- 乐观合并（离线，手工构造探测记录）----------------
def _mk(probes):
    bm = Bookmark(title="t", url="https://example.com/x")
    for exit_name, code, err, soft in probes:
        bm.add_probe(Probe(exit_profile=exit_name, status_code=code,
                           error=err, soft404=soft, ts=1))
    bm.merge_verdict()
    return bm


def t_merge_ok_when_any_exit_succeeds():
    """核心规则：任一出口成功即判可访问，并标注环境矛盾。"""
    bm = _mk([(EXIT_DIRECT, 0, "连接被拒绝", False),
              (EXIT_SYSTEM, 200, "", False)])
    assert bm.verdict == V_OK, bm.verdict
    assert bm.subtype == "环境矛盾", bm.subtype
    return "直连失败 + 代理成功 → 可访问（环境矛盾）"


def t_merge_dead_when_all_404():
    bm = _mk([(EXIT_DIRECT, 404, "", False), (EXIT_SYSTEM, 410, "", False)])
    assert bm.verdict == V_DEAD, bm.verdict
    return "全部 404/410 → 已失效（高置信）"


def t_merge_limited_on_403():
    """401/403/429 说明站点活着只是拒绝程序访问，判「可访问」（不是失效也不是存疑）。"""
    bm = _mk([(EXIT_DIRECT, 403, "", False), (EXIT_SYSTEM, 403, "", False)])
    assert bm.verdict == V_OK, bm.verdict
    assert bm.subtype == ST_LIMITED, bm.subtype
    assert bm.confidence == CONF_MID, bm.confidence
    return "全部 403 → 可访问（访问受限，站点活着）"


def t_merge_soft404_is_suspect():
    """软 404 必须判「存疑」而不是「可访问」。

    此前判 V_OK，导致明明检测出「内容像页面不存在」却报可访问，
    这批假活链接一直藏在可访问里、用户根本看不见。
    """
    bm = _mk([(EXIT_SYSTEM, 200, "", True)])
    assert bm.verdict == V_SUSPECT, bm.verdict
    assert bm.subtype == ST_SOFT404, bm.subtype
    return "200 且内容像「页面不存在」→ 存疑（不再藏在可访问里）"


def _mk_probed(url, body_hash="", body_len=2048, is_spa=False, final_url=""):
    """造一条已探测完毕的书签（含正文指纹），用于统一页面判定测试。"""
    bm = Bookmark(title="t", url=url)
    bm.add_probe(Probe(exit_profile=EXIT_DIRECT, status_code=200, ts=1,
                       body_hash=body_hash, body_len=body_len, is_spa=is_spa,
                       final_url=final_url or url))
    bm.merge_verdict()
    return bm


def t_uniform_by_redirect():
    """同域名 3 个不同链接全部跳到同一地址 → 站点关停后的兜底跳转。"""
    from core.prober import mark_uniform_pages
    bms = [_mk_probed(f"https://old-site.com/post{i}",
                      final_url="https://old-site.com/") for i in range(3)]
    n = mark_uniform_pages(bms)
    assert n == 3, f"应标记 3 条，实际 {n}"
    assert all(b.verdict == V_SUSPECT for b in bms), [b.verdict for b in bms]
    assert all(b.subtype == ST_LANDING for b in bms), [b.subtype for b in bms]
    return "3 条不同链接跳同一地址 → 存疑（疑似统一页面）"


def t_uniform_by_body():
    """同域名 4 条链接返回完全相同的正文 → 整站只剩一种页面。"""
    from core.prober import mark_uniform_pages
    bms = [_mk_probed(f"https://gone.com/p{i}", body_hash="deadbeef")
           for i in range(4)]
    n = mark_uniform_pages(bms)
    assert n == 4, f"应标记 4 条，实际 {n}"
    assert bms[0].subtype == ST_LANDING, bms[0].subtype
    return "4 条正文完全相同 → 存疑（疑似统一页面）"


def t_uniform_partial():
    """站点仍有正常页面时，被下架的那批文章也要能识别出来。

    站点关停后首页往往还在，只有部分文章返回统一提示页——
    若要求「整站只剩一种内容」就会漏检，这批假活链接又会藏起来。
    """
    from core.prober import mark_uniform_pages
    bms = [
        _mk_probed("https://site.com/post1", body_hash="offline"),
        _mk_probed("https://site.com/post2", body_hash="offline"),
        _mk_probed("https://site.com/post3", body_hash="offline"),
        _mk_probed("https://site.com/", body_hash="home", body_len=9000),
        _mk_probed("https://site.com/about", body_hash="about", body_len=8000),
    ]
    n = mark_uniform_pages(bms)
    assert n == 3, f"应只标记 3 条下架文章，实际 {n}"
    assert all(b.subtype == ST_LANDING for b in bms[:3]), [b.subtype for b in bms]
    assert all(b.verdict == V_OK for b in bms[3:]), "首页/关于页被误伤了"
    return "整站仍有正常页面时，3 条下架文章仍被识别，首页与关于页不受影响"


def t_uniform_short_page():
    """停服提示页往往只有一两百字节，最小长度门槛设高会整批漏掉（实测踩过）。"""
    from core.prober import mark_uniform_pages
    bms = [_mk_probed(f"https://short.com/x{i}", body_hash="tiny",
                      body_len=113) for i in range(3)]
    n = mark_uniform_pages(bms)
    assert n == 3, f"113 字节的短兜底页应被识别，实际标记了 {n} 条"
    return "113 字节的短兜底页 → 仍能识别（不被最小长度门槛滤掉）"


def t_uniform_end_to_end():
    """真实 HTTP 端到端：走完整探测链路，不手工构造 Probe。

    首页/关于页仍正常（内容各异），被下架的 3 篇文章返回同一份
    「系统升级中」提示页——HTTP 200，且措辞刻意不含软 404 关键词，
    规则词表无从判断，只能靠域名内横向比对发现。
    """
    import http.server
    import socketserver
    import threading

    offline = (b"<html><head><title>site</title></head><body>"
               b"<h1>system upgrading</h1><p>please come back later.</p>"
               b"</body></html>")
    home = b"<html><head><title>home</title></head><body><h1>welcome</h1>" \
           + b"<p>resources.</p>" * 60 + b"</body></html>"
    about = b"<html><head><title>about</title></head><body><h1>about</h1>" \
            + b"<p>founded 2020.</p>" * 60 + b"</body></html>"
    route = {"/post1": (200, offline), "/post2": (200, offline),
             "/post3": (200, offline), "/": (200, home), "/about": (200, about)}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, head_only):
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head_only:
                self.wfile.write(body)

        def do_HEAD(self):
            self.do_GET(head_only=True)

        def do_GET(self, head_only=False):
            code, body = route.get(self.path, (404, b"<html>404</html>"))
            self._send(code, body, head_only)

    class S(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    from core.prober import ProbeConfig, mark_uniform_pages, probe_all
    srv = S(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        port = srv.server_address[1]
        bms = [Bookmark(title=p, url=f"http://127.0.0.1:{port}{p}")
               for p in ("/post1", "/post2", "/post3", "/", "/about")]
        # 本机测试必须走直连，否则会被系统代理拦截
        probe_all(bms, ProbeConfig(exit_profile=EXIT_DIRECT, workers=5,
                                   timeout=5, retries=0, domain_delay=0),
                  only=bms)
        n = mark_uniform_pages(bms)
        assert n == 3, f"应标记 3 条被下架文章，实际 {n}"
        assert all(b.subtype == ST_LANDING for b in bms[:3]), \
            [b.subtype for b in bms]
        assert all(b.verdict == V_OK for b in bms[3:]), "首页/关于页被误伤"
        return "真实 HTTP：3 条下架文章被识别，首页与关于页不受影响"
    finally:
        srv.shutdown()
        srv.server_close()


def t_uniform_spa_safe():
    """SPA 所有路由共用一份 index.html，内容相同属正常，绝不能误判。"""
    from core.prober import mark_uniform_pages
    bms = [_mk_probed(f"https://spa.com/route{i}", body_hash="same",
                      is_spa=True) for i in range(4)]
    n = mark_uniform_pages(bms)
    assert n == 0, f"SPA 被误判了 {n} 条"
    assert bms[0].verdict == V_OK, bms[0].verdict
    return "SPA 内容相同 → 不误判，仍判可访问"


def t_uniform_distinct_safe():
    """正常站点不同页面内容各不相同，不能误判为统一页面。"""
    from core.prober import mark_uniform_pages
    bms = [_mk_probed(f"https://normal.com/a{i}", body_hash=f"h{i}",
                      body_len=5000 + i) for i in range(3)]
    n = mark_uniform_pages(bms)
    assert n == 0, f"正常站点被误判了 {n} 条"
    assert all(b.verdict == V_OK for b in bms), [b.verdict for b in bms]
    return "内容各不相同 → 不误判"


def t_uniform_login_redirect_safe():
    """3 条都跳到 /login → 是被登录拦截，不是站点关停，不能判统一页面。"""
    from core.prober import mark_uniform_pages
    bms = [_mk_probed(f"https://member.com/doc{i}",
                      final_url="https://member.com/login") for i in range(3)]
    n = mark_uniform_pages(bms)
    assert n == 0, f"登录跳转被误判了 {n} 条"
    return "跳转到 /login → 不误判（属访问受限，非站点关停）"


def t_merge_tls_error_is_suspect():
    """TLS/证书握手失败 = 服务器在监听，但不能证明页面能打开 → 存疑（需人工确认）。"""
    bm = _mk([(EXIT_DIRECT, 0, "SSL 证书错误", False)])
    assert bm.verdict == V_SUSPECT, bm.verdict
    assert bm.subtype == ST_TLS, bm.subtype
    assert bm.confidence == CONF_LOW, bm.confidence
    return "TLS 握手失败 → 存疑 / TLS限制（不能确定页面能打开，需人工确认）"


def t_merge_override_wins():
    bm = _mk([(EXIT_DIRECT, 404, "", False)])
    bm.override = "ok"
    bm.merge_verdict()
    assert bm.effective_verdict == V_OK, bm.effective_verdict
    return "人工裁定优先于自动判定"


def t_probe_replace_same_exit():
    """同出口的新探测应替换旧记录，不同出口的应并存。"""
    bm = _mk([(EXIT_DIRECT, 403, "", False), (EXIT_SYSTEM, 200, "", False)])
    assert len(bm.probes) == 2
    bm.add_probe(Probe(exit_profile=EXIT_DIRECT, status_code=200, ts=2))
    assert len(bm.probes) == 2, "同出口应替换而非追加"
    exits = {p.exit_profile for p in bm.probes}
    assert exits == {EXIT_DIRECT, EXIT_SYSTEM}
    return "同出口替换、跨出口并存"


def t_rules():
    rs = {}
    rules_mod.put_rule(rs, "example.com", rules_mod.ACTION_PROXY, "需代理")
    rules_mod.put_rule(rs, "gov.cn", rules_mod.ACTION_DIRECT)
    rules_mod.put_rule(rs, "internal.corp", rules_mod.ACTION_SKIP)
    assert rules_mod.match_rule("a.example.com", rs).action == "require_proxy"
    assert rules_mod.match_rule("www.gov.cn", rs).action == "require_direct"
    assert rules_mod.match_rule("internal.corp", rs).action == "skip"
    assert rules_mod.match_rule("other.com", rs) is None

    bms = [Bookmark(url="https://a.example.com/1"),
           Bookmark(url="https://www.gov.cn/2"),
           Bookmark(url="https://internal.corp/3"),
           Bookmark(url="https://plain.com/4")]
    skip, proxy, direct = rules_mod.partition_by_rules(bms, rs)
    assert len(skip) == 1 and len(proxy) == 1 and len(direct) == 1
    return "精确 + 父域名匹配、三组划分正确"


def t_head404_must_be_confirmed_by_get():
    """回归测试：HEAD 返回 404 时，必须用 GET 复核后才能判死。

    很多站点（尤其经过 CDN 的国内站）没正确实现 HEAD，会直接返回 404，
    而 GET 是正常的 200。实测中 yige.baidu.com / chat.baidu.com /
    arc.tencent.com 都是这种情况，曾导致整批误判为「已失效」。

    这里用本地 HTTP 服务器模拟，完全离线且结果确定。
    """
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def _send(self, code, body=b"", head_only=False):
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not head_only and body:
                self.wfile.write(body)

        def do_GET(self):
            if self.path == "/head404":
                self._send(200, b"<html><body>normal page</body></html>")
            elif self.path == "/gone":
                self._send(404, b"<html><body>page not found</body></html>")
            elif self.path == "/soft404":
                self._send(200, b"<html><body>page not found</body></html>")
            else:
                self._send(200, b"<html><body>hello world</body></html>")

        def do_HEAD(self):
            # 关键：/head404 的 HEAD 返回 404，但 GET 是 200
            self._send(404 if self.path in ("/head404", "/gone") else 200,
                       head_only=True)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{port}"
        from core.models import EXIT_DIRECT
        from core.prober import ProbeConfig, probe_all

        bms = [Bookmark(url=f"{base}{p}")
               for p in ("/head404", "/gone", "/soft404", "/ok")]
        # 本地测试必须走直连，否则会被系统代理拦截
        probe_all(bms, ProbeConfig(exit_profile=EXIT_DIRECT, workers=4,
                                   timeout=5, retries=0, domain_delay=0),
                  only=bms)

        head404, gone, soft404, ok = bms
        assert head404.effective_verdict == V_OK, (
            f"HEAD=404/GET=200 的站点被误判为 {head404.effective_verdict}")
        assert gone.effective_verdict == V_DEAD, (
            f"真正 404 的站点被判为 {gone.effective_verdict}")
        assert soft404.effective_verdict == V_SUSPECT, (
            f"软 404 应判存疑，实际为 {soft404.effective_verdict}")
        assert ok.effective_verdict == V_OK
        return "HEAD=404/GET=200 → 可访问；真 404 → 已失效；软 404 → 存疑"
    finally:
        srv.shutdown()
        srv.server_close()


def t_hints():
    missing = [v for v in (V_OK, V_DEAD, V_SUSPECT, "跳过", V_UNKNOWN)
               if v not in STATUS_HINT]
    assert not missing, f"缺少说明：{missing}"
    assert len(SUBTYPE_HINT) >= 8
    return f"结论 {len(STATUS_HINT)} 项，子类型 {len(SUBTYPE_HINT)} 项"


def t_dedupe_www():
    """www.x.com 与 x.com 应被归一化为同一资源（标准模式即合并）。"""
    bms = [
        Bookmark(title="A", url="http://www.example.com/page", folder="F"),
        Bookmark(title="A", url="https://example.com/page", folder="F"),
    ]
    removed = deduplicate(bms, LEVEL_NORMAL)
    assert removed == 1, f"www 未归一化，剔除 {removed}"
    return "www 与裸域合并为 1 组"


def t_dedupe_title_loose():
    """宽松模式：同域名下标题仅差站点后缀（首页/分隔符）应判重复。"""
    bms = [
        Bookmark(title="淘宝网 - 首页", url="https://taobao.com/a", folder="F"),
        Bookmark(title="淘宝网", url="https://taobao.com/b", folder="F"),
    ]
    removed = deduplicate(bms, LEVEL_LOOSE, title_threshold=0.9)
    assert removed == 1, f"标题相似未合并，剔除 {removed}"
    return "标题相似合并为 1 组"


def t_classify_tools_fixed():
    """修复前 json.cn 等工具域名因重复键被丢弃；修复后应归到「工具」。"""
    tax = load_taxonomy("")
    b = Bookmark(title="JSON 在线格式化", url="https://www.json.cn/", folder="开发")
    cat = classify_one(b, tax)
    assert cat == "工具", f"json.cn 未正确归类：{cat}"
    # 反向：mytool.com 这种子串误命中应避免（精度）
    b2 = Bookmark(title="My Tool", url="https://mytool.com/x", folder="")
    cat2 = classify_one(b2, tax)
    assert cat2 != "工具", f"mytool.com 误判为工具：{cat2}"
    return f"json.cn→工具，mytool.com→{cat2}"


def t_classify_domain_precision():
    """域名改为标签/后缀匹配后，tool.lu 命中而 mytool.com 不误命中。"""
    tax = load_taxonomy("")
    b_tool = Bookmark(title="Tool", url="https://tool.lu/x", folder="")
    b_my = Bookmark(title="My Tool", url="https://mytool.com/x", folder="")
    assert classify_one(b_tool, tax) == "工具"
    assert classify_one(b_my, tax) != "工具"
    return "tool.lu→工具，mytool.com 不误判"


def t_pick_primary_live():
    """重复组优选：可访问 + 真实标题 > 仅 URL 标题 > 已失效。"""
    bms = [
        Bookmark(title="", url="http://a.com/1"),        # 已失效
        Bookmark(title="真实标题", url="http://a.com/2"),  # 可访问
        Bookmark(title="http://a.com/3", url="http://a.com/3"),  # 存疑, 标题=URL
    ]
    bms[0].verdict = V_DEAD
    bms[1].verdict = V_OK
    bms[2].verdict = V_SUSPECT
    from core.dedupe import pick_primary
    assert pick_primary([0, 1, 2], bms) == 1, "未优先保留可访问且标题真实的条目"
    return "优先保留可访问+真实标题条目"


def t_ai_judge_dead_alive_skip():
    """存疑+正文：AI 判 dead→已失效、alive→可访问；无正文/非存疑不动。"""
    from core import ai_judge

    bm_dead = Bookmark(title="旧文", url="https://old.example.com/a")
    bm_dead.verdict = V_SUSPECT
    bm_dead.subtype = ST_SOFT404
    bm_dead.probes = [Probe(status_code=200,
                           text="抱歉，您访问的文章已被删除，页面不存在。")]

    bm_alive = Bookmark(title="首页", url="https://live.example.com/")
    bm_alive.verdict = V_SUSPECT
    bm_alive.subtype = ST_SOFT404
    bm_alive.probes = [Probe(status_code=200,
                            text="欢迎来到我的博客，这里分享技术文章与日常。导航：关于/文章/友链。")]

    bm_no_text = Bookmark(title="连不上", url="https://down.example.com/")
    bm_no_text.verdict = V_SUSPECT
    bm_no_text.probes = [Probe(status_code=0, error="连接失败")]

    bm_ok = Bookmark(title="正常", url="https://ok.example.com/")
    bm_ok.verdict = V_OK
    bm_ok.probes = [Probe(status_code=200, text="正文")]

    bms = [bm_dead, bm_alive, bm_no_text, bm_ok]

    class FakeClient:
        def judge_alive_batch(self, items):
            out = {}
            for (i, t, u, s, x, f) in items:
                if "已被删除" in x or "不存在" in x:
                    out[i] = ("dead", "错误页提示已删除")
                else:
                    out[i] = ("alive", "正常内容页")
            return out

    done = ai_judge.judge_suspects(bms, FakeClient(), {})
    assert done == 2, f"应处理 2 条有正文的存疑，实际 {done}"
    assert bm_dead.verdict == V_DEAD and bm_dead.subtype == ST_AI_DEAD, \
        (bm_dead.verdict, bm_dead.subtype)
    assert bm_alive.verdict == V_OK and bm_alive.subtype == ST_AI_OK
    assert bm_no_text.verdict == V_SUSPECT, "无正文不应被改"
    assert bm_ok.verdict == V_OK and bm_ok.subtype != ST_AI_OK, "非存疑不应被 AI 改"
    return "dead→已失效, alive→可访问, 无正文/非存疑不动"


def t_aiclient_judge_parse():
    """AIClient.judge_alive_batch 正确解析模型返回，忽略非法 alive 值。"""
    from core.ai import AIClient
    c = AIClient(api_key="x")
    c.chat_json = lambda prompt, system="": {  # 用假 chat_json 替换网络调用
        "results": [
            {"id": 0, "alive": "dead", "reason": "站点已关闭"},
            {"id": 1, "alive": "alive", "reason": "正常页面"},
            {"id": 2, "alive": "unknown", "reason": "未知"},  # 非法值应被忽略
        ]
    }
    res = c.judge_alive_batch([
        (0, "t", "u", 200, "x", "http://final"), (1, "t", "u", 200, "y", ""),
        (2, "t", "u", 0, "z", "http://sedo.com/")])
    assert res == {0: ("dead", "站点已关闭"), 1: ("alive", "正常页面")}, res
    assert 2 not in res, "非法 alive 值应被忽略"
    return "正确解析 alive/dead，忽略非法值"


def t_taxonomy_expanded():
    """默认分类体系已扩展：类别足够多，且每类带边界描述（供 AI prompt）。"""
    tax = load_taxonomy("")
    assert len(tax) >= 20, f"默认分类应扩展到 ≥20，实际 {len(tax)}"
    missing = [n for n, r in tax.items() if not r.get("description")]
    assert not missing, f"缺少描述的分类：{missing}"
    return f"默认 {len(tax)} 个分类，全部带描述"


def t_taxonomy_merge_extra():
    """老用户 taxonomy.json 升级时：保留自定义、补入新内置类别、补齐描述。"""
    import json
    import tempfile
    old = {"旧自定义类": {"domains": ["myold"], "keywords": []}}
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "taxonomy.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump(old, f, ensure_ascii=False)
        tax = load_taxonomy(p)
    assert "旧自定义类" in tax, "用户自定义分类被吞掉了"
    assert "旧自定义类" not in DEFAULT_TAXONOMY
    for name in ("办公", "理财", "教育", "求职", "开发", "人工智能",
                 "素材资源", "视频剪辑"):
        assert name in tax, f"新内置类别 {name} 未合并进老配置"
    assert tax["开发"].get("description"), "内置分类应有描述"
    assert tax["旧自定义类"].get("description") == ""
    return f"老配置合并后 {len(tax)} 类：自定义保留、新类别补入"


def t_aiclient_classify_low_conf_skip():
    """AI 分类：低置信不采纳（交本地规则兜底）、高置信采纳、prompt 含分类描述。"""
    from core.ai import AIClient
    c = AIClient(api_key="x")
    calls = {}

    def fake(prompt, system="", retries=0):
        calls["prompt"] = prompt
        return {"results": [
            {"id": 0, "category": "开发", "confidence": "high", "reason": "github"},
            {"id": 1, "category": "工具", "confidence": "low", "reason": "拿不准"},
        ]}

    c.chat_json = fake
    bms = [Bookmark(title="A", url="https://github.com/x"),
           Bookmark(title="B", url="https://tool.lu/x")]
    res = c.classify_batch([(0, bms[0]), (1, bms[1])],
                           ["开发", "工具"],
                           {"开发": "编程开发与代码托管",
                            "工具": "在线转换工具"})
    assert res == {0: "开发"}, res
    assert "编程开发与代码托管" in calls["prompt"], "prompt 应含分类描述"
    assert "confidence" in calls["prompt"], "prompt 应要求置信度"
    return "高置信采纳、低置信跳过、prompt 带描述与置信度要求"


def t_import_analyze():
    """导入预览分析：内部重复组、空 URL、特殊协议、与现有重复数。"""
    from core.importing import analyze_incoming
    bms = [
        Bookmark(title="A", url="https://x.com/a"),
        Bookmark(title="B", url="https://x.com/a"),          # 内部完全重复
        Bookmark(title="C", url="https://y.com/b"),
        Bookmark(title="", url=""),                            # 空 URL
        Bookmark(title="D", url="chrome://settings/"),         # 特殊协议
    ]
    s = analyze_incoming(bms, [Bookmark(url="https://x.com/a")])
    assert s["total"] == 5 and s["folders"] == 0, s
    assert s["int_dup_groups"] == 1, s
    assert s["empty_url"] == 1 and s["other_scheme"] == 1, s
    assert s["dup_with_existing"] == 2, s    # x.com/a 两条都算与现有重复
    return f"分析结果 {s}"


def t_import_merge_strategies():
    """三种导入策略：替换 / 合并（跳过重复）/ 追加（不去重）。"""
    from core.importing import (STRATEGY_APPEND, STRATEGY_MERGE,
                                STRATEGY_REPLACE, apply_import)
    ex = [Bookmark(title="旧", url="https://x.com/a")]
    inc = [Bookmark(title="新1", url="https://x.com/a"),   # 与现有重复
           Bookmark(title="新2", url="https://y.com/b")]
    merged, st = apply_import(ex, inc, STRATEGY_MERGE)
    assert len(merged) == 2 and st["added"] == 1 and st["skipped_dup"] == 1, \
        (len(merged), st)
    assert merged[0].title == "旧" and merged[1].title == "新2"
    repl, st2 = apply_import(ex, inc, STRATEGY_REPLACE)
    assert len(repl) == 2 and st2["kept_existing"] == 0
    app, st3 = apply_import(ex, inc, STRATEGY_APPEND)
    assert len(app) == 3 and st3["added"] == 2 and st3["kept_existing"] == 1
    return "merge 跳过重复 / replace 替换 / append 全追加"


def main():
    os.makedirs(TMP, exist_ok=True)
    check("解析合成样本", t_parse)
    check("URL 归一化", t_normalize)
    check("去重三档", t_dedupe)
    check("去重：www 归并", t_dedupe_www)
    check("去重：标题相似(宽松)", t_dedupe_title_loose)
    check("去重：优先保留存活条目", t_pick_primary_live)
    check("规则分类", t_classify)
    check("分类：工具域名修复+精度", t_classify_tools_fixed)
    check("分类：域名标签匹配精度", t_classify_domain_precision)
    check("导航页生成", t_nav)
    check("导出往返", t_export_roundtrip)
    check("合并：任一出口成功", t_merge_ok_when_any_exit_succeeds)
    check("合并：全部 404", t_merge_dead_when_all_404)
    check("合并：403 判可访问", t_merge_limited_on_403)
    check("合并：软 404 判存疑", t_merge_soft404_is_suspect)
    check("统一页面：跳转聚合", t_uniform_by_redirect)
    check("统一页面：内容聚合", t_uniform_by_body)
    check("统一页面：部分下架也能识别", t_uniform_partial)
    check("统一页面：短兜底页不被滤掉", t_uniform_short_page)
    check("统一页面：真实 HTTP 端到端", t_uniform_end_to_end)
    check("统一页面：不误伤 SPA", t_uniform_spa_safe)
    check("统一页面：内容不同不误判", t_uniform_distinct_safe)
    check("统一页面：登录跳转不误判", t_uniform_login_redirect_safe)
    check("合并：TLS 握手失败→存疑", t_merge_tls_error_is_suspect)
    check("合并：人工裁定优先", t_merge_override_wins)
    check("探测记录替换规则", t_probe_replace_same_exit)
    check("HEAD 404 必须 GET 复核", t_head404_must_be_confirmed_by_get)
    check("域名规则", t_rules)
    check("状态说明完整性", t_hints)
    check("AI 判活：dead/alive/不动", t_ai_judge_dead_alive_skip)
    check("AIClient 判活解析", t_aiclient_judge_parse)
    check("分类体系：扩展+描述", t_taxonomy_expanded)
    check("分类体系：老配置增量合并", t_taxonomy_merge_extra)
    check("AI 分类：低置信不采纳", t_aiclient_classify_low_conf_skip)
    check("导入：预览分析", t_import_analyze)
    check("导入：三种合并策略", t_import_merge_strategies)

    print("\n" + "=" * 62)
    print(f"{'结果':<6}{'检查项':<24}说明")
    print("-" * 62)
    for st, name, info in results:
        print(f"{st:<6}{name:<24}{info}")
    print("=" * 62)
    n_fail = sum(1 for r in results if r[0] == "失败")
    print(f"共 {len(results)} 项，失败 {n_fail} 项")
    return 1 if n_fail else 0


if __name__ == "__main__":
    sys.exit(main())
