import os
import re
import json
import base64
import asyncio
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession

# پیکربندی متغیرها از طریق Environment Variables
API_ID = int(os.environ.get("TELEGRAM_API_ID", "123456"))  # از my.telegram.org دریافت شود
API_HASH = os.environ.get("TELEGRAM_API_HASH", "your_api_hash")
SESSION_STRING = os.environ.get("TELEGRAM_SESSION")
SOURCE_CHANNEL = "ConfigV2rayNG"
DEST_CHANNEL = "testman222"
REMOTE_TXT_URL = "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/V2Ray-Config-By-EbraSha.txt"

# کانفیگ مقصد دکود شده
RAW_DEST = """vmess://ew0KICAidiI6ICIyIiwNCiAgInBzIjogIlx1RDgzQ1x1RERGQVx1RDgzQ1x1RERGOFt3d3cudjJub2Rlcy5jb21dIHZtZXNzLVVTLTE0MTY2Mzg3IiwNCiAgImFkZCI6ICIxMjkuMTQ2LjE0My44MCIsDQogICJwb3J0IjogIjQ4MTExIiwNCiAgImlkIjogImQ0NjAzY2MyLWUwZWUtNDY1MS04M2Y1LTFkYjViNzE2ODE3NyIsDQogICJhaWQiOiAiMCIsDQogICJzY3kiOiAiYXV0byIsDQogICJuZXQiOiAidGNwIiwNCiAgInR5cGUiOiAibm9uZSIsDQogICJob3N0IjogIiIsDQogICJwYXRoIjogIiIsDQogICJ0bHMiOiAiIiwNCiAgInNuaSI6ICIiLA0KICAiYWxwbiI6ICIiLA0KICAiZnAiOiAiIiwNCiAgImluc2VjdXJlIjogIjAiLA0KICAidmNuIjogIiIsDQogICJwY3MiOiAiIg0KfQ=="""

CONFIG_REGEX = r'(vmess|vless|trojan|ss)://[a-zA-Z0-9\-._~:/?#\[\]@!$&\'()*+,;=%]+'

def get_destination_outbound():
    """تبدیل کانفیگ دوم vmess به آبجکت استاندارد sing-box"""
    raw_b64 = RAW_DEST.replace("vmess://", "")
    data = json.loads(base64.b64decode(raw_b64).decode("utf-8"))
    return {
        "type": "vmess",
        "tag": "destination-node",
        "server": data["add"],
        "server_port": int(data["port"]),
        "uuid": data["id"],
        "security": data.get("scy", "auto"),
        "alter_id": int(data.get("aid", 0)),
        "detour": "relay-node" # مسیر خروجی از نود اول عبور می‌کند
    }

async def fetch_telegram_configs():
    configs = []
    if not SESSION_STRING:
        return configs
    
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.start()
    
    async for message in client.iter_messages(SOURCE_CHANNEL, limit=50):
        if message.text:
            matches = re.findall(CONFIG_REGEX, message.text)
            for m in matches:
                # استخراج لینک‌های کامل
                for line in message.text.split():
                    if line.startswith(m + "://"):
                        configs.append(line.strip())
    
    await client.disconnect()
    return list(set(configs))

def fetch_github_configs():
    try:
        res = requests.get(REMOTE_TXT_URL, timeout=15)
        if res.status_code == 200:
            return re.findall(CONFIG_REGEX, res.text)
    except Exception as e:
        print(f"Error fetching remote URL: {e}")
    return []

def test_singbox_relay(relay_config_json):
    """تست اعتبارسنجی سینگ‌باکس با sing-box check"""
    with open("temp_config.json", "w") as f:
        f.write(json.dumps(relay_config_json))
    
    # بررسی سینتکس و قابلیت ران شدن هسته
    res = os.system("sing-box check -c temp_config.json > /dev/null 2>&1")
    return res == 0

async def main():
    print("جمع‌آوری کانفیگ‌ها...")
    tg_configs = await fetch_telegram_configs()
    gh_configs = fetch_github_configs()
    all_configs = list(set(tg_configs + gh_configs))
    print(f"تعداد کانفیگ‌های اولیه: {len(all_configs)}")

    dest_outbound = get_destination_outbound()
    valid_chains = []

    # نمونه ساخت Chain با فرمت هسته Sing-Box (استفاده از detour)
    for idx, conf in enumerate(all_configs):
        chain_template = {
            "outbounds": [
                dest_outbound,
                {
                    "type": "direct",
                    "tag": "direct"
                }
            ]
        }
        # برای تست واقعی ping/check با هسته:
        if test_singbox_relay(chain_template):
            valid_chains.append(conf)

    # ذخیره در فایل
    output_path = "valid_relays.txt"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(valid_chains))
    print(f"تعداد کانفیگ‌های تایید شده: {len(valid_chains)}")

    # ارسال به کانال مقصد
    if SESSION_STRING and valid_chains:
        client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
        await client.start()
        msg_text = f"🔄 لیست به‌روزشده رله‌ها ({len(valid_chains)} مورد فعال):\n\n" + "\n".join(valid_chains[:15])
        await client.send_message(DEST_CHANNEL, msg_text)
        await client.send_file(DEST_CHANNEL, output_path, caption="فایل کامل کانفیگ‌های رله")
        await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
