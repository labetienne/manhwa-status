#!/usr/bin/env python3
"""Manhwa Status — serveur local : sert la page et vérifie la disponibilité des sites.
Lancer :  python3 server.py   puis ouvrir http://localhost:8765 (ou http://<IP-du-Mac>:8765 sur le téléphone)."""
import json, ssl, socket, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent
PORT = 8765
TIMEOUT = 8
CACHE_TTL = 60  # secondes
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
_cache = {"t": 0, "data": None}
SEIZED_MARKERS = ("coda-cj.jp", "seized", "ace-anti-piracy", "alliance4creativity")
# Pages de blocage des filtres réseau (Wi-Fi d'école, d'entreprise, contrôle parental…)
BLOCK_MARKERS = ("fortiguard", "web filter violation", "web page blocked", "access blocked",
                 "sophos", "zscaler", "blocked by your network", "cisco umbrella", "opendns")


_NOVERIFY = ssl.create_default_context()
_NOVERIFY.check_hostname = False
_NOVERIFY.verify_mode = ssl.CERT_NONE


def check(site, verify=True):
    url = site["url"]
    t0 = time.time()
    res = {**site, "status": "down", "code": None, "ms": None, "detail": "", "final_url": url}
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context() if verify else _NOVERIFY) as r:
            res["code"] = r.status
            res["final_url"] = r.geturl()
            res["status"] = "up"
    except urllib.error.HTTPError as e:
        res["code"] = e.code
        server = (e.headers.get("server") or "").lower()
        try:
            body = e.read(80000).decode("utf-8", "ignore").lower()
        except Exception:  # noqa
            body = ""
        if any(k in body for k in BLOCK_MARKERS):
            res["status"] = "blocked"
            res["detail"] = "Filtre réseau"
        elif e.code in (403, 429, 503) and ("cloudflare" in server or e.headers.get("cf-ray")):
            # Site joignable mais protégé anti-bot : il fonctionne dans un navigateur.
            res["status"] = "up"
            res["detail"] = "Protégé (Cloudflare)"
        elif e.code < 500:
            res["status"] = "up"
            res["detail"] = f"HTTP {e.code}"
        else:
            res["detail"] = f"Erreur serveur {e.code}"
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, socket.gaierror):
            res["detail"] = "Domaine introuvable"
        elif isinstance(reason, (socket.timeout, TimeoutError)):
            res["detail"] = "Délai dépassé"
        elif isinstance(reason, ssl.SSLCertVerificationError) and verify:
            # Proxy/antivirus local ou certificat atypique : on teste la disponibilité sans vérifier le certificat.
            return check(site, verify=False)
        elif isinstance(reason, ssl.SSLError):
            res["detail"] = "Erreur SSL"
        else:
            res["detail"] = str(reason)[:60]
    except (socket.timeout, TimeoutError):
        res["detail"] = "Délai dépassé"
    except Exception as e:  # noqa
        res["detail"] = str(e)[:60]
    res["ms"] = int((time.time() - t0) * 1000)
    if res["status"] == "up" and any(k in urlparse(res["final_url"]).netloc for k in SEIZED_MARKERS):
        res["status"] = "down"
        res["detail"] = "Saisi (anti-piratage)"
        return res
    if res["status"] == "up" and urlparse(res["final_url"]).netloc != urlparse(url).netloc:
        res["detail"] = (res["detail"] + " · " if res["detail"] else "") + "Redirige vers " + urlparse(res["final_url"]).netloc
    return res


def check_all(force=False):
    if not force and _cache["data"] and time.time() - _cache["t"] < CACHE_TTL:
        return _cache["data"]
    sites = json.loads((ROOT / "sites.json").read_text(encoding="utf-8"))
    with ThreadPoolExecutor(max_workers=16) as ex:
        results = list(ex.map(check, sites))
    data = {"checked_at": int(time.time()), "sites": results}
    _cache.update(t=time.time(), data=data)
    return data


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT / "public"), **kw)

    def do_GET(self):
        if self.path.startswith("/api/status"):
            body = json.dumps(check_all(force="force=1" in self.path), ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    import subprocess

    class DualStackServer(ThreadingHTTPServer):
        address_family = socket.AF_INET6

        def server_bind(self):
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)  # IPv4 + IPv6
            super().server_bind()

    try:
        httpd = DualStackServer(("::", PORT), Handler)
    except OSError:
        print(f"Le serveur tourne déjà → http://localhost:{PORT}")
        raise SystemExit(0)
    print(f"Manhwa Status → http://localhost:{PORT}")
    ip = subprocess.run(["ipconfig", "getifaddr", "en0"], capture_output=True, text=True).stdout.strip()
    if ip and not ip.startswith("192.0.0."):
        print(f"Sur le téléphone (même réseau) → http://{ip}:{PORT}")
    else:  # réseau IPv6 seulement (ex. partage de connexion)
        out = subprocess.run(["ifconfig", "en0"], capture_output=True, text=True).stdout
        v6 = [l.split()[1] for l in out.splitlines()
              if "inet6" in l and "autoconf" in l and "temporary" not in l and not l.split()[1].startswith("fe80")]
        if v6:
            print(f"Sur le téléphone (même réseau) → http://[{v6[0]}]:{PORT}")
    httpd.serve_forever()
