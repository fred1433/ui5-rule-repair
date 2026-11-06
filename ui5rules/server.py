"""Local copy of the SAP OpenUI5 Shopping Cart demo, with named variants.

URL layout:  http://127.0.0.1:<port>/<variant>/1.154.0/test-resources/sap/m/demokit/cart/webapp/index.html

* Every file comes from ``copy/sdk/`` (a byte-for-byte cache of https://sdk.openui5.org,
  version 1.154.0, Apache-2.0).  A file missing from the cache is a 404, unless the server
  was started with ``fetch_missing=True`` (used once, to fill the cache; never in tests).
* A variant other than ``base`` may override app files from ``copy/variants/<variant>/``,
  paths relative to the ``webapp/`` folder.  These overrides are our modifications and are
  listed in ``copy/variants/README.md``.
* ``Component-preload.js`` of the app is never served, in any variant, so that UI5 loads the
  individual view files and an override is always the file actually used.
"""
from __future__ import annotations

import mimetypes
import threading
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SDK_CACHE = ROOT / "copy" / "sdk"
VARIANTS = ROOT / "copy" / "variants"
UI5_VERSION = "1.154.0"
APP_PREFIX = f"{UI5_VERSION}/test-resources/sap/m/demokit/cart/webapp/"
UPSTREAM = "https://sdk.openui5.org/"


def variant_names() -> list[str]:
    names = ["base"]
    if VARIANTS.exists():
        names += sorted(p.name for p in VARIANTS.iterdir() if p.is_dir())
    return names


def app_url(base: str, variant: str = "base") -> str:
    return f"{base}/{variant}/{APP_PREFIX}index.html"


class _Handler(SimpleHTTPRequestHandler):
    fetch_missing = False
    lock = threading.Lock()

    def log_message(self, *args):  # quiet
        pass

    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0].split("#", 1)[0].lstrip("/")
        variant, _, rest = path.partition("/")
        if variant not in variant_names() or ".." in rest:
            return self._send(404, b"unknown variant", "text/plain")
        if rest == APP_PREFIX + "Component-preload.js":
            return self._send(404, b"preload disabled", "text/plain")
        body = None
        if variant != "base" and rest.startswith(APP_PREFIX):
            override = VARIANTS / variant / rest[len(APP_PREFIX):]
            if override.is_file():
                body = override.read_bytes()
        if body is None:
            cached = SDK_CACHE / rest
            if cached.is_file():
                body = cached.read_bytes()
            elif self.fetch_missing:
                body = self._fetch(rest, cached)
        if body is None:
            return self._send(404, b"not in local copy", "text/plain")
        ctype = mimetypes.guess_type(rest)[0] or "application/octet-stream"
        if rest.endswith((".properties", ".xml", ".js", ".json", ".css", ".html")):
            ctype += "; charset=utf-8"
        self._send(200, body, ctype)

    def _fetch(self, rest: str, dest: Path):
        with self.lock:
            if dest.is_file():
                return dest.read_bytes()
            try:
                req = urllib.request.Request(UPSTREAM + rest, headers={"User-Agent": "ui5-rule-repair cache fill (one fetch per file)"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = r.read()
            except Exception:
                return None
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return data

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class LocalCopy:
    """Context manager: serves the local copy on 127.0.0.1 (random free port)."""

    def __init__(self, fetch_missing: bool = False, port: int = 0):
        handler = type("H", (_Handler,), {"fetch_missing": fetch_missing})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    def url(self, variant: str = "base") -> str:
        return app_url(self.base, variant)


if __name__ == "__main__":
    import argparse
    import time

    ap = argparse.ArgumentParser(description="Serve the local copy on 127.0.0.1")
    ap.add_argument("--port", type=int, default=8811)
    ap.add_argument("--fetch-missing", action="store_true", help="fill the cache from sdk.openui5.org (one fetch per file)")
    a = ap.parse_args()
    with LocalCopy(a.fetch_missing, a.port) as lc:
        for v in variant_names():
            print(lc.url(v))
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
