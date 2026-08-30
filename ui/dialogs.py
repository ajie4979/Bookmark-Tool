"""设置对话框与分类体系编辑器。"""

from __future__ import annotations

import json
from typing import Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QTabWidget, QVBoxLayout, QWidget, QCheckBox,
)

from core.dedupe import LEVELS
from core.models import EXIT_CUSTOM, EXIT_DIRECT, EXIT_SYSTEM
from ui.workers import AITestWorker

EXIT_PROFILES = [EXIT_DIRECT, EXIT_SYSTEM, EXIT_CUSTOM]


class SettingsDialog(QDialog):
    def __init__(self, cfg: Dict, parent=None):
        super().__init__(parent)
        self.cfg = dict(cfg)
        self.setWindowTitle("设置")
        self.resize(520, 460)
        self._tester = None

        tabs = QTabWidget(self)
        tabs.addTab(self._ai_tab(), "AI 配置")
        tabs.addTab(self._check_tab(), "失效检测")
        tabs.addTab(self._dedupe_tab(), "去重")

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        box.button(QDialogButtonBox.Ok).setText("确定")
        box.button(QDialogButtonBox.Cancel).setText("取消")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(box)

    # ---------- AI ----------
    def _ai_tab(self):
        w = QWidget()
        f = QFormLayout(w)
        f.setLabelAlignment(Qt.AlignRight)

        self.ed_key = QLineEdit(self.cfg.get("api_key", ""))
        self.ed_key.setEchoMode(QLineEdit.Password)
        self.ed_key.setPlaceholderText("sk-…")
        self.ed_url = QLineEdit(self.cfg.get("base_url", ""))
        self.ed_url.setPlaceholderText("留空用官方接口，或填中转站域名，如 https://kg-api.cloud")
        self.ed_model = QLineEdit(self.cfg.get("model", "gpt-4o-mini"))
        self.sp_batch = QSpinBox()
        self.sp_batch.setRange(5, 100)
        self.sp_batch.setValue(int(self.cfg.get("batch_size", 25)))
        self.sp_workers = QSpinBox()
        self.sp_workers.setRange(1, 10)
        self.sp_workers.setValue(int(self.cfg.get("ai_workers", 3)))
        self.sp_ai_timeout = QSpinBox()
        self.sp_ai_timeout.setRange(15, 300)
        self.sp_ai_timeout.setValue(int(self.cfg.get("ai_timeout", 90)))
        self.sp_ai_timeout.setSuffix(" 秒")

        f.addRow("API Key", self.ed_key)
        f.addRow("接口地址", self.ed_url)
        f.addRow("模型", self.ed_model)
        f.addRow("每批条数", self.sp_batch)
        f.addRow("并发请求数", self.sp_workers)
        f.addRow("请求超时", self.sp_ai_timeout)

        row = QHBoxLayout()
        btn = QPushButton("测试连接")
        btn.clicked.connect(self._test)
        self.lb_test = QLabel("")
        self.lb_test.setWordWrap(True)
        row.addWidget(btn)
        row.addWidget(self.lb_test, 1)
        f.addRow("", self._wrap(row))

        tip = QLabel(
            "没填 Key 也能用：程序会自动回退到本地规则分类。\n"
            "接口地址会自动补全 /v1/chat/completions，填域名或完整地址均可。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#888780;font-size:12px")
        f.addRow("", tip)
        return w

    def _wrap(self, layout):
        w = QWidget()
        w.setLayout(layout)
        return w

    def _test(self):
        cfg = self._collect()
        if not cfg["api_key"]:
            QMessageBox.information(self, "提示", "请先填写 API Key")
            return
        self.lb_test.setText("连接中…")
        self._tester = AITestWorker(cfg, self)
        self._tester.finished_ok.connect(lambda info: self.lb_test.setText("✓ " + info))
        self._tester.failed.connect(lambda e: self.lb_test.setText("✗ " + str(e)))
        self._tester.start()

    # ---------- 检测 ----------
    def _check_tab(self):
        w = QWidget()
        f = QFormLayout(w)
        f.setLabelAlignment(Qt.AlignRight)
        self.sp_cw = QSpinBox()
        self.sp_cw.setRange(1, 128)
        self.sp_cw.setValue(int(self.cfg.get("check_workers", 32)))
        self.sp_ct = QSpinBox()
        self.sp_ct.setRange(1, 60)
        self.sp_ct.setValue(int(self.cfg.get("check_timeout", 8)))
        self.sp_ct.setSuffix(" 秒")
        self.sp_cr = QSpinBox()
        self.sp_cr.setRange(0, 5)
        self.sp_cr.setValue(int(self.cfg.get("check_retries", 1)))
        self.cb_ssl = QCheckBox("校验 SSL 证书（关闭可避免证书错误误判）")
        self.cb_ssl.setChecked(bool(self.cfg.get("verify_ssl", False)))

        self.cb_exit = QComboBox()
        self.cb_exit.addItems(EXIT_PROFILES)
        cur_exit = self.cfg.get("exit_profile", EXIT_SYSTEM)
        self.cb_exit.setCurrentIndex(
            EXIT_PROFILES.index(cur_exit) if cur_exit in EXIT_PROFILES else 1)
        self.ed_proxy = QLineEdit(self.cfg.get("custom_proxy", ""))
        self.ed_proxy.setPlaceholderText("如 http://127.0.0.1:7890 或 socks5://127.0.0.1:1080")

        self.sp_delay = QSpinBox()
        self.sp_delay.setRange(0, 2000)
        self.sp_delay.setSingleStep(50)
        self.sp_delay.setValue(int(self.cfg.get("domain_delay", 100)))
        self.sp_delay.setSuffix(" 毫秒")

        self.cb_fallback = QCheckBox(
            "HEAD 返回 4xx/5xx 时用 GET 复核（强烈建议开启）")
        self.cb_fallback.setChecked(bool(self.cfg.get("enable_fallback", True)))
        self.cb_soft404 = QCheckBox("检测软 404（返回 200 但内容是「页面不存在」）")
        self.cb_soft404.setChecked(bool(self.cfg.get("enable_soft404", True)))
        self.cb_pubip = QCheckBox("记录本次验证的公网出口（会访问外部 IP 查询服务）")
        self.cb_pubip.setChecked(bool(self.cfg.get("record_public_ip", False)))

        f.addRow("默认网络出口", self.cb_exit)
        f.addRow("自定义代理", self.ed_proxy)
        f.addRow("并发线程数", self.sp_cw)
        f.addRow("单条超时", self.sp_ct)
        f.addRow("失败重试次数", self.sp_cr)
        f.addRow("同域名最小间隔", self.sp_delay)
        f.addRow("", self.cb_fallback)
        f.addRow("", self.cb_soft404)
        f.addRow("", self.cb_pubip)
        f.addRow("", self.cb_ssl)

        tip = QLabel(
            "站点能不能访问，取决于检测时的网络出口。\n"
            "验证后若有「存疑」，切换网络（开/关 VPN）再点「复检存疑项」，\n"
            "任一出口能通即判定为可访问。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#888780;font-size:12px")
        f.addRow("", tip)
        return w

    # ---------- 去重 ----------
    def _dedupe_tab(self):
        w = QWidget()
        f = QFormLayout(w)
        f.setLabelAlignment(Qt.AlignRight)
        self.cb_level = QComboBox()
        self.cb_level.addItems(LEVELS)
        lv = self.cfg.get("dedupe_level", "标准")
        self.cb_level.setCurrentIndex(LEVELS.index(lv) if lv in LEVELS else 1)
        self.sp_th = QDoubleSpinBox()
        self.sp_th.setRange(0.5, 1.0)
        self.sp_th.setSingleStep(0.01)
        self.sp_th.setDecimals(2)
        self.sp_th.setValue(float(self.cfg.get("dedupe_threshold", 0.92)))

        f.addRow("严格度", self.cb_level)
        f.addRow("标题相似度阈值", self.sp_th)

        tip = QLabel(
            "严格：仅归一化后完全相同的 URL\n"
            "标准：额外合并同域名同路径（忽略 http/https 与查询串差异）\n"
            "宽松：再叠加同域名下标题高度相似的条目"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#888780;font-size:12px")
        f.addRow("", tip)
        return w

    def _collect(self) -> Dict:
        cfg = dict(self.cfg)
        cfg.update({
            "api_key": self.ed_key.text().strip(),
            "base_url": self.ed_url.text().strip(),
            "model": self.ed_model.text().strip() or "gpt-4o-mini",
            "batch_size": self.sp_batch.value(),
            "ai_workers": self.sp_workers.value(),
            "ai_timeout": self.sp_ai_timeout.value(),
            "check_workers": self.sp_cw.value(),
            "check_timeout": self.sp_ct.value(),
            "check_retries": self.sp_cr.value(),
            "verify_ssl": self.cb_ssl.isChecked(),
            "exit_profile": self.cb_exit.currentText(),
            "custom_proxy": self.ed_proxy.text().strip(),
            "domain_delay": self.sp_delay.value(),
            "enable_fallback": self.cb_fallback.isChecked(),
            "enable_soft404": self.cb_soft404.isChecked(),
            "record_public_ip": self.cb_pubip.isChecked(),
            "dedupe_level": self.cb_level.currentText(),
            "dedupe_threshold": self.sp_th.value(),
        })
        return cfg

    def result_config(self) -> Dict:
        return self._collect()


class TaxonomyDialog(QDialog):
    """分类体系编辑器：增改分类、域名与关键词。"""

    def __init__(self, taxonomy: Dict, parent=None):
        super().__init__(parent)
        self.taxonomy = json.loads(json.dumps(taxonomy, ensure_ascii=False))
        self.setWindowTitle("分类体系")
        self.resize(720, 520)
        self._dirty = False

        self.list = QListWidget()
        self.list.setMaximumWidth(210)
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        for name in self.taxonomy:
            self.list.addItem(name)
        self.list.currentItemChanged.connect(self._on_select)

        self.ed_name = QLineEdit()
        self.ed_dom = QPlainTextEdit()
        self.ed_dom.setPlaceholderText("每行一个域名片段，如 unrealengine、blender、.gov.cn")
        self.ed_kw = QPlainTextEdit()
        self.ed_kw.setPlaceholderText("每行一个关键词，如 虚幻引擎、渲染、材质")

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        form.addRow("分类名", self.ed_name)
        form.addRow("域名特征", self.ed_dom)
        form.addRow("关键词", self.ed_kw)

        btns = QHBoxLayout()
        b_add = QPushButton("新增分类")
        b_del = QPushButton("删除分类")
        b_add.clicked.connect(self._add)
        b_del.clicked.connect(self._del)
        btns.addWidget(b_add)
        btns.addWidget(b_del)
        btns.addStretch(1)

        right = QVBoxLayout()
        right.addLayout(form)
        right.addLayout(btns)
        right.addStretch(1)

        main = QHBoxLayout()
        main.addWidget(self.list)
        main.addLayout(right, 1)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        box.button(QDialogButtonBox.Ok).setText("确定")
        box.button(QDialogButtonBox.Cancel).setText("取消")
        box.accepted.connect(self._on_ok)
        box.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(main, 1)
        tip = QLabel("改动仅影响本地规则分类；使用 AI 分类时这里同时作为候选分类列表。")
        tip.setStyleSheet("color:#888780;font-size:12px")
        lay.addWidget(tip)
        lay.addWidget(box)

        if self.list.count():
            self.list.setCurrentRow(0)

    def _cur_name(self) -> str:
        it = self.list.currentItem()
        return it.text() if it else ""

    def _save_current(self):
        old = self._cur_name()
        if not old:
            return
        new = self.ed_name.text().strip()
        if not new:
            return
        rules = {
            "domains": [x.strip() for x in self.ed_dom.toPlainText().splitlines() if x.strip()],
            "keywords": [x.strip() for x in self.ed_kw.toPlainText().splitlines() if x.strip()],
        }
        if new != old:
            self.taxonomy.pop(old, None)
        self.taxonomy[new] = rules
        if new != old:
            self.list.currentItem().setText(new)

    def _on_select(self, cur, prev):
        if prev is not None:
            self._save_current()
        if cur is None:
            return
        rules = self.taxonomy.get(cur.text(), {})
        self.ed_name.setText(cur.text())
        self.ed_dom.setPlainText("\n".join(rules.get("domains", [])))
        self.ed_kw.setPlainText("\n".join(rules.get("keywords", [])))

    def _add(self):
        name, ok = QInputDialog.getText(self, "新增分类", "分类名：")
        if ok and name.strip():
            name = name.strip()
            if name in self.taxonomy:
                QMessageBox.warning(self, "提示", "该分类已存在")
                return
            self.taxonomy[name] = {"domains": [], "keywords": []}
            self.list.addItem(name)
            self.list.setCurrentRow(self.list.count() - 1)

    def _del(self):
        it = self.list.currentItem()
        if not it:
            return
        if QMessageBox.question(self, "确认", f"删除分类「{it.text()}」？") != QMessageBox.Yes:
            return
        self.taxonomy.pop(it.text(), None)
        self.list.takeItem(self.list.row(it))

    def _on_ok(self):
        self._save_current()
        self.accept()

    def result_taxonomy(self) -> Dict:
        return self.taxonomy
