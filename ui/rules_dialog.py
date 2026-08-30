"""域名规则管理器。

规则让工具「越用越准」：把人工裁定或复检结论沉淀下来，
下次验证时自动生效，不再重复踩同一个坑。
"""

from __future__ import annotations

from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from core.rules import (
    ACTION_DIRECT, ACTION_PROXY, ACTION_SKIP, ACTIONS, Rule, remove_rule,
)


class RulesDialog(QDialog):
    def __init__(self, rules: Dict[str, Rule], parent=None):
        super().__init__(parent)
        self.rules = dict(rules or {})
        self.setWindowTitle("域名规则")
        self.resize(620, 420)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["域名", "规则", "备注"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)

        btns = QHBoxLayout()
        b_add = QPushButton("新增")
        b_del = QPushButton("删除")
        b_add.clicked.connect(self._add)
        b_del.clicked.connect(self._del)
        btns.addWidget(b_add)
        btns.addWidget(b_del)
        btns.addStretch(1)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "规则在验证时自动生效：需代理的域名只走代理出口，"
            "需直连的只走直连，跳过的不再检测。"))
        lay.addWidget(self.table, 1)
        lay.addLayout(btns)

        bbox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bbox.button(QDialogButtonBox.Ok).setText("确定")
        bbox.button(QDialogButtonBox.Cancel).setText("取消")
        bbox.accepted.connect(self.accept)
        bbox.rejected.connect(self.reject)
        lay.addWidget(bbox)

        self._reload()

    def _reload(self):
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for i, (domain, r) in enumerate(sorted(self.rules.items())):
            self.table.insertRow(i)
            self.table.setItem(i, 0, QTableWidgetItem(domain))
            self.table.setItem(i, 1, QTableWidgetItem(ACTIONS.get(r.action, r.action)))
            it = QTableWidgetItem(r.note or "")
            it.setFlags(it.flags() | Qt.ItemIsEditable)
            self.table.setItem(i, 2, it)
        self.table.blockSignals(False)

    def _on_item_changed(self, item):
        if item.column() != 2:
            return
        row = item.row()
        d = self.table.item(row, 0)
        if not d:
            return
        r = self.rules.get(d.text())
        if r:
            r.note = item.text().strip()

    def _add(self):
        domain, ok = QInputDialog.getText(
            self, "新增规则", "域名（如 example.com，会匹配其子域名）：")
        if not ok or not domain.strip():
            return
        domain = domain.strip().lower()
        opts = list(ACTIONS.values())
        action_label, ok2 = QInputDialog.getItem(
            self, "选择规则", "规则类型：", opts, 0, False)
        if not ok2:
            return
        for key, label in ACTIONS.items():
            if label == action_label:
                from core.rules import put_rule
                put_rule(self.rules, domain, key)
                break
        self._reload()

    def _del(self):
        row = self.table.currentRow()
        if row < 0:
            return
        d = self.table.item(row, 0)
        if not d:
            return
        if QMessageBox.question(self, "确认",
                                f"删除规则「{d.text()}」？") != QMessageBox.Yes:
            return
        remove_rule(self.rules, d.text())
        self._reload()

    def result_rules(self) -> Dict[str, Rule]:
        return self.rules
