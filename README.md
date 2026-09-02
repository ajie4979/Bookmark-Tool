# 书签工具（Bookmark Tool）

一个 Windows 桌面端的离线书签治理工具。读取浏览器导出的书签文件，
完成 **去重 → 可达性验证 → 重新归类 → 生成导航网页 / 导回浏览器** 的完整闭环。

设计目标：把散乱、重复、失效的浏览器书签，整理成干净、有序、可一键导航的收藏体系。

设计过程中参考过一年前的同名 Chrome 扩展（bookmark-sage 1.0.0），
但本工具是**完全独立的设计与实现**，零代码继承。详见 [`docs/设计文档.md`](docs/设计文档.md)。

> **作者**：阿杰 · **项目地址**：<https://github.com/ajie4979/Bookmark-Tool>
> **最新版本**：v1.3.1 · **下载**：[Releases 页面](https://github.com/ajie4979/Bookmark-Tool/releases)

## 快速开始

从 [Releases](https://github.com/ajie4979/Bookmark-Tool/releases) 下载最新版 `BookmarkTool_v1.3.1.zip`，解压后运行 `BookmarkTool.exe`（目录分发），无需安装 Python 或任何依赖。

1. **导入书签** —— 支持 Chrome / Edge / Firefox 导出的书签 HTML，也支持 JSON / CSV
2. **去重** —— 标记重复项，可切换严格度
3. **检测失效链接** —— 多线程并发，状态细分，可随时中止
4. **归类** —— AI 智能归类，或本地规则归类
5. **写回文件夹** —— 把新分类固化到目录结构
6. **生成导航网页 / 导出** —— 产出可浏览的单文件网页，或导回浏览器

## 功能说明

### 去重
URL 归一化后比对：统一大小写、去掉默认端口、剔除 `utm_*` / `spm` / `from` 等 20+ 种追踪参数、
去末尾斜杠与片段标识符。三档严格度：

| 档位 | 规则 |
|------|------|
| 严格 | 仅归一化后完全相同的 URL |
| 标准 | 追加合并同域名同路径（忽略 http/https、忽略查询串差异） |
| 宽松 | 再叠加同域名下标题高度相似（阈值可调，默认 0.92） |

重复组里保留**最早添加**的那条，其余标记为剔除。勾选「隐藏重复项」可只看保留结果，
随时可以右键单条切换保留/剔除。

### 失效链接检测
先发 HEAD，HEAD 超时 / 连接失败 / 返回 4xx/5xx 时立即降级为 GET 复核（很多国内站点不支持 HEAD，直接不响应）。状态细分，避免误杀：

检测结论只有三档，尽量把「活着但程序打不开」和「真的死了」分开：

| 结论 | 含义 | 算失效吗 |
|------|------|---------|
| **可访问** | 服务器有响应：2xx / 3xx；或连接重置 / 重定向过多（站点活着但拒绝了程序请求） | 否 |
| **存疑** | 超时 / 无响应 / 连接失败，或 401/403/429/451（访问受限）、502/504（网关错误）、TLS 握手失败、疑似软404、疑似统一错误页 | 否（建议换网络或人工复检） |
| **已失效** | 404 / 410，或域名解析失败、端口/连接被拒 | 是 |
| **未检测** | 还没跑 | 不适用 |
| **跳过** | `chrome://`、`javascript:`、本地文件、命中跳过规则 | 不适用 |

> 子类型会记下具体原因（如「访问受限 403」「地区限制 451」「服务端错误 5xx」「域名不存在」「环境矛盾」「TLS限制」「网络超时」等），直接显示在表格的「结论」列（如「存疑（网络超时）」），方便判断要不要人工复核。

### 关于「访问受限 / 地区限制 / 服务端错误」

站点返回 403 / 451 / 5xx，可能只是**拒绝了程序访问**或**代理 / 网络层故障**
（Cloudflare 挑战、缺 Cookie、风控、地区/法律限制、对方网关临时故障），
用浏览器打开**未必**正常。所以这些都归为「存疑」，既不轻易误杀，也不假装活着，建议挑出来人工复检。

程序已模拟完整 Chrome 请求头（含 `Sec-Fetch-*`、`sec-ch-ua` 系列），
但对需要跑 JS 挑战或有账号风控的站点仍可能返回 403——这类只能人工确认。
建议用状态筛选把它们挑出来抽查，而不是直接删掉。

**什么时候才是真的失效？** 只有 404/410、域名解析失败、或端口/连接被拒，才算「已失效」；
而完全连不上（仅超时 / 无响应）记为「存疑」，不轻易判定死亡。

默认 32 线程、8 秒超时、失败重试 1 次，均可在「设置 → 失效检测」中调整，运行中可随时「停止」。

### 用 AI 进一步判定（可选，默认关闭）
规则引擎只能看状态码，分不清「返回 200 但内容其实是错误页 / 占位页 / 站点已关停」这类**假活**。
点工具栏「**AI 复检存疑**」，程序会把每条存疑链接**已经抓取到的正文文本**发给大模型判读，
AI 读完内容后能稳健判断它是真实可用的页面，还是错误 / 占位 / 关停页（跨语言、各种措辞都有效）。

- **隐私**：只发送页面**正文片段**，**不把 URL 交给云端浏览器去抓**；只对「存疑」子集调用，其余结论不打扰。
- **内网可用**：正文是程序在本机抓的，AI 只负责读文本，因此内网书签也能判。
- **开启方式**：「设置 → AI 配置」填好 API Key，并勾选「允许用 AI 复检」；可接任意 OpenAI 兼容中转（DeepSeek / 通义等）。

### 归类：AI 与本地规则双引擎
- **AI 智能归类**：OpenAI 兼容接口，可填任意中转站地址。批量并发请求，自动解析 JSON。
  没填 Key、断网或接口报错时，自动回退到本地规则，保证流程跑完。
- **本地规则归类**：内置 31 个单一概念分类的规则库（域名特征 + 关键词 + 原文件夹弱信号），
  打分取最高。867 条约 0.1 秒完成，实测未分类率约 11%。

内置分类（全部为独立单一概念，无合并命名）：
人工智能、三维设计、设计、素材资源、开发、前端、数据可视化、摄影、视频剪辑、GIS、
学习、文档、工具、资讯、社区、影音、游戏、电商、生活、出行、政务、玩机、办公、理财、
健康、健身、教育、考试、阅读、写作、求职，加「其他未分类」兜底。

分类体系可在「设置 → 分类体系」里增删改，也可以加自己的分类和关键词。
改动同时会作为 AI 归类的候选分类列表。

### 导航网页生成
产出单个 HTML 文件，离线可用，自带：

- 左侧分类导航（带计数）+ 状态筛选
- 实时搜索（标题 / 网址 / 文件夹）
- 卡片 / 列表两种视图，可按域名 / 状态 / 标题排序
- 深浅色主题切换（记忆到本地）
- 自动抓取站点 favicon，失败时回退为首字母色块

### 导入导出
- **导入**：Netscape 书签 HTML、JSON、CSV
- **导出**：浏览器可直接导入的 Netscape HTML、JSON、CSV
- 导出时可选「只导出保留项（已去重）」或「全部」
- 执行「把分类写回文件夹结构」后再导出，得到的就是按新体系组织的目录树

## 目录结构

```
bookmark-tool/
├── app.py               入口
├── config.py            配置读写（存 %LOCALAPPDATA%\BookmarkTool\）
├── core/
│   ├── models.py        数据模型与状态词典（v2：verdict/subtype/confidence/probes）
│   ├── parser.py        Netscape / JSON / CSV 解析与导出
│   ├── dedupe.py        去重（并查集分组）
│   ├── prober.py        多出口验证引擎（直连/系统代理/自定义 + 乐观合并）
│   ├── classifier.py    本地规则分类引擎
│   ├── ai.py            OpenAI 兼容客户端
│   ├── rules.py         域名规则沉淀（require_proxy / require_direct / skip）
│   └── navgen.py        导航网页生成
├── ui/
│   ├── main_window.py   主窗口（结论/置信度/出口列、人工裁定右键菜单）
│   ├── workers.py       后台任务线程（QThread）
│   ├── dialogs.py       设置 / 分类体系编辑器
│   ├── recheck_dialog.py 复检存疑项向导
│   └── rules_dialog.py  域名规则管理器
├── resources/           图标
│   ├── icon.ico         多尺寸（16/20/24/32/40/48/64/128/256）
│   └── icon.png         512×512，用于文档
├── tools/
│   └── make_icon.py     图标生成脚本（4× 超采样）
├── tests/
│   └── sample_bookmarks.html  合成测试样本
├── docs/
│   └── 设计文档.md      完整产品设计文档（1030 行）
├── LICENSE              MIT
├── NOTICE               致谢与第三方署名
├── BookmarkTool.spec    PyInstaller 打包配置
└── README.md
```

> 打包成品（`dist/BookmarkTool/`）不在仓库内，请从 [Releases](https://github.com/ajie4979/Bookmark-Tool/releases) 下载。

## 从源码运行 / 重新打包

```bash
python -m venv .venv
.venv\Scripts\pip install PySide6 requests pyinstaller Pillow
python app.py

# 目录分发打包
python -m PyInstaller --noconfirm --windowed --name BookmarkTool --onedir \
  --icon resources/icon.ico \
  --add-data "resources/icon.ico;resources" \
  --add-data "resources/icon.png;resources" \
  --collect-submodules PySide6 \
  --exclude-module PySide6.Qt3D* --exclude-module PySide6.QtCharts \
  --exclude-module PySide6.QtWebEngine* --exclude-module PySide6.QtMultimedia* \
  app.py

# 或直接使用仓库内的 BookmarkTool.spec（推荐）：
python -m PyInstaller --noconfirm BookmarkTool.spec
# 产物在 dist/BookmarkTool/，可执行文件名与目录名均保持 BookmarkTool
```

## 说明

- 配置与分类体系保存在 `%LOCALAPPDATA%\BookmarkTool\`（macOS：`~/Library/Application Support/BookmarkTool`，Linux：`~/.config/BookmarkTool`），删掉即恢复默认
- 菜单「帮助 → 关于」里可看到作者信息与项目仓库地址（超链接，点击直达）
- 首次运行若杀软报毒，属 PyInstaller 打包程序的常见误报，放行即可
- 整理前建议先导出一份原始书签备份
