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

# v1.4 分类体系重构：全部为「单一概念」命名，不再使用「XX与XX」合并类。
# 每个分类带 description（一句话边界说明），供 AI 分类 prompt 使用，
# 让模型理解每个类别的含什么、不含什么，减少相邻类别误判。
DEFAULT_TAXONOMY: Dict[str, dict] = {
    "人工智能": {
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
        "description": "AI 聊天/绘画/视频工具、大模型与提示词、机器学习深度学习平台、智能体应用",
    },
    "三维设计": {
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
        "description": "三维建模/渲染/引擎（Unreal/Blender/C4D/Houdini）、实时视觉与互动装置、创意编程",
    },
    "设计": {
        "domains": ["zcool", "pinterest", "behance", "dribbble", "uisdc",
                    "canva", "figma", "mastergo", "jsdelivr", "sketch.com",
                    "67design", "68design", "logosc", "logoly", "undraw"],
        "keywords": ["设计", "ui", "ux", "logo", "插画", "海报", "配色", "灵感",
                     "样机", "mockup", "版式", "平面", "视觉", "壁纸", "排版",
                     "品牌", "vi", "banner", "详情页"],
        "description": "UI/UX 与平面设计、logo 与海报、配色排版、品牌视觉",
    },
    "素材资源": {
        "domains": ["huaban", "iconfont", "flaticon", "freepik", "unsplash",
                    "pexels", "pixabay", "vecteezy", "588ku", "tukuchina",
                    "58pic", "ibaotu", "fontawesome", "fonts.google", "zhfont",
                    "qiuziti"],
        "keywords": ["素材", "图标", "字体", "图库", "免抠", "psd", "笔刷",
                     "壁纸下载", "png", "svg", "图片素材", "音效", "模板"],
        "description": "图库、图标/字体/笔刷素材站、免抠与模板下载",
    },
    "开发": {
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
                     "mysql", "redis", "docker", "git", "逆向", "反编译", "注入",
                     "算法", "leetcode", "数据结构"],
        "description": "编程开发、代码托管、开源项目、技术问答、后端/数据库/框架、逆向与安全",
    },
    "前端": {
        "domains": ["vuejs", "react.dev", "nextjs", "nuxt", "vitejs", "webpack",
                    "sass", "tailwindcss", "element-plus", "antd", "bootstrap",
                    "codepen", "jsfiddle", "codesandbox", "stackblitz", "caniuse",
                    "mdn", "css-tricks", "smashingmagazine", "wordpress",
                    "hexo", "vitepress", "docsify", "notion"],
        "keywords": ["前端", "网页设计", "建站", "自助建站", "html", "css", "vue",
                     "react", "组件库", "布局", "响应式", "脚手架", "网站模板",
                     "wordpress", "域名注册", "虚拟主机", "备案", "seo",
                     "小程序", "h5", "响应式布局"],
        "description": "前端框架与组件库、HTML/CSS/JS、建站与 WordPress、域名与 SEO",
    },
    "数据可视化": {
        "domains": ["echarts", "antv", "d3js", "highcharts", "chartjs", "threejs",
                    "tableau", "powerbi", "finebi", "superset", "grafana",
                    "makeapie", "datav.aliyun", "chartcube", "visactor",
                    "apache.org/echarts", "observablehq"],
        "keywords": ["可视化", "大屏", "图表", "dashboard", "看板", "数据大屏",
                     "echarts", "d3", "三维可视化", "孪生", "gis", "地图"],
        "description": "图表库（ECharts/D3）、数据大屏、BI 报表、地图可视化",
    },
    "摄影": {
        "domains": ["fotomen", "cppfoto", "hellorf", "vsco", "500px",
                    "lightroom", "captureone", "dpreview", "tuchong", "vcg",
                    "hotoome", "flickr", "dji"],
        "keywords": ["摄影", "修图", "调色", "相机", "镜头", "胶片", "样片",
                     "拍摄", "供稿", "无人机", "航拍", "布光", "写真", "人像"],
        "description": "摄影教程与图库、相机镜头、调色修图、航拍布光",
    },
    "视频剪辑": {
        "domains": ["xinpianchang", "sucai", "xinpian", "blackmagicdesign",
                    "adobe.com/products/premiere", "adobe.com/products/aftereffects",
                    "jianying", "capcut"],
        "keywords": ["后期", "剪辑", "达芬奇", "davinci", "premiere", "剪映",
                     "after effects", "ae教程", "转场", "调色", "字幕", "特效",
                     "pr", "ae", "final cut", "pr模板"],
        "description": "视频后期剪辑（达芬奇/PR/剪映/AE）、特效与字幕模板",
    },
    "GIS": {
        "domains": ["arcgis", "mapbox", "openlayers", "leaflet", "cesium",
                    "supermap", "geoserver", "qgis", "tianditu", "amap",
                    "map.qq", "baidu.com/map", "osgeo", "postgis"],
        "keywords": ["智慧城市", "城市", "gis", "地理", "遥感", "倾斜摄影",
                     "bim", "iot", "物联网", "图层", "瓦片", "坐标系", "osm"],
        "description": "GIS/地图 SDK、遥感倾斜摄影、智慧城市与物联网",
    },
    "学习": {
        "domains": ["zhihu", "jianshu", "yuque", "shimo", "notion.so",
                    "docs.qq", "kdocs", "feishu", "wolai", "coursera",
                    "udemy", "mooc", "icourse163", "xuetangx",
                    "runoob", "liaoxuefeng", "yiibai", "pandas.pydata",
                    "docs.python", "tensorflow", "pytorch"],
        "keywords": ["教程", "学习", "课程", "入门", "指南", "面经", "面试题",
                     "博客", "wiki", "笔记", "慕课", "公开课", "知识"],
        "description": "教程/课程、在线教育平台、博客与知识问答（知乎）、面试经验",
    },
    "文档": {
        "domains": ["wikipedia", "zh.wikipedia", "baidu.com/baike",
                    "developer.mozilla", "mdn", "gitbook", "readthedocs",
                    "docs.docker", "docs.microsoft", "learn.microsoft",
                    "kubernetes.io", "developer.apple"],
        "keywords": ["文档", "手册", "知识库", "百科", "说明书", "api文档",
                     "reference", "changelog", "规范"],
        "description": "文档手册、百科、API 参考与规范说明",
    },
    "工具": {
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
        "description": "在线转换/格式化/查重、网盘与传输、翻译词典、OCR、实用小工具",
    },
    "资讯": {
        "domains": ["tophub", "news", "36kr", "huxiu", "ithome", "cnbeta",
                    "solidot", "sspai", "ifanr", "geekpark", "infoq",
                    "mp.weixin", "weixin", "sina", "sohu", "news.163.com",
                    "news.qq.com", "toutiao", "thepaper", "chinadaily",
                    "hacker-news", "oschina", "juejin.im"],
        "keywords": ["资讯", "新闻", "热点", "榜单", "排行", "公众号", "日报",
                     "周刊", "热榜", "头条", "快讯", "报道", "网易", "腾讯新闻"],
        "description": "新闻资讯、热点榜单、公众号文章、行业快讯",
    },
    "社区": {
        "domains": ["v2ex", "reddit", "douban", "tieba", "hupu",
                    "weibo", "bbs", "forum", "discourse", "club", "taptap",
                    "csdn", "segmentfault", "cnblogs", "gitee"],
        "keywords": ["社区", "论坛", "帖子", "水木", "贴吧", "小组", "话题",
                     "讨论", "经验分享", "微博"],
        "description": "技术社区、论坛、微博与话题讨论（V2EX/Reddit/豆瓣小组）",
    },
    "影音": {
        "domains": ["youtube", "bilibili", "iqiyi", "youku", "v.qq", "mgtv",
                    "netflix", "spotify", "music.163", "kugou", "kuwo",
                    "qqmusic", "douyu", "huya", "twitch", "douban.com/movie",
                    "bangumi", "acg", "anime", "xiaoyuzhou", "kuaishou"],
        "keywords": ["视频", "影视", "电影", "剧", "音乐", "直播", "动漫",
                     "追番", "综艺", "弹幕", "up主", "番剧", "播客", "有声书"],
        "description": "视频平台、电影剧集、音乐播放、直播、动漫追番与播客",
    },
    "游戏": {
        "domains": ["steam", "epic", "epicgames", "ubisoft", "playstation",
                    "xbox", "nintendo", "switch", "taptap", "gamersky",
                    "3dmgame", "gog.com", "riotgames", "bungie", "ea.com",
                    "game", "games"],
        "keywords": ["游戏", "电竞", "手游", "端游", "主机", "steam", "epic",
                     "攻略", "通关", "mod", "汉化", "加速器游戏", "单机"],
        "description": "游戏平台（Steam/Epic）、电竞、游戏攻略与资讯",
    },
    "电商": {
        "domains": ["taobao", "tmall", "jd.com", "pdd", "douyin", "xiaohongshu",
                    "amazon", "ebay", "suning", "kaola", "1688", "aliexpress",
                    "shein", "taobao.com", "tmall.com"],
        "keywords": ["购物", "商城", "淘宝", "京东", "拼多多", "优惠", "折扣",
                     "交易", "二手", "闲鱼", "秒杀", "薅羊毛", "返利", "比价"],
        "description": "电商购物平台（淘宝/京东/拼多多）、优惠折扣与二手交易",
    },
    "生活": {
        "domains": ["meituan", "dianping", "ele.me", "58.com", "ganji",
                    "xianyu", "sf-express", "zto", "yto", "sto.cn",
                    "kuaidi100", "10086.cn", "10010.com", "10000", "95598",
                    "95533", "anjuke", "lianjia", "autohome", "carhome"],
        "keywords": ["外卖", "快递", "物流", "话费", "充值", "缴费", "水电煤",
                     "租房", "二手房", "二手车", "家政", "维修", "开锁",
                     "物业", "装修", "生活缴费"],
        "description": "外卖、快递物流、话费缴费、租房、家政维修等生活服务",
    },
    "出行": {
        "domains": ["amap", "gaode", "map.baidu", "google.com/maps",
                    "ctrip", "fliggy", "qunar.com", "booking.com",
                    "airbnb", "12306.cn", "trip.com", "didi"],
        "keywords": ["地图", "导航", "机票", "酒店", "火车票", "高铁", "打车",
                     "滴滴", "民宿", "签证", "旅游", "景点"],
        "description": "地图导航、机票酒店、火车票、打车与旅游",
    },
    "政务": {
        "domains": [".gov.cn", ".gov.hk", "mohrss", "samr", "miit",
                    "stats.gov", "court.gov", "chinatax", "ndrc"],
        "keywords": ["政府", "政务", "税务", "社保", "公积金", "法院", "检察院",
                     "工商", "监管", "统计局", "人社", "发改委", "办事大厅",
                     "便民", "12345"],
        "description": "政府政务网站、税务社保公积金、办事大厅、监管机构",
    },
    "玩机": {
        "domains": ["xda-developers", "get.droidplug", "magisk", "twrp",
                    "lineageos", "miui", "hyperos", "coloros", "oxygenos",
                    "oneplus", "oppo.com", "xiaomi", "qualcomm", "mediatek",
                    "adb", "fastboot", "gsmarena", "4pda"],
        "keywords": ["刷机", "root", "magisk", "twrp", "recovery", "fastboot",
                     "adb", "rom", "固件", "解锁", "bootloader", "一加",
                     "小米", "澎湃", "氧os", "线刷", "卡刷", "救砖"],
        "description": "手机刷机/Root、ROM 固件、Magisk/TWRP、设备解锁",
    },
    "办公": {
        "domains": ["feishu", "larksuite", "dingtalk", "wps.cn", "kdocs",
                    "shimo.im", "notion.so", "teambition", "trello.com",
                    "jira", "confluence", "slack.com", "zoom.us",
                    "meeting.tencent", "voovmeeting", "wecom", "work.weixin",
                    "docs.qq", "docs.google", "sheets.google", "slides.google",
                    "aliwork", "yuque", "feishu.cn"],
        "keywords": ["飞书", "钉钉", "企业微信", "腾讯会议", "zoom", "协作",
                     "文档", "表格", "项目", "任务", "甘特图", "看板", "会议",
                     "在线文档", "石墨", "wps", "办公", "协同"],
        "description": "在线文档表格、团队协作（飞书/钉钉/企微/Slack）、会议与项目管理",
    },
    "理财": {
        "domains": ["eastmoney", "10jqka", "xueqiu", "danjuanapp", "fund.eastmoney",
                    "cmbchina", "icbc.com", "ccb.com", "abchina", "boc.cn",
                    "bankcomm", "cgbchina", "spdb", "cib.com", "95588",
                    "alipay", "pbc.gov", "ssc.gov", "csrc.gov",
                    "tradingview", "binance", "okx.com", "huobi", "coinbase",
                    "bitfinex", "sinafinance", "wind", "bloomberg", "investing",
                    "choice.eastmoney", "tonghuashun", "etnet", "aastocks"],
        "keywords": ["股票", "基金", "理财", "银行", "证券", "期货", "行情",
                     "投资", "记账", "币圈", "比特币", "加密货币", "钱包",
                     "股票代码", "市盈率", "均线", "打新", "可转债", "存款",
                     "余额宝", "房贷", "贷款", "信用卡"],
        "description": "银行/支付、股票基金行情、证券交易、理财记账、加密货币",
    },
    "健康": {
        "domains": ["dxy.cn", "dxy.com", "tengxunyiyuan", "haodf.com",
                    "120ask", "39.net", "nih.gov", "who.int", "msdmanuals",
                    "mayoclinic", "webmd", "guahao.com", "12320", "jdhealth"],
        "keywords": ["健康", "医疗", "医生", "挂号", "体检", "疾病", "症状",
                     "用药", "养生", "康复", "心理咨询", "体检报告", "问诊"],
        "description": "医疗健康科普、挂号问诊、体检、用药与养生",
    },
    "健身": {
        "domains": ["keep.com", "boohee", "youdao.fit", "strava", "codoon",
                    "yujia", "running", "fit"],
        "keywords": ["健身", "跑步", "瑜伽", "减肥", "食谱", "卡路里", "撸铁",
                     "有氧", "无氧", "体态", "拉伸", "增肌", "减脂"],
        "description": "健身运动、跑步瑜伽、减肥食谱与体态管理",
    },
    "教育": {
        "domains": ["icourse163", "mooc", "xuetangx", "kaoyan", "kaoyan.com",
                    "fenbi", "offcn", "huatu.com", "zhonggong", "eol.cn",
                    "crj", "yingjiesheng", "jzb.com", "ask.q.da"],
        "keywords": ["考研", "考公", "公务员", "事业单位", "教师资格", "考证",
                     "课程", "mooc", "慕课", "学习强国", "学历", "自考",
                     "专升本", "研究生"],
        "description": "考研考公考证、学历提升、MOOC 课程与备考平台",
    },
    "考试": {
        "domains": ["exam8", "cet", "ielts", "toefl", "kaogu", "enexam",
                    "wenkuxiazai", "xdf", "koolearn", "hujiang"],
        "keywords": ["四六级", "雅思", "托福", "驾考", "科目一", "刷题", "题库",
                     "考试", "普通话", "计算机等级", "报名", "准考证", "真题"],
        "description": "四六级/雅思/托福/驾考、题库刷题、考试报名与真题",
    },
    "阅读": {
        "domains": ["weread", "weread.qq", "kindle", "amazon.cn/kindle",
                    "qidian.com", "jjwxc", "hongxiu", "book.douban.com",
                    "readfree", "zlib", "oceanofpdf"],
        "keywords": ["读书", "阅读", "小说", "书单", "电子书", "kindle",
                     "微信读书", "起点", "晋江", "摘抄", "书评", "出版社",
                     "文学", "名著", "连载"],
        "description": "电子书与阅读（微信读书/Kindle/起点/晋江）、书单与书评",
    },
    "写作": {
        "domains": ["zotero", "typora", "obsidian", "markdown", "publish",
                    "write", "jianshu", "zhuanlan", "evernote", "youdao",
                    "wiz.cn", "github.com/readme", "logseq", "remnote",
                    "app.yinxiang", "yuque"],
        "keywords": ["写作", "笔记", "markdown", "摘录", "大纲", "思维导图",
                     "素材库", "创作", "文案"],
        "description": "写作平台、笔记软件、Markdown 与知识管理（Obsidian/Notion）",
    },
    "求职": {
        "domains": ["zhipin", "lagou", "51job.com", "job.51job", "zhaopin",
                    "liepin", "maimai.cn", "nowcoder", "linkedin.com",
                    "jobbole", "100offer", "hiredchina", "kanzhun",
                    "51job", "jobui", "zhiye", "qichacha", "tianyancha",
                    "aiqicha"],
        "keywords": ["招聘", "求职", "简历", "面试", "offer", "内推", "跳槽",
                     "hr", "薪资", "猎头", "背调", "校招", "社招",
                     "牛客", "脉脉", "面经", "职场", "企业查询", "工商信息"],
        "description": "招聘网站（BOSS/拉勾/智联/前程无忧）、企业信息查询、面试刷题",
    },
}


def _full_default_taxonomy() -> Dict[str, dict]:
    """内置完整默认分类体系（含描述）。"""
    return {name: dict(rules) for name, rules in DEFAULT_TAXONOMY.items()}


def load_taxonomy(path: str) -> Dict[str, dict]:
    """加载分类体系。

    用户已有 taxonomy.json 时做**增量合并**：保留用户所有自定义（含删除/改名），
    并把新内置类别与分类描述补进去——这样老用户升级后也能看到更细的分类，
    不会被锁死在旧分类表里。描述字段同时供 AI 分类 prompt 使用。
    """
    base = _full_default_taxonomy()
    if not path or not os.path.exists(path):
        return base
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:  # noqa: BLE001
        return base
    if not (isinstance(data, dict) and data):
        return base
    merged = dict(base)                      # 新内置类别兜底
    for name, rules in data.items():
        if isinstance(rules, dict):
            r = dict(rules)
            if not r.get("description"):
                r["description"] = DEFAULT_TAXONOMY.get(name, {}).get(
                    "description", "")
            merged[name] = r                 # 用户已有分类以用户版本为准
    return merged


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


# ---------------------------------------------------------------- 兜底启发式
# 规则全部零命中时的最后一道防线：按域名后缀、主机名词、路径特征猜一个归属。
# 匹配一律用「主机分段精确相等」或「路径片段」，避免 tool 误伤 mytool.com。

FALLBACK_SUFFIX = (
    (".edu.cn", "学习"), (".ac.cn", "学习"), (".edu", "学习"),
    (".gov.cn", "政务"), (".gov", "政务"), (".mil.cn", "政务"),
    (".org.cn", "资讯"),
)

FALLBACK_HOST_WORDS = (
    (("blog", "blogs", "diary", "journal", "note", "notes"), "学习"),
    (("docs", "doc", "documentation", "wiki", "manual", "guide",
      "tutorial", "kb", "help", "course", "learn", "study"), "学习"),
    (("news", "daily", "press", "magazine", "info", "toutiao"), "资讯"),
    (("forum", "bbs", "community", "club", "discuss", "talk"), "社区"),
    (("shop", "store", "mall", "market", "buy", "cart", "sale"), "电商"),
    (("job", "jobs", "hire", "hr", "zhaopin"), "求职"),
    (("tool", "tools", "util", "utils", "online", "web", "app", "apps"), "工具"),
    (("pan", "drive", "cloud", "disk", "mail"), "工具"),
    (("api", "dev", "developer", "developers", "sdk", "code", "git",
      "lab", "labs"), "开发"),
    (("video", "tv", "movie", "film", "music", "radio", "fm", "live"), "影音"),
    (("game", "games", "play"), "游戏"),
    (("photo", "photos", "pic", "pics", "image", "images", "img",
      "gallery", "picasso"), "摄影"),
    (("map", "maps", "geo", "gis"), "GIS"),
    (("design", "ui", "ux", "icon", "icons", "font", "fonts"), "设计"),
)

FALLBACK_PATH_WORDS = (
    (("/docs/", "/doc/", "/wiki/", "/blog/", "/tutorial/", "/guide/",
      "/manual/", "/course/"), "学习"),
    (("/news/", "/article/", "/post/"), "资讯"),
    (("/forum/", "/bbs/", "/thread/"), "社区"),
    (("/shop/", "/store/", "/product/", "/item/"), "电商"),
    (("/tool/", "/tools/", "/util/"), "工具"),
    (("/api/", "/developer/", "/sdk/"), "开发"),
)


def _fallback_category(bm: Bookmark, taxonomy: Dict[str, dict]) -> str:
    """规则零命中时的兜底猜测；猜不出返回空串。"""
    host = (bm.domain or "").lower()
    try:
        path = urlsplit(bm.url).path.lower()
    except ValueError:
        path = ""

    for suffix, cat in FALLBACK_SUFFIX:
        if host.endswith(suffix) and cat in taxonomy:
            return cat

    segs = host.split(".")
    for words, cat in FALLBACK_HOST_WORDS:
        if cat not in taxonomy:
            continue
        if any(w in segs for w in words):
            return cat

    for words, cat in FALLBACK_PATH_WORDS:
        if cat not in taxonomy:
            continue
        if any(w in path for w in words):
            return cat
    return ""


def classify_one(bm: Bookmark, taxonomy: Dict[str, dict]) -> str:
    best, best_score, best_folder = DEFAULT_CATEGORY, 0, False
    for cat, rules in taxonomy.items():
        s, fhit = _score(bm, rules)
        # 仅当分数更高，或分数相同但本分类命中了原文件夹而当前最佳没有时，才替换
        if s > best_score or (s == best_score and s > 0 and fhit and not best_folder):
            best, best_score, best_folder = cat, s, fhit
    if best_score == 0:
        fb = _fallback_category(bm, taxonomy)
        if fb:
            return fb
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
