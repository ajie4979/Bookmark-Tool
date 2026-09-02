"""重复组对比对话框。

去重后按「重复组」分组展示：同一组内相同链接的所有书签逐条列出，
标出算法建议（主条目「建议保留」/ 其余「删除」），
方便人工核对每组留哪条、删哪条，避免删错。
"""

from __future__ import annotations

from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from core.models import V_DEAD, V_OK, V_SUSPECT, Bookmark

COL_CHECK, COL_NAME, COL_URL, COL_VERDICT, COL_SUGGEST = range(5)
HEADERS = ["选择", "名称", "URL", "状态", "建议"]

VERDICT_COLOR = {
    V_OK: "#3B6D11",
    V_SUSPECT: "#854F0B",
    V_DEAD: "#A32D2D",
}

STYLE = """
QDialog { background:#ffffff; }
QTableWidget { gridline-color:#eceae4; selection-background-color:#e6f1fb;
  selection-color:#185fa5; }
QHeaderView::section { background:#fafaf9; padding:6px; border:none;
  border-right:1px solid #eceae4; border-bottom:1px solid #e3e2dd; }
QPushButton { padding:5px 12px; border:1px solid #d3d1c7; border-radius:6px;
  background:#ffffff; color:#2c2c2a; }
QPushButton:hover { background:#f1efe8; border-color:#b4b2a9; }
QPushButton#danger { color:#a32d2d; }
QPushButton#danger:hover { background:#fcebeb; border-color:#f09595; }
QPushButton#primary { background:#185fa5; border-color:#185fa5; color:#ffffff; }
QPushButton#primary:hover { background:#0c447c; border-color:#0c447c; }
"""


class DupReviewDialog(QDialog):
    def __init__(self, bookmarks: List[Bookmark], parent=None,
                 on_change: Optional[Callable[[], None]] = None):
        super().__init__(parent)
        self.bookmarks = bookmarks
        self.on_change = on_change or (lambda: None)
        self._loading = False

        self.setWindowTitle("重复组对比")
        self.resize(880, 580)
        self.setStyleSheet(STYLE)

        lay = QVBoxLayout(self)

        self.head = QLabel()
        self.head.setWordWrap(True)
        self.head.setTextFormat(Qt.RichText)
        self.head.setStyleSheet("color:#5F5E5A;font-size:12px;padding-bottom:4px")
        lay.addWidget(self.head)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemChanged.connect(self._on_item_changed)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(COL_CHECK, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_NAME, QHeaderView.Interactive)
        hh.setSectionResizeMode(COL_URL, QHeaderView.Stretch)
        hh.setSectionResizeMode(COL_VERDICT, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_SUGGEST, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(COL_NAME, 240)
        lay.addWidget(self.table, 1)

        # 第一行：快捷勾选（一键选中建议删除项 / 全选 / 清空）
        row_sel = QHBoxLayout()
        self.lb_sel = QLabel("已选 0 条")
        self.lb_sel.setStyleSheet("color:#5F5E5A;font-size:12px")
        self.btn_auto = QPushButton("一键勾选建议删除")
        self.btn_auto.setObjectName("primary")
        self.btn_all = QPushButton("全选")
        self.btn_none = QPushButton("清空选择")
        self.btn_auto.clicked.connect(
            lambda: self._apply_check(lambda bm: not bm.is_primary))
        self.btn_all.clicked.connect(
            lambda: self._apply_check(lambda bm: True))
        self.btn_none.clicked.connect(
            lambda: self._apply_check(lambda bm: False))
        row_sel.addWidget(self.lb_sel)
        row_sel.addStretch(1)
        row_sel.addWidget(self.btn_auto)
        row_sel.addWidget(self.btn_all)
        row_sel.addWidget(self.btn_none)
        lay.addLayout(row_sel)

        # 第二行：批量操作
        row = QHBoxLayout()
        self.btn_toggle = QPushButton("切换保留/剔除")
        self.btn_del = QPushButton("删除选中")
        self.btn_del.setObjectName("danger")
        self.btn_close = QPushButton("关闭")
        self.btn_toggle.clicked.connect(self._toggle_selected)
        self.btn_del.clicked.connect(self._delete_selected)
        self.btn_close.clicked.connect(self.accept)
        row.addStretch(1)
        row.addWidget(self.btn_toggle)
        row.addWidget(self.btn_del)
        row.addWidget(self.btn_close)
        lay.addLayout(row)

        self._rebuild()

    # ---------------------------------------------------------------- 数据
    def _groups(self):
        by_g = {}
        for bm in self.bookmarks:
            if bm.dup_group >= 0:
                by_g.setdefault(bm.dup_group, []).append(bm)
        # 只展示真正成组的重复（组内 ≥ 2 条），删除后残留的单条不再算重复
        return sorted((gid, v) for gid, v in by_g.items() if len(v) >= 2)

    # ---------------------------------------------------------------- 渲染
    def _rebuild(self):
        self._loading = True
        self.table.setRowCount(0)
        groups = self._groups()
        self._n_groups = len(groups)
        self._n_dup = sum(len(v) for _, v in groups)

        r = 0
        for gid, items in groups:
            # 组头行：合并整行，标出组类型与数量
            dup_type = items[0].dup_type or "标准化一致"
            head_item = QTableWidgetItem(f"重复组（{dup_type}）· {len(items)} 项")
            head_item.setBackground(QBrush(QColor("#eef4fb")))
            head_item.setForeground(QBrush(QColor("#185fa5")))
            head_item.setFlags(Qt.ItemIsEnabled)
            font = head_item.font()
            font.setBold(True)
            head_item.setFont(font)
            self.table.insertRow(r)
            self.table.setItem(r, 0, head_item)
            self.table.setSpan(r, 0, 1, len(HEADERS))

            # 组内：主条目在前，其次可访问优先，便于一眼对比
            ordered = sorted(
                items,
                key=lambda bm: (not bm.is_primary, bm.effective_verdict != V_OK),
            )
            for bm in ordered:
                r += 1
                self.table.insertRow(r)
                self._set_row(r, bm)
            r += 1
        self._loading = False
        self._refresh_head()
        self._update_sel_label()

    def _set_row(self, r: int, bm: Bookmark):
        it_check = QTableWidgetItem()
        it_check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        it_check.setCheckState(Qt.Checked if bm.selected else Qt.Unchecked)
        it_check.setData(Qt.UserRole, bm)
        it_check.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(r, COL_CHECK, it_check)

        name = bm.display_title(60)
        if bm.is_primary:
            name += "  · 主条目"
        it_name = QTableWidgetItem(name)
        it_name.setData(Qt.UserRole, bm)
        it_name.setToolTip(bm.title)
        if not bm.keep:
            it_name.setForeground(QBrush(QColor("#B4B2A9")))
        self.table.setItem(r, COL_NAME, it_name)

        it_url = QTableWidgetItem(bm.url)
        it_url.setData(Qt.UserRole, bm)
        it_url.setToolTip(bm.url)
        self.table.setItem(r, COL_URL, it_url)

        v = bm.effective_verdict
        it_v = QTableWidgetItem(v)
        it_v.setData(Qt.UserRole, bm)
        it_v.setForeground(QBrush(QColor(VERDICT_COLOR.get(v, "#5F5E5A"))))
        self.table.setItem(r, COL_VERDICT, it_v)

        it_sug = QTableWidgetItem("建议保留" if bm.is_primary else "删除")
        it_sug.setData(Qt.UserRole, bm)
        it_sug.setTextAlignment(Qt.AlignCenter)
        if bm.is_primary:
            it_sug.setForeground(QBrush(QColor("#1a7f37")))
            it_sug.setBackground(QBrush(QColor("#e6f4ea")))
        else:
            it_sug.setForeground(QBrush(QColor("#A32D2D")))
            it_sug.setBackground(QBrush(QColor("#fdecea")))
        self.table.setItem(r, COL_SUGGEST, it_sug)

    def _refresh_head(self):
        self.head.setText(
            f"共 <b>{self._n_groups}</b> 个重复组 · <b>{self._n_dup}</b> 条重复书签。"
            f"同一组内链接相同，标「建议保留」为主条目，其余建议删除，"
            f"请核对名称 / 链接后再操作。"
        )

    # ---------------------------------------------------------------- 操作
    def _row_bm(self, row: int):
        it = self.table.item(row, COL_CHECK)
        return it.data(Qt.UserRole) if it else None

    def _checked_bms(self):
        out = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, COL_CHECK)
            if it and it.checkState() == Qt.Checked:
                bm = it.data(Qt.UserRole)
                if bm is not None:
                    out.append(bm)
        return out

    def _on_item_changed(self, it: QTableWidgetItem):
        if self._loading or it.column() != COL_CHECK:
            return
        bm = it.data(Qt.UserRole)
        if bm is None:
            return
        bm.selected = (it.checkState() == Qt.Checked)
        self._update_sel_label()

    def _update_sel_label(self):
        self.lb_sel.setText(f"已选 {len(self._checked_bms())} 条")

    def _apply_check(self, predicate):
        """按条件批量勾选/取消：predicate(bm) 为 True 勾选、False 取消。

        组头行没有关联书签，直接跳过。加载期屏蔽 itemChanged，避免逐行回调。
        """
        self._loading = True
        try:
            for r in range(self.table.rowCount()):
                it = self.table.item(r, COL_CHECK)
                if it is None:
                    continue
                bm = it.data(Qt.UserRole)
                if bm is None:
                    continue
                on = bool(predicate(bm))
                bm.selected = on
                it.setCheckState(Qt.Checked if on else Qt.Unchecked)
        finally:
            self._loading = False
        self._update_sel_label()

    def _toggle_selected(self):
        sel = self._checked_bms()
        if not sel:
            QMessageBox.information(self, "提示", "请先勾选要切换的书签")
            return
        for bm in sel:
            bm.keep = not bm.keep
        self._rebuild()
        self.on_change()

    def _delete_selected(self):
        sel = self._checked_bms()
        if not sel:
            QMessageBox.information(self, "提示", "请先勾选要删除的书签")
            return
        ans = QMessageBox.question(
            self, "确认删除",
            f"确定删除勾选的 {len(sel)} 条书签？此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        drop = set(id(b) for b in sel)
        self.bookmarks[:] = [b for b in self.bookmarks if id(b) not in drop]
        self._rebuild()
        self.on_change()
