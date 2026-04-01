"""
工具模块 — 对应 src/tools.ts

定义了 6 个核心工具（read_file, write_file, edit_file, list_files, grep_search, run_shell），
以及工具执行、危险命令检测、权限检查、结果截断等逻辑。
"""

import os
import re
import glob as glob_module
import subprocess

# ─── 工具定义（Anthropic Tool 格式）──────────────────────────

tool_definitions = [
    {
        "name": "read_file",
        "description": "Read the contents of a file. Returns the file content with line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The path to the file to read",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file. Creates the file if it doesn't exist, overwrites if it does.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The path to the file to write",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file",
                },
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": (
            "Edit a file by replacing an exact string match with new content. "
            "The old_string must match exactly (including whitespace and indentation)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "The path to the file to edit",
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact string to find and replace",
                },
                "new_string": {
                    "type": "string",
                    "description": "The string to replace it with",
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    },
    {
        "name": "list_files",
        "description": "List files matching a glob pattern. Returns matching file paths.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": 'Glob pattern to match files (e.g., "**/*.ts", "src/**/*")',
                },
                "path": {
                    "type": "string",
                    "description": "Base directory to search from. Defaults to current directory.",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "grep_search",
        "description": "Search for a pattern in files. Returns matching lines with file paths and line numbers.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The regex pattern to search for",
                },
                "path": {
                    "type": "string",
                    "description": "Directory or file to search in. Defaults to current directory.",
                },
                "include": {
                    "type": "string",
                    "description": 'File glob pattern to include (e.g., "*.ts", "*.py")',
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "run_shell",
        "description": (
            "Execute a shell command and return its output. "
            "Use this for running tests, installing packages, git operations, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute",
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout in milliseconds (default: 30000)",
                },
            },
            "required": ["command"],
        },
    },
]


# ─── 工具实现 ─────────────────────────────────────────────────

def _read_file(file_path: str) -> str:
    """读取文件内容，返回带行号的文本。"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        numbered = [f"{str(i+1).rjust(4)} | {line.rstrip()}" for i, line in enumerate(lines)]
        return "\n".join(numbered)
    except Exception as e:
        return f"Error reading file: {e}"


def _write_file(file_path: str, content: str) -> str:
    """写入文件，自动创建目录。"""
    try:
        dir_name = os.path.dirname(file_path)
        if dir_name and not os.path.exists(dir_name):
            os.makedirs(dir_name, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote to {file_path}"
    except Exception as e:
        return f"Error writing file: {e}"


def _edit_file(file_path: str, old_string: str, new_string: str) -> str:
    """精确替换文件中的字符串（必须唯一匹配）。"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        count = content.count(old_string)
        if count == 0:
            return f"Error: old_string not found in {file_path}"
        if count > 1:
            return f"Error: old_string found {count} times. Must be unique."
        new_content = content.replace(old_string, new_string, 1)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        return f"Successfully edited {file_path}"
    except Exception as e:
        return f"Error editing file: {e}"


def _list_files(pattern: str, path: str | None = None) -> str:
    """用 glob 匹配文件，排除 node_modules 和 .git，最多返回 200 条。"""
    try:
        base = path or os.getcwd()
        full_pattern = os.path.join(base, pattern)
        files = glob_module.glob(full_pattern, recursive=True)
        # 过滤掉目录和 node_modules/.git
        files = [
            f for f in files
            if os.path.isfile(f)
            and "node_modules" not in f
            and ".git" not in f.split(os.sep)
        ]
        if not files:
            return "No files found matching the pattern."
        result = "\n".join(files[:200])
        if len(files) > 200:
            result += f"\n... and {len(files) - 200} more"
        return result
    except Exception as e:
        return f"Error listing files: {e}"


def _grep_search(pattern: str, path: str | None = None, include: str | None = None) -> str:
    """用 grep 搜索文件内容，最多返回 100 条匹配。"""
    try:
        args = ["grep", "--line-number", "--color=never", "-r"]
        if include:
            args.append(f"--include={include}")
        args.append(pattern)
        args.append(path or ".")
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 1:
            return "No matches found."
        if result.returncode != 0:
            return f"Error: {result.stderr}"
        lines = [line for line in result.stdout.split("\n") if line]
        output = "\n".join(lines[:100])
        if len(lines) > 100:
            output += f"\n... and {len(lines) - 100} more matches"
        return output
    except subprocess.TimeoutExpired:
        return "Error: grep timed out after 10 seconds."
    except Exception as e:
        return f"Error: {e}"


def _run_shell(command: str, timeout: int | None = None) -> str:
    """执行 shell 命令，返回输出。"""
    timeout_sec = (timeout or 30000) / 1000  # ms -> seconds
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        output = result.stdout or ""
        if result.returncode != 0:
            stderr = f"\nStderr: {result.stderr}" if result.stderr else ""
            stdout = f"\nStdout: {result.stdout}" if result.stdout else ""
            return f"Command failed (exit code {result.returncode}){stdout}{stderr}"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout_sec:.0f} seconds."
    except Exception as e:
        return f"Error: {e}"


# ─── 危险命令检测 ─────────────────────────────────────────────

DANGEROUS_PATTERNS = [
    re.compile(r"\brm\s"),
    re.compile(r"\bgit\s+(push|reset|clean|checkout\s+\.)"),
    re.compile(r"\bsudo\b"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\s"),
    re.compile(r">\s*/dev/"),
    re.compile(r"\bkill\b"),
    re.compile(r"\bpkill\b"),
    re.compile(r"\breboot\b"),
    re.compile(r"\bshutdown\b"),
]


def is_dangerous(command: str) -> bool:
    """检查命令是否包含危险模式。"""
    return any(p.search(command) for p in DANGEROUS_PATTERNS)


def needs_confirmation(tool_name: str, input_data: dict) -> str | None:
    """
    统一权限检查 — 如果操作需要用户确认，返回确认消息字符串；
    否则返回 None 表示安全放行。
    """
    # Shell 命令：检查危险模式
    if tool_name == "run_shell" and is_dangerous(input_data.get("command", "")):
        return input_data["command"]
    # 写入新文件需要确认
    if tool_name == "write_file" and not os.path.exists(input_data.get("file_path", "")):
        return f"write new file: {input_data['file_path']}"
    # 编辑不存在的文件需要确认
    if tool_name == "edit_file" and not os.path.exists(input_data.get("file_path", "")):
        return f"edit non-existent file: {input_data['file_path']}"
    return None


# ─── 结果截断（保护上下文窗口）────────────────────────────────

MAX_RESULT_CHARS = 50000


def _truncate_result(result: str) -> str:
    """如果结果超过 50KB，保留首尾各 25KB，中间截断。"""
    if len(result) <= MAX_RESULT_CHARS:
        return result
    keep_each = (MAX_RESULT_CHARS - 60) // 2
    return (
        result[:keep_each]
        + f"\n\n[... truncated {len(result) - keep_each * 2} chars ...]\n\n"
        + result[-keep_each:]
    )


# ─── 工具执行入口 ─────────────────────────────────────────────

async def execute_tool(name: str, input_data: dict) -> str:
    """根据工具名称分发执行，返回截断后的结果字符串。"""
    if name == "read_file":
        result = _read_file(input_data["file_path"])
    elif name == "write_file":
        result = _write_file(input_data["file_path"], input_data["content"])
    elif name == "edit_file":
        result = _edit_file(
            input_data["file_path"],
            input_data["old_string"],
            input_data["new_string"],
        )
    elif name == "list_files":
        result = _list_files(input_data["pattern"], input_data.get("path"))
    elif name == "grep_search":
        result = _grep_search(
            input_data["pattern"],
            input_data.get("path"),
            input_data.get("include"),
        )
    elif name == "run_shell":
        result = _run_shell(input_data["command"], input_data.get("timeout"))
    else:
        return f"Unknown tool: {name}"
    return _truncate_result(result)
