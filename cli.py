#!/usr/bin/env python3
"""
CLI 入口 — 对应 src/cli.ts

负责：
1. 解析命令行参数（--yolo, --model, --api-base, --api-key, --resume, --thinking）
2. 解析 API 配置（CLI 参数 > 环境变量，自动检测 Anthropic / OpenAI）
3. 创建 Agent 实例
4. One-shot 模式（直接传 prompt）或 REPL 交互模式
5. Ctrl+C 处理（第一次中断当前处理，第二次退出）
6. REPL 命令：/clear, /cost, /compact
"""

import os
import sys
import signal
import argparse
import asyncio

from agent import Agent
from session import load_session, get_latest_session_id
from ui import print_welcome, print_user_prompt, print_error, print_info


def parse_args():
    parser = argparse.ArgumentParser(
        description="Mini Claude Code — A minimal coding agent (Python)",
        add_help=False,
    )
    parser.add_argument("--yolo", "-y", action="store_true", help="Skip all confirmation prompts")
    parser.add_argument("--thinking", action="store_true", help="Enable extended thinking (Anthropic only)")
    parser.add_argument("--model", "-m", default=None, help="Model to use")
    parser.add_argument("--api-base", default=None, help="Use OpenAI-compatible API endpoint")
    parser.add_argument("--api-key", default=None, help="API key for the specified endpoint")
    parser.add_argument("--resume", action="store_true", help="Resume the last session")
    parser.add_argument("--help", "-h", action="store_true", help="Show this help")
    parser.add_argument("prompt", nargs="*", help="One-shot prompt")

    args = parser.parse_args()

    if args.help:
        print("""
Usage: python cli.py [options] [prompt]

Options:
  --yolo, -y       Skip all confirmation prompts
  --thinking       Enable extended thinking (Anthropic only)
  --model, -m      Model to use (default: claude-opus-4-6, or MINI_CLAUDE_MODEL env)
  --api-base URL   Use OpenAI-compatible API endpoint
  --api-key KEY    API key for the specified endpoint
  --resume         Resume the last session
  --help, -h       Show this help

REPL commands:
  /clear           Clear conversation history
  /cost            Show token usage and cost
  /compact         Manually compact conversation

Examples:
  python cli.py "fix the bug in src/app.py"
  python cli.py --yolo "run all tests and fix failures"
  python cli.py --api-base https://api.example.com/v1 --api-key sk-xxx --model gpt-4o "hello"
  python cli.py --resume
  python cli.py  # starts interactive REPL
""")
        sys.exit(0)

    return args


async def run_repl(agent: Agent):
    """交互式 REPL 循环。"""
    sigint_count = 0

    def sigint_handler(sig, frame):
        nonlocal sigint_count
        if agent.is_processing:
            agent.abort()
            print("\n  (interrupted)")
            sigint_count = 0
            print_user_prompt()
        else:
            sigint_count += 1
            if sigint_count >= 2:
                print("\nBye!\n")
                sys.exit(0)
            print("\n  Press Ctrl+C again to exit.")
            print_user_prompt()

    signal.signal(signal.SIGINT, sigint_handler)
    print_welcome()

    loop = asyncio.get_event_loop()

    while True:
        print_user_prompt()
        try:
            # 在 executor 中读取用户输入，避免阻塞事件循环
            user_input = await loop.run_in_executor(None, sys.stdin.readline)
        except EOFError:
            print("\nBye!\n")
            break

        user_input = user_input.strip() if user_input else ""
        sigint_count = 0

        if not user_input:
            continue
        if user_input in ("exit", "quit"):
            print("\nBye!\n")
            break

        # REPL 命令
        if user_input == "/clear":
            agent.clear_history()
            continue
        if user_input == "/cost":
            agent.show_cost()
            continue
        if user_input == "/compact":
            try:
                await agent.compact()
            except Exception as e:
                print_error(str(e))
            continue

        # 正常对话
        try:
            await agent.chat(user_input)
        except KeyboardInterrupt:
            pass  # 已由 sigint_handler 处理
        except Exception as e:
            if "aborted" in str(e).lower():
                pass
            else:
                print_error(str(e))


async def main():
    args = parse_args()

    model = args.model or os.environ.get("MINI_CLAUDE_MODEL", "claude-opus-4-6")
    api_base = getattr(args, "api_base", None)
    api_key = getattr(args, "api_key", None)
    use_openai = bool(api_base)

    # 解析 API 配置：CLI 参数 > 环境变量
    if not api_key:
        if os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENAI_BASE_URL"):
            api_key = os.environ["OPENAI_API_KEY"]
            api_base = api_base or os.environ.get("OPENAI_BASE_URL")
            use_openai = True
        elif os.environ.get("ANTHROPIC_API_KEY"):
            api_key = os.environ["ANTHROPIC_API_KEY"]
            api_base = api_base or os.environ.get("ANTHROPIC_BASE_URL")
            use_openai = False
        elif os.environ.get("OPENAI_API_KEY"):
            api_key = os.environ["OPENAI_API_KEY"]
            api_base = api_base or os.environ.get("OPENAI_BASE_URL")
            use_openai = True

    if not api_key:
        print_error(
            "API key is required.\n"
            "  Set ANTHROPIC_API_KEY (+ optional ANTHROPIC_BASE_URL) for Anthropic format,\n"
            "  or OPENAI_API_KEY + OPENAI_BASE_URL for OpenAI-compatible format,\n"
            "  or use --api-key / --api-base flags."
        )
        sys.exit(1)

    agent = Agent(
        yolo=args.yolo,
        model=model,
        thinking=args.thinking,
        api_base=api_base if use_openai else None,
        anthropic_base_url=api_base if not use_openai else None,
        api_key=api_key,
    )

    # 恢复会话
    if args.resume:
        session_id = get_latest_session_id()
        if session_id:
            session = load_session(session_id)
            if session:
                agent.restore_session({
                    "anthropicMessages": session.get("anthropicMessages"),
                    "openaiMessages": session.get("openaiMessages"),
                })
            else:
                print_info("No session found to resume.")
        else:
            print_info("No previous sessions found.")

    # One-shot 或 REPL
    prompt = " ".join(args.prompt) if args.prompt else None
    if prompt:
        try:
            await agent.chat(prompt)
        except Exception as e:
            print_error(str(e))
            sys.exit(1)
    else:
        await run_repl(agent)


if __name__ == "__main__":
    asyncio.run(main())
