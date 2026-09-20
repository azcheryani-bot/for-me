import asyncio
import builtins
import os
import runpy
import shutil
import sys
from pathlib import Path

from pyrogram import Client


OUTPUT_NAME = "all_countries_v2nodes.txt"
WORKSPACE = Path.cwd()
DESKTOP = WORKSPACE / "Desktop"
ORIGINAL_INPUT = builtins.input


def noninteractive_input(prompt=""):
    if not sys.stdin.isatty():
        print("ورودی تعاملی در GitHub Actions در دسترس نیست؛ اجرای fallback متوقف شد.")
        return ""
    return ORIGINAL_INPUT(prompt)


def run_generator():
    original_input = builtins.input
    builtins.input = noninteractive_input
    try:
        runpy.run_module("v2nodes_configs", run_name="__main__")
    finally:
        builtins.input = original_input


async def send_output(output_path):
    api_id = int(os.environ["TELEGRAM_API_ID"])
    api_hash = os.environ["TELEGRAM_API_HASH"]
    session_string = os.environ["TELEGRAM_SESSION"]
    async with Client(
        "v2nodes_sender",
        api_id=api_id,
        api_hash=api_hash,
        session_string=session_string,
        in_memory=True,
    ) as app:
        await app.send_document(
            "testman222",
            str(output_path),
            caption="✅ کانفیگ‌های all countries v2nodes",
        )


def main():
    DESKTOP.mkdir(parents=True, exist_ok=True)
    run_generator()
    generated_path = DESKTOP / OUTPUT_NAME
    workspace_path = WORKSPACE / OUTPUT_NAME
    if not generated_path.is_file():
        raise FileNotFoundError(f"فایل خروجی ساخته نشد: {generated_path}")
    shutil.copyfile(generated_path, workspace_path)
    asyncio.run(send_output(workspace_path))


if __name__ == "__main__":
    main()
