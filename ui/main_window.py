"""主窗口。"""

from __future__ import annotations

import os
import time
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QAction, QBrush, QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QFileDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMenu, QMessageBox, QProgressBar, QPushButton, QStatusBar, QTableWidget,
    QTableWidgetItem, QTextEdit, QTextBrowser, QToolBar, QVBoxLayout, QWidget,
)

import config
from core import classifier, navgen, parser, rules as rules_mod
from core.models import (
    BAD_VERDICTS, EXIT_CUSTOM, EXIT_DIRECT, EXIT_SYSTEM, OVERRIDE_DEAD,
    OVERRIDE_OK, STATUS_HINT, SUBTYPE_HINT, SUBTYPES, V_DEAD,
    V_OK, V_SKIPPED, V_SUSPECT, V_UNKNOWN, VERDICTS, Bookmark, domain_of,
    verdict_sort_key,
)
from ui.dialogs import SettingsDialog, TaxonomyDialog
from ui.recheck_dialog import RecheckDialog
from ui.workers import (
    AIClassifyWorker, DedupeWorker, LoadWorker, LocalClassifyWorker,
    ProbeWorker,
)

COL_CHECK, COL_KEEP, COL_VERDICT, COL_CONF, COL_TITLE, COL_URL, COL_FOLDER, COL_CAT, COL_EXIT = range(9)
HEADERS = ["选择", "保留", "结论", "置信度", "标题", "网址", "原文件夹", "新分类", "出口"]

VERDICT_COLOR = {
    V_OK: "#3B6D11",
    V_SUSPECT: "#854F0B",
    V_DEAD: "#A32D2D",
    V_SKIPPED: "#888780",
    V_UNKNOWN: "#888780",
}

VERDICT_ORDER = {
    V_OK: 0, V_UNKNOWN: 1, V_SKIPPED: 2, V_SUSPECT: 3, V_DEAD: 4,
}

STYLE = """
QMainWindow, QDialog { background:#ffffff; }
QToolBar { background:#fafaf9; border:none; padding:6px 8px; spacing:4px; }
QToolBar QToolButton { padding:6px 12px; border:1px solid #e3e2dd;
  border-radius:6px; background:#ffffff; }
QToolBar QToolButton:hover { background:#f1efe8; }
QToolBar QToolButton:disabled { color:#b4b2a9; background:#fafaf9; }
QTableWidget { gridline-color:#eceae4; selection-background-color:#e6f1fb;
  selection-color:#185fa5; }
QHeaderView::section { background:#fafaf9; padding:6px; border:none;
  border-right:1px solid #eceae4; border-bottom:1px solid #e3e2dd; }
QLineEdit, QComboBox { padding:5px 8px; border:1px solid #e3e2dd;
  border-radius:6px; background:#ffffff; }
QLineEdit:focus, QComboBox:focus { border-color:#378ADD; }
QProgressBar { border:1px solid #e3e2dd; border-radius:6px; height:16px;
  background:#f1efe8; text-align:center; }
QProgressBar::chunk { background:#378ADD; border-radius:5px; }
QTextEdit { border:1px solid #e3e2dd; border-radius:6px; background:#fafaf9; }
"""


class VerdictItem(QTableWidgetItem):
    """让「结论」列按严重度排序，而非字典序。"""

    def __lt__(self, other):
        a = VERDICT_ORDER.get(self.text(), 9)
        b = VERDICT_ORDER.get(other.text(), 9) if hasattr(other, "text") else 9
        return a < b


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = config.load_config()
        self.taxonomy = classifier.load_taxonomy(config.taxonomy_path())
        self.rules: Dict[str, object] = rules_mod.load_rules(config.rules_path())
        self.bookmarks: List[Bookmark] = []
        self.folders: List[str] = []
        self.worker = None
        self.source_path = ""
        self.last_exit = ""
        self.last_ip = ""

        self.setWindowTitle("书签医生 · Bookmark Doctor")
        self.resize(1240, 780)
        self.setStyleSheet(STYLE)

        self._build_actions()
        self._build_ui()
        self.setStatusBar(QStatusBar())
        self._refresh_stats()
        self._log("就绪。请先「导入书签」——支持 Chrome / Edge / Firefox 导出的 HTML，以及 JSON / CSV。")

    # ---------------------------------------------------------------- 界面
    def _build_actions(self):
        self.act_import = QAction("导入书签", self)
        self.act_import.triggered.connect(self.do_import)
        self.act_export_html = QAction("导出为浏览器书签 HTML", self)
        self.act_export_html.triggered.connect(lambda: self.do_export("html"))
        self.act_export_json = QAction("导出为 JSON", self)
        self.act_export_json.triggered.connect(lambda: self.do_export("json"))
        self.act_export_csv = QAction("导出为 CSV", self)
        self.act_export_csv.triggered.connect(lambda: self.do_export("csv"))

        self.act_dedupe = QAction("去重", self)
        self.act_dedupe.triggered.connect(self.do_dedupe)
        self.act_probe = QAction("验证可达性", self)
        self.act_probe.triggered.connect(self.do_probe)
        self.act_recheck = QAction("复检存疑项", self)
        self.act_recheck.triggered.connect(self.do_recheck)
        self.act_classify_local = QAction("本地规则归类", self)
        self.act_classify_local.triggered.connect(self.do_classify_local)
        self.act_classify_ai = QAction("AI 智能归类", self)
        self.act_classify_ai.triggered.connect(self.do_classify_ai)
        self.act_apply = QAction("把分类写回文件夹结构", self)
        self.act_apply.triggered.connect(self.do_apply_category)
        self.act_nav = QAction("生成导航网页", self)
        self.act_nav.triggered.connect(self.do_nav)
        self.act_settings = QAction("设置", self)
        self.act_settings.triggered.connect(self.do_settings)
        self.act_tax = QAction("分类体系", self)
        self.act_tax.triggered.connect(self.do_taxonomy)
        self.act_rules = QAction("域名规则", self)
        self.act_rules.triggered.connect(self.do_rules)
        self.act_stop = QAction("停止", self)
        self.act_stop.triggered.connect(self.do_stop)
        self.act_stop.setEnabled(False)
        self.act_about = QAction("关于", self)
        self.act_about.triggered.connect(self.do_about)

        menubar = self.menuBar()
        m_file = menubar.addMenu("文件")
        m_file.addAction(self.act_import)
        m_file.addSeparator()
        for a in (self.act_export_html, self.act_export_json, self.act_export_csv):
            m_file.addAction(a)
        m_file.addSeparator()
        m_file.addAction(self.act_settings)

        m_tool = menubar.addMenu("处理")
        m_tool.addAction(self.act_dedupe)
        m_tool.addAction(self.act_probe)
        m_tool.addAction(self.act_recheck)
        m_tool.addSeparator()
        m_tool.addAction(self.act_classify_local)
        m_tool.addAction(self.act_classify_ai)
        m_tool.addAction(self.act_apply)
        m_tool.addSeparator()
        m_tool.addAction(self.act_nav)
        m_tool.addAction(self.act_tax)
        m_tool.addAction(self.act_rules)

        m_help = menubar.addMenu("帮助")
        m_help.addAction(self.act_about)

    def _build_ui(self):
        self._loading = False
        tb = QToolBar("主工具栏")
        tb.setMovable(False)
        self.addToolBar(tb)
        for act in (self.act_import, self.act_dedupe, self.act_probe,
                    self.act_recheck, self.act_classify_local,
                    self.act_classify_ai, self.act_nav, self.act_apply):
            tb.addAction(act)
        tb.addSeparator()
        tb.addAction(self.act_settings)
        tb.addAction(self.act_tax)
        tb.addAction(self.act_rules)
        tb.addSeparator()
        tb.addAction(self.act_stop)

        self.ed_search = QLineEdit()
        self.ed_search.setPlaceholderText("搜索标题 / 网址 / 文件夹 / 分类…")
        self.ed_search.setClearButtonEnabled(True)
        self.ed_search.textChanged.connect(self._populate)
        self.cb_verdict = QComboBox()
        self.cb_verdict.addItem("全部结论")
        self.cb_verdict.currentIndexChanged.connect(self._populate)
        self.cb_subtype = QComboBox()
        self.cb_subtype.addItem("全部原因")
        self.cb_subtype.currentIndexChanged.connect(self._populate)
        self.cb_cat = QComboBox()
        self.cb_cat.addItem("全部分类")
        self.cb_cat.currentIndexChanged.connect(self._populate)
        self.ck_hide_dup = QCheckBox("隐藏重复项")
        self.ck_hide_dup.stateChanged.connect(self._populate)
        self.ck_suspect = QCheckBox("只看存疑")
        self.ck_suspect.stateChanged.connect(self._populate)
        self.lb_stats = QLabel("")

        # 批量操作区
        self.lb_selected = QLabel("已选 0 条")
        self.btn_sel_all = QPushButton("全选")
        self.btn_sel_none = QPushButton("取消")
        self.btn_mark_ok = QPushButton("标可访问")
        self.btn_mark_dead = QPushButton("标失效")
        self.btn_del = QPushButton("删除选中")
        self.btn_exp = QPushButton("导出选中")
        self.btn_sel_all.clicked.connect(lambda: self._select_all())
        self.btn_sel_none.clicked.connect(lambda: self._select_none())
        self.btn_mark_ok.clicked.connect(lambda: self._batch_override(OVERRIDE_OK))
        self.btn_mark_dead.clicked.connect(lambda: self._batch_override(OVERRIDE_DEAD))
        self.btn_del.clicked.connect(lambda: self._batch_delete())
        self.btn_exp.clicked.connect(lambda: self._batch_export())
        for b in (self.btn_mark_ok, self.btn_mark_dead, self.btn_del, self.btn_exp):
            b.setEnabled(False)

        filt = QHBoxLayout()
        filt.addWidget(self.ed_search, 2)
        filt.addWidget(self.cb_verdict)
        filt.addWidget(self.cb_subtype)
        filt.addWidget(self.cb_cat)
        filt.addWidget(self.ck_hide_dup)
        filt.addWidget(self.ck_suspect)
        filt.addStretch(1)
        filt.addWidget(self.lb_stats)
        filt.addSpacing(14)
        filt.addWidget(QLabel("批量:"))
        filt.addWidget(self.btn_sel_all)
        filt.addWidget(self.btn_sel_none)
        filt.addWidget(self.lb_selected)
        filt.addWidget(self.btn_mark_ok)
        filt.addWidget(self.btn_mark_dead)
        filt.addWidget(self.btn_del)
        filt.addWidget(self.btn_exp)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.doubleClicked.connect(lambda _: self._open_selected())
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(COL_CHECK, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_KEEP, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_VERDICT, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_CONF, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_TITLE, QHeaderView.Interactive)
        hh.setSectionResizeMode(COL_URL, QHeaderView.Stretch)
        hh.setSectionResizeMode(COL_FOLDER, QHeaderView.Interactive)
        hh.setSectionResizeMode(COL_CAT, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_EXIT, QHeaderView.ResizeToContents)
        self.table.setColumnWidth(COL_TITLE, 200)
        self.table.setColumnWidth(COL_FOLDER, 140)

        self.progress = QProgressBar()
        self.progress.setTextVisible(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(120)

        bot = QHBoxLayout()
        bot.addWidget(QLabel("进度"))
        bot.addWidget(self.progress, 1)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(8)
        lay.addLayout(filt)
        lay.addWidget(self.table, 1)
        lay.addLayout(bot)
        lay.addWidget(self.log)
        self.setCentralWidget(central)

    # ---------------------------------------------------------------- 工具
    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log.append(f'<span style="color:#888780">[{ts}]</span> {msg}')
        self.statusBar().showMessage(msg, 8000)

    def _set_busy(self, busy: bool, label: str = ""):
        for act in (self.act_import, self.act_dedupe, self.act_probe,
                    self.act_recheck, self.act_classify_local,
                    self.act_classify_ai, self.act_nav, self.act_apply,
                    self.act_export_html, self.act_export_json,
                    self.act_export_csv, self.act_tax, self.act_rules):
            act.setEnabled(not busy)
        self.act_stop.setEnabled(busy)
        if busy:
            self.progress.setValue(0)
        elif label:
            self._log(label)

    def _run_worker(self, worker, on_done, on_fail=None):
        self.worker = worker
        self._set_busy(True)
        worker.progress.connect(self._on_progress)
        worker.log.connect(self._log)
        worker.finished_ok.connect(on_done)
        worker.failed.connect(on_fail or (lambda e: self._log(f"✗ {e}")))
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        worker.start()

    def _on_worker_finished(self, worker):
        if self.worker is worker:
            self._set_busy(False)

    def _on_progress(self, done: int, total: int, msg: str):
        if total > 0:
            self.progress.setValue(min(100, int(done * 100 / total)))
        if msg:
            self.statusBar().showMessage(f"{done}/{total} · {msg}", 3000)

    def _visible(self, bm: Bookmark) -> bool:
        q = self.ed_search.text().strip().lower()
        if q:
            hay = f"{bm.title} {bm.url} {bm.folder} {bm.category}".lower()
            if q not in hay:
                return False
        vt = self.cb_verdict.currentText()
        if vt != "全部结论" and bm.effective_verdict != vt:
            return False
        st = self.cb_subtype.currentText()
        if st != "全部原因" and bm.effective_subtype != st:
            return False
        ct = self.cb_cat.currentText()
        if ct != "全部分类" and (bm.category or "未分类") != ct:
            return False
        if self.ck_hide_dup.isChecked() and not bm.keep:
            return False
        if self.ck_suspect.isChecked() and bm.effective_verdict != V_SUSPECT:
            return False
        return True

    def _populate(self):
        self._loading = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        rows = [(i, b) for i, b in enumerate(self.bookmarks) if self._visible(b)]
        self.table.setRowCount(len(rows))
        for r, (i, bm) in enumerate(rows):
            self._set_row(r, i, bm)
        self.table.setSortingEnabled(True)
        self._loading = False
        self._refresh_stats()
        self._update_selected_label()

    def _set_row(self, r: int, i: int, bm: Bookmark):
        def item(text, tip=""):
            it = QTableWidgetItem(text)
            it.setData(Qt.UserRole, i)
            if tip:
                it.setToolTip(tip)
            return it

        it_check = QTableWidgetItem()
        it_check.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
        it_check.setCheckState(Qt.Checked if bm.selected else Qt.Unchecked)
        it_check.setTextAlignment(Qt.AlignCenter)
        it_check.setData(Qt.UserRole, i)
        self.table.setItem(r, COL_CHECK, it_check)

        it_keep = item("✓" if bm.keep else "✗")
        it_keep.setTextAlignment(Qt.AlignCenter)
        if not bm.keep:
            it_keep.setForeground(QBrush(QColor("#A32D2D")))
        self.table.setItem(r, COL_KEEP, it_keep)

        v = bm.effective_verdict
        hint = STATUS_HINT.get(v, "")
        if bm.effective_subtype:
            hint = SUBTYPE_HINT.get(bm.effective_subtype, hint)
        it_v = VerdictItem(v)
        it_v.setData(Qt.UserRole, i)
        it_v.setToolTip(hint)
        it_v.setForeground(QBrush(QColor(VERDICT_COLOR.get(v, "#5F5E5A"))))
        self.table.setItem(r, COL_VERDICT, it_v)

        self.table.setItem(r, COL_CONF, item(bm.confidence))

        it_title = item(bm.display_title(80), bm.title)
        if not bm.keep:
            it_title.setForeground(QBrush(QColor("#B4B2A9")))
        self.table.setItem(r, COL_TITLE, it_title)

        self.table.setItem(r, COL_URL, item(bm.url, bm.url))
        self.table.setItem(r, COL_FOLDER, item(bm.folder, bm.folder))
        self.table.setItem(r, COL_CAT, item(bm.category or "未分类"))

        it_exit = item(bm.exits)
        if bm.probes:
            it_exit.setToolTip("\n".join(p.brief() for p in bm.probes[-6:]))
        self.table.setItem(r, COL_EXIT, it_exit)

    def _refresh_stats(self):
        total = len(self.bookmarks)
        # 计数一律基于「当前筛选结果」，未筛选时才等于全量
        shown = [b for b in self.bookmarks if self._visible(b)]
        n = len(shown)
        keep = sum(1 for b in shown if b.keep)
        dup = n - keep
        suspect = sum(1 for b in shown if b.effective_verdict == V_SUSPECT)
        dead = sum(1 for b in shown if b.effective_verdict == V_DEAD)
        ok = sum(1 for b in shown if b.effective_verdict == V_OK)

        if n == total:
            head = f'总计 <b>{total}</b> 条'
        else:
            head = (f'<span style="color:#185FA5">筛出 <b>{n}</b></span>'
                    f' / 总计 {total}')

        self.lb_stats.setText(
            f'{head} · 可访问 <b>{ok}</b>'
            f' · 存疑 <b>{suspect}</b> · 失效 <b>{dead}</b> · 重复 <b>{dup}</b>'
        )
        self._sync_filters()

    def _sync_filters(self):
        seen, subs = [], []
        for b in self.bookmarks:
            if b.effective_verdict not in seen:
                seen.append(b.effective_verdict)
            if b.effective_subtype and b.effective_subtype not in subs:
                subs.append(b.effective_subtype)

        cur_v = self.cb_verdict.currentText()
        self.cb_verdict.blockSignals(True)
        self.cb_verdict.clear()
        self.cb_verdict.addItem("全部结论")
        for s in seen:
            self.cb_verdict.addItem(s)
        if cur_v in seen:
            self.cb_verdict.setCurrentText(cur_v)
        self.cb_verdict.blockSignals(False)

        cur_s = self.cb_subtype.currentText()
        self.cb_subtype.blockSignals(True)
        self.cb_subtype.clear()
        self.cb_subtype.addItem("全部原因")
        for s in subs:
            self.cb_subtype.addItem(s)
        if cur_s in subs:
            self.cb_subtype.setCurrentText(cur_s)
        self.cb_subtype.blockSignals(False)

        cats = sorted({b.category for b in self.bookmarks if b.category})
        cur_c = self.cb_cat.currentText()
        self.cb_cat.blockSignals(True)
        self.cb_cat.clear()
        self.cb_cat.addItem("全部分类")
        self.cb_cat.addItems(cats)
        if cur_c in cats:
            self.cb_cat.setCurrentText(cur_c)
        self.cb_cat.blockSignals(False)

    def _selected_index(self) -> Optional[int]:
        row = self.table.currentRow()
        if row < 0:
            return None
        it = self.table.item(row, COL_CHECK)
        return it.data(Qt.UserRole) if it else None

    def _selected_bookmarks(self) -> List[Bookmark]:
        return [b for b in self.bookmarks if b.selected]

    def _on_item_changed(self, it: QTableWidgetItem):
        if self._loading:
            return
        if it.column() != COL_CHECK:
            return
        i = it.data(Qt.UserRole)
        if i is None:
            return
        self.bookmarks[i].selected = (it.checkState() == Qt.Checked)
        self._update_selected_label()

    def _update_selected_label(self):
        n = sum(1 for b in self.bookmarks if b.selected)
        self.lb_selected.setText(f"已选 {n} 条")
        has = n > 0
        self.btn_mark_ok.setEnabled(has)
        self.btn_mark_dead.setEnabled(has)
        self.btn_del.setEnabled(has)
        self.btn_exp.setEnabled(has)

    def _select_all(self):
        self._loading = True
        for r in range(self.table.rowCount()):
            it = self.table.item(r, COL_CHECK)
            if it is None:
                continue
            i = it.data(Qt.UserRole)
            if i is not None:
                self.bookmarks[i].selected = True
                it.setCheckState(Qt.Checked)
        self._loading = False
        self._update_selected_label()

    def _select_none(self):
        self._loading = True
        for r in range(self.table.rowCount()):
            it = self.table.item(r, COL_CHECK)
            if it is None:
                continue
            i = it.data(Qt.UserRole)
            if i is not None:
                self.bookmarks[i].selected = False
                it.setCheckState(Qt.Unchecked)
        self._loading = False
        self._update_selected_label()

    def _open_selected(self):
        i = self._selected_index()
        if i is None:
            return
        QDesktopServices.openUrl(QUrl(self.bookmarks[i].url))

    # ---------------------------------------------------------------- 右键
    def _menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        it = self.table.item(row, COL_CHECK)
        cur = it.data(Qt.UserRole) if it else None
        if cur is None:
            return
        sel = [i for i, b in enumerate(self.bookmarks) if b.selected]
        targets = sel if sel else [cur]
        n = len(targets)

        m = QMenu(self)
        if n == 1:
            m.addAction("打开链接",
                        lambda: QDesktopServices.openUrl(QUrl(self.bookmarks[cur].url)))
            m.addAction("复制网址",
                        lambda: QApplication.clipboard().setText(self.bookmarks[cur].url))
        else:
            m.addAction(f"打开选中的 {n} 条链接",
                        lambda: [QDesktopServices.openUrl(QUrl(self.bookmarks[i].url))
                                 for i in targets])
            m.addAction(f"复制选中的 {n} 条网址",
                        lambda: QApplication.clipboard().setText(
                            "\n".join(self.bookmarks[i].url for i in targets)))
        m.addSeparator()
        m.addAction("标记为可访问 ★", lambda: self._batch_override(OVERRIDE_OK, targets))
        m.addAction("标记为已失效 ★", lambda: self._batch_override(OVERRIDE_DEAD, targets))
        m.addAction("清除人工裁定", lambda: self._batch_clear_override(targets))
        m.addSeparator()
        m.addAction("重新验证选中项", lambda: self._batch_reprobe(targets))
        m.addAction("查看探测历史", lambda: self._show_probes(cur))
        m.addSeparator()
        sub = m.addMenu("对选中域名应用规则")
        sub.addAction("需要代理访问",
                      lambda: self._batch_apply_rule(targets, rules_mod.ACTION_PROXY))
        sub.addAction("需要直连访问",
                      lambda: self._batch_apply_rule(targets, rules_mod.ACTION_DIRECT))
        sub.addAction("跳过检测",
                      lambda: self._batch_apply_rule(targets, rules_mod.ACTION_SKIP))
        m.addSeparator()
        m.addAction("切换保留/剔除", lambda: self._batch_toggle_keep(targets))
        m.addAction("删除选中项", lambda: self._batch_delete(targets))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _toggle_keep(self, i: int):
        self.bookmarks[i].keep = not self.bookmarks[i].keep
        self._populate()

    def _delete(self, i: int):
        del self.bookmarks[i]
        self._populate()

    def _override(self, i: int, kind: str):
        bm = self.bookmarks[i]
        bm.override = kind
        bm.merge_verdict()
        self._populate()
        if kind:
            label = "可访问" if kind == OVERRIDE_OK else "已失效"
            self._log(f"已人工标记「{bm.display_title(30)}」为 {label}（不会被自动检测覆盖）")

    def _apply_rule(self, i: int, action: str):
        bm = self.bookmarks[i]
        dom = bm.domain or domain_of(bm.url)
        if not dom:
            QMessageBox.information(self, "提示", "该条目没有有效域名")
            return
        rules_mod.put_rule(self.rules, dom, action)
        rules_mod.save_rules(config.rules_path(), self.rules)
        self._log(f"已保存规则：{dom} → {rules_mod.ACTIONS.get(action, action)}")
        self._populate()

    def _show_probes(self, i: int):
        bm = self.bookmarks[i]
        dlg = QDialog(self)
        dlg.setWindowTitle(f"探测历史 · {bm.display_title(40)}")
        dlg.resize(560, 340)
        lay = QVBoxLayout(dlg)
        txt = QTextBrowser()
        lines = [f"<b>{bm.url}</b>", ""]
        if not bm.probes:
            lines.append("尚未检测")
        else:
            for p in bm.probes:
                t = time.strftime("%m-%d %H:%M:%S", time.localtime(p.ts))
                detail = f"HTTP {p.status_code}" if p.status_code else p.error
                soft = " · 疑似软404" if p.soft404 else ""
                ip = f" · 公网 {p.public_ip}" if p.public_ip else ""
                lines.append(
                    f"<b>{p.exit_profile}</b> · {t}<br>"
                    f"&nbsp;&nbsp;{p.method or '—'} → {detail}{soft} · {p.elapsed_ms}ms{ip}"
                )
        txt.setHtml("<br>".join(lines))
        lay.addWidget(txt)
        dlg.exec()

    def _reprobe_one(self, i: int):
        from config import make_probe_config
        self._run_worker(
            ProbeWorker(self.bookmarks, self.cfg, self.rules,
                        only=[self.bookmarks[i]]),
            lambda stats: self._populate(),
        )

    # ---------------------------------------------------------------- 批量操作
    def _batch_override(self, kind: str, targets: Optional[List[int]] = None):
        sel = [self.bookmarks[i] for i in targets] if targets is not None \
            else self._selected_bookmarks()
        if not sel:
            QMessageBox.information(self, "提示", "请先勾选要操作的书签")
            return
        for b in sel:
            b.override = kind
            b.merge_verdict()
        label = "可访问" if kind == OVERRIDE_OK else "已失效"
        self._log(f"已批量标记 {len(sel)} 条为「{label}」")
        self._populate()

    def _batch_clear_override(self, targets: List[int]):
        for i in targets:
            self.bookmarks[i].override = ""
            self.bookmarks[i].merge_verdict()
        self._log(f"已清除 {len(targets)} 条的人工裁定")
        self._populate()

    def _batch_toggle_keep(self, targets: List[int]):
        for i in targets:
            self.bookmarks[i].keep = not self.bookmarks[i].keep
        self._log(f"已切换 {len(targets)} 条的保留状态")
        self._populate()

    def _batch_reprobe(self, targets: List[int]):
        if not targets:
            return
        from config import make_probe_config
        self._run_worker(
            ProbeWorker(self.bookmarks, self.cfg, self.rules,
                        only=[self.bookmarks[i] for i in targets]),
            lambda stats: self._populate(),
        )

    def _batch_apply_rule(self, targets: List[int], action: str):
        doms = set()
        for i in targets:
            dom = self.bookmarks[i].domain or domain_of(self.bookmarks[i].url)
            if dom:
                rules_mod.put_rule(self.rules, dom, action)
                doms.add(dom)
        if not doms:
            QMessageBox.information(self, "提示", "选中项没有有效域名")
            return
        rules_mod.save_rules(config.rules_path(), self.rules)
        self._log(f"已对 {len(doms)} 个域名应用规则："
                  f"{rules_mod.ACTIONS.get(action, action)}")
        self._populate()

    def _batch_delete(self, targets: Optional[List[int]] = None):
        sel = targets if targets is not None \
            else [i for i, b in enumerate(self.bookmarks) if b.selected]
        if not sel:
            QMessageBox.information(self, "提示", "请先勾选要删除的书签")
            return
        ans = QMessageBox.question(
            self, "确认删除",
            f"确定删除勾选的 {len(sel)} 条书签？此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        drop = set(sel)
        self.bookmarks = [b for j, b in enumerate(self.bookmarks) if j not in drop]
        self._log(f"已删除 {len(sel)} 条书签")
        self._populate()

    def _batch_export(self):
        sel = self._selected_bookmarks()
        if not sel:
            QMessageBox.information(self, "提示", "请先勾选要导出的书签")
            return
        self._export_items(sel, "选中项", "html")

    # ---------------------------------------------------------------- 功能
    def do_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择书签文件", self.cfg.get("last_dir", "") or os.path.expanduser("~"),
            "书签文件 (*.html *.htm *.json *.csv);;所有文件 (*.*)")
        if not path:
            return
        self.cfg["last_dir"] = os.path.dirname(path)
        config.save_config(self.cfg)
        self.source_path = path
        self._run_worker(LoadWorker(path), self._on_loaded)

    def _on_loaded(self, result):
        self.folders, self.bookmarks = result
        self._log(f"导入成功：{len(self.bookmarks)} 条书签")
        self._populate()

    def do_dedupe(self):
        if not self.bookmarks:
            return self._need_data()
        lvl = self.cfg.get("dedupe_level", "标准")
        self._run_worker(
            DedupeWorker(self.bookmarks, lvl, float(self.cfg.get("dedupe_threshold", 0.92))),
            lambda n: (self._populate(),
                       self._log(f"去重完成，已剔除标记 {n} 条"
                                 f"（可取消「隐藏重复项」查看）")),
        )

    def do_probe(self):
        if not self.bookmarks:
            return self._need_data()
        self._start_probe(None, self.cfg.get("exit_profile", EXIT_SYSTEM))

    def do_recheck(self):
        if not self.bookmarks:
            return self._need_data()
        targets = self._recheck_targets()
        if not targets:
            QMessageBox.information(
                self, "无需复检",
                "没有需要复检的条目。\n\n"
                "「复检」只重跑存疑与未确认的条目——"
                "已确认可访问的不会重复检测。")
            return
        dlg = RecheckDialog(targets, self.last_exit, self.last_ip, self)
        if not dlg.exec():
            return
        rc = dlg.result_config()
        cfg = dict(self.cfg)
        cfg.update(rc)
        self._start_probe(targets, rc["exit_profile"], cfg)

    def _recheck_targets(self):
        from core.prober import collect_for_recheck
        return collect_for_recheck(self.bookmarks, also_dead=True)

    def _start_probe(self, only, exit_profile, cfg=None):
        cfg = cfg or self.cfg
        self.last_exit = exit_profile
        self._run_worker(
            ProbeWorker(self.bookmarks, cfg, self.rules, only=only),
            self._on_probe_done,
        )

    def _on_probe_done(self, stats):
        self._populate()
        suspect = stats.get(V_SUSPECT, 0)
        if suspect:
            self._log(f"还有 {suspect} 条存疑，可切换网络后点「复检存疑项」继续。")

    def do_classify_local(self):
        if not self.bookmarks:
            return self._need_data()
        self._run_worker(LocalClassifyWorker(self.bookmarks, self.taxonomy),
                         lambda counts: self._populate())

    def do_classify_ai(self):
        if not self.bookmarks:
            return self._need_data()
        if not self.cfg.get("api_key"):
            r = QMessageBox.question(
                self, "未配置 AI",
                "还没有配置 API Key。\n\n点「是」去设置，点「否」改用本地规则归类。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if r == QMessageBox.Yes:
                self.do_settings()
                if not self.cfg.get("api_key"):
                    return
            else:
                return self.do_classify_local()
        cats = classifier.category_names(self.taxonomy)

        def on_done(res):
            self._populate()
            if res.get("failed"):
                self._log("正在用本地规则补齐 AI 未覆盖的条目…")
                self._run_worker(LocalClassifyWorker(self.bookmarks, self.taxonomy),
                                 lambda c: self._populate())

        self._run_worker(AIClassifyWorker(self.bookmarks, self.cfg, cats), on_done)

    def do_apply_category(self):
        if not self.bookmarks:
            return self._need_data()
        if not any(b.category for b in self.bookmarks):
            QMessageBox.information(self, "提示", "请先执行归类（AI 或本地规则）")
            return
        n = 0
        for b in self.bookmarks:
            if b.category:
                b.folder = b.category
                n += 1
        self._populate()
        self._log(f"已把新分类写回文件夹结构（{n} 条），导出后即为新的目录层级")

    def do_nav(self):
        if not self.bookmarks:
            return self._need_data()
        default = os.path.join(self.cfg.get("last_dir", "") or os.path.expanduser("~"),
                               "书签导航.html")
        path, _ = QFileDialog.getSaveFileName(self, "保存导航网页", default, "网页 (*.html)")
        if not path:
            return
        try:
            n = navgen.generate_nav(self.bookmarks, path, title="我的书签导航")
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "生成失败", str(e))
            return
        self._log(f"导航页已生成：{n} 条 → {path}")
        if QMessageBox.question(
                self, "完成", f"已生成 {n} 条书签的导航页：\n{path}\n\n立即打开？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes) == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _ask_export_scope(self):
        """让用户选择导出范围。有筛选时默认导出筛选结果。"""
        shown = [b for b in self.bookmarks if self._visible(b)]
        kept = [b for b in self.bookmarks if b.keep]
        total = len(self.bookmarks)

        box = QMessageBox(self)
        box.setWindowTitle("导出范围")
        box.setText("要导出哪些书签？")
        box.setInformativeText(
            f"当前筛选结果：{len(shown)} 条\n"
            f"保留项（已去重）：{len(kept)} 条\n"
            f"全部：{total} 条")

        b_shown = box.addButton("导出筛选结果", QMessageBox.AcceptRole)
        b_kept = box.addButton("导出保留项", QMessageBox.ActionRole)
        b_all = box.addButton("导出全部", QMessageBox.ActionRole)
        box.addButton("取消", QMessageBox.RejectRole)
        # 正在筛选时，最可能想要的就是筛选结果
        box.setDefaultButton(b_shown if len(shown) < total else b_kept)
        box.exec()

        clicked = box.clickedButton()
        if clicked is b_shown:
            return shown, "筛选结果"
        if clicked is b_kept:
            return kept, "保留项"
        if clicked is b_all:
            return list(self.bookmarks), "全部"
        return None, ""

    def do_export(self, kind: str):
        if not self.bookmarks:
            return self._need_data()

        items, scope = self._ask_export_scope()
        if items is None:
            return
        if not items:
            QMessageBox.information(self, "提示", "该范围内没有书签")
            return
        self._export_items(items, scope, kind)

    def _export_items(self, items, scope: str, kind: str):
        base = self.cfg.get("last_dir", "") or os.path.expanduser("~")
        if kind == "html":
            path, _ = QFileDialog.getSaveFileName(self, "导出书签 HTML",
                                                  os.path.join(base, "bookmarks.html"),
                                                  "书签 HTML (*.html)")
            fn = parser.export_netscape
        elif kind == "json":
            path, _ = QFileDialog.getSaveFileName(self, "导出 JSON",
                                                  os.path.join(base, "bookmarks.json"),
                                                  "JSON (*.json)")
            fn = parser.export_json
        else:
            path, _ = QFileDialog.getSaveFileName(self, "导出 CSV",
                                                  os.path.join(base, "bookmarks.csv"),
                                                  "CSV (*.csv)")
            fn = parser.export_csv
        if not path:
            return
        try:
            n = fn(items, path)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "导出失败", str(e))
            return
        self._log(f"已导出 {n} 条（{scope}）→ {path}")

    def do_settings(self):
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec():
            self.cfg = dlg.result_config()
            config.save_config(self.cfg)
            self._log("设置已保存")

    def do_taxonomy(self):
        dlg = TaxonomyDialog(self.taxonomy, self)
        if dlg.exec():
            self.taxonomy = dlg.result_taxonomy()
            classifier.save_taxonomy(config.taxonomy_path(), self.taxonomy)
            self._log(f"分类体系已保存（{len(self.taxonomy)} 个分类）")

    def do_rules(self):
        from ui.rules_dialog import RulesDialog
        dlg = RulesDialog(self.rules, self)
        if dlg.exec():
            self.rules = dlg.result_rules()
            rules_mod.save_rules(config.rules_path(), self.rules)
            self._log(f"域名规则已保存（{len(self.rules)} 条）")

    def do_stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.request_stop()
            self._log("正在停止…（已得结果会保留）")

    def do_about(self):
        from app import APP_VERSION
        from ui.about_dialog import AboutDialog

        dlg = AboutDialog(self, version=APP_VERSION)
        dlg.exec()

    def _need_data(self):
        QMessageBox.information(self, "提示", "请先导入书签文件")

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.worker.request_stop()
            self.worker.wait(3000)
        config.save_config(self.cfg)
        event.accept()
