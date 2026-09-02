"""回归：全选 + 改筛选后，批量删除只作用于当前可见视图。

完全离线，使用 tests/sample_bookmarks.html 的 36 条合成样本，不触碰真实书签。
样本默认都是「未检测」，这里手动给前若干条打上裁定，模拟一次扫描后的状态，
以便筛选下拉里出现「可访问 / 已失效」等可选项。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QMessageBox

from core.models import OVERRIDE_OK, OVERRIDE_DEAD
from core.parser import load_bookmarks
from ui.main_window import MainWindow

SAMPLE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "tests", "sample_bookmarks.html")

app = QApplication.instance() or QApplication([])

win = MainWindow.__new__(MainWindow)
MainWindow.__init__(win)
folders, bms = load_bookmarks(SAMPLE)
win.bookmarks = bms

# 模拟扫描后：前 6 条可访问、随后 3 条失效，其余未检测
for i, b in enumerate(bms):
    if i < 6:
        b.override = OVERRIDE_OK
    elif i < 9:
        b.override = OVERRIDE_DEAD
win._populate()

total = len(win.bookmarks)
print(f"载入 {total} 条书签；下拉项: "
      f"{[win.cb_verdict.itemText(j) for j in range(win.cb_verdict.count())]}")

# 让 QMessageBox.question 自动点「是」，验证删除路径
_orig_q = QMessageBox.question
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)

# ---- 场景 1：全选（无筛选）后，再改筛选，旧勾选应被清空 ----
win._select_all()
assert len(win._visible_selected_indices()) == win.table.rowCount()
print("场景1a 全选后已选:", len(win._visible_selected_indices()))

win.cb_verdict.setCurrentText("已失效")   # 触发 _on_filter_changed -> 清空选择
print("场景1b 改筛选后可访问视图行数:", win.table.rowCount(),
      "已选(应为0):", len(win._visible_selected_indices()))
assert len(win._visible_selected_indices()) == 0, "筛选变化后选择未清空！"
assert sum(1 for b in win.bookmarks if b.selected) == 0, "筛选变化后仍有隐藏行被勾选！"

# ---- 场景 2：在新视图里全选，再删除，只删可见行而非全部 ----
win.cb_verdict.setCurrentText("可访问")
visible_before = win.table.rowCount()
win._select_all()
sel_idx = win._visible_selected_indices()
print(f"场景2 可访问视图 {visible_before} 行，已选 {len(sel_idx)}")
assert len(sel_idx) == visible_before
assert len(sel_idx) < total, "可见集应小于全量，否则无法证明已按视图过滤"

before = len(win.bookmarks)
win._batch_delete()  # 无 targets -> 走 _visible_selected_indices
after = len(win.bookmarks)
print(f"场景2 删除前 {before} 条，删除后 {after} 条，删了 {before - after} 条")
assert before - after == len(sel_idx), "删除数量与可见已选不一致！"
assert before - after < total, "误删了被隐藏的行（旧的 bug）！"

# ---- 场景 3：手动把一条「被过滤掉」的行设成 selected（脏状态），
#            可见已选集与批量删除都应排除它 ----
win.cb_verdict.setCurrentText("已失效")   # 只看已失效；其余均被隐藏
# 挑一条当前不可见的书签（这里取一个「未检测」的下标）
hidden_idx = next(i for i, b in enumerate(win.bookmarks) if not win._visible(b))
win.bookmarks[hidden_idx].selected = True   # 模拟脏勾选（正常流程不会发生）
dirty = win.bookmarks[hidden_idx]            # 记下对象引用，删除后下标会变
vis_sel = win._visible_selected_indices()
print(f"场景3 隐藏行#{hidden_idx}被勾选，可见已选集={vis_sel}")
assert hidden_idx not in vis_sel, "隐藏行的 selected 不应进入可见已选集"
assert all(win._visible(i) for i in vis_sel), "可见已选集里混入了不可见行！"
# 复选：选中可见行后再删除，只删可见已选
win._select_all()
sel_count = len(win._visible_selected_indices())
before3 = len(win.bookmarks)
win._batch_delete()
after3 = len(win.bookmarks)
print(f"场景3 删除前 {before3} 条，删除后 {after3} 条，删了 {before3 - after3} 条")
assert before3 - after3 == sel_count, "删除数量与可见已选不一致！"
assert dirty.selected, "隐藏的脏勾选行被误删了！"
print("场景3 隐藏行保留、可见已选被删 -> OK")

QMessageBox.question = staticmethod(_orig_q)
print("\n全部回归通过：筛选会清空选择、批量操作只认当前可见已选。")
