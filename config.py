"""配置读写：配置、分类体系与域名规则保存在用户目录下，不随程序目录走。"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

APP_NAME = "BookmarkDoctor"

DEFAULT_CONFIG: Dict[str, Any] = {
    # AI
    "api_key": "",
    "base_url": "",
    "model": "gpt-4o-mini",
    "batch_size": 25,
    "ai_workers": 3,
    "ai_timeout": 90,
    # 验证
    "check_workers": 32,
    "check_timeout": 8,
    "check_retries": 1,
    "verify_ssl": False,
    "exit_profile": "系统代理",
    "custom_proxy": "",
    "domain_delay": 100,        # 毫秒
    "enable_soft404": True,
    "enable_fallback": True,
    "record_public_ip": False,
    # 去重
    "dedupe_level": "标准",
    "dedupe_threshold": 0.92,
    # 其它
    "last_dir": "",
}


def config_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        path = os.path.expanduser("~")
    return path


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


def taxonomy_path() -> str:
    return os.path.join(config_dir(), "taxonomy.json")


def rules_path() -> str:
    return os.path.join(config_dir(), "rules.json")


def load_config() -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:  # noqa: BLE001
        pass
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    try:
        with open(config_path(), "w", encoding="utf-8", newline="\n") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def make_probe_config(cfg: Dict[str, Any]):
    """把界面配置转成 prober.ProbeConfig。"""
    from core.models import EXIT_CUSTOM, EXIT_DIRECT, EXIT_SYSTEM
    from core.prober import ProbeConfig

    return ProbeConfig(
        exit_profile=cfg.get("exit_profile", EXIT_SYSTEM) or EXIT_SYSTEM,
        custom_proxy=cfg.get("custom_proxy", ""),
        workers=int(cfg.get("check_workers", 32)),
        timeout=float(cfg.get("check_timeout", 8)),
        retries=int(cfg.get("check_retries", 1)),
        verify_ssl=bool(cfg.get("verify_ssl", False)),
        domain_delay=max(0.0, float(cfg.get("domain_delay", 100)) / 1000.0),
        enable_soft404=bool(cfg.get("enable_soft404", True)),
        enable_fallback=bool(cfg.get("enable_fallback", True)),
        record_public_ip=bool(cfg.get("record_public_ip", False)),
    )
