"""书签医生（Bookmark Doctor）—— 书签清洗整理工具入口。"""

from __future__ import annotations

import os
import sys

APP_NAME = "Bookmark Doctor"
APP_NAME_CN = "书签医生"
APP_ORG = "Bookmark Doctor"
APP_VERSION = "1.0.0"
ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")


def _setup_path():
    base = os.path.dirname(os.path.abspath(__file__))
    if base not in sys.path:
        sys.path.insert(0, base)


def _load_icon():
    """尝试加载自定义图标；失败则用应用默认图标。"""
    from PySide6.QtGui import QIcon
    for name in ("icon.ico", "icon.png"):
        path = os.path.join(ICON_DIR, name)
        if os.path.exists(path):
            ic = QIcon(path)
            if not ic.isNull():
                return ic
    return QIcon()


def main():
    _setup_path()

    # 高 DPI 下图标与文字更清晰
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except Exception:  # noqa: BLE001
        pass

    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFont

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME_CN)
    app.setOrganizationName(APP_ORG)
    app.setStyle("Fusion")
    app.setWindowIcon(_load_icon())

    f = QFont("Microsoft YaHei UI", 9)
    app.setFont(f)

    from ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
