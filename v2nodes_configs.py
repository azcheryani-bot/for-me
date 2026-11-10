import os
import re
import time
import base64
import requests
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed

# آدرس پایه سایت
SITE_URL = "https://www.v2nodes.com"

# لیست کامل تمام کدهای استاندارد دوحرفی کشورهای جهان (ISO 3166-1 alpha-2) + all
COUNTRY_CODES = [
    "all", "ad", "ae", "af", "ag", "ai", "al", "am", "ao", "aq", "ar", "as", "at", "au", "aw", "ax", "az",
    "ba", "bb", "bd", "be", "bf", "bg", "bh", "bi", "bj", "bl", "bm", "bn", "bo", "bq", "br", "bs", "bt",
    "bv", "bw", "by", "bz", "ca", "cc", "cd", "cf", "cg", "ch", "ci", "ck", "cl", "cm", "cn", "co", "cr",
    "cu", "cv", "cw", "cx", "cy", "cz", "de", "dj", "dk", "dm", "do", "dz", "ec", "ee", "eg", "eh", "er",
    "es", "et", "fi", "fj", "fk", "fm", "fo", "fr", "ga", "gb", "gd", "ge", "gf", "gg", "gh", "gi", "gl",
    "gm", "gn", "gp", "gq", "gr", "gs", "gt", "gu", "gw", "gy", "hk", "hm", "hn", "hr", "ht", "hu", "id",
    "ie", "il", "im", "in", "io", "iq", "ir", "is", "it", "je", "jm", "jo", "jp", "ke", "kg", "kh", "ki",
    "km", "kn", "kp", "kr", "kw", "ky", "kz", "la", "lb", "lc", "li", "lk", "lr", "ls", "lt", "lu", "lv",
    "ly", "ma", "mc", "md", "me", "mf", "mg", "mh", "mk", "ml", "mm", "mn", "mo", "mp", "mq", "mr", "ms",
    "mt", "mu", "mv", "mw", "mx", "my", "mz", "na", "nc", "ne", "nf", "ng", "ni", "nl", "no", "np", "nr",
    "nu", "nz", "om", "pa", "pe", "pf", "pg", "ph", "pk", "pl", "pm", "pn", "pr", "ps", "pt", "pw", "py",
    "qa", "re", "ro", "rs", "ru", "rw", "sa", "sb", "sc", "sd", "se", "sg", "sh", "si", "sj", "sk", "sl",
    "sm", "sn", "so", "sr", "ss", "st", "sv", "sx", "sy", "sz", "tc", "td", "tf", "tg", "th", "tj", "tk",
    "tl", "tm", "tn", "to", "tr", "tt", "tv", "tw", "tz", "ua", "ug", "um", "us", "uy", "uz", "va", "vc",
    "ve", "vg", "vi", "vn", "vu", "wf", "ws", "ye", "yt", "za", "zm", "zw"
]

PROTOCOLS = ("vmess://", "vless://", "trojan://", "ss://", "ssr://", "hy2://", "tuic://")


KEY_FETCH_ATTEMPTS = 3
KEY_FETCH_TIMEOUT = 20


def get_latest_key_from_site(session: requests.Session) -> str | None:
    """دریافت خودکار آخرین کلید فعال از صفحه اصلی سایت (با چند تلاش و وقفه)"""
    print("[*] در حال واکشی آخرین کلید از سایت v2nodes.com...")
    patterns = [
        r"/subscriptions/country/[a-zA-Z]+/?[?]key=([a-zA-Z0-9]+)",
        r"[?&]key=([a-zA-Z0-9]{10,40})",
        r"key=([0-9A-Fa-f]{10,40})"
    ]
    for attempt in range(1, KEY_FETCH_ATTEMPTS + 1):
        try:
            res = session.get(SITE_URL, timeout=KEY_FETCH_TIMEOUT)
            print(f"[*] تلاش {attempt}/{KEY_FETCH_ATTEMPTS} برای دریافت کلید: HTTP {res.status_code}، {len(res.content)} بایت")
            if res.status_code == 200:
                html = res.text
                for pattern in patterns:
                    matches = re.findall(pattern, html)
                    if matches:
                        print(f"[✓] کلید در تلاش {attempt} پیدا شد")
                        return matches[0]
                print(f"[!] تلاش {attempt}: صفحه رسید اما هیچ کلیدی در آن پیدا نشد")
            else:
                print(f"[!] تلاش {attempt}: وضعیت غیر 200")
        except requests.RequestException as e:
            print(f"[!] تلاش {attempt}/{KEY_FETCH_ATTEMPTS} برای دریافت کلید خطا خورد: {type(e).__name__}: {e}")
        if attempt < KEY_FETCH_ATTEMPTS:
            wait = 5 * attempt
            print(f"[*] {wait} ثانیه صبر و تلاش دوباره برای دریافت کلید...")
            time.sleep(wait)
    print("[!] دریافت کلید پس از همه تلاش‌ها ناموفق بود")
    return None


def safe_b64decode(s: str) -> str:
    """دیکود رشته با اصلاح اتوماتیک پدینگ Base64"""
    s = s.strip().replace("\r", "").replace(" ", "")
    padding = len(s) % 4
    if padding:
        s += "=" * (4 - padding)
    return base64.b64decode(s).decode("utf-8", errors="ignore")


def parse_subscription_payload(raw_content: str) -> list[str]:
    """استخراج و دیکود کانفیگ‌ها از ساختار Base64 یا متن ساده"""
    found = []
    text_to_scan = raw_content

    try:
        decoded_block = safe_b64decode(raw_content)
        if any(proto in decoded_block for proto in PROTOCOLS):
            text_to_scan = decoded_block
    except Exception:
        pass

    for line in text_to_scan.splitlines():
        line = line.strip()
        if not line:
            continue

        if line.startswith(PROTOCOLS):
            found.append(line)
        else:
            try:
                decoded_line = safe_b64decode(line)
                if decoded_line.startswith(PROTOCOLS):
                    found.append(decoded_line)
            except Exception:
                pass

    return found


def fetch_country_configs(country: str, base_url: str, key: str, session: requests.Session) -> tuple[str, list[str]]:
    url = f"{base_url}/{country}/?key={key}"
    try:
        res = session.get(url, timeout=10)
        if res.status_code == 200 and res.text.strip():
            configs = parse_subscription_payload(res.text)
            return country, configs
        print(f"[!] {country}: HTTP {res.status_code} یا پاسخ خالی")
    except requests.RequestException as e:
        print(f"[!] {country}: خطا {type(e).__name__}: {e}")
    return country, []


def get_desktop_path() -> str:
    return os.path.join(os.path.expanduser("~"), "Desktop")


def main():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    })

    key = get_latest_key_from_site(session)

    if key:
        print(f"[✓] آخرین کلید با موفقیت از سایت دریافت شد: {key}")
    else:
        print("[-] دریافت خودکار کلید با شکست مواجه شد (احتمالاً به دلیل محدودیت شبکه یا تغییر ساختار سایت).")
        user_input = input("لطفاً نمونه لینک سابسکریپشن یا کلید را به صورت دستی وارد کنید:\n> ").strip()

        key_match = re.search(r"key=([a-zA-Z0-9]+)", user_input)
        if key_match:
            key = key_match.group(1)
        elif re.match(r"^[a-zA-Z0-9]+$", user_input):
            key = user_input
        else:
            print("خطا: کلید معتبری یافت نشد.")
            return

    session.headers.update({"User-Agent": "v2rayN/6.23"})
    base_url = f"{SITE_URL}/subscriptions/country"
    all_configs = set()

    print(f"\nدر حال جمع‌آوری و دیکود از {len(COUNTRY_CODES)} کشور به‌صورت همزمان...\n")

    countries_ok = 0
    countries_empty = 0
    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = [
            executor.submit(fetch_country_configs, country, base_url, key, session)
            for country in COUNTRY_CODES
        ]

        for future in as_completed(futures):
            country, configs = future.result()
            if configs:
                countries_ok += 1
                new_added = 0
                for cfg in configs:
                    if cfg not in all_configs:
                        all_configs.add(cfg)
                        new_added += 1
                print(f"[✓] {country.upper()}: {len(configs)} کانفیگ دریافت شد (+{new_added} جدید)")
            else:
                countries_empty += 1

    print(f"\n[خلاصه] {countries_ok} کشور کانفیگ دادند، {countries_empty} کشور خالی/ناموفق، مجموع یکتا: {len(all_configs)}")

    if not all_configs:
        print("\nهیچ کانفیگی دریافت نشد! مطمئن شوید اینترنت شما به دامنه سایت دسترسی دارد.")
        return

    desktop_path = get_desktop_path()
    output_path = os.path.join(desktop_path, "all_countries_v2nodes.txt")

    with open(output_path, "w", encoding="utf-8") as f:
        for cfg in sorted(all_configs):
            f.write(cfg + "\n")

    print("\n" + "=" * 45)
    print("عملیات با موفقیت انجام شد.")
    print(f"تعداد کل کانفیگ‌های یکتا: {len(all_configs)}")
    print(f"مسیر فایل خروجی: {output_path}")
    print("=" * 45)


if __name__ == "__main__":
    main()
