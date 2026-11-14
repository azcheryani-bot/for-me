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
DESKTOP = Path.home() / "Desktop"
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
    app = Client("v2nodes_sender", api_id=api_id, api_hash=api_hash, session_string=session_string, in_memory=True)
    async with app:
        await app.send_document("enteghalbede", output_path, caption=f"{output_path.name}")


def main():
    # پالایش تهران v2nodes در v2nodes_configs.py انجام می‌شود (۱ پروب برای هر
    # هاست، fail-open). این فرایند جداگانه است، ولی حافظهٔ هاست با
    # relay_builder.py از راه فایل .globalping_host_cache.json در فضای کاری
    # همین اجرای ورک‌فلو مشترک است، پس هاست‌های بررسی‌شده دوباره تست نمی‌شوند.
    print("[Globalping][v2nodes] پالایش تهران در v2nodes_configs.py انجام می‌شود (۱ پروب برای هر هاست؛ حافظهٔ هاست با relay_builder.py مشترک است)")
    run_generator()
    print("[Globalping][v2nodes] مرحلهٔ v2nodes تمام شد؛ خروجی در ادامه کپی و ارسال می‌شود")
    desktop_output = DESKTOP / OUTPUT_NAME
    workspace_output = WORKSPACE / OUTPUT_NAME
    if not desktop_output.exists():
        raise FileNotFoundError(f"Expected output was not created: {desktop_output}")
    # خروجی خالی یعنی v2nodes.com در این اجرا کانفیگی نداد (مثلاً کلید پویا
    # پیدا نشد یا همهٔ کشورها 404 دادند). فایل خالی نه قابل ارسال به تلگرام
    # است (Pyrogram با «File size equals to 0 B» خطا می‌دهد) و نه باید جای
    # فایل قبلی مخزن را بگیرد؛ پس بدون کپی و بدون ارسال، با موفقیت برگردید
    # تا مرحلهٔ کامیت ورک‌فلو برای valid_relays.txt همچنان اجرا شود.
    if desktop_output.stat().st_size == 0:
        print(f"[v2nodes] خروجی خالی است ({desktop_output}، 0 بایت) — v2nodes.com در این اجرا کانفیگی نداد؛ فایل قبلی مخزن حفظ شد و چیزی ارسال نشد (fail-open)")
        return
    shutil.copyfile(desktop_output, workspace_output)
    print(f"Copied {desktop_output} -> {workspace_output}")
    asyncio.run(send_output(workspace_output))


if __name__ == "__main__":
    main()
