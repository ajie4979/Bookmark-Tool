"""复检向导：切换网络出口后重跑未确认的条目。

用法：验证完成后若有存疑/失效项，用户切换网络环境（开/关 VPN），
再打开本向导选另一个出口，只重跑这些条目——结果叠加而非覆盖。
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QRadioButton, QVBoxLayout,
)

from core.models import EXIT_CUSTOM, EXIT_DIRECT, EXIT_SYSTEM, Bookmark


class RecheckDialog(QDialog):
    def __init__(self, targets: List[Bookmark], last_exit: str = "",
                 last_ip: str = "", parent=None):
        super().__init__(parent)
        self.targets = targets
        self.setWindowTitle("复检存疑项")
        self.resize(460, 320)

        lay = QVBoxLayout(self)

        head = QLabel(
            "切换网络环境（开 / 关 VPN）后，用另一个出口再跑一次。\n"
            "任一出口能通，即判定为可访问。"
        )
        head.setWordWrap(True)
        head.setStyleSheet("color:#5F5E5A;font-size:12px")
        lay.addWidget(head)

        box = QGroupBox("本次使用的网络出口")
        f = QFormLayout(box)
        self.rb_direct = QRadioButton(EXIT_DIRECT)
        self.rb_system = QRadioButton(EXIT_SYSTEM)
        self.rb_custom = QRadioButton(EXIT_CUSTOM)
        self.ed_proxy = QLineEdit()
        self.ed_proxy.setPlaceholderText("如 http://127.0.0.1:7890 或 socks5://127.0.0.1:1080")
        self.rb_custom.toggled.connect(self.ed_proxy.setEnabled)
        self.ed_proxy.setEnabled(False)

        self.group = QButtonGroup(self)
        for rb in (self.rb_direct, self.rb_system, self.rb_custom):
            self.group.addButton(rb)
            f.addRow(rb)

        # 默认选中一个与上次不同的出口，省一次点击
        if last_exit == EXIT_DIRECT:
            self.rb_system.setChecked(True)
        else:
            self.rb_direct.setChecked(True)

        f.addRow("代理地址", self.ed_proxy)
        lay.addWidget(box)

        if last_exit or last_ip:
            bits = []
            if last_exit:
                bits.append(f"出口 {last_exit}")
            if last_ip:
                bits.append(f"公网 {last_ip}")
            lb = QLabel("上次验证：" + " · ".join(bits))
            lb.setStyleSheet("color:#888780;font-size:12px")
            lay.addWidget(lb)

        n = len(targets)
        est = max(1, round(n / 32))
        lb2 = QLabel(f"待复检 <b>{n}</b> 条，预计 {est}–{max(2, est * 3)} 秒")
        lb2.setTextFormat(Qt.RichText)
        lay.addWidget(lb2)

        lay.addStretch(1)

        bbox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bbox.button(QDialogButtonBox.Ok).setText("开始复检")
        bbox.button(QDialogButtonBox.Cancel).setText("取消")
        bbox.accepted.connect(self._on_ok)
        bbox.rejected.connect(self.reject)
        lay.addWidget(bbox)

    def _on_ok(self):
        if self.rb_custom.isChecked() and not self.ed_proxy.text().strip():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "提示", "请填写代理地址")
            return
        self.accept()

    def result_config(self) -> dict:
        if self.rb_direct.isChecked():
            profile = EXIT_DIRECT
        elif self.rb_custom.isChecked():
            profile = EXIT_CUSTOM
        else:
            profile = EXIT_SYSTEM
        return {
            "exit_profile": profile,
            "custom_proxy": self.ed_proxy.text().strip(),
        }
