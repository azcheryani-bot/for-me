import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request


def parse_vless(link):
    parsed = urllib.parse.urlparse(link.strip())
    q = dict(urllib.parse.parse_qsl(parsed.query))
    ob = {
        "tag": "front-proxy",
        "type": "vless",
        "server": parsed.hostname,
        "server_port": int(parsed.port or 443),
        "uuid": parsed.username,
    }
    if q.get("security", "").lower() == "tls":
        ob["tls"] = {
            "enabled": True,
            "server_name": q.get("sni") or parsed.hostname,
            "insecure": q.get("insecure", "0") in ("1", "true"),
        }
    if q.get("packetEncoding"):
        ob["packet_encoding"] = q["packetEncoding"]
    return ob


def main():
    link = os.environ.get("FRONT_PROXY_VLESS", "")
    if not link:
        print("FRONT_PROXY_VLESS secret is empty or missing")
        sys.exit(2)
    front = parse_vless(link)
    print("front proxy:", front["server"], front["server_port"], "tls sni:", front.get("tls", {}).get("server_name"))
    cfg = {
        "log": {"level": "info"},
        "inbounds": [
            {"type": "mixed", "tag": "mixed-in", "listen": "127.0.0.1", "listen_port": 18080}
        ],
        "outbounds": [
            front,
            {"type": "direct", "tag": "direct"},
            {"type": "block", "tag": "block"},
        ],
        "route": {"rules": [{"protocol": "dns", "outbound": "direct"}]},
    }
    with open("front_proxy_test.json", "w", encoding="utf-8") as f:
        json.dump(cfg, f)
    r = subprocess.run(["sing-box", "check", "-c", "front_proxy_test.json"], capture_output=True, text=True)
    print("sing-box check rc:", r.returncode)
    print(r.stdout)
    print(r.stderr)
    if r.returncode != 0:
        sys.exit(3)
    proc = subprocess.Popen(["sing-box", "run", "-c", "front_proxy_test.json"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    time.sleep(2)
    ok = False
    try:
        proxy = urllib.request.ProxyHandler({"http": "http://127.0.0.1:18080", "https": "http://127.0.0.1:18080"})
        opener = urllib.request.build_opener(proxy)
        req = urllib.request.Request("http://cp.cloudflare.com/generate_204", headers={"User-Agent": "curl"})
        with opener.open(req, timeout=15) as resp:
            print("generate_204 status:", resp.status)
            ok = resp.status in (200, 204)
    except Exception as e:
        print("request through front proxy FAILED:", repr(e))
    finally:
        proc.terminate()
        try:
            out, _ = proc.communicate(timeout=5)
            print("sing-box log tail:", out[-2000:] if out else "")
        except Exception:
            proc.kill()
    print("RESULT:", "FRONT_PROXY_OK" if ok else "FRONT_PROXY_FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
