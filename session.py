"""
会话持久化模块 — 对应 src/session.ts

将对话历史保存到 ~/.mini-claude/sessions/{id}.json，
支持保存、加载、列出、获取最新会话。
"""

import os
import json
from pathlib import Path

SESSION_DIR = Path.home() / ".mini-claude" / "sessions"


def _ensure_dir():
    SESSION_DIR.mkdir(parents=True, exist_ok=True)


def save_session(session_id: str, data: dict) -> None:
    """保存会话数据到 JSON 文件。"""
    _ensure_dir()
    file_path = SESSION_DIR / f"{session_id}.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_session(session_id: str) -> dict | None:
    """根据 ID 加载会话数据。"""
    file_path = SESSION_DIR / f"{session_id}.json"
    if not file_path.exists():
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def list_sessions() -> list[dict]:
    """列出所有已保存会话的 metadata。"""
    _ensure_dir()
    results = []
    for file_path in SESSION_DIR.glob("*.json"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "metadata" in data:
                results.append(data["metadata"])
        except Exception:
            continue
    return results


def get_latest_session_id() -> str | None:
    """获取最近一次会话的 ID（按 startTime 降序排列）。"""
    sessions = list_sessions()
    if not sessions:
        return None
    sessions.sort(key=lambda s: s.get("startTime", ""), reverse=True)
    return sessions[0].get("id")
