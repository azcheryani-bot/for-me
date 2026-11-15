"""پالایش کانفیگ‌ها بر اساس دسترسی‌پذیری سرور از داخل ایران، با Globalping.

چرا این فایل هست: تست پینگ معمولی پایپ‌لاین (ping_filter در relay_builder.py)
از روی رانر گیت‌هاب انجام می‌شود و فقط سالم‌بودن زنجیره را نشان می‌دهد؛
سروری که از گیت‌هاب در دسترس است ممکن است از داخل ایران پینگ نخورد.
اینجا سرور هر کانفیگ از چند پروب تهران (Globalping) پینگ می‌شود و فقط
کانفیگ‌هایی که دست‌کم از یک پروب تهران جواب می‌گیرند نگه داشته می‌شوند.

مراحل پالایش تهران در این مخزن (به ترتیب اجرا در یک اجرای ورک‌فلو —
v2nodes اول سهمیه می‌گیرد، بقیه با هرچه ماند):
  1. v2nodes_configs.py: خروجی v2nodes (stage="v2nodes"، همیشه ۱ پروب
     برای هر هاست) — چون فرایند جداگانه‌ای است، حافظه از راه فایل
     مشترک در فضای کاری ورک‌فلو به اشتراک گذاشته می‌شود.
  2. relay_builder.py: همهٔ کانفیگ‌های ترجمه‌شده، پیش از تست زنجیره
     (stage="all-configs") — تا کانفیگی که سرورش از تهران دیده نمی‌شود
     اصلاً وارد تست زنجیره نشود؛ با سهمیهٔ باقی‌مانده پس از v2nodes.
  3. relay_builder.py: رله‌های سالم زنجیره، پس از ping_filter
     (stage="post-chain") — همان فیلتر قبلی؛ هاست‌هایی که در مرحله‌های
     ۱ و ۲ بررسی شده‌اند دوباره تست نمی‌شوند (حافظهٔ درون‌اجرا، پایین).

بودجهٔ تست: با توکن حساب ثبت‌شده ۵۰۰ تست در ساعت است (بدون توکن ۲۵۰).
هر پروب یک تست حساب می‌شود. پیش از هر مرحله، هاست‌های یکتا شمرده
می‌شوند و اگر ۲ پروب برای هر هاست در بودجه جا نشود، خودکار به ۱ پروب
برای هر هاست کم می‌شود؛ اگر بودجه برای همهٔ هاست‌ها کافی نباشد،
همان‌قدر که می‌رسد با ۱ پروب تست می‌شود و بقیهٔ هاست‌ها «نامشخص»
می‌مانند و نگه داشته می‌شوند (تا سهمیهٔ باقی‌مانده هدر نرود)؛ اگر
بودجه صفر باشد، آن مرحله رد می‌شود (fail-open) و فهرست پالایش‌نشده
حفظ می‌شود. هاست‌هایی که نتیجهٔ قطعی (در دسترس / در دسترس نیست)
دارند، در حافظهٔ درون‌اجرا نگه داشته می‌شوند تا مرحله‌های بعدی همان
اجرا دوباره برایشان تست مصرف نکنند.

حافظهٔ درون‌اجرا: یک دیکشنری در حافظهٔ همین فرایند + یک فایل JSON در
فضای کاری (پیش‌فرض .globalping_host_cache.json). فایل فقط برای اشتراک
نتیجه بین دو فرایند relay_builder.py و run_v2nodes_workflow.py در یک
اجرای ورک‌فلو است؛ ورک‌فلو فقط valid_relays.txt و
all_countries_v2nodes.txt را کامیت می‌کند، پس این فایل کامیت نمی‌شود.
فقط نتیجه‌های قطعی ذخیره می‌شوند؛ هاست «نامشخص» (خطای API) ذخیره
نمی‌شود تا مرحلهٔ بعد بتواند دوباره امتحانش کند.

نکته‌ها:
- پینگ ICMP است، نه تست کامل کانفیگ؛ یعنی «سرور از تهران دیده می‌شود»،
  نه «کانفیگ از تهران حتماً کار می‌کند».
- اگر Globalping در دسترس نباشد یا سقف تست‌ها تمام شده باشد، تابع‌های
  پالایش مقدار None برمی‌گردانند و فراخواننده فهرست پالایش‌نشده را نگه
  می‌دارد (fail-open: اجرا متوقف نمی‌شود).
- اگر هیچ هاستی از تهران جواب نگرفت، احتمالاً مشکل از پروب‌هاست نه از
  همهٔ کانفیگ‌ها؛ در این حالت هم فهرست پالایش‌نشده برگردانده می‌شود.

متغیرهای محیطی (همه اختیاری):
  GLOBALPING_TOKEN       توکن API برای سقف بالاتر (بدون آن هم کار می‌کند)
  GLOBALPING_PROBES      تعداد پروب‌های تهران برای هر هاست (پیش‌فرض ۲)
  GLOBALPING_ENABLED     اگر "0" باشد، پالایش تهران انجام نمی‌شود
  GLOBALPING_CACHE_FILE  مسیر فایل حافظهٔ هاست (پیش‌فرض .globalping_host_cache.json)
"""

import base64
import json
import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

API_BASE = "https://api.globalping.io/v1"
TEHRAN_LOCATION = {"magic": "Tehran"}

PROBES_PER_HOST = int(os.environ.get("GLOBALPING_PROBES", "2"))
HOURLY_TEST_BUDGET = 500  # سقف تست با توکن حساب ثبت‌شده؛ بدون توکن، سقف واقعی از /limits خوانده می‌شود
PACKETS = 3
CREATE_TIMEOUT = 120          # ساخت measurement گاهی تا ~۸۰ ثانیه طول می‌کشد
POLL_TIMEOUT = 180
POLL_INTERVAL = 5
CREATE_WORKERS = 6
POLL_WORKERS = 6
CACHE_FILE = os.environ.get("GLOBALPING_CACHE_FILE", ".globalping_host_cache.json")

# حافظهٔ درون‌اجرا: host -> {"reachable": bool, "avg": float|None}؛ فقط نتیجهٔ قطعی.
_MEMORY_CACHE = {}
# خلاصهٔ آخرین اجرای tehran_filter، برای لاگ مرحله‌های فراخواننده.
LAST_RUN = {"probes_per_host": None, "unique_hosts": 0, "cached_hosts": 0, "tested_hosts": 0, "tests_used": 0}


def _headers():
    headers = {"Content-Type": "application/json"}
    token = os.environ.get("GLOBALPING_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _limits_remaining():
    """تعداد تست‌های باقی‌مانده در ساعت جاری؛ در صورت خطا None."""
    try:
        res = requests.get(f"{API_BASE}/limits", headers=_headers(), timeout=20)
        if res.status_code != 200:
            print(f"[Globalping] خواندن سقف تست‌ها ناموفق: HTTP {res.status_code}")
            return None
        return res.json()["rateLimit"]["measurements"]["create"]["remaining"]
    except Exception as e:
        print(f"[Globalping] خطا در خواندن سقف تست‌ها: {e}")
        return None


def _load_cache():
    """خواندن حافظهٔ فایلی هاست‌ها (اگر هست) در حافظهٔ درون‌فرایند."""
    if _MEMORY_CACHE:
        return
    try:
        if os.path.isfile(CACHE_FILE):
            with open(CACHE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for host, item in data.items():
                    if isinstance(item, dict) and item.get("reachable") in (True, False):
                        _MEMORY_CACHE[host] = {"reachable": item["reachable"], "avg": item.get("avg")}
                print(f"[Globalping] حافظهٔ هاست از {CACHE_FILE} خوانده شد: {len(_MEMORY_CACHE)} هاست")
    except Exception as e:
        print(f"[Globalping] خواندن حافظهٔ هاست ناموفق: {e}")


def _save_cache():
    """ذخیرهٔ نتیجه‌های قطعی در فایل حافظه، برای فرایند بعدی همان اجرا."""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_MEMORY_CACHE, f, ensure_ascii=False)
    except Exception as e:
        print(f"[Globalping] ذخیرهٔ حافظهٔ هاست ناموفق: {e}")


def _choose_probes_per_host(n_uncached, remaining, max_probes=None):
    """تعداد پروب برای هر هاست با توجه به بودجه: ۲ اگر جا شود، وگرنه ۱، وگرنه ۰."""
    if n_uncached <= 0:
        return 0
    want = PROBES_PER_HOST
    if max_probes is not None:
        want = min(want, max_probes)
    if want < 1:
        want = 1
    budget = remaining if remaining is not None else HOURLY_TEST_BUDGET
    if n_uncached * want <= budget:
        return want
    if n_uncached * 1 <= budget:
        print(f"[Globalping] بودجهٔ تست برای {want} پروب/هاست کافی نیست (لازم {n_uncached * want}، بودجه {budget})؛ با ۱ پروب برای هر هاست ادامه می‌دهم")
        return 1
    print(f"[Globalping] بودجهٔ تست حتی برای ۱ پروب/هاست کافی نیست (لازم {n_uncached}، بودجه {budget}) — پالایش تهران رد شد")
    return 0


def _create_measurement(target, probes=PROBES_PER_HOST):
    """ساخت یک measurement پینگ از تهران برای یک هاست؛ id یا None."""
    try:
        res = requests.post(
            f"{API_BASE}/measurements",
            headers=_headers(),
            json={
                "type": "ping",
                "target": target,
                "locations": [TEHRAN_LOCATION],
                "limit": probes,
                "measurementOptions": {"packets": PACKETS},
            },
            timeout=CREATE_TIMEOUT,
        )
        if res.status_code not in (200, 202):
            print(f"[Globalping] ساخت تست برای {target} ناموفق: HTTP {res.status_code} {res.text[:200]}")
            return None
        return res.json().get("id")
    except Exception as e:
        print(f"[Globalping] خطا در ساخت تست برای {target}: {e}")
        return None


def _poll_measurement(measurement_id):
    """خواندن نتیجه تا finished؛ دیکشنری نتیجه یا None."""
    deadline = time.time() + POLL_TIMEOUT
    while time.time() < deadline:
        try:
            res = requests.get(
                f"{API_BASE}/measurements/{measurement_id}",
                headers=_headers(),
                timeout=20,
            )
            if res.status_code != 200:
                print(f"[Globalping] خواندن نتیجه {measurement_id} ناموفق: HTTP {res.status_code}")
                return None
            data = res.json()
            if data.get("status") == "finished":
                return data
            if data.get("status") == "failed":
                print(f"[Globalping] تست {measurement_id} ناموفق شد")
                return None
        except Exception as e:
            print(f"[Globalping] خطا در خواندن نتیجه {measurement_id}: {e}")
            return None
        time.sleep(POLL_INTERVAL)
    print(f"[Globalping] نتیجه {measurement_id} در مهلت {POLL_TIMEOUT} ثانیه آماده نشد")
    return None


def _host_reachable(data):
    """آیا دست‌کم یک پروب تهران به هاست جواب داده؟ (avg هم برگردانده می‌شود)"""
    best_avg = None
    for item in data.get("results", []):
        result = item.get("result") or {}
        if result.get("status") != "finished":
            continue
        stats = result.get("stats") or {}
        rcv = stats.get("rcv")
        loss = stats.get("loss")
        if (rcv is not None and rcv > 0) or (loss is not None and loss < 100):
            avg = stats.get("avg")
            if avg is not None and (best_avg is None or avg < best_avg):
                best_avg = avg
            return True, best_avg
    return False, None


def probe_host(target, probes=None):
    """پینگ یک هاست از تهران؛ (reachable, avg_ms یا None)."""
    measurement_id = _create_measurement(target, probes or PROBES_PER_HOST)
    if not measurement_id:
        return None, None
    data = _poll_measurement(measurement_id)
    if not data:
        return None, None
    return _host_reachable(data)


def tehran_filter(hosts, *, stage="tehran", max_probes=None):
    """پالایش فهرست هاست‌ها بر اساس دسترسی از تهران.

    برمی‌گرداند: dict با کلید هاست و مقدار {"reachable": bool, "avg": float|None}،
    یا None اگر Globalping در دسترس نباشد / سقف تست‌ها کافی نباشد.
    هاست‌هایی که در همین اجرا قبلاً بررسی شده‌اند (حافظهٔ درون‌فرایند یا
    فایل حافظه) دوباره تست نمی‌شوند و در LAST_RUN شمرده می‌شوند.
    """
    if os.environ.get("GLOBALPING_ENABLED", "1") == "0":
        print("[Globalping] با GLOBALPING_ENABLED=0 غیرفعال است")
        return None

    _load_cache()
    unique_hosts = []
    for host in hosts:
        host = (host or "").strip()
        if host and host not in unique_hosts:
            unique_hosts.append(host)
    if not unique_hosts:
        LAST_RUN.update({"probes_per_host": 0, "unique_hosts": 0, "cached_hosts": 0, "tested_hosts": 0, "tests_used": 0})
        return {}

    cached = {h: _MEMORY_CACHE[h] for h in unique_hosts if h in _MEMORY_CACHE}
    uncached = [h for h in unique_hosts if h not in _MEMORY_CACHE]
    probes = 0
    to_test = uncached  # هاست‌هایی که در این مرحله واقعاً تست می‌شوند
    if uncached:
        remaining = _limits_remaining()
        probes = _choose_probes_per_host(len(uncached), remaining, max_probes=max_probes)
        if probes == 0:
            budget = remaining if remaining is not None else HOURLY_TEST_BUDGET
            if budget and budget > 0:
                # بودجه برای همهٔ هاست‌ها کافی نیست، ولی برای بخشی از آن‌ها
                # هست: به‌جای رد کامل مرحله، همان‌قدر که بودجه می‌رسد با
                # ۱ پروب تست می‌شود و بقیهٔ هاست‌ها «نامشخص» می‌مانند و نگه
                # داشته می‌شوند — تا سهمیهٔ باقی‌مانده هدر نرود.
                probes = 1
                to_test = uncached[:budget]
                print(f"[Globalping][{stage}] بودجهٔ تست ({budget}) برای همهٔ {len(uncached)} هاست کافی نیست؛ {len(to_test)} هاست با ۱ پروب تست می‌شوند و {len(uncached) - len(to_test)} هاست نامشخص می‌مانند (نگه داشته می‌شوند)")
            else:
                print(f"[Globalping][{stage}] سقف تست‌ها کافی نیست — پالایش تهران رد شد (fail-open)")
                LAST_RUN.update({"probes_per_host": 0, "unique_hosts": len(unique_hosts), "cached_hosts": len(cached), "tested_hosts": 0, "tests_used": 0})
                return None
    needed = len(to_test) * probes
    partial_note = f"؛ {len(uncached) - len(to_test)} هاست تست نمی‌شوند (بودجه نرسید)" if len(to_test) < len(uncached) else ""
    print(f"[Globalping][{stage}] پینگ {len(unique_hosts)} هاست یکتا از تهران ({probes} پروب برای هر هاست، {needed} تست تازه؛ {len(cached)} هاست از حافظهٔ همین اجرا{partial_note})")

    results = dict(cached)
    if to_test:
        with ThreadPoolExecutor(max_workers=CREATE_WORKERS) as executor:
            ids = dict(zip(to_test, executor.map(lambda h: _create_measurement(h, probes), to_test)))
        todo = {h: mid for h, mid in ids.items() if mid}
        failed_create = [h for h, mid in ids.items() if not mid]
        for host in failed_create:
            # تست ساخته نشد (مثلاً هاست نامعتبر/خصوصی یا خطای موقت API) — وضعیت
            # «نامشخص» می‌ماند تا فراخواننده آن هاست را نگه دارد، نه حذف کند.
            print(f"[Globalping] ⏭️ {host}: تست ساخته نشد (وضعیت نامشخص)")
            results[host] = {"reachable": None, "avg": None}
        with ThreadPoolExecutor(max_workers=POLL_WORKERS) as executor:
            datas = dict(zip(todo.keys(), executor.map(_poll_measurement, todo.values())))
        for host, data in datas.items():
            if not data:
                print(f"[Globalping] ⏭️ {host}: نتیجه‌ای نرسید")
                results[host] = {"reachable": None, "avg": None}
                continue
            reachable, avg = _host_reachable(data)
            results[host] = {"reachable": reachable, "avg": avg}
            if reachable:
                print(f"[Globalping] 🟢 {host}: از تهران در دسترس است (avg {avg} ms)")
                _MEMORY_CACHE[host] = {"reachable": True, "avg": avg}
            else:
                print(f"[Globalping] 🔴 {host}: از تهران جواب نداد")
                _MEMORY_CACHE[host] = {"reachable": False, "avg": avg}
        _save_cache()
    # هاست‌هایی که به‌علت کمبود بودجه تست نشدند، «نامشخص» می‌مانند تا
    # فراخواننده آن‌ها را نگه دارد، نه حذف کند.
    for host in uncached:
        if host not in results:
            results[host] = {"reachable": None, "avg": None}
    LAST_RUN.update({"probes_per_host": probes, "unique_hosts": len(unique_hosts), "cached_hosts": len(cached), "tested_hosts": len(to_test), "tests_used": needed})
    return results


def filter_relay_nodes(nodes, *, stage="relays", max_probes=None):
    """پالایش نودهای سینگ‌باکس بر اساس دسترسی سرور از تهران.

    برمی‌گرداند (kept_nodes, stats)؛ اگر Globalping در دسترس نباشد،
    kept_nodes برابر None است و فراخواننده باید فهرست اصلی را نگه دارد.
    اگر هیچ هاستی از تهران جواب نگرفت، فهرست اصلی برگردانده می‌شود
    (fail-open) و stats علت را می‌گوید.
    """
    total = len(nodes)
    servers = [n.get("server") for n in nodes if n.get("server")]
    results = tehran_filter(servers, stage=stage, max_probes=max_probes)
    if results is None:
        print(f"[Globalping][{stage}] کانفیگ‌ها: {total}، هاست یکتا: {len(set(servers))}، پروب/هاست: -، نگه‌داشته‌شده: {total}، حذف‌شده: 0 (پالایش رد شد، fail-open)")
        return None, {"skipped": True, "reason": "globalping-unavailable", "total": total, "unique_hosts": len(set(servers)), "kept": total, "dropped": 0}
    reachable_hosts = {h for h, r in results.items() if r.get("reachable")}
    unknown_hosts = {h for h, r in results.items() if r.get("reachable") is None}
    # فقط هاست‌هایی حذف می‌شوند که ثابت شده از تهران جواب نمی‌دهند؛
    # هاست‌های «نامشخص» (خطای API) نگه داشته می‌شوند.
    kept = [n for n in nodes if n.get("server") in reachable_hosts or n.get("server") in unknown_hosts]
    dropped = len(nodes) - len(kept)
    stats = {
        "skipped": False,
        "total": total,
        "unique_hosts": len(results),
        "probes_per_host": LAST_RUN.get("probes_per_host"),
        "tested_hosts": len(results),
        "reachable_hosts": len(reachable_hosts),
        "unknown_hosts": len(unknown_hosts),
        "dropped_hosts": dropped,
        "kept": len(kept),
        "dropped": dropped,
    }
    print(f"[Globalping][{stage}] کانفیگ‌ها: {total}، هاست یکتا: {len(results)}، پروب/هاست: {LAST_RUN.get('probes_per_host')}، نگه‌داشته‌شده: {len(kept)}، حذف‌شده: {dropped}")
    if not reachable_hosts:
        print("[Globalping] ⚠️ هیچ سروری از تهران جواب نگرفت — احتمال مشکل پروب‌هاست؛ فهرست پالایش‌نشده حفظ شد")
        stats["reason"] = "zero-reachable-fallback"
        return list(nodes), stats
    print(f"[Globalping] از تهران: {len(kept)} از {len(nodes)} کانفیگ ماند ({dropped} سرور از تهران جواب نداد)")
    return kept, stats


def extract_host_from_link(link):
    """استخراج هاست سرور از یک لینک کانفیگ (vmess/vless/trojan/ss/ssr/hy2/tuic)؛ None اگر نشد."""
    link = (link or "").strip()
    if not link:
        return None
    try:
        if link.startswith("vmess://"):
            b64_part = link[8:].split("#")[0].strip()
            b64_part += "=" * (-len(b64_part) % 4)
            data = json.loads(base64.b64decode(b64_part).decode("utf-8", errors="ignore"))
            return (data.get("add") or "").strip() or None
        if link.startswith("ssr://"):
            b64_part = link[6:].split("#")[0].strip()
            b64_part += "=" * (-len(b64_part) % 4)
            decoded = base64.b64decode(b64_part).decode("utf-8", errors="ignore")
            parts = decoded.split(":")
            if len(parts) >= 2:
                return parts[0].strip() or None
            return None
        if link.startswith("ss://"):
            raw = link[5:].split("#")[0]
            if "@" in raw:
                host_port = raw.rsplit("@", 1)[1]
                return urlparse(f"//{host_port}").hostname
            padded = raw + "=" * (-len(raw) % 4)
            decoded = base64.b64decode(padded).decode("utf-8", errors="ignore")
            if "@" in decoded:
                host_port = decoded.rsplit("@", 1)[1]
                return urlparse(f"//{host_port}").hostname
            return None
        return urlparse(link).hostname
    except Exception:
        return None


def filter_config_links(links, *, stage="v2nodes", max_probes=1):
    """پالایش لینک‌های خام کانفیگ بر اساس دسترسی هاست از تهران.

    برمی‌گرداند (kept_links, stats)؛ اگر بودجهٔ تست کافی نباشد یا
    Globalping در دسترس نباشد، kept_links برابر فهرست اصلی است و
    stats["skipped"] برابر True است (fail-open).
    لینک‌هایی که هاستشان استخراج نمی‌شود نگه داشته می‌شوند.
    """
    total = len(links)
    hosts = [extract_host_from_link(link) for link in links]
    host_list = [h for h in hosts if h]
    results = tehran_filter(host_list, stage=stage, max_probes=max_probes)
    if results is None:
        print(f"[Globalping][{stage}] کانفیگ‌ها: {total}، هاست یکتا: {len(set(host_list))}، پروب/هاست: -، نگه‌داشته‌شده: {total}، حذف‌شده: 0 (پالایش رد شد، fail-open)")
        return list(links), {"skipped": True, "reason": "globalping-unavailable", "total": total, "unique_hosts": len(set(host_list)), "kept": total, "dropped": 0}
    reachable_hosts = {h for h, r in results.items() if r.get("reachable")}
    unknown_hosts = {h for h, r in results.items() if r.get("reachable") is None}
    kept = [link for link, host in zip(links, hosts) if host is None or host in reachable_hosts or host in unknown_hosts]
    dropped = total - len(kept)
    stats = {
        "skipped": False,
        "total": total,
        "unique_hosts": len(results),
        "probes_per_host": LAST_RUN.get("probes_per_host"),
        "reachable_hosts": len(reachable_hosts),
        "unknown_hosts": len(unknown_hosts),
        "kept": len(kept),
        "dropped": dropped,
    }
    print(f"[Globalping][{stage}] کانفیگ‌ها: {total}، هاست یکتا: {len(results)}، پروب/هاست: {LAST_RUN.get('probes_per_host')}، نگه‌داشته‌شده: {len(kept)}، حذف‌شده: {dropped}")
    if not reachable_hosts:
        print("[Globalping] ⚠️ هیچ سروری از تهران جواب نگرفت — احتمال مشکل پروب‌هاست؛ فهرست پالایش‌نشده حفظ شد")
        stats["reason"] = "zero-reachable-fallback"
        return list(links), stats
    return kept, stats
