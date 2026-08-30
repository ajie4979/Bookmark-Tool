"""核心模块冒烟测试。

全部离线：解析 → 去重 → 分类 → 导航页 → 导出回读 → 乐观合并 → 域名规则。
使用 tests/sample_bookmarks.html 合成样本，不依赖真实书签数据，不发网络请求。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import classifier, navgen, parser, rules as rules_mod  # noqa: E402
from core.classifier import (  # noqa: E402
    DEFAULT_CATEGORY, classify_one, load_taxonomy,
)
from core.dedupe import LEVEL_LOOSE, LEVEL_NORMAL, LEVEL_STRICT, deduplicate  # noqa: E402
from core.models import (  # noqa: E402
    CONF_LOW, CONF_MID, EXIT_DIRECT, EXIT_SYSTEM, STATUS_HINT, ST_LIMITED,
    ST_SOFT404, ST_TLS, SUBTYPE_HINT,
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


def t_merge_soft404_is_ok():
    bm = _mk([(EXIT_SYSTEM, 200, "", True)])
    assert bm.verdict == V_OK, bm.verdict
    assert bm.subtype == ST_SOFT404, bm.subtype
    return "200 且内容像「页面不存在」→ 可访问（疑似软404，仅作备注）"


def t_merge_tls_error_is_ok():
    """TLS/证书握手失败 = 服务器回了握手 = 站点活着 → 可访问（≠ 失效）。"""
    bm = _mk([(EXIT_DIRECT, 0, "SSL 证书错误", False)])
    assert bm.verdict == V_OK, bm.verdict
    assert bm.subtype == ST_TLS, bm.subtype
    assert bm.confidence == CONF_MID, bm.confidence
    return "TLS 握手失败 → 可访问 / TLS限制（站点多半正常，浏览器能开）"


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
        assert soft404.effective_verdict == V_OK, (
            f"软 404 被判为 {soft404.effective_verdict}")
        assert ok.effective_verdict == V_OK
        return "HEAD=404/GET=200 → 可访问；真 404 → 已失效；软 404 → 可访问"
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
    """修复前 json.cn 等工具域名因重复键被丢弃；修复后应归到「工具与效率」。"""
    tax = load_taxonomy("")
    b = Bookmark(title="JSON 在线格式化", url="https://www.json.cn/", folder="开发")
    cat = classify_one(b, tax)
    assert cat == "工具与效率", f"json.cn 未正确归类：{cat}"
    # 反向：mytool.com 这种子串误命中应避免（精度）
    b2 = Bookmark(title="My Tool", url="https://mytool.com/x", folder="")
    cat2 = classify_one(b2, tax)
    assert cat2 != "工具与效率", f"mytool.com 误判为工具与效率：{cat2}"
    return f"json.cn→工具与效率，mytool.com→{cat2}"


def t_classify_domain_precision():
    """域名改为标签/后缀匹配后，tool.lu 命中而 mytool.com 不误命中。"""
    tax = load_taxonomy("")
    b_tool = Bookmark(title="Tool", url="https://tool.lu/x", folder="")
    b_my = Bookmark(title="My Tool", url="https://mytool.com/x", folder="")
    assert classify_one(b_tool, tax) == "工具与效率"
    assert classify_one(b_my, tax) != "工具与效率"
    return "tool.lu→工具与效率，mytool.com 不误判"


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
    check("合并：软 404 判可访问", t_merge_soft404_is_ok)
    check("合并：TLS 握手失败→可访问", t_merge_tls_error_is_ok)
    check("合并：人工裁定优先", t_merge_override_wins)
    check("探测记录替换规则", t_probe_replace_same_exit)
    check("HEAD 404 必须 GET 复核", t_head404_must_be_confirmed_by_get)
    check("域名规则", t_rules)
    check("状态说明完整性", t_hints)

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
