"""
Jinja2 模板渲染工具
"""

import os
from functools import lru_cache

from jinja2 import Environment, FileSystemLoader


@lru_cache(maxsize=1)
def _get_env():
    template_dir = os.path.join(os.path.dirname(__file__), "templates")
    return Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_template(template_name, **context):
    env = _get_env()
    tpl = env.get_template(template_name)
    return tpl.render(**context)
