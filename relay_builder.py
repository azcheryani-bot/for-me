import os
import re
import json
import time
import base64
import asyncio
import requests
import subprocess
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pyrogram import Client

API_ID = int(os.environ.get("TELEGRAM_API_ID", "123456"))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "")
SESSION_STRING = os.environ.get("TELEGRAM_SESSION", "")
SOURCE_CHANNEL = "ConfigV2rayNG"
DEST_CHANNEL = "testman222"
REMOTE_TXT_URL = "https://raw.githubusercontent.com/ebrasha/free-v2ray-public-list/refs/heads/main/V2Ray-Config-By-EbraSha.txt"

# کانفیگ ثابت نود مقصد (exit-node)
EXIT_NODE = {
    "tag": "exit-node",
    "server": "129.146.143.80",
    "server_port": 48111,
    "detour": "relay-node",
    "type": "vmess",
    "uuid": "d4603cc2-e0ee-4651-83f5-1db5b7168177",
    "security": "auto",
    "alter_id": 0
}

# رجکس استخراج لینک‌های خام
URL_REGEX = r'((?:vmess|vless|trojan|ss|hysteria2|hy2)://[^\s<>"\']+)'

def parse_proxy_url(url_str):
    """تبدیل لینک‌های مختلف پروتکل‌ها به آبجکت outbound سینگ‌باکس با تگ relay-node"""
    url_str = url_str.strip()
    if not url_str:
        return None

    # 1. VLESS
    if url_str.startswith("vless://"):
        try:
            parsed = urllib.parse.urlparse(url_str)
            query = dict(urllib.parse.parse_qsl(parsed.query))
            outbound = {
                "tag": "relay-node",
                "server": parsed.hostname,
                "server_port": int(parsed.port or 443),
                "type": "vless",
                "uuid": parsed.username
            }
            if query.get("flow"):
                outbound["flow"] = query["flow"]

            net_type = query.get("type", "tcp").lower()
            if net_type == "ws":
                headers = {"Host": query["host"]} if "host" in query else {}
                outbound["transport"] = {
                    "type": "ws",
                    "path": query.get("path", "/"),
                    "headers": headers
                }
            elif net_type == "grpc":
                outbound["transport"] = {
                    "type": "grpc",
                    "service_name": query.get("serviceName", "")
                }

            security = query.get("security", "").lower()
            if security == "reality":
                outbound["tls"] = {
                    "enabled": True,
                    "server_name": query.get("sni", parsed.hostname),
                    "insecure": False,
                    "reality": {
                        "enabled": True,
                        "public_key": query.get("pbk", ""),
                        "short_id": query.get("sid", "")
                    }
                }
            elif security == "tls":
                outbound["tls"] = {
                    "enabled": True,
                    "server_name": query.get("sni") or query.get("host") or parsed.hostname,
                    "insecure": query.get("allowInsecure", "0") in ["1", "true"]
                }
            return outbound
        except Exception:
            return None

    # 2. Trojan
    elif url_str.startswith("trojan://"):
        try:
            parsed = urllib.parse.urlparse(url_str)
            query = dict(urllib.parse.parse_qsl(parsed.query))
            outbound = {
                "tag": "relay-node",
                "server": parsed.hostname,
                "server_port": int(parsed.port or 443),
                "type": "trojan",
                "password": parsed.username
            }
            net_type = query.get("type", "tcp").lower()
            if net_type == "ws":
                headers = {"Host": query["host"]} if "host" in query else {}
                outbound["transport"] = {
                    "type": "ws",
                    "path": query.get("path", "/"),
                    "headers": headers
                }
            elif net_type == "grpc":
                outbound["transport"] = {
                    "type": "grpc",
                    "service_name": query.get("serviceName", "")
                }

            security = query.get("security", "tls").lower()
            if security == "tls" or security == "":
                outbound["tls"] = {
                    "enabled": True,
                    "server_name": query.get("sni") or query.get("host") or parsed.hostname,
                    "insecure": query.get("allowInsecure", "0") in ["1", "true"]
                }
            return outbound
        except Exception:
            return None

    # 3. Shadowsocks
    elif url_str.startswith("ss://"):
        try:
            raw = url_str[5:].split("#")[0]
            if "@" in raw:
                user_info, host_port = raw.split("@", 1)
                if ":" in user_info:
                    method, password = user_info.split(":", 1)
                else:
                    padded = user_info + '=' * (-len(user_info) % 4)
                    decoded = base64.b64decode(padded).decode("utf-8")
                    method, password = decoded.split(":", 1)
                host, port = host_port.split(":", 1)
            else:
                padded = raw + '=' * (-len(raw) % 4)
                decoded = base64.b64decode(padded).decode("utf-8")
                user_info, host_port = decoded.split("@", 1)
                method, password = user_info.split(":", 1)
                host, port = host_port.split(":", 1)

            return {
                "tag": "relay-node",
                "server": host,
                "server_port": int(port),
                "type": "shadowsocks",
                "method": method,
                "password": password
            }
        except Exception:
            return None

    # 4. Hysteria2
    elif url_str.startswith("hysteria2://") or url_str.startswith("hy2://"):
        try:
            parsed = urllib.parse.urlparse(url_str)
            query = dict(urllib.parse.parse_qsl(parsed.query))
            return {
                "tag": "relay-node",
                "server": parsed.hostname,
                "server_port": int(parsed.port or 443),
                "type": "hysteria2",
                "up_mbps": 100,
                "down_mbps": 100,
                "password": parsed.username,
                "tls": {
                    "enabled": True,
                    "server_name": query.get("sni", parsed.hostname),
                    "insecure": query.get("insecure", "0") in ["1", "true"]
                }
            }
        except Exception:
            return None

    # 5. VMess
    elif url_str.startswith("vmess://"):
        try:
            b64_part = url_str[8:].strip()
            b64_part += '=' * (-len(b64_part) % 4)
            data = json.loads(base64.b64decode(b64_part).decode("utf-8", errors="ignore"))
            outbound = {
                "tag": "relay-node",
                "server": data.get("add", ""),
                "server_port": int(data.get("port", 443)),
                "type": "vmess",
                "uuid": data.get("id", ""),
                "security": data.get("scy", "auto"),
                "alter_id": int(data.get("aid", 0))
            }
            net = data.get("net", "tcp").lower()
            if net == "ws":
                headers = {"Host": data.get("host")} if data.get("host") else {}
                outbound["transport"] = {
                    "type": "ws",
                    "path": data.get("path", "/"),
                    "headers": headers
                }
            elif net == "grpc":
                outbound["transport"] = {
                    "type": "grpc",
                    "service_name": data.get("path", "")
                }
            if data.get("tls") == "tls":
                outbound["tls"] = {
                    "enabled": True,
                    "server_name": data.get("sni") or data.get("host") or data.get("add"),
                    "insecure": data.get("insecure", "0") in ["1", "true"]
                }
            return outbound
        except Exception:
            return None

    return None

def build_singbox_full_json(relay_node_outbound):
    """ایجاد ساختار کامل JSON نهایی مطابق قالب خواسته شده کاربر با inbound tun"""
    return {
        "log": {
            "level": "info"
        },
        "inbounds": [
            {
                "type": "tun",
                "tag": "tun-in",
                "interface_name": "tun0",
                "inet4_address": "172.19.0.1/30",
                "auto_route": True,
                "strict_route": True,
                "endpoint_independent_nat": True,
                "stack": "system",
                "sniff": True
            }
        ],
        "outbounds": [
            EXIT_NODE,
            relay_node_outbound,
            {
                "type": "direct",
                "tag": "direct"
            },
            {
                "type": "block",
                "tag": "block"
            }
        ],
        "route": {
            "auto_detect_interface": True,
            "rules": [
                {
                    "protocol": "dns",
                    "outbound": "direct"
                }
            ]
        }
    }

def test_single_relay(relay_outbound, test_port):
    """تست زنده پینگ از طریق زنجیره رله با ایجاد پورت موقت HTTP Proxy در Sing-box"""
    test_config = {
        "log": {"level": "warn"},
        "inbounds": [
            {
                "type": "mixed",
                "tag": "mixed-in",
                "listen": "127.0.0.1",
                "listen_port": test_port
            }
        ],
        "outbounds": [
            EXIT_NODE,
            relay_outbound,
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"}
        ],
        "route": {
            "rules": [
                {"protocol": "dns", "outbound": "direct"}
            ]
        }
    }

    config_filename = f"test_{test_port}.json"
    with open(config_filename, "w", encoding="utf-8") as f:
        json.dump(test_config, f)

    # تست سینتکس سینگ‌باکس
    if os.system(f"sing-box check -c {config_filename} > /dev/null 2>&1") != 0:
        if os.path.exists(config_filename):
            os.remove(config_filename)
        return False

    # اجرای پروسه سینگ‌باکس
    proc = subprocess.Popen(
        ["sing-box", "run", "-c", config_filename],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    time.sleep(0.8)

    proxies = {
        "http": f"http://127.0.0.1:{test_port}",
        "https": f"http://127.0.0.1:{test_port}"
    }

    is_alive = False
    try:
        # ارسال درخواست تست اتصال از داخل زنجیره تونل شده
        r = requests.get("http://cp.cloudflare.com/generate_204", proxies=proxies, timeout=3.5)
        if r.status_code in [200, 204]:
            is_alive = True
    except Exception:
        pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except Exception:
            proc.kill()
        if os.path.exists(config_filename):
            os.remove(config_filename)

    return is_alive

def ping_filter(relay_outbounds):
    """اجرای هم‌زمان و موازی تست پینگ برای سرعت بالا"""
    alive_nodes = []
    print(f"شروع تست پینگ فعال برای {len(relay_outbounds)} کانفیگ...")

    def worker(item):
        idx, node = item
        port = 20000 + (idx % 80)
        if test_single_relay(node, port):
            print(f"🟢 پینگ موفق: {node.get('server')}:{node.get('server_port')} [{node.get('type')}]")
            return node
        return None

    with ThreadPoolExecutor(max_workers=6) as executor:
        results = executor.map(worker, enumerate(relay_outbounds))
        for res in results:
            if res:
                alive_nodes.append(res)

    return alive_nodes

async def fetch_telegram_configs():
    configs = []
    if not SESSION_STRING:
        print("TELEGRAM_SESSION مقداردهی نشده است.")
        return configs

    app = Client("session_bot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING, in_memory=True)
    async with app:
        async for message in app.get_chat_history(SOURCE_CHANNEL, limit=50):
            text = message.text or message.caption
            if text:
                matches = re.findall(URL_REGEX, text, re.IGNORECASE)
                for item in matches:
                    configs.append(item.strip())
    return list(set(configs))

def fetch_github_configs():
    try:
        res = requests.get(REMOTE_TXT_URL, timeout=15)
        if res.status_code == 200:
            return re.findall(URL_REGEX, res.text, re.IGNORECASE)
    except Exception as e:
        print(f"خطا در دریافت کانفیگ‌های گیت‌هاب: {e}")
    return []

async def main():
    print("جمع‌آوری لینک‌های اولیه...")
    tg_links = await fetch_telegram_configs()
    gh_links = fetch_github_configs()
    all_raw_links = list(set(tg_links + gh_links))
    print(f"تعداد لینک‌های خام استخراج شده: {len(all_raw_links)}")

    # تبدیل لینک‌های خام به آبجکت outbound
    parsed_outbounds = []
    for link in all_raw_links:
        parsed = parse_proxy_url(link)
        if parsed:
            parsed_outbounds.append(parsed)
    print(f"تعداد کانفیگ‌های ترجمه شده به سینگ‌باکس: {len(parsed_outbounds)}")

    # تست پینگ واقعی روی تک‌تک زنجیره‌ها
    working_nodes = ping_filter(parsed_outbounds)
    print(f"تعداد نهایی کانفیگ‌های سالم با پینگ تایید شده: {len(working_nodes)}")

    if not working_nodes:
        print("هیچ کانفیگی در این نوبت تست پینگ موفق ثبت نکرد.")
        return

    # قالب‌بندی خروجی به‌صورت بلوک‌های کامل JSON جداگانه
    output_blocks = []
    for node in working_nodes:
        full_cfg = build_singbox_full_json(node)
        output_blocks.append(json.dumps(full_cfg, indent=2, ensure_ascii=False))

    output_content = "\n".join(output_blocks)
    output_filename = "valid_relays.txt"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write(output_content)
    print(f"فایل {output_filename} با موفقیت ذخیره شد.")

    # ارسال به کانال تلگرام
    if SESSION_STRING:
        app = Client("sender_bot", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING, in_memory=True)
        async with app:
            caption = f"✅ تعداد {len(working_nodes)} کانفیگ زنجیره‌ای Sing-box تست‌شده با پینگ موفق"
            await app.send_document(DEST_CHANNEL, output_filename, caption=caption)
            print("فایل خروجی با موفقیت در کانال تلگرام بارگذاری شد.")

if __name__ == "__main__":
    asyncio.run(main())
