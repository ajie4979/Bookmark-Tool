"""书签医生的"关于"对话框。

使用自定义 QDialog 而非 QMessageBox.about，以便：
- 配置目录展示通用形式（%LOCALAPPDATA%\\BookmarkDoctor 等），不暴露用户名；
- 提供可点击的 GitHub 仓库超链接；
- 更宽松的排版控制。
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app import APP_NAME_CN
import config


# 项目作者与仓库地址
AUTHOR = "阿杰"
GITHUB_URL = "https://github.com/ajie4979/Bookmark-Tool"


def _generic_config_dir() -> str:
    """返回与操作系统无关的通用配置目录描述（不含用户名）。"""
    if sys.platform.startswith("win"):
        return r"%LOCALAPPDATA%\BookmarkDoctor"
    if sys.platform == "darwin":
        return "~/Library/Application Support/BookmarkDoctor"
    return "~/.config/BookmarkDoctor"


class AboutDialog(QDialog):
    """关于对话框。"""

    def __init__(self, parent: QWidget | None = None, version: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle(f"关于 - {APP_NAME_CN}")
        self.setMinimumWidth(520)
        self.setModal(True)

        # 标题
        title = QLabel(
            f"<h2 style='margin:0 0 4px 0;'>书签医生 · Bookmark Doctor</h2>"
        )
        title.setTextFormat(Qt.TextFormat.RichText)
        title.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)

        version_str = f"v{version} · " if version else ""
        subtitle = QLabel(
            f"<p style='margin:0 0 12px 0; color:#666;'>"
            f"{version_str}离线书签治理工具：导入 → 去重 → 验证 → 归类 → 导航页 / 导出。</p>"
        )
        subtitle.setTextFormat(Qt.TextFormat.RichText)
        subtitle.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        subtitle.setWordWrap(True)

        # 关于失效检测
        probe = QLabel(
            "<p style='margin:0 0 10px 0;'><b>关于失效检测</b><br>"
            "站点能不能访问，取决于检测时的网络出口。程序会区分"
            "「确认失效」与「存疑」——存疑不代表坏了，"
            "往往是站点拒绝程序访问或需要特定网络环境。<br>"
            "切换网络（开/关 VPN）后点「复检存疑项」，"
            "任一出口能通即判定为可访问。</p>"
        )
        probe.setTextFormat(Qt.TextFormat.RichText)
        probe.setWordWrap(True)

        # 配置与规则（通用路径 + 实际路径，便于对照）
        cfg_generic = _generic_config_dir()
        cfg_actual = config.config_dir()
        config_section = QLabel(
            "<p style='margin:0 0 10px 0;'><b>配置与规则</b><br>"
            f"通用目录：<code>{cfg_generic}</code><br>"
            "<span style='color:#888;'>实际位置：</span>"
            f"<code style='color:#888;'>{cfg_actual}</code></p>"
        )
        config_section.setTextFormat(Qt.TextFormat.RichText)
        config_section.setWordWrap(True)

        # AI 归类
        ai = QLabel(
            "<p style='margin:0 0 10px 0;'><b>AI 归类</b><br>"
            "使用 OpenAI 兼容接口；未配置时自动回退本地规则。</p>"
        )
        ai.setTextFormat(Qt.TextFormat.RichText)
        ai.setWordWrap(True)

        # 作者 + GitHub 超链接
        author_section = QLabel(
            f"<p style='margin:0 0 4px 0;'><b>作者：</b>{AUTHOR}</p>"
            f"<p style='margin:0;'><b>GitHub：</b>"
            f"<a href='{GITHUB_URL}'>{GITHUB_URL}</a></p>"
        )
        author_section.setTextFormat(Qt.TextFormat.RichText)
        author_section.setOpenExternalLinks(True)
        author_section.setWordWrap(True)

        # OK 按钮
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.setContentsMargins(0, 8, 0, 0)
        buttons.accepted.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(0)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(6)
        layout.addWidget(probe)
        layout.addWidget(config_section)
        layout.addWidget(ai)
        layout.addWidget(author_section)
        layout.addWidget(buttons)