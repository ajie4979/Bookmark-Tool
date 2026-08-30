"""本地规则分类引擎（AI 不可用时的兜底，也可单独使用）。

打分规则：
  域名命中         +3
  标题命中关键词   +2
  URL 路径命中     +1
  原文件夹名命中   +2
取总分最高者；无人命中则落入「其他未分类」。
分类体系可在界面中编辑，保存到 taxonomy.json。
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, Iterable, List, Sequence
from urllib.parse import urlsplit

from .models import Bookmark

DEFAULT_CATEGORY = "其他未分类"

DEFAULT_TAXONOMY: Dict[str, dict] = {
    "AI 与机器学习": {
        "domains": ["openai", "anthropic", "claude.ai", "huggingface", "midjourney",
                    "tongyi.aliyun", "bailian", "dashscope", "deepseek", "moonshot",
                    "chatglm", "zhipuai", "bigmodel", "baichuan", "dify.ai", "coze",
                    "langchain", "replicate", "civitai", "stability.ai", "runwayml",
                    "suno", "udio", "trae", "cursor", "copilot", "perplexity",
                    "gemini", "aistudio", "siliconflow", "volcengine", "ark.cn",
                    "lingyiwanwu", "01.ai", "qwenlm", "ollama", "kg-api",
                    "ai.com", "poe.com", "flowgpt", "promptbase", "krea.ai", "luma"],
        "keywords": ["人工智能", "大模型", "gpt", "chatgpt", "llm", "提示词", "prompt",
                     "机器学习", "深度学习", "神经网络", "comfyui", "stable diffusion",
                     "sd", "智能体", "agent", "rag", "向量", "微调", "炼丹", "中转",
                     "ai", "aigc", "生图", "文生图", "文生视频", "模型"],
    },
    "3D 与图形创作": {
        "domains": ["unrealengine", "epicgames", "blender", "cinema4d", "maxon",
                    "derivative.ca", "touchdesigner", "houdini", "sidefx", "maya",
                    "autodesk", "unity", "sketchfab", "polyhaven", "cgmodel",
                    "substance3d", "quixel", "textures.com", "ambientcg",
                    "blueprintue", "3dmax", "c4d", "notch", "ventuz", "disguise",
                    "engineworld", "shenyecg", "agancg", "cgfxw", "cgjoy",
                    "quadspinner", "arduino", "processing.org", "mixly",
                    "openframeworks", "vvvv", "resolume", "madmapper", "isadora",
                    "creativecoding", "shadertoy"],
        "keywords": ["ue4", "ue5", "unreal", "虚幻", "蓝图", "blueprint", "niagara",
                     "材质", "渲染", "建模", "blender", "c4d", "cinema 4d",
                     "touchdesigner", "touch designer", "houdini", "地形", "光照",
                     "粒子", "骨骼", "动画", "shader", "着色器", "贴图", "舞美",
                     "3d", "渲染器", "镜头", "绿幕", "led大屏", "互动装置", "装置",
                     "投影", "mapping", "创意编程", "生成艺术", "cg", "三维"],
    },
    "设计与素材": {
        "domains": ["zcool", "huaban", "pinterest", "behance", "dribbble", "uisdc",
                    "iconfont", "flaticon", "freepik", "unsplash", "pexels",
                    "pixabay", "vecteezy", "588ku", "tukuchina", "58pic", "ibaotu",
                    "canva", "figma", "mastergo", "jsdelivr", "sketch.com",
                    "fontawesome", "fonts.google", "zhfont", "qiuziti",
                    "67design", "68design", "logosc", "logoly", "undraw"],
        "keywords": ["素材", "设计", "ui", "ux", "logo", "图标", "插画", "海报",
                     "字体", "配色", "灵感", "图库", "免抠", "psd", "笔刷",
                     "样机", "mockup", "版式", "平面", "视觉", "壁纸"],
    },
    "开发与技术": {
        "domains": ["github", "githubusercontent", "gitlab", "gitee", "stackoverflow",
                    "csdn", "juejin", "segmentfault", "cnblogs", "npmjs", "pypi",
                    "crates.io", "maven", "docker", "kubernetes", "jenkins",
                    "vercel", "netlify", "cloudflare", "aws.amazon", "azure",
                    "aliyun", "tencentcloud", "huaweicloud", "jetbrains",
                    "visualstudio", "python.org", "golang.org", "rust-lang",
                    "developer.mozilla", "w3school", "runoob", "geeksforgeeks",
                    "huggingface.co/docs", "anaconda", "conda", "postman",
                    "apifox", "apipost"],
        "keywords": ["开发", "编程", "代码", "爬虫", "github", "开源", "项目",
                     "sdk", "api接口", "接口", "框架", "库", "部署", "运维",
                     "python", "java", "c++", "golang", "rust", "javascript",
                     "typescript", "vue", "react", "node", "spring", "数据库",
                     "mysql", "redis", "docker", "git", "逆向", "反编译", "注入"],
    },
    "前端与网页": {
        "domains": ["vuejs", "react.dev", "nextjs", "nuxt", "vitejs", "webpack",
                    "sass", "tailwindcss", "element-plus", "antd", "bootstrap",
                    "codepen", "jsfiddle", "codesandbox", "stackblitz", "caniuse",
                    "mdn", "css-tricks", "smashingmagazine", "建站", "wordpress",
                    "hexo", "vitepress", "docsify", "notion"],
        "keywords": ["前端", "网页设计", "建站", "自助建站", "html", "css", "vue",
                     "react", "组件库", "布局", "响应式", "脚手架", "网站模板",
                     "wordpress", "域名注册", "虚拟主机", "备案", "seo"],
    },
    "数据可视化": {
        "domains": ["echarts", "antv", "d3js", "highcharts", "chartjs", "threejs",
                    "tableau", "powerbi", "finebi", "superset", "grafana",
                    "makeapie", "datav.aliyun", "chartcube", "visactor",
                    "apache.org/echarts", "observablehq"],
        "keywords": ["可视化", "大屏", "图表", "dashboard", "看板", "数据大屏",
                     "echarts", "d3", "三维可视化", "孪生", "gis", "地图"],
    },
    "摄影与后期": {
        "domains": ["fotomen", "cppfoto", "hellorf", "xinpianchang", "vsco",
                    "500px", "lightroom", "captureone", "dpreview", "tuchong",
                    "vcg", "hotoome", "flickr", "sucai", "xinpian", "dji",
                    "blackmagicdesign", "adobe.com/products/premiere",
                    "adobe.com/products/aftereffects", "jianying", "capcut"],
        "keywords": ["摄影", "后期", "修图", "调色", "相机", "镜头", "胶片",
                     "样片", "拍摄", "供稿", "剪辑", "达芬奇", "davinci",
                     "premiere", "剪映", "after effects", "ae教程", "无人机",
                     "航拍", "布光", "写真", "人像"],
    },
    "智慧城市与GIS": {
        "domains": ["arcgis", "mapbox", "openlayers", "leaflet", "cesium",
                    "supermap", "geoserver", "qgis", "tianditu", "amap",
                    "map.qq", "baidu.com/map", "osgeo", "postgis"],
        "keywords": ["智慧城市", "城市", "gis", "地理", "遥感", "倾斜摄影",
                     "bim", "iot", "物联网", "图层", "瓦片", "坐标系", "osm"],
    },
    "学习与文档": {
        "domains": ["zhihu", "jianshu", "yuque", "shimo", "notion.so",
                    "docs.qq", "kdocs", "feishu", "wolai", "coursera",
                    "udemy", "mooc", "icourse163", "bilibili", "xuetangx",
                    "wikipedia", "zh.wikipedia", "baidu.com/baike",
                    "runoob", "liaoxuefeng", "yiibai", "pandas.pydata",
                    "docs.python", "tensorflow", "pytorch"],
        "keywords": ["教程", "学习", "文档", "手册", "笔记", "课程", "入门",
                     "指南", "总结", "面经", "面试题", "知识库", "wiki", "博客"],
    },
    "工具与效率": {
        "domains": ["json.cn", "tool", "convert", "smallpdf", "ilovepdf",
                    "processon", "draw.io", "excalidraw", "mubu", "getpostman",
                    "tinypng", "squoosh", "remove.bg", "uutool", "tool.lu",
                    "caniuse", "regex101", "crontab", "base64", "qrcode",
                    "pan.baidu", "aliyundrive", "lanzou", "weiyun", "123pan",
                    "notepad", "sublimetext", "vscode", "everything",
                    "google.com", "bing.com", "duckduckgo", "fanyi.youdao",
                    "translate.google", "deepl", "baidu.com/s", "sm.ms",
                    "rutracker", "thepiratebay", "1337x"],
        "keywords": ["工具", "在线", "转换", "格式化", "压缩", "解析", "生成",
                     "查询", "检测", "计算器", "下载", "网盘", "vpn", "代理",
                     "加速器", "密码", "加密", "解密", "翻译", "词典", "搜索",
                     "查重", "论文", "源码", "种子", "磁力", "追踪", "快递",
                     "验证码", "接码", "ocr", "识别"],
    },
    "资讯与社区": {
        "domains": ["tophub", "news", "36kr", "huxiu", "ithome", "cnbeta",
                    "solidot", "v2ex", "reddit", "hacker-news", "news.ycombinator",
                    "sspai", "ifanr", "geekpark", "infoq", "oschina",
                    "mp.weixin", "weixin", "juejin.im", "douban", "tieba",
                    "sina", "sohu", "163.com", "qq.com", "toutiao", "thepaper"],
        "keywords": ["资讯", "新闻", "热点", "榜单", "排行", "社区", "论坛",
                     "公众号", "日报", "周刊", "热榜", "头条"],
    },
    "影音娱乐": {
        "domains": ["youtube", "bilibili", "iqiyi", "youku", "v.qq", "mgtv",
                    "netflix", "spotify", "music.163", "kugou", "kuwo",
                    "qqmusic", "douyu", "huya", "twitch", "steam", "epic",
                    "douban.com/movie", "bangumi", "acg", "anime"],
        "keywords": ["视频", "影视", "电影", "剧", "音乐", "直播", "游戏",
                     "动漫", "追番", "综艺", "弹幕", "up主", "番剧"],
    },
    "电商与生活": {
        "domains": ["taobao", "tmall", "jd.com", "pdd", "douyin", "xiaohongshu",
                    "amazon", "ebay", "suning", "kaola", "1688", "aliexpress",
                    "shein", "meituan", "dianping", "ele.me", "ctrip",
                    "qunar", "fliggy", "12306", "zhipin", "lagou", "51job",
                    "liepin", "anjuke", "lianjia", "autohome", "carhome"],
        "keywords": ["购物", "商城", "淘宝", "京东", "拼多多", "优惠", "折扣",
                     "外卖", "旅行", "机票", "酒店", "招聘", "求职", "租房",
                     "汽车", "交易", "二手", "闲鱼"],
    },
    "政府与机构": {
        "domains": [".gov.cn", ".gov.hk", "mohrss", "samr", "miit",
                    "stats.gov", "court.gov", "chinatax", "ndrc"],
        "keywords": ["政府", "政务", "税务", "社保", "公积金", "法院", "检察院",
                     "工商", "监管", "统计局", "人社", "发改委", "办事大厅"],
    },
    "玩机与刷机": {
        "domains": ["xda-developers", "get.droidplug", "magisk", "twrp",
                    "lineageos", "miui", "hyperos", "coloros", "oxygenos",
                    "oneplus", "oppo.com", "xiaomi", "qualcomm", "mediatek",
                    "adb", "fastboot", "gsmarena", "4pda"],
        "keywords": ["刷机", "root", "magisk", "twrp", "recovery", "fastboot",
                     "adb", "rom", "固件", "解锁", "bootloader", "一加",
                     "小米", "澎湃", "氧os", "线刷", "卡刷", "救砖"],
    },
}


def load_taxonomy(path: str) -> Dict[str, dict]:
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and data:
                return data
        except Exception:  # noqa: BLE001
            pass
    return json.loads(json.dumps(DEFAULT_TAXONOMY, ensure_ascii=False))


def save_taxonomy(path: str, taxonomy: Dict[str, dict]) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(taxonomy, f, ensure_ascii=False, indent=2)


def category_names(taxonomy: Dict[str, dict]) -> List[str]:
    return list(taxonomy.keys()) + [DEFAULT_CATEGORY]


def _is_cjk(s: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in s)


def _host_match(rule: str, host: str) -> bool:
    """精确域名匹配（替代朴素子串，减少误判）。

    - 以 "." 开头：后缀匹配（如 .gov.cn）
    - 完全相等 / 以 ".rule" 结尾：根域或子域命中（如 aliyun / a.aliyun.com）
    - 否则：主机名某一段恰好等于 rule（如 tool 命中 tool.lu 但不命中 mytool.com）
    """
    rule = (rule or "").strip().lower()
    if not rule:
        return False
    host = host.lower()
    if rule.startswith("."):
        return host.endswith(rule)
    if host == rule or host.endswith("." + rule):
        return True
    return rule in host.split(".")


def _domain_hit(rule: str, host: str, path: str) -> bool:
    """支持 "host/path" 形式的规则（如 baidu.com/map）。"""
    rule = (rule or "").strip()
    if "/" in rule:
        dh, dp = rule.split("/", 1)
        if not _host_match(dh, host):
            return False
        return dp.lower() in (path or "").lower()
    return _host_match(rule, host)


def _score(bm: Bookmark, rules: dict) -> tuple:
    """返回 (总分, 是否命中原文件夹)。原文件夹是用户自己的归类意图，用作平局裁决。"""
    score = 0
    folder_hit = False
    host = bm.domain.lower()
    host_segs = host.split(".")
    try:
        path = urlsplit(bm.url).path.lower()
    except ValueError:
        path = ""
    title_l = (bm.title or "").lower()
    folder_l = (bm.folder or "").lower()

    for d in rules.get("domains", []):
        if _domain_hit(d, host, path):
            score += 3

    for raw in rules.get("keywords", []):
        k = raw.strip().lower()
        if not k:
            continue
        if _is_cjk(k):
            # 中文关键词：子串匹配即可，歧义小
            if k in title_l:
                score += 2
            if k in folder_l:
                score += 1          # 文件夹只是弱信号，用户自建目录往往很乱
                folder_hit = True
            if k in path:
                score += 1
            continue
        # 英文关键词：用词边界，避免 ai 命中 detail、sd 命中 https
        if re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", title_l):
            score += 3
        if re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", folder_l):
            score += 1
            folder_hit = True
        if len(k) <= 3:
            if k in host_segs:
                score += 3
        else:
            if k in host:
                score += 3
            if k in path:
                score += 1
    return score, folder_hit


def classify_one(bm: Bookmark, taxonomy: Dict[str, dict]) -> str:
    best, best_score, best_folder = DEFAULT_CATEGORY, 0, False
    for cat, rules in taxonomy.items():
        s, fhit = _score(bm, rules)
        # 仅当分数更高，或分数相同但本分类命中了原文件夹而当前最佳没有时，才替换
        if s > best_score or (s == best_score and s > 0 and fhit and not best_folder):
            best, best_score, best_folder = cat, s, fhit
    return best


def classify_all(
    bookmarks: Sequence[Bookmark],
    taxonomy: Dict[str, dict],
    only_kept: bool = True,
    use_ai_results: bool = True,
) -> Dict[str, int]:
    """给所有书签打上新分类，返回各分类计数。"""
    counts: Dict[str, int] = {}
    for bm in bookmarks:
        if only_kept and not bm.keep:
            bm.category = ""
            continue
        if use_ai_results and bm.category:
            counts[bm.category] = counts.get(bm.category, 0) + 1
            continue
        cat = classify_one(bm, taxonomy)
        bm.category = cat
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def group_by_category(bookmarks: Iterable[Bookmark]) -> Dict[str, List[Bookmark]]:
    out: Dict[str, List[Bookmark]] = {}
    for bm in bookmarks:
        out.setdefault(bm.category or DEFAULT_CATEGORY, []).append(bm)
    return out
