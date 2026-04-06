"""
配置与环境变量工具
"""

import os
from typing import Optional

_ENV_LOADED = False


def get_project_root() -> str:
    """返回项目根目录（a-share-daily-report）。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def get_default_env_path() -> str:
    """
    默认 .env 路径（workspace-trader/.env）。
    目录关系: scripts/utils -> scripts -> a-share-daily-report -> skills -> workspace-trader
    """
    return os.path.normpath(os.path.join(get_project_root(), "..", "..", ".env"))


def load_project_env(override: bool = False) -> Optional[str]:
    """
    加载项目 .env（最多加载一次）。
    可用 A_SHARE_ENV_FILE 指定自定义路径。
    返回实际加载的路径；未加载时返回 None。
    """
    global _ENV_LOADED
    if _ENV_LOADED:
        return None

    env_path = os.getenv("A_SHARE_ENV_FILE", "").strip() or get_default_env_path()
    if not os.path.exists(env_path):
        _ENV_LOADED = True
        return None

    try:
        from dotenv import load_dotenv
    except ImportError:
        _ENV_LOADED = True
        return None

    load_dotenv(env_path, override=override)
    _ENV_LOADED = True
    return env_path
