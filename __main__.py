"""使得 `python -m python` 可用（从 python/ 目录的父目录运行）。"""
from cli import main
import asyncio

asyncio.run(main())
