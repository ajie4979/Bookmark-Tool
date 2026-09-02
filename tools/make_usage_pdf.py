#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
生成《书签工具 Bookmark Tool · 使用说明》PDF。
用法：python tools/make_usage_pdf.py [输出路径]
依赖：reportlab + 系统雅黑字体（C:/Windows/Fonts/msyh.ttc 等）。
字体嵌入，离线可读，不依赖阅读器自带中文字体。
"""
import os
import sys

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable,
)

APP_NAME_CN = "书签工具"
APP_NAME_EN = "Bookmark Tool"
APP_VERSION = "1.3.1"
AUTHOR = "阿杰"
REPO_URL = "https://github.com/ajie4979/Bookmark-Tool"

# ---- 字体注册（嵌入微软雅黑）----
def register_fonts():
    font_dir = r"C:/Windows/Fonts"
    reg = os.path.join(font_dir, "msyh.ttc")
    bold = os.path.join(font_dir, "msyhbd.ttc")
    if not (os.path.exists(reg) and os.path.exists(bold)):
        raise RuntimeError("未找到微软雅黑字体，请确认 C:/Windows/Fonts/msyh.ttc 存在")
    pdfmetrics.registerFont(TTFont("YaHei", reg, subfontIndex=0))
    pdfmetrics.registerFont(TTFont("YaHei-Bold", bold, subfontIndex=0))
    pdfmetrics.registerFontFamily(
        "YaHei", normal="YaHei", bold="YaHei-Bold",
        italic="YaHei", boldItalic="YaHei-Bold",
    )

# ---- 配色 ----
NAVY = colors.HexColor("#1F3864")
BLUE = colors.HexColor("#2E74B5")
LIGHT = colors.HexColor("#DCE6F1")
GREY = colors.HexColor("#595959")
ROW_ALT = colors.HexColor("#F2F6FC")


def styles():
    ss = getSampleStyleSheet()
    out = {}
    out["cover_title"] = ParagraphStyle(
        "cover_title", parent=ss["Title"], fontName="YaHei-Bold",
        fontSize=34, leading=42, textColor=NAVY, alignment=TA_CENTER,
    )
    out["cover_sub"] = ParagraphStyle(
        "cover_sub", parent=ss["Normal"], fontName="YaHei",
        fontSize=20, leading=28, textColor=BLUE, alignment=TA_CENTER,
    )
    out["cover_meta"] = ParagraphStyle(
        "cover_meta", parent=ss["Normal"], fontName="YaHei",
        fontSize=12, leading=22, textColor=GREY, alignment=TA_CENTER,
    )
    out["h1"] = ParagraphStyle(
        "h1", parent=ss["Heading1"], fontName="YaHei-Bold",
        fontSize=17, leading=24, textColor=NAVY, spaceBefore=10, spaceAfter=8,
    )
    out["h2"] = ParagraphStyle(
        "h2", parent=ss["Heading2"], fontName="YaHei-Bold",
        fontSize=13, leading=20, textColor=BLUE, spaceBefore=8, spaceAfter=4,
    )
    out["body"] = ParagraphStyle(
        "body", parent=ss["Normal"], fontName="YaHei",
        fontSize=10.5, leading=17, textColor=colors.black, spaceAfter=5,
    )
    out["bullet"] = ParagraphStyle(
        "bullet", parent=out["body"], leftIndent=14, bulletIndent=2, spaceAfter=3,
    )
    out["cell"] = ParagraphStyle(
        "cell", parent=ss["Normal"], fontName="YaHei",
        fontSize=9.5, leading=14, textColor=colors.black,
    )
    out["cell_h"] = ParagraphStyle(
        "cell_h", parent=ss["Normal"], fontName="YaHei-Bold",
        fontSize=9.5, leading=14, textColor=colors.white,
    )
    out["note"] = ParagraphStyle(
        "note", parent=out["body"], textColor=GREY, fontSize=9.5,
    )
    return out


def hr():
    return HRFlowable(width="100%", thickness=0.8, color=LIGHT, spaceBefore=4, spaceAfter=8)


def bullets(st, items):
    return [Paragraph("• " + t, st["bullet"]) for t in items]


def make_table(st, header, rows, col_widths):
    data = [[Paragraph(h, st["cell_h"]) for h in header]]
    for r in rows:
        data.append([Paragraph(str(c), st["cell"]) for c in r])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFBFBF")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    t.setStyle(TableStyle(style))
    return t


def build(out_path):
    register_fonts()
    st = styles()
    doc = SimpleDocTemplate(
        out_path, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=16 * mm,
        title="%s %s 使用说明" % (APP_NAME_CN, APP_NAME_EN),
        author=AUTHOR,
    )
    W = doc.width
    el = []

    # ---------- 封面 ----------
    el.append(Spacer(1, 38 * mm))
    el.append(Paragraph(APP_NAME_CN, st["cover_title"]))
    el.append(Spacer(1, 4 * mm))
    el.append(Paragraph(APP_NAME_EN, st["cover_sub"]))
    el.append(Spacer(1, 3 * mm))
    el.append(Paragraph("使 用 说 明", st["cover_sub"]))
    el.append(Spacer(1, 16 * mm))
    el.append(hr())
    el.append(Paragraph("版本 %s" % APP_VERSION, st["cover_meta"]))
    el.append(Paragraph("作者：%s" % AUTHOR, st["cover_meta"]))
    el.append(Paragraph("项目地址：%s" % REPO_URL, st["cover_meta"]))
    el.append(hr())
    el.append(Spacer(1, 10 * mm))
    el.append(Paragraph(
        "一款 Windows 桌面端离线书签治理工具：读取浏览器导出的书签，"
        "完成「去重 → 可达性验证 → 重新归类 → 生成导航网页 / 导回浏览器」的完整闭环。",
        st["cover_meta"]))
    el.append(PageBreak())

    # ---------- 1. 软件简介 ----------
    el.append(Paragraph("一、软件简介", st["h1"]))
    el.append(hr())
    el.append(Paragraph(
        "%s（%s）是一款完全离线运行的桌面程序，不收集、不上传任何书签数据。"
        "它把散乱、重复、失效的浏览器书签，整理成干净、有序、可一键导航的收藏体系。"
        % (APP_NAME_CN, APP_NAME_EN), st["body"]))
    el.append(Paragraph("核心能力：", st["h2"]))
    for b in bullets(st, [
        "去重：URL 归一化后比对，三档严格度可切换，支持「仅看重复项」。",
        "失效链接检测：多线程并发，结论细分「可访问 / 存疑 / 已失效」，不轻易误杀。",
        "AI 复检存疑：用大模型读取已抓取的正文，进一步区分「真失效」与「假活 / 被拒」，只发文本不上传 URL。",
        "归类：AI 智能归类或本地规则归类（双引擎，可混用）。",
        "导航网页：一键生成离线可用的单文件 HTML 收藏站。",
        "导入导出：兼容 Chrome / Edge / Firefox 书签格式（HTML / JSON / CSV）。",
    ]):
        el.append(b)
    el.append(Paragraph(
        "配置与分类体系保存在系统用户目录（见第八节），删除即恢复默认，可放心试用。",
        st["note"]))

    # ---------- 2. 快速开始 ----------
    el.append(Paragraph("二、快速开始", st["h1"]))
    el.append(hr())
    el.append(Paragraph("标准六步流程：", st["h2"]))
    for b in bullets(st, [
        "<b>导入书签</b> —— 支持 Chrome / Edge / Firefox 导出的书签 HTML，也支持 JSON / CSV。",
        "<b>去重</b> —— 标记重复项，可在「严格 / 标准 / 宽松」间切换，并可只看重复项。",
        "<b>检测失效链接</b> —— 多线程并发，状态细分，可随时中止。",
        "<b>归类</b> —— 选择 AI 智能归类或本地规则归类。",
        "<b>写回文件夹</b> —— 把新分类固化到目录结构。",
        "<b>生成导航网页 / 导出</b> —— 产出可浏览的单文件网页，或导回浏览器。",
    ]):
        el.append(b)

    # ---------- 3. 去重 ----------
    el.append(Paragraph("三、去重详解", st["h1"]))
    el.append(hr())
    el.append(Paragraph(
        "URL 归一化后比对：统一大小写、去掉默认端口、剔除 utm_* / spm / from 等 20+ 种追踪参数、"
        "去末尾斜杠与片段标识符（#xxx）。", st["body"]))
    el.append(make_table(st,
        ["档位", "规则"],
        [
            ["严格", "仅归一化后完全相同的 URL"],
            ["标准", "追加合并同域名同路径（忽略 http/https、忽略查询串差异）"],
            ["宽松", "再叠加同域名下标题高度相似（阈值可调，默认 0.92）"],
        ],
        [W * 0.18, W * 0.82]))
    el.append(Spacer(1, 4))
    el.append(Paragraph(
        "重复组里保留<b>最早添加</b>的那条，其余标记为剔除。顶部「显示范围」下拉可切换："
        "全部 / 仅保留 / 仅重复项 / 仅存疑；勾选后表格实时筛选。右键单条可随时切换保留 / 剔除。",
        st["body"]))

    # ---------- 4. 失效链接检测 ----------
    el.append(Paragraph("四、失效链接检测详解", st["h1"]))
    el.append(hr())
    el.append(Paragraph(
        "先发 HEAD，遇到 403/405/501 自动降级为 GET（只取头部不下载正文）。"
        "检测结论只有三档，尽量把「活着但程序打不开」和「真的死了」分开：", st["body"]))
    el.append(make_table(st,
        ["结论", "含义", "算失效吗"],
        [
            ["可访问", "服务器有响应：2xx/3xx，或 TLS 握手失败（连得上仅握手受限）", "否"],
            ["存疑", "超时 / 无响应 / 连接失败，或 401/403/429/451（访问受限）、502/504（网关错误）、疑似软404、疑似统一错误页", "否（建议换网络或人工复检）"],
            ["已失效", "404 / 410，或域名解析失败、端口 / 连接被拒", "是"],
            ["未检测", "还没跑", "不适用"],
            ["跳过", "chrome://、javascript:、本地文件、命中跳过规则", "不适用"],
        ],
        [W * 0.16, W * 0.62, W * 0.22]))
    el.append(Spacer(1, 4))
    el.append(Paragraph(
        "站点返回 403 / 451 / 5xx 可能只是<b>拒绝了程序访问</b>或<b>代理 / 网络层故障</b>"
        "（Cloudflare 挑战、缺 Cookie、地区 / 法律限制、对方网关临时故障），用浏览器打开<b>未必</b>正常；"
        "因此一律归为「存疑」而非「可访问」，既不轻易误杀，也不假装活着。建议挑出来人工复检。",
        st["body"]))
    el.append(Paragraph("用 AI 进一步判定（可选，默认关闭）", st["h2"]))
    el.append(Paragraph(
        "规则引擎只能看状态码，分不清「返回 200 但其实是错误页 / 占位页 / 站点已关停」这类<b>假活</b>。"
        "点工具栏「<b>AI 复检存疑</b>」，程序会把每条存疑链接<b>已经抓取到的正文文本</b>发给大模型判读："
        "AI 读完内容后能稳健判断它是真实可用的页面，还是错误 / 占位 / 关停页——这一步对跨语言、各种措辞都有效。", st["body"]))
    el.append(Paragraph(
        "<b>隐私与成本</b>：只发送页面<b>正文片段</b>，<b>不把 URL 交给云端浏览器去抓</b>；"
        "且只对「存疑」子集调用，其余结论不打扰。需在「设置 → AI 配置」填好 API Key 并勾选「允许用 AI 复检」，"
        "可接任意 OpenAI 兼容中转（如 DeepSeek / 通义）。内网地址也能判——因为正文是程序在本机抓的，AI 只负责读文本。", st["note"]))
    el.append(Paragraph(
        "默认 32 线程、8 秒超时、失败重试 1 次，均可在「设置 → 失效检测」中调整，运行中可随时「停止」。",
        st["note"]))

    # ---------- 5. 归类 ----------
    el.append(Paragraph("五、归类：AI 与本地规则双引擎", st["h1"]))
    el.append(hr())
    el.append(Paragraph(
        "<b>AI 智能归类</b>：OpenAI 兼容接口，可填任意中转站地址。批量并发请求、自动解析 JSON；"
        "没填 Key、断网或接口报错时，自动回退到本地规则，保证流程跑完。", st["body"]))
    el.append(Paragraph(
        "<b>本地规则归类</b>：内置 16 个分类的规则库（域名特征 + 关键词 + 原文件夹弱信号），打分取最高；"
        "命中零规则的链接启用兜底启发式（.edu/.gov 后缀、blog/docs/wiki 等主机词），进一步降低未分类率。",
        st["body"]))
    el.append(Paragraph("内置分类：", st["h2"]))
    el.append(Paragraph(
        "AI 与机器学习、3D 与图形创作、设计与素材、开发与技术、前端与网页、数据可视化、"
        "智慧城市与 GIS、摄影与后期、学习与文档、工具与效率、资讯与社区、影音娱乐、"
        "电商与生活、政府与机构、玩机与刷机、其他未分类。", st["body"]))
    el.append(Paragraph(
        "分类体系可在「设置 → 分类体系」里增删改，也可加自己的分类和关键词；"
        "改动同时会作为 AI 归类的候选分类列表。", st["note"]))

    # ---------- 6. 导航网页 ----------
    el.append(Paragraph("六、导航网页生成", st["h1"]))
    el.append(hr())
    el.append(Paragraph("产出单个 HTML 文件，离线可用，自带：", st["h2"]))
    for b in bullets(st, [
        "左侧分类导航（带计数）+ 状态筛选",
        "实时搜索（标题 / 网址 / 文件夹）",
        "卡片 / 列表两种视图，可按域名 / 状态 / 标题排序",
        "深浅色主题切换（记忆到本地）",
        "自动抓取站点 favicon，失败时回退为首字母色块",
    ]):
        el.append(b)

    # ---------- 7. 导入导出 ----------
    el.append(Paragraph("七、导入导出", st["h1"]))
    el.append(hr())
    el.append(make_table(st,
        ["方向", "格式"],
        [
            ["导入", "Netscape 书签 HTML、JSON、CSV"],
            ["导出", "浏览器可直接导入的 Netscape HTML、JSON、CSV"],
        ],
        [W * 0.2, W * 0.8]))
    el.append(Spacer(1, 4))
    el.append(Paragraph(
        "导出时可选「只导出保留项（已去重）」或「全部」。执行「把分类写回文件夹结构」后再导出，"
        "得到的就是按新体系组织的目录树。", st["body"]))

    # ---------- 8. 关于与配置 ----------
    el.append(Paragraph("八、关于页与配置位置", st["h1"]))
    el.append(hr())
    el.append(Paragraph(
        "菜单「帮助 → 关于」可看到作者信息与项目仓库地址（超链接，点击直达）。"
        "配置、分类体系、规则库等保存在系统用户目录：", st["body"]))
    el.append(make_table(st,
        ["系统", "配置目录"],
        [
            ["Windows", r"C:\Users\<用户名>\AppData\Local\BookmarkTool"],
            ["macOS", "~/Library/Application Support/BookmarkTool"],
            ["Linux", "~/.config/BookmarkTool"],
        ],
        [W * 0.22, W * 0.78]))
    el.append(Spacer(1, 4))
    el.append(Paragraph(
        "说明：上表中 Windows 路径里的 <用户名> 会替换为你本机登录用户名，"
        "他人电脑安装后显示的也是其各自用户名，属正常占位显示。删除该目录即恢复默认设置。",
        st["note"]))

    # ---------- 9. 常见问题 ----------
    el.append(Paragraph("九、常见问题", st["h1"]))
    el.append(hr())
    for b in bullets(st, [
        "<b>杀软报毒？</b> 属 PyInstaller 打包程序的常见误报，放行即可；本程序不联网上传任何数据。",
        "<b>整理前要不要备份？</b> 建议在导入前先导出一份原始书签备份，便于回滚。",
        "<b>大量「存疑」怎么办？</b> 多为网络环境限制导致连不上，可换网络后用「复检存疑项」向导重测。",
        "<b>归类不准？</b> 在「设置 → 分类体系」里增删分类 / 关键词，或改用 AI 归类提升准确率。",
        "<b>AI 复检和直接检测有什么区别？</b> 直接检测看状态码，分不清「200 但内容是错误页」的假活；"
        "AI 复检读正文语义，能识别出占位页 / 关停页，且只发文本不上传 URL，内网书签也能用。默认关闭、需自备 Key。",
        "<b>窗口标题 / 程序名？</b> 本程序名为「%s（%s）」，可执行文件为 BookmarkTool.exe。"
        % (APP_NAME_CN, APP_NAME_EN),
    ]):
        el.append(b)
    el.append(Spacer(1, 6))
    el.append(Paragraph("祝整理愉快 —— %s" % AUTHOR, st["note"]))

    doc.build(el)
    print("已生成：%s" % out_path)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "BookmarkTool_使用说明.pdf"
    build(out)
