"""UI 冒烟测试：构造主窗口、灌入合成样本、执行各步骤并截图。

不依赖真实书签数据，不发网络请求。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "tests", "sample_bookmarks.html")
OUTDIR = os.path.join(HERE, "_tmp_test_out")
OUT = os.path.join(OUTDIR, "shot_main.png")


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    from core import classifier, navgen, parser
    from core.dedupe import LEVEL_NORMAL, deduplicate
    from core.models import Bookmark
    from ui.main_window import MainWindow

    win = MainWindow()
    win.resize(1280, 800)

    folders, bms = parser.load_bookmarks(SRC)
    win.folders, win.bookmarks = folders, bms
    removed = deduplicate(bms, LEVEL_NORMAL, 0.92)
    tax = classifier.load_taxonomy("")
    counts = classifier.classify_all(bms, tax, only_kept=True)

    # 造几个假探测记录，验证结论着色与出口列（不发网络请求）
    import random
    random.seed(7)
    from core.models import EXIT_DIRECT, EXIT_SYSTEM, Probe
    cases = [
        [(EXIT_SYSTEM, 200, "", False)] * 12,
        [(EXIT_DIRECT, 404, "", False)],
        [(EXIT_DIRECT, 0, "请求超时", False)],
        [(EXIT_SYSTEM, 403, "", False)],
        [(EXIT_SYSTEM, 451, "", False)],
        [(EXIT_SYSTEM, 500, "", False)],
        [(EXIT_SYSTEM, 200, "", True)],
        [(EXIT_DIRECT, 0, "连接被拒绝", False), (EXIT_SYSTEM, 200, "", False)],
    ]
    pool = [c for c in cases for _ in range(3)]
    for b in bms:
        if not b.keep:
            continue
        for exit_name, code, err, soft in random.choice(pool):
            b.add_probe(Probe(exit_profile=exit_name, status_code=code,
                              error=err, soft404=soft, ts=1))
        b.merge_verdict()
    win._populate()

    print(f"书签 {len(bms)} 条，去重剔除 {removed}，分类 {len(counts)} 个")
    print("表格行数:", win.table.rowCount(), " 列数:", win.table.columnCount())
    print("统计标签:", win.lb_stats.text())

    # 复检目标收集
    targets = win._recheck_targets()
    print(f"复检目标: {len(targets)} 条（应为存疑+失效）")

    # 回归：workers._summarize 必须能无错运行（曾因漏导入 V_LIMITED 在真实验证时 NameError）
    from ui import workers as _wk

    class _Stub:
        def __init__(self):
            self.logs = []

            class _L:
                def __init__(s, out):
                    s.out = out

                def emit(s, m):
                    s.out.logs.append(m)

            self.log = _L(self)

        def _stats(self, ts):
            return _wk.ProbeWorker._stats(self, ts)

    stub = _Stub()
    _wk.ProbeWorker._summarize(stub, bms)
    assert any("验证完成" in m for m in stub.logs), stub.logs
    print("回归 OK：workers._summarize 正常运行（无 NameError）")


    os.makedirs(OUTDIR, exist_ok=True)
    nav = os.path.join(OUTDIR, "nav.html")
    n = navgen.generate_nav(bms, nav)
    print(f"导航页 {n} 条 -> {nav}")

    win.grab().save(OUT)
    print("截图已保存:", OUT, f"({os.path.getsize(OUT)/1024:.0f} KB)")

    # 各对话框能否正常构造
    from ui.dialogs import SettingsDialog, TaxonomyDialog
    from ui.recheck_dialog import RecheckDialog
    from ui.rules_dialog import RulesDialog
    d1 = SettingsDialog(win.cfg, win)
    d2 = TaxonomyDialog(win.taxonomy, win)
    d3 = RecheckDialog(targets, EXIT_DIRECT, "1.2.3.4", win)
    d4 = RulesDialog(win.rules, win)
    print(f"设置 {d1.windowTitle()} | 分类体系 {d2.list.count()} 个分类 | "
          f"复检 {d3.windowTitle()} | 规则 {d4.windowTitle()}")


if __name__ == "__main__":
    main()
