"""
核心 Agent 模块 — 对应 src/agent.ts

实现了完整的 AI 编程助手循环：
1. 接收用户消息
2. 调用 LLM（Anthropic 或 OpenAI 兼容）获取流式回复
3. 解析工具调用（tool_use）
4. 执行工具并收集结果
5. 将工具结果送回 LLM，循环直到无工具调用
6. 自动压缩对话上下文（85% 阈值）
7. 自动保存会话

支持双后端（Anthropic / OpenAI）、指数退避重试、权限确认、中断处理。
"""

import os
import json
import time
import random
import asyncio
from datetime import datetime
from uuid import uuid4

import anthropic
import openai

from tools import tool_definitions, execute_tool, needs_confirmation
from ui import (
    print_assistant_text, print_tool_call, print_tool_result,
    print_error, print_confirmation, print_divider,
    print_cost, print_retry, print_info,
)
from session import save_session
from prompt import build_system_prompt


# ─── 模型上下文窗口大小 ──────────────────────────────────────

MODEL_CONTEXT = {
    "claude-opus-4-6": 200000,
    "claude-sonnet-4-6": 200000,
    "claude-sonnet-4-20250514": 200000,
    "claude-haiku-4-5-20251001": 200000,
    "claude-opus-4-20250514": 200000,
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
}


def _get_context_window(model: str) -> int:
    return MODEL_CONTEXT.get(model, 200000)


# ─── 指数退避重试 ────────────────────────────────────────────

def _is_retryable(error: Exception) -> bool:
    """判断错误是否值得重试（429/503/529、网络错误、过载）。"""
    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    if status in (429, 503, 529):
        return True
    msg = str(error).lower()
    if "overloaded" in msg or "connection" in msg or "timeout" in msg:
        return True
    return False


async def _with_retry(fn, max_retries: int = 3):
    """
    带指数退避的重试包装器。
    fn 是一个 async 函数，最多重试 max_retries 次。
    """
    for attempt in range(max_retries + 1):
        try:
            return await fn()
        except Exception as error:
            if attempt >= max_retries or not _is_retryable(error):
                raise
            delay = min(1000 * (2 ** attempt), 30000) + random.random() * 1000
            reason = str(getattr(error, "status_code", "")) or type(error).__name__
            print_retry(attempt + 1, max_retries, reason)
            await asyncio.sleep(delay / 1000)


# ─── 将工具定义转换为 OpenAI 格式 ────────────────────────────

def _to_openai_tools() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tool_definitions
    ]


# ─── Agent 类 ────────────────────────────────────────────────

class Agent:
    """
    核心 Agent，维护对话历史，驱动 LLM ↔ 工具 循环。

    参数:
        yolo:             跳过所有确认提示
        model:            模型名称
        api_base:         OpenAI 兼容 API 地址
        anthropic_base_url: Anthropic 代理地址
        api_key:          API 密钥
        thinking:         启用扩展思考（仅 Anthropic）
    """

    def __init__(
        self,
        yolo: bool = False,
        model: str = "claude-opus-4-6",
        api_base: str | None = None,
        anthropic_base_url: str | None = None,
        api_key: str | None = None,
        thinking: bool = False,
    ):
        self.yolo = yolo
        self.thinking = thinking
        self.model = model
        self.use_openai = bool(api_base)
        self.system_prompt = build_system_prompt()
        self.effective_window = _get_context_window(model) - 20000
        self.session_id = str(uuid4())[:8]
        self.session_start_time = datetime.now().isoformat()

        # Token 统计
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self._last_input_token_count = 0

        # 中断标志
        self._aborted = False
        self._is_processing = False

        # 权限白名单（本次会话已确认的操作）
        self._confirmed_paths: set[str] = set()

        # 分别维护 Anthropic / OpenAI 的消息历史
        self._anthropic_messages: list[dict] = []
        self._openai_messages: list[dict] = []

        # 初始化客户端
        if self.use_openai:
            self._openai_client = openai.AsyncOpenAI(
                base_url=api_base,
                api_key=api_key,
            )
            self._openai_messages.append({"role": "system", "content": self.system_prompt})
        else:
            kwargs = {"api_key": api_key}
            if anthropic_base_url:
                kwargs["base_url"] = anthropic_base_url
            self._anthropic_client = anthropic.AsyncAnthropic(**kwargs)

    # ─── 公共属性 ────────────────────────────────────────────

    @property
    def is_processing(self) -> bool:
        return self._is_processing

    def abort(self):
        self._aborted = True

    # ─── 主入口 ──────────────────────────────────────────────

    async def chat(self, user_message: str) -> None:
        """处理一轮用户输入（可能包含多次工具调用循环）。"""
        self._aborted = False
        self._is_processing = True
        try:
            if self.use_openai:
                await self._chat_openai(user_message)
            else:
                await self._chat_anthropic(user_message)
        finally:
            self._is_processing = False
        print_divider()
        self._auto_save()

    # ─── REPL 命令 ───────────────────────────────────────────

    def clear_history(self):
        self._anthropic_messages = []
        self._openai_messages = []
        if self.use_openai:
            self._openai_messages.append({"role": "system", "content": self.system_prompt})
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self._last_input_token_count = 0
        print_info("Conversation cleared.")

    def show_cost(self):
        cost_in = (self.total_input_tokens / 1_000_000) * 3
        cost_out = (self.total_output_tokens / 1_000_000) * 15
        total = cost_in + cost_out
        print_info(
            f"Tokens: {self.total_input_tokens} in / {self.total_output_tokens} out\n"
            f"  Estimated cost: ${total:.4f}"
        )

    async def compact(self):
        await self._compact_conversation()

    # ─── 会话恢复 ────────────────────────────────────────────

    def restore_session(self, data: dict):
        if data.get("anthropicMessages"):
            self._anthropic_messages = data["anthropicMessages"]
        if data.get("openaiMessages"):
            self._openai_messages = data["openaiMessages"]
        count = self._get_message_count()
        print_info(f"Session restored ({count} messages).")

    def _get_message_count(self) -> int:
        return len(self._openai_messages) if self.use_openai else len(self._anthropic_messages)

    def _auto_save(self):
        try:
            save_session(self.session_id, {
                "metadata": {
                    "id": self.session_id,
                    "model": self.model,
                    "cwd": os.getcwd(),
                    "startTime": self.session_start_time,
                    "messageCount": self._get_message_count(),
                },
                "anthropicMessages": self._anthropic_messages if not self.use_openai else None,
                "openaiMessages": self._openai_messages if self.use_openai else None,
            })
        except Exception:
            pass

    # ─── 自动压缩 ────────────────────────────────────────────

    async def _check_and_compact(self):
        if self._last_input_token_count > self.effective_window * 0.85:
            print_info("Context window filling up, compacting conversation...")
            await self._compact_conversation()

    async def _compact_conversation(self):
        if self.use_openai:
            await self._compact_openai()
        else:
            await self._compact_anthropic()
        print_info("Conversation compacted.")

    async def _compact_anthropic(self):
        if len(self._anthropic_messages) < 4:
            return
        last_user_msg = self._anthropic_messages[-1]
        # 用 LLM 总结之前的对话
        summary_resp = await self._anthropic_client.messages.create(
            model=self.model,
            max_tokens=2048,
            system="You are a conversation summarizer. Be concise but preserve important details.",
            messages=[
                *self._anthropic_messages[:-1],
                {
                    "role": "user",
                    "content": "Summarize the conversation so far in a concise paragraph, "
                               "preserving key decisions, file paths, and context needed to continue the work.",
                },
            ],
        )
        summary_text = (
            summary_resp.content[0].text
            if summary_resp.content and summary_resp.content[0].type == "text"
            else "No summary available."
        )
        self._anthropic_messages = [
            {"role": "user", "content": f"[Previous conversation summary]\n{summary_text}"},
            {"role": "assistant", "content": "Understood. I have the context from our previous conversation. How can I continue helping?"},
        ]
        if last_user_msg.get("role") == "user":
            self._anthropic_messages.append(last_user_msg)
        self._last_input_token_count = 0

    async def _compact_openai(self):
        if len(self._openai_messages) < 5:
            return
        system_msg = self._openai_messages[0]
        last_user_msg = self._openai_messages[-1]
        summary_resp = await self._openai_client.chat.completions.create(
            model=self.model,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": "You are a conversation summarizer. Be concise but preserve important details."},
                *self._openai_messages[1:-1],
                {
                    "role": "user",
                    "content": "Summarize the conversation so far in a concise paragraph, "
                               "preserving key decisions, file paths, and context needed to continue the work.",
                },
            ],
        )
        summary_text = summary_resp.choices[0].message.content or "No summary available."
        self._openai_messages = [
            system_msg,
            {"role": "user", "content": f"[Previous conversation summary]\n{summary_text}"},
            {"role": "assistant", "content": "Understood. I have the context from our previous conversation. How can I continue helping?"},
        ]
        if last_user_msg.get("role") == "user":
            self._openai_messages.append(last_user_msg)
        self._last_input_token_count = 0

    # ─── Anthropic 后端 ──────────────────────────────────────

    async def _chat_anthropic(self, user_message: str):
        self._anthropic_messages.append({"role": "user", "content": user_message})

        while True:
            if self._aborted:
                break

            response = await self._call_anthropic_stream()

            # 统计 token
            self.total_input_tokens += response.usage.input_tokens
            self.total_output_tokens += response.usage.output_tokens
            self._last_input_token_count = response.usage.input_tokens

            # 提取工具调用
            tool_uses = [block for block in response.content if block.type == "tool_use"]

            # 将助手回复加入历史（序列化 content blocks）
            self._anthropic_messages.append({
                "role": "assistant",
                "content": [self._serialize_block(b) for b in response.content],
            })

            # 没有工具调用，对话结束
            if not tool_uses:
                print_cost(self.total_input_tokens, self.total_output_tokens)
                break

            # 执行每个工具调用
            tool_results = []
            for tool_use in tool_uses:
                if self._aborted:
                    break
                input_data = dict(tool_use.input) if hasattr(tool_use.input, 'items') else tool_use.input
                print_tool_call(tool_use.name, input_data)

                # 权限检查
                if not self.yolo:
                    confirm_msg = needs_confirmation(tool_use.name, input_data)
                    if confirm_msg and confirm_msg not in self._confirmed_paths:
                        confirmed = await self._confirm_dangerous(confirm_msg)
                        if not confirmed:
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": tool_use.id,
                                "content": "User denied this action.",
                            })
                            continue
                        self._confirmed_paths.add(confirm_msg)

                result = await execute_tool(tool_use.name, input_data)
                print_tool_result(tool_use.name, result)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use.id,
                    "content": result,
                })

            # 将工具结果作为 user 消息送回
            self._anthropic_messages.append({"role": "user", "content": tool_results})
            await self._check_and_compact()

    def _serialize_block(self, block) -> dict:
        """将 Anthropic SDK 的 content block 对象序列化为字典。"""
        if block.type == "text":
            return {"type": "text", "text": block.text}
        elif block.type == "tool_use":
            return {
                "type": "tool_use",
                "id": block.id,
                "name": block.name,
                "input": dict(block.input) if hasattr(block.input, 'items') else block.input,
            }
        # 其他类型（thinking 等）直接跳过
        return {"type": block.type}

    async def _call_anthropic_stream(self):
        """调用 Anthropic API（流式），实时打印文本，返回完整 Message。"""
        async def _call():
            create_params = {
                "model": self.model,
                "max_tokens": 16000 if self.thinking else 8096,
                "system": self.system_prompt,
                "tools": tool_definitions,
                "messages": self._anthropic_messages,
            }
            if self.thinking:
                create_params["thinking"] = {"type": "enabled", "budget_tokens": 10000}

            # 流式调用
            first_text = True
            async with self._anthropic_client.messages.stream(**create_params) as stream:
                async for text in stream.text_stream:
                    if first_text:
                        print_assistant_text("\n")
                        first_text = False
                    print_assistant_text(text)
                response = await stream.get_final_message()

            # 过滤掉 thinking blocks
            if self.thinking:
                response.content = [b for b in response.content if b.type != "thinking"]

            return response

        return await _with_retry(_call)

    # ─── OpenAI 兼容后端 ─────────────────────────────────────

    async def _chat_openai(self, user_message: str):
        self._openai_messages.append({"role": "user", "content": user_message})

        while True:
            if self._aborted:
                break

            response = await self._call_openai_stream()

            # 统计 token
            if response.get("usage"):
                self.total_input_tokens += response["usage"]["prompt_tokens"]
                self.total_output_tokens += response["usage"]["completion_tokens"]
                self._last_input_token_count = response["usage"]["prompt_tokens"]

            message = response["choices"][0]["message"]

            # 加入历史
            self._openai_messages.append(message)

            # 没有工具调用，对话结束
            tool_calls = message.get("tool_calls")
            if not tool_calls:
                print_cost(self.total_input_tokens, self.total_output_tokens)
                break

            # 执行工具调用
            for tc in tool_calls:
                if self._aborted:
                    break
                if tc.get("type") != "function":
                    continue
                fn_name = tc["function"]["name"]
                try:
                    input_data = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    input_data = {}

                print_tool_call(fn_name, input_data)

                # 权限检查
                if not self.yolo:
                    confirm_msg = needs_confirmation(fn_name, input_data)
                    if confirm_msg and confirm_msg not in self._confirmed_paths:
                        confirmed = await self._confirm_dangerous(confirm_msg)
                        if not confirmed:
                            self._openai_messages.append({
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": "User denied this action.",
                            })
                            continue
                        self._confirmed_paths.add(confirm_msg)

                result = await execute_tool(fn_name, input_data)
                print_tool_result(fn_name, result)
                self._openai_messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

            await self._check_and_compact()

    async def _call_openai_stream(self) -> dict:
        """调用 OpenAI API（流式），实时打印文本，返回组装后的 ChatCompletion 字典。"""
        async def _call():
            stream = await self._openai_client.chat.completions.create(
                model=self.model,
                max_tokens=8096,
                tools=_to_openai_tools(),
                messages=self._openai_messages,
                stream=True,
                stream_options={"include_usage": True},
            )

            content = ""
            first_text = True
            tool_calls: dict[int, dict] = {}  # index -> {id, name, arguments}
            finish_reason = ""
            usage = None

            async for chunk in stream:
                # Usage 在最后一个 chunk（没有 delta）
                if chunk.usage:
                    usage = {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                    }

                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta

                # 流式输出文本
                if delta and delta.content:
                    if first_text:
                        print_assistant_text("\n")
                        first_text = False
                    print_assistant_text(delta.content)
                    content += delta.content

                # 累积工具调用（参数分块到达）
                if delta and delta.tool_calls:
                    for tc in delta.tool_calls:
                        if tc.index in tool_calls:
                            existing = tool_calls[tc.index]
                            if tc.function and tc.function.arguments:
                                existing["arguments"] += tc.function.arguments
                        else:
                            tool_calls[tc.index] = {
                                "id": tc.id or "",
                                "name": tc.function.name if tc.function else "",
                                "arguments": tc.function.arguments if tc.function else "",
                            }

                if chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason

            # 组装完整的 tool_calls 列表
            assembled_tool_calls = None
            if tool_calls:
                assembled_tool_calls = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": tc["arguments"]},
                    }
                    for _, tc in sorted(tool_calls.items())
                ]

            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": assembled_tool_calls,
                    },
                    "finish_reason": finish_reason or "stop",
                }],
                "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0},
            }

        return await _with_retry(_call)

    # ─── 权限确认 ────────────────────────────────────────────

    async def _confirm_dangerous(self, command: str) -> bool:
        """在终端提示用户确认危险操作。"""
        print_confirmation(command)
        loop = asyncio.get_event_loop()
        answer = await loop.run_in_executor(None, lambda: input("  Allow? (y/n): "))
        return answer.strip().lower().startswith("y")
