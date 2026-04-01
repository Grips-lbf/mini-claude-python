"""
系统提示词模块 — 对应 src/prompt.ts

负责：
1. 从当前目录向上遍历加载所有 CLAUDE.md 文件
2. 获取 Git 上下文（分支、最近提交、状态）
3. 用运行时信息替换模板变量，构建最终系统提示词
"""

import os
import platform
import subprocess
from datetime import date


def load_claude_md() -> str:
    """
    从当前工作目录向上遍历到根目录，收集所有 CLAUDE.md 文件内容。
    越靠近根目录的 CLAUDE.md 越靠前（优先级最低），
    越靠近当前目录的越靠后（优先级最高）。
    """
    parts: list[str] = []
    current = os.getcwd()
    while True:
        claude_file = os.path.join(current, "CLAUDE.md")
        if os.path.isfile(claude_file):
            try:
                with open(claude_file, "r", encoding="utf-8") as f:
                    parts.insert(0, f.read())
            except Exception:
                pass
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent

    if parts:
        return "\n\n# Project Instructions (CLAUDE.md)\n" + "\n\n---\n\n".join(parts)
    return ""


def get_git_context() -> str:
    """
    获取当前目录的 Git 上下文：分支名、最近 5 条提交、工作区状态。
    如果当前目录不是 Git 仓库，返回空字符串。
    """
    def _run(cmd: str) -> str:
        try:
            return subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=3
            ).stdout.strip()
        except Exception:
            return ""

    try:
        branch = _run("git rev-parse --abbrev-ref HEAD")
        if not branch:
            return ""
        log = _run("git log --oneline -5")
        status = _run("git status --short")
        result = f"\nGit branch: {branch}"
        if log:
            result += f"\nRecent commits:\n{log}"
        if status:
            result += f"\nGit status:\n{status}"
        return result
    except Exception:
        return ""


def build_system_prompt() -> str:
    """
    读取 system_prompt.md 模板，用运行时环境信息替换占位符变量：
    - {{cwd}}         当前工作目录
    - {{date}}        今天日期
    - {{platform}}    操作系统 + 架构
    - {{shell}}       Shell 路径
    - {{git_context}} Git 分支/提交/状态
    - {{claude_md}}   CLAUDE.md 内容
    """
    # 模板文件和本 .py 文件在同一目录
    template_path = os.path.join(os.path.dirname(__file__), "system_prompt.md")
    with open(template_path, "r", encoding="utf-8") as f:
        template = f.read()

    today = date.today().isoformat()
    plat = f"{platform.system().lower()} {platform.machine()}"
    shell = os.environ.get("SHELL", "unknown")
    git_context = get_git_context()
    claude_md = load_claude_md()

    return (
        template
        .replace("{{cwd}}", os.getcwd())
        .replace("{{date}}", today)
        .replace("{{platform}}", plat)
        .replace("{{shell}}", shell)
        .replace("{{git_context}}", git_context)
        .replace("{{claude_md}}", claude_md)
    )
