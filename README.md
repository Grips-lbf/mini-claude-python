# Mini Claude Code (Python)

从零实现一个迷你版 [Claude Code](https://docs.anthropic.com/en/docs/claude-code) —— 一个 AI 编程助手 CLI 工具。

本项目从 [claude-code-from-scratch](https://github.com/Windy3f3f3f3f/claude-code-from-scratch)（TypeScript）翻译而来，旨在帮助你**用 Python 理解 AI Agent 的核心实现原理**。

## 它能做什么？

和真正的 Claude Code 一样，Mini Claude Code 可以：

- **读写文件** — 自动读取代码、创建新文件、精确编辑已有文件
- **搜索代码** — 用 glob 匹配文件，用正则搜索内容
- **执行命令** — 运行测试、安装依赖、执行 git 操作
- **多轮对话** — 自动循环调用工具直到任务完成
- **流式输出** — 实时逐字打印 AI 回复
- **会话持久化** — 对话自动保存，可恢复上次会话

## Quick Start

### 1. 克隆项目

```bash
git clone https://github.com/Grips-lbf/mini-claude-python.git
cd mini-claude-python
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

依赖只有 3 个包：
- `anthropic` — Anthropic API SDK
- `openai` — OpenAI 兼容 API SDK
- `colorama` — 终端彩色输出

### 3. 配置 API Key

**Anthropic（推荐）：**

```bash
export ANTHROPIC_API_KEY="sk-ant-your-key-here"
```

**OpenAI 兼容 API：**

```bash
export OPENAI_API_KEY="sk-your-key"
export OPENAI_BASE_URL="https://api.openai.com/v1"
```

### 4. 运行

```bash
# 交互模式（REPL）
python cli.py

# 一次性模式
python cli.py "帮我看看当前目录有哪些文件"

# 跳过所有确认提示
python cli.py --yolo "运行所有测试并修复失败的用例"
```

## 使用示例

### 交互模式

```
  Mini Claude Code — A minimal coding agent (Python)

  Type your request, or 'exit' to quit.
  Commands: /clear /cost /compact

> 帮我读一下 cli.py 的内容

  📖 read_file cli.py
  (文件内容显示...)

这是 CLI 入口文件，负责参数解析和 REPL 循环...

  ──────────────────────────────────────────────────

> 把 print_welcome 函数里的标题改成 "My Agent"

  🔧 edit_file ui.py
  Successfully edited ui.py

已将标题从 "Mini Claude Code" 改为 "My Agent"。

  ──────────────────────────────────────────────────
```

### 命令行参数

| 参数 | 说明 |
|------|------|
| `--yolo`, `-y` | 跳过所有危险操作确认 |
| `--thinking` | 启用扩展思考（仅 Anthropic） |
| `--model`, `-m` | 指定模型（默认 `claude-opus-4-6`） |
| `--api-base URL` | 使用 OpenAI 兼容 API |
| `--api-key KEY` | 指定 API Key |
| `--resume` | 恢复上次会话 |

### REPL 命令

| 命令 | 说明 |
|------|------|
| `/clear` | 清空对话历史 |
| `/cost` | 查看 token 用量和费用估算 |
| `/compact` | 手动压缩对话上下文 |
| `exit` | 退出 |

## 项目架构

```
mini-claude-python/
├── cli.py              ← 入口：参数解析 + REPL 循环 + Ctrl+C 处理
├── agent.py            ← 核心：Agent Loop（LLM ↔ 工具 循环）
├── tools.py            ← 工具：6 个工具的定义 + 执行 + 权限检查
├── prompt.py           ← 提示词：系统提示词构建（Git 上下文 + CLAUDE.md）
├── session.py          ← 持久化：会话保存 / 加载 / 恢复
├── ui.py               ← UI：终端彩色输出
├── system_prompt.md    ← 系统提示词模板
├── requirements.txt    ← Python 依赖
└── __main__.py         ← python -m 入口
```

### 核心循环（agent.py）

整个项目的精髓在 Agent Loop，这是所有 AI Agent 的通用模式：

```
┌─────────────────────────────────────────────────┐
│                  用户输入                         │
└──────────────────────┬──────────────────────────┘
                       ▼
              ┌────────────────┐
              │  加入消息历史    │
              └───────┬────────┘
                      ▼
        ┌──────────────────────────┐
        │  调用 LLM API（流式输出）  │◄─────────┐
        └──────────┬───────────────┘           │
                   ▼                           │
          ┌────────────────┐                   │
          │  有工具调用吗？   │                   │
          └──┬──────────┬──┘                   │
          No │          │ Yes                  │
             ▼          ▼                      │
     ┌──────────┐  ┌───────────────┐           │
     │ 输出结果  │  │ 权限检查       │           │
     │ 打印费用  │  │ 执行工具       │           │
     │ 保存会话  │  │ 截断超长结果   │           │
     └──────────┘  │ 结果送回 LLM   │───────────┘
                   └───────────────┘
                          │
                          ▼
                  ┌──────────────┐
                  │ 上下文 > 85%？│
                  │ → 自动压缩    │
                  └──────────────┘
```

### 6 个工具（tools.py）

| 工具 | 功能 | 安全级别 |
|------|------|---------|
| `read_file` | 读取文件（带行号） | 安全 |
| `write_file` | 创建/覆写文件 | 新文件需确认 |
| `edit_file` | 精确替换文件内容（必须唯一匹配） | 安全 |
| `list_files` | Glob 模式匹配文件 | 安全（限 200 条） |
| `grep_search` | 正则搜索文件内容 | 安全（限 100 条） |
| `run_shell` | 执行 Shell 命令 | 危险命令需确认 |

**危险命令检测**：`rm`, `git push/reset`, `sudo`, `kill`, `reboot` 等会触发确认提示（`--yolo` 可跳过）。

### 上下文管理

- 每个模型有对应的上下文窗口大小（如 Claude: 200K, GPT-4o: 128K）
- 预留 20K buffer，实际可用 = 窗口 - 20000
- 当已用 token 超过 85% 时自动压缩：用 LLM 总结历史对话，保留最后一条消息
- 工具返回超过 50KB 的结果会被截断（保留首尾各 25KB）

### 双后端支持

同时支持 **Anthropic** 和 **OpenAI 兼容** API：

```bash
# Anthropic（默认）
export ANTHROPIC_API_KEY="sk-ant-xxx"
python cli.py

# OpenAI
export OPENAI_API_KEY="sk-xxx"
export OPENAI_BASE_URL="https://api.openai.com/v1"
python cli.py --model gpt-4o

# 任意 OpenAI 兼容 API
python cli.py --api-base https://your-api.com/v1 --api-key sk-xxx --model your-model
```

### 会话持久化（session.py）

- 每次对话后自动保存到 `~/.mini-claude/sessions/{id}.json`
- `--resume` 恢复上次会话，继续之前的对话

### 系统提示词（prompt.py）

运行时自动注入环境信息：
- 当前工作目录、日期、操作系统
- Git 分支、最近 5 条提交、工作区状态
- 从当前目录向上遍历所有 `CLAUDE.md` 文件的内容

## 推荐阅读顺序

如果你想理解 AI Agent 的实现原理，建议按以下顺序阅读代码：

1. **`tools.py`** — 最直观，看 AI 有哪些能力（工具定义 + 执行）
2. **`prompt.py`** — 最短，看系统提示词如何构建
3. **`ui.py`** — 纯 UI 层，看终端输出如何格式化
4. **`session.py`** — 会话持久化，简单的 JSON 读写
5. **`agent.py`** — **核心重点**，理解 Agent Loop 的完整流程
6. **`cli.py`** — 入口文件，看参数解析和 REPL 循环

## 与原版 TypeScript 的对应关系

| TypeScript | Python | 关键差异 |
|-----------|--------|---------|
| `@anthropic-ai/sdk` | `anthropic` | Python SDK 用 `AsyncAnthropic` |
| `openai` npm | `openai` pip | Python SDK 用 `AsyncOpenAI` |
| `chalk` | `colorama` + ANSI | 更轻量 |
| `AbortController` | `bool` 标志位 | Python 没有原生 AbortController |
| `readline` | `input()` + `asyncio.run_in_executor` | 异步 REPL |
| `glob` npm | `glob` 标准库 | Python 内置 |
| `child_process.execSync` | `subprocess.run` | 标准库 |
| ES Modules | Python modules | 直接 import |

## License

MIT
