"""
终端 UI 模块 — 对应 src/ui.ts

负责所有彩色终端输出：欢迎信息、用户提示符、助手文本流式输出、
工具调用/结果展示、错误/确认/重试/信息提示、分隔线、费用统计。
"""

import sys
from colorama import init, Fore, Style

# 初始化 colorama（Windows 兼容）
init()

# ─── 工具图标 ─────────────────────────────────────────────────

TOOL_ICONS = {
    "read_file": "\U0001f4d6",    # 📖
    "write_file": "\u270f\ufe0f",  # ✏️
    "edit_file": "\U0001f527",     # 🔧
    "list_files": "\U0001f4c1",    # 📁
    "grep_search": "\U0001f50d",   # 🔍
    "run_shell": "\U0001f4bb",     # 💻
}


def _get_tool_icon(name: str) -> str:
    return TOOL_ICONS.get(name, "\U0001f528")  # 🔨


def _get_tool_summary(name: str, input_data: dict) -> str:
    """根据工具名和输入参数生成一行摘要。"""
    if name in ("read_file", "write_file", "edit_file"):
        return input_data.get("file_path", "")
    if name == "list_files":
        return input_data.get("pattern", "")
    if name == "grep_search":
        pattern = input_data.get("pattern", "")
        path = input_data.get("path", ".")
        return f'"{pattern}" in {path}'
    if name == "run_shell":
        cmd = input_data.get("command", "")
        return cmd[:60] + "..." if len(cmd) > 60 else cmd
    return ""


# ─── 公共输出函数 ─────────────────────────────────────────────

def print_welcome():
    print(
        f"\n  {Style.BRIGHT}{Fore.CYAN}Mini Claude Code{Style.RESET_ALL}"
        f"{Fore.LIGHTBLACK_EX} — A minimal coding agent (Python){Style.RESET_ALL}\n"
    )
    print(f"{Fore.LIGHTBLACK_EX}  Type your request, or 'exit' to quit.")
    print(f"  Commands: /clear /cost /compact\n{Style.RESET_ALL}")


def print_user_prompt():
    sys.stdout.write(f"\n{Style.BRIGHT}{Fore.GREEN}> {Style.RESET_ALL}")
    sys.stdout.flush()


def print_assistant_text(text: str):
    """流式输出助手文本（逐块写入，不换行）。"""
    sys.stdout.write(text)
    sys.stdout.flush()


def print_tool_call(name: str, input_data: dict):
    icon = _get_tool_icon(name)
    summary = _get_tool_summary(name, input_data)
    print(
        f"\n  {Fore.YELLOW}{icon} {name}{Style.RESET_ALL}"
        f"{Fore.LIGHTBLACK_EX} {summary}{Style.RESET_ALL}"
    )


def print_tool_result(name: str, result: str):
    max_len = 500
    if len(result) > max_len:
        truncated = result[:max_len] + f"\n  {Fore.LIGHTBLACK_EX}... ({len(result)} chars total){Style.RESET_ALL}"
    else:
        truncated = result
    lines = truncated.split("\n")
    indented = "\n".join("  " + line for line in lines)
    print(f"{Style.DIM}{indented}{Style.RESET_ALL}")


def print_error(msg: str):
    print(f"\n  {Fore.RED}Error: {msg}{Style.RESET_ALL}", file=sys.stderr)


def print_confirmation(command: str):
    print(
        f"\n  {Fore.YELLOW}\u26a0 Dangerous command: {Style.RESET_ALL}"
        f"{Style.BRIGHT}{command}{Style.RESET_ALL}"
    )


def print_divider():
    print(f"\n  {Fore.LIGHTBLACK_EX}{'─' * 50}{Style.RESET_ALL}")


def print_cost(input_tokens: int, output_tokens: int):
    cost_in = (input_tokens / 1_000_000) * 3
    cost_out = (output_tokens / 1_000_000) * 15
    total = cost_in + cost_out
    print(
        f"{Fore.LIGHTBLACK_EX}"
        f"\n  Tokens: {input_tokens} in / {output_tokens} out (~${total:.4f})"
        f"{Style.RESET_ALL}"
    )


def print_retry(attempt: int, max_retries: int, reason: str):
    print(f"\n  {Fore.YELLOW}\u21bb Retry {attempt}/{max_retries}: {reason}{Style.RESET_ALL}")


def print_info(msg: str):
    print(f"\n  {Fore.CYAN}\u2139 {msg}{Style.RESET_ALL}")
