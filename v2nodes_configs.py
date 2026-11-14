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

def extract_configs_from_text(text):
    """استخراج لینک‌های کانفیگ از متن"""
    if not text:
        return []
    links = []
    for line in text.splitlines():
        for part in re.split(r'[\s,;]+', line.strip()):
            part = part.strip()
            if not part or not any(part.startswith(proto) for proto in PROTOCOLS):
                continue
            parsed = urlparse(part)
            if not parsed.scheme or not parsed.netloc:
                continue
            if '#' in part:
                part = part.split('#')[0]
            if part not in links:
                links.append(part)
    return links

def extract_configs_from_bytes(content):
    """استخراج لینک‌های کانفیگ از محتوای باینری"""
    try:
        decoded = base64.b64decode(content)
        text = decoded.decode('utf-8', errors='ignore')
        if any(proto in text for proto in PROTOCOLS):
            return extract_configs_from_text(text)
    except Exception:
        pass
    try:
        text = content.decode('utf-8', errors='ignore')
        return extract_configs_from_text(text)
    except Exception:
        return []

def fetch_page(url, timeout=20, max_retries=2):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.v2nodes.com/"
    }
    for attempt in range(max_retries + 1):
        try:
            res = requests.get(url, headers=headers, timeout=timeout)
            if res.status_code == 200:
                return res
            print(f"HTTP {res.status_code} برای {url}")
            if attempt == max_retries:
                return None
        except Exception as e:
            if attempt == max_retries:
                print(f"خطا در دریافت {url}: {e}")
                return None
            time.sleep(1)
    return None

def get_dynamic_key(session):
    """دریافت کلید پویا از سایت"""
    for attempt in range(KEY_FETCH_ATTEMPTS):
        try:
            res = fetch_page(SITE_URL, timeout=KEY_FETCH_TIMEOUT)
            if res is None:
                print(f"تلاش {attempt+1}: دریافت صفحه اصلی ناموفق")
                continue
            match = re.search(r'/__[a-zA-Z0-9]+/', res.text)
            if match:
                key = match.group(0)
                print(f"کلید پویا دریافت شد: {key}")
                return key
            print(f"تلاش {attempt+1}: کلید پویا در صفحه یافت نشد")
        except Exception as e:
            print(f"تلاش {attempt+1}: خطا {e}")
        time.sleep(1)
    print("هشدار: کلید پویا یافت نشد، ادامه بدون کلید")
    return ""

def fetch_configs(country_code, key, session):
    """دریافت کانفیگ‌های یک کشور"""
    if key:
        url = f"{SITE_URL}{key}{country_code}"
    else:
        url = f"{SITE_URL}/{country_code}"
    res = fetch_page(url, timeout=20)
    if res is None:
        print(f"دریافت کانفیگ {country_code} ناموفق")
        return []
    try:
        links = extract_configs_from_bytes(res.content)
    except Exception as e:
        print(f"خطا در استخراج {country_code}: {e}")
        return []
    return links

def main():
    print("دریافت کانفیگ‌ها از v2nodes.com")
    print(f"تعداد کشورها: {len(COUNTRY_CODES)}")
    session = requests.Session()
    key = get_dynamic_key(session)
    all_configs = set()
    try:
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = {executor.submit(fetch_configs, code, key, session): code for code in COUNTRY_CODES}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    links = future.result()
                    all_configs.update(links)
                    if links:
                        print(f"{code}: {len(links)} کانفیگ")
                except Exception as e:
                    print(f"خطا در پردازش {code}: {e}")
    finally:
        session.close()

    # خلاصه نتایج
    print(f"تعداد کل کانفیگ‌های یکتا (بدون تکرار): {len(all_configs)}")

    # پالایش تهران با Globalping (۱ پروب برای هر هاست، fail-open):
    # فقط کانفیگ‌هایی که سرورشان از تهران دیده می‌شود در خروجی می‌مانند.
    # این مرحله در فرایند جداگانهٔ run_v2nodes_workflow.py اجرا می‌شود، پس
    # نتیجهٔ هاست‌هایی که relay_builder.py در همین اجرای ورک‌فلو بررسی کرده
    # از فایل حافظهٔ مشترک (.globalping_host_cache.json) خوانده می‌شود و
    # برایشان تست تازه مصرف نمی‌شود. اگر بودجهٔ ۵۰۰ تست/ساعت برای همهٔ
    # هاست‌های یکتا کافی نباشد، این پالایش رد می‌شود و فهرست پالایش‌نشده
    # حفظ می‌شود (fail-open) — هرگز اجرا را خراب نمی‌کند.
    if not all_configs:
        print("[Globalping][v2nodes] کانفیگ‌ها: 0 — پالایش تهران انجام نشد (ورودی خالی؛ v2nodes.com در این اجرا کانفیگی نداد)")
    else:
        try:
            import globalping_filter
            v2nodes_links, gp_v2_stats = globalping_filter.filter_config_links(
                sorted(all_configs), stage="v2nodes", max_probes=1
            )
            all_configs = set(v2nodes_links)
            if gp_v2_stats.get("skipped"):
                print("[Globalping][v2nodes] پالایش تهران انجام نشد؛ فهرست پالایش‌نشده حفظ شد (fail-open)")
            elif gp_v2_stats.get("reason") == "zero-reachable-fallback":
                print("[Globalping][v2nodes] هیچ سروری از تهران جواب نگرفت؛ فهرست پالایش‌نشده حفظ شد (fail-open)")
            else:
                print(f"[Globalping][v2nodes] {gp_v2_stats['kept']} از {gp_v2_stats['total']} کانفیگ پس از پالایش تهران ماند")
        except Exception as e:
            print(f"[Globalping][v2nodes] پالایش تهران انجام نشد: {e} — فهرست پالایش‌نشده حفظ شد (fail-open)")

    # خروجی برای خروجی به فایل متنی
    try:
        from pathlib import Path
        desktop = Path(os.path.expanduser("~/Desktop"))
        output_path = desktop / "all_countries_v2nodes.txt"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for link in sorted(all_configs):
                f.write(f"{link}\n")
        print(f"کانفیگ‌ها در {output_path} ذخیره شدند")
    except Exception as e:
        print(f"خطا در ذخیره فایل: {e}")
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        fallback_path = os.path.join(desktop, "all_countries_v2nodes.txt")
        os.makedirs(desktop, exist_ok=True)
        with open(fallback_path, "w", encoding="utf-8") as f:
            for link in sorted(all_configs):
                f.write(f"{link}\n")
        print(f"کانفیگ‌ها در {fallback_path} ذخیره شدند")

if __name__ == "__main__":
    main()
