"""پالایش کانفیگ‌ها بر اساس دسترسی‌پذیری سرور از داخل ایران، با Globalping.

چرا این فایل هست: تست پینگ معمولی پایپ‌لاین (ping_filter در relay_builder.py)
از روی رانر گیت‌هاب انجام می‌شود و فقط سالم‌بودن زنجیره را نشان می‌دهد؛
سروری که از گیت‌هاب در دسترس است ممکن است از داخل ایران پینگ نخورد.
اینجا سرور هر کانفیگ از چند پروب تهران (Globalping) پینگ می‌شود و فقط
کانفیگ‌هایی که دست‌کم از یک پروب تهران جواب می‌گیرند نگه داشته می‌شوند.

محدودیت API رایگان: بدون توکن ۲۵۰ تست در ساعت برای هر IP؛ با توکن رایگان
(ساخت حساب با گیت‌هاب) ۵۰۰ تست در ساعت. هر پروب یک تست حساب می‌شود، پس
به‌ازای هر هاست PROBES تست مصرف می‌شود. فهرست رله معمولاً ~۲۰ کانفیگ است،
پس مصرف هر اجرا حدود ۴۰ تست است و خیلی زیر سقف می‌ماند.

نکته‌ها:
- پینگ ICMP است، نه تست کامل کانفیگ؛ یعنی «سرور از تهران دیده می‌شود»،
  نه «کانفیگ از تهران حتماً کار می‌کند».
- اگر Globalping در دسترس نباشد یا سقف تست‌ها تمام شده باشد، تابع
  filter_relay_nodes مقدار None برمی‌گرداند و فراخواننده فهرست
  پالایش‌نشده را نگه می‌دارد (fail-open: اجرا متوقف نمی‌شود).
- اگر هیچ هاستی از تهران جواب نگرفت، احتمالاً مشکل از پروب‌هاست نه از
  همهٔ کانفیگ‌ها؛ در این حالت هم فهرست پالایش‌نشده برگردانده می‌شود.

متغیرهای محیطی (همه اختیاری):
  GLOBALPING_TOKEN    توکن API برای سقف بالاتر (بدون آن هم کار می‌کند)
  GLOBALPING_PROBES   تعداد پروب‌های تهران برای هر هاست (پیش‌فرض ۲)
  GLOBALPING_ENABLED  اگر "0" باشد، پالایش تهران انجام نمی‌شود
"""

import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor

API_BASE = "https://api.globalping.io/v1"
TEHRAN_LOCATION = {"magic": "Tehran"}

PROBES_PER_HOST = int(os.environ.get("GLOBALPING_PROBES", "2"))
PACKETS = 3
CREATE_TIMEOUT = 120          # ساخت measurement گاهی تا ~۸۰ ثانیه طول می‌کشد
POLL_TIMEOUT = 180
POLL_INTERVAL = 5
CREATE_WORKERS = 6
POLL_WORKERS = 6


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


def _create_measurement(target):
    """ساخت یک measurement پینگ از تهران برای یک هاست؛ id یا None."""
    try:
        res = requests.post(
            f"{API_BASE}/measurements",
            headers=_headers(),
            json={
                "type": "ping",
                "target": target,
                "locations": [TEHRAN_LOCATION],
                "limit": PROBES_PER_HOST,
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


def probe_host(target):
    """پینگ یک هاست از تهران؛ (reachable, avg_ms یا None)."""
    measurement_id = _create_measurement(target)
    if not measurement_id:
        return None, None
    data = _poll_measurement(measurement_id)
    if not data:
        return None, None
    return _host_reachable(data)


def tehran_filter(hosts):
    """پالایش فهرست هاست‌ها بر اساس دسترسی از تهران.

    برمی‌گرداند: dict با کلید هاست و مقدار {"reachable": bool, "avg": float|None}،
    یا None اگر Globalping در دسترس نباشد / سقف تست‌ها کافی نباشد.
    """
    if os.environ.get("GLOBALPING_ENABLED", "1") == "0":
        print("[Globalping] با GLOBALPING_ENABLED=0 غیرفعال است")
        return None

    unique_hosts = []
    for host in hosts:
        host = (host or "").strip()
        if host and host not in unique_hosts:
            unique_hosts.append(host)
    if not unique_hosts:
        return {}

    needed = len(unique_hosts) * PROBES_PER_HOST
    remaining = _limits_remaining()
    if remaining is not None and remaining < needed:
        print(f"[Globalping] سقف تست‌ها کافی نیست: لازم {needed}، باقی‌مانده {remaining} — پالایش تهران رد شد")
        return None
    print(f"[Globalping] پینگ {len(unique_hosts)} هاست یکتا از تهران ({PROBES_PER_HOST} پروب برای هر هاست، {needed} تست)")

    results = {}
    with ThreadPoolExecutor(max_workers=CREATE_WORKERS) as executor:
        # ساخت همهٔ تست‌ها اول (ساخت هر تست کند است)، بعد خواندن نتیجه‌ها
        ids = dict(zip(unique_hosts, executor.map(_create_measurement, unique_hosts)))
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
        else:
            print(f"[Globalping] 🔴 {host}: از تهران جواب نداد")
    return results


def filter_relay_nodes(nodes):
    """پالایش نودهای سینگ‌باکس بر اساس دسترسی سرور از تهران.

    برمی‌گرداند (kept_nodes, stats)؛ اگر Globalping در دسترس نباشد،
    kept_nodes برابر None است و فراخواننده باید فهرست اصلی را نگه دارد.
    اگر هیچ هاستی از تهران جواب نگرفت، فهرست اصلی برگردانده می‌شود
    (fail-open) و stats علت را می‌گوید.
    """
    servers = [n.get("server") for n in nodes if n.get("server")]
    results = tehran_filter(servers)
    if results is None:
        return None, {"skipped": True, "reason": "globalping-unavailable"}
    reachable_hosts = {h for h, r in results.items() if r.get("reachable")}
    unknown_hosts = {h for h, r in results.items() if r.get("reachable") is None}
    # فقط هاست‌هایی حذف می‌شوند که ثابت شده از تهران جواب نمی‌دهند؛
    # هاست‌های «نامشخص» (خطای API) نگه داشته می‌شوند.
    kept = [n for n in nodes if n.get("server") in reachable_hosts or n.get("server") in unknown_hosts]
    dropped = len(nodes) - len(kept)
    stats = {
        "skipped": False,
        "tested_hosts": len(results),
        "reachable_hosts": len(reachable_hosts),
        "unknown_hosts": len(unknown_hosts),
        "dropped_hosts": dropped,
        "kept": len(kept),
    }
    if not reachable_hosts:
        print("[Globalping] ⚠️ هیچ سروری از تهران جواب نگرفت — احتمال مشکل پروب‌هاست؛ فهرست پالایش‌نشده حفظ شد")
        stats["reason"] = "zero-reachable-fallback"
        return list(nodes), stats
    print(f"[Globalping] از تهران: {len(kept)} از {len(nodes)} کانفیگ ماند ({dropped} سرور از تهران جواب نداد)")
    return kept, stats
