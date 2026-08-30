"""打包自检：验证 exe 内所有依赖都已正确打包。

用 PyInstaller --console 打包后运行，会逐项打印检查结果。
"""

from __future__ import annotations

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

OK, FAIL = "通过", "失败"
results = []


def check(name: str, fn):
    try:
        info = fn()
        results.append((OK, name, info or ""))
    except Exception as e:  # noqa: BLE001
        results.append((FAIL, name, f"{type(e).__name__}: {e}"))
        traceback.print_exc()


def t_requests():
    import requests
    r = requests.get("https://www.baidu.com", timeout=10)
    return f"HTTP {r.status_code}"


def t_urllib3():
    import urllib3
    return urllib3.__version__


def t_pyside():
    from PySide6 import QtCore, QtGui, QtWidgets
    return f"Qt {QtCore.qVersion()}"


def t_desktopservices():
    from PySide6.QtGui import QDesktopServices
    return "可用" if hasattr(QDesktopServices, "openUrl") else "缺失"


def t_core():
    from core import ai, classifier, dedupe, models, navgen, parser, prober, rules
    return f"{len(classifier.DEFAULT_TAXONOMY)} 个默认分类，{len(rules.ACTIONS)} 条规则动作"


def t_parse_real():
    from core import parser
    # 用随包合成样本，不碰任何真实书签数据
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "tests", "sample_bookmarks.html")
    if not os.path.exists(src):
        raise FileNotFoundError(f"缺少样本文件 {src}")
    _, bms = parser.load_bookmarks(src)
    return f"{len(bms)} 条（合成样本）"


def t_normalize():
    from core.models import normalize_url
    # 归一化会剔除追踪参数、统一大小写与末尾斜杠，但保留协议差异
    a = normalize_url("https://Example.COM/a/?utm_source=x&b=1#top")
    b = normalize_url("https://example.com/a?b=1")
    assert a == b, f"{a} != {b}"
    return a


def t_linkcheck():
    from core.models import Bookmark
    from core.prober import ProbeConfig, probe_all
    bms = [Bookmark(title="baidu", url="https://www.baidu.com")]
    probe_all(bms, ProbeConfig(workers=2, timeout=10))
    return bms[0].effective_verdict


def t_ui():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from ui.main_window import MainWindow
    w = MainWindow()
    return f"主窗口已构造，表格 {w.table.columnCount()} 列"


def main():
    check("requests 网络请求", t_requests)
    check("urllib3", t_urllib3)
    check("PySide6", t_pyside)
    check("QDesktopServices", t_desktopservices)
    check("core 全部模块", t_core)
    check("解析合成样本", t_parse_real)
    check("URL 归一化", t_normalize)
    check("失效检测（联网）", t_linkcheck)
    check("主窗口构造", t_ui)

    print("\n" + "=" * 56)
    print(f"{'结果':<6}{'检查项':<22}说明")
    print("-" * 56)
    for st, name, info in results:
        print(f"{st:<6}{name:<22}{info}")
    print("=" * 56)
    n_fail = sum(1 for r in results if r[0] == FAIL)
    print(f"共 {len(results)} 项，失败 {n_fail} 项")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()
