"""导入预览 / 导入策略 / 导入报告对话框。"""

from __future__ import annotations

from typing import Dict, List, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QDialog, QDialogButtonBox, QHeaderView,
    QLabel, QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
    QFormLayout, QFrame,
)

from core import importing
from core.models import Bookmark

PREVIEW_MAX = 200          # 预览表最多显示条数，避免几万条书签撑爆内存


def _label(text: str, obj="hint"):
    lb = QLabel(text)
    lb.setObjectName(obj)
    lb.setWordWrap(True)
    return lb


class ImportPreviewDialog(QDialog):
    """选择书签文件后先展示预览，确认来源/数量/重复/异常，再选导入策略。"""

    def __init__(self, path: str, folders: List[str],
                 bms: Sequence[Bookmark],
                 existing: Sequence[Bookmark], parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入预览")
        self.resize(760, 600)
        self._strategy = importing.STRATEGY_REPLACE
        stats = importing.analyze_incoming(bms, existing)

        src = importing.detect_source(path)

        info = QFormLayout()
        info.setLabelAlignment(Qt.AlignRight)
        info.addRow("来源", _label(src))
        info.addRow("书签数量", _label(
            f"<b>{stats['total']}</b> 条 · {stats['folders']} 个文件夹"))
        warn = []
        if stats["int_dup_groups"]:
            warn.append(f"文件内部有 <b>{stats['int_dup_groups']}</b> 组完全重复")
        if stats["dup_with_existing"]:
            warn.append(f"与当前列表重复 <b>{stats['dup_with_existing']}</b> 条")
        if stats["empty_url"]:
            warn.append(f"空 URL <b>{stats['empty_url']}</b> 条")
        if stats["other_scheme"]:
            warn.append(f"特殊协议 <b>{stats['other_scheme']}</b> 条")
        info.addRow("初步检查", _label(
            "；".join(warn) if warn else "未发现明显问题", "hint"))

        # 导入方式用单选按钮平铺：选项少、直接可见，避免下拉弹出项被遮挡看不清
        self._rad_merge = QRadioButton("合并到当前列表（跳过重复，不丢已有数据）")
        self._rad_replace = QRadioButton("替换当前列表（用这个文件重新开始）")
        self._rad_append = QRadioButton("追加到当前列表（不去重）")
        self._grp = QButtonGroup(self)
        self._grp.addButton(self._rad_merge, 0)
        self._grp.addButton(self._rad_replace, 1)
        self._grp.addButton(self._rad_append, 2)
        has_existing = bool(existing)
        self._rad_merge.setEnabled(has_existing)
        self._rad_merge.setChecked(has_existing)
        self._rad_replace.setChecked(not has_existing)
        strategy_box = QVBoxLayout()
        strategy_box.setContentsMargins(0, 0, 0, 0)
        strategy_box.setSpacing(4)
        strategy_box.addWidget(self._rad_merge)
        strategy_box.addWidget(self._rad_replace)
        strategy_box.addWidget(self._rad_append)
        info.addRow("导入方式", strategy_box)

        head = QFrame()
        head.setObjectName("card")
        lay = QVBoxLayout(head)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.addLayout(info)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["标题", "网址", "文件夹"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Interactive)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Interactive)
        self.table.setColumnWidth(0, 240)
        self.table.setColumnWidth(2, 160)

        shown = bms[:PREVIEW_MAX]
        self.table.setRowCount(len(shown))
        for r, b in enumerate(shown):
            self.table.setItem(r, 0, QTableWidgetItem(b.display_title(60)))
            it_url = QTableWidgetItem(b.url)
            it_url.setToolTip(b.url)
            self.table.setItem(r, 1, it_url)
            self.table.setItem(r, 2, QTableWidgetItem(b.folder))
        lb_hint = _label(
            f"以下仅预览前 {min(len(bms), PREVIEW_MAX)} 条，"
            f"全部 {stats['total']} 条都会按所选方式导入。", "hint")

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        box.button(QDialogButtonBox.Ok).setText("开始导入")
        box.button(QDialogButtonBox.Cancel).setText("取消")
        box.accepted.connect(self._on_ok)
        box.rejected.connect(self.reject)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        root.addWidget(head)
        root.addWidget(self.table, 1)
        root.addWidget(lb_hint)
        root.addWidget(box)

    def _on_ok(self):
        mapping = {0: importing.STRATEGY_MERGE,
                   1: importing.STRATEGY_REPLACE,
                   2: importing.STRATEGY_APPEND}
        self._strategy = mapping.get(self._grp.checkedId(),
                                     importing.STRATEGY_REPLACE)
        self.accept()

    def strategy(self) -> str:
        return self._strategy


class ImportReportDialog(QDialog):
    """导入完成后的结果报告：新增 / 跳过 / 保留。"""

    def __init__(self, stats: Dict[str, int], strategy: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("导入完成")
        self.resize(420, 240)

        info = QFormLayout()
        info.setLabelAlignment(Qt.AlignRight)
        if strategy == importing.STRATEGY_REPLACE:
            info.addRow("导入方式", _label("替换当前列表"))
            info.addRow("", _label(
                f"新增 <b>{stats['added']}</b> 条，原有数据已被替换。", "hint"))
        else:
            mode = "合并（跳过重复）" if strategy == importing.STRATEGY_MERGE \
                else "追加（不去重）"
            info.addRow("导入方式", _label(mode))
            info.addRow("新增", _label(f"<b>{stats['added']}</b> 条"))
            info.addRow("保留原有", _label(f"<b>{stats['kept_existing']}</b> 条"))
            if stats.get("skipped_dup"):
                info.addRow("跳过重复", _label(
                    f"<b>{stats['skipped_dup']}</b> 条（URL 与已有相同）"))
        info.addRow("", _label(
            "接下来可以做：去重 → 验证可达性 → 归类 → 导出。", "hint"))

        box = QDialogButtonBox(QDialogButtonBox.Ok, self)
        box.button(QDialogButtonBox.Ok).setText("好的")
        box.accepted.connect(self.accept)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.addLayout(info)
        lay.addWidget(box)
