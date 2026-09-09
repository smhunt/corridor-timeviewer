#!/usr/bin/env python3
"""
serve.py -- local server for the viewer.

Three jobs:
  /                    the viewer
  /cache/...           harvested scans and web renders
  /tiles/<source>/z/x/y  remote tile services, cached to disk on first request

The tile cache is the point. Provincial imagery services rate-limit and go
down; once a tile is on disk the animation renders the same way every time,
offline. Nothing is ever re-fetched unless you delete it.

    ./serve.py                 start on :3033, HTTPS if the dev cert is present
    ./serve.py --port 5504     any other allocated port
    ./serve.py --http          plain HTTP, no TLS
    ./serve.py discover swoop  list live layers under a raster source
"""

import argparse
import base64
import hashlib
import json
import mimetypes
import socketserver
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
TILES = ROOT / "cache" / "tiles"
UA = "airphoto-corridor/1.0 (local archival research cache)"

# 1x1 transparent PNG, served in place of a tile the upstream would not give
# us. A render walking the timeline must not stall or blank on one dead tile.
BLANK_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)

# Shared mkcert certificate, signed for *.dev.ecoworks.ca as well as localhost.
# Missing is fine -- the server falls back to plain HTTP and says so.
CERT_DIR = Path.home() / "Code" / ".traefik" / "certs"
HOSTNAME = "dev.ecoworks.ca"

_stats = {"hit": 0, "miss": 0, "fail": 0}
_lock = threading.Lock()


def config():
    with open(ROOT / "sources.yaml") as fh:
        return yaml.safe_load(fh)


def tile_url(src, z, x, y):
    kind = src.get("kind")
    if kind == "xyz":
        return (src["url"].replace("{z}", str(z))
                .replace("{x}", str(x)).replace("{y}", str(y)))
    if kind == "arcgis_export":
        # ArcGIS MapServer export: convert the XYZ tile to a Web Mercator bbox
        import math
        n = 2 ** z
        span = 20037508.342789244
        west = x / n * 2 * span - span
        east = (x + 1) / n * 2 * span - span
        north = span - y / n * 2 * span
        south = span - (y + 1) / n * 2 * span
        q = urllib.parse.urlencode({
            "bbox": f"{west},{south},{east},{north}",
            "bboxSR": 3857, "imageSR": 3857, "size": "256,256",
            "format": "jpg", "transparent": "false", "f": "image",
            "layers": src.get("layers", "show:0"),
        })
        return f"{src['url'].rstrip('/')}/export?{q}"
    raise ValueError(f"source kind '{kind}' is not tileable")


class Handler(SimpleHTTPRequestHandler):
    cfg = None

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, *a):
        pass  # the tile counter below is the useful signal

    def end_headers(self):
        # The viewer and its manifest change every time the cache does. Tiles
        # and scans are immutable and keep their long-lived caching below.
        if getattr(self, "_nocache", False):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        if self.path.startswith("/tiles/"):
            return self.serve_tile()
        bare = self.path.split("?")[0]
        self._nocache = bare.endswith((".html", "/", "manifest.json"))
        if self.path in ("/", "/index.html", "/viewer"):
            # Redirect rather than rewrite. The viewer resolves manifest.json
            # and '../cache/...' against the browser's URL, so the base has to
            # actually be /viewer/ -- a silent server-side rewrite leaves it
            # at / and the manifest 404s.
            self.send_response(302)
            self.send_header("Location", "/viewer/")
            self.end_headers()
            return
        if self.path == "/stats":
            return self.send_json(_stats)
        return super().do_GET()

    def do_POST(self):
        """Receive rendered frames from the viewer's precise export.

        The browser cannot encode a high-bitrate MP4 on its own, so the viewer
        renders one PNG per frame and posts it here. When the last frame lands
        we print the ffmpeg command to turn the sequence into video.
        """
        if not self.path.startswith("/frames/"):
            return self.send_error(404)
        parts = self.path.strip("/").split("/")
        if len(parts) < 3:
            return self.send_error(400, "expected /frames/<take>/<index>")
        take, index = parts[1], parts[2].split("?")[0]
        if not take.replace("-", "").replace("_", "").isalnum() or not index.isdigit():
            return self.send_error(400, "bad take or frame index")

        length = int(self.headers.get("Content-Length", 0))
        blob = self.rfile.read(length)
        out = ROOT / "export" / take
        out.mkdir(parents=True, exist_ok=True)
        (out / f"frame_{int(index):05d}.png").write_bytes(blob)

        fps = self.headers.get("X-Fps", "30")
        if self.headers.get("X-Final") == "1":
            n = len(list(out.glob("frame_*.png")))
            rel = out.relative_to(ROOT)
            print(f"\n{n} frames written to {rel}/\n")
            print("  mp4   ffmpeg -framerate %s -i %s/frame_%%05d.png"
                  " -c:v libx264 -pix_fmt yuv420p -crf 16 %s.mp4" % (fps, rel, take))
            print("  prores ffmpeg -framerate %s -i %s/frame_%%05d.png"
                  " -c:v prores_ks -profile:v 3 %s.mov" % (fps, rel, take))
            print("  gif   ffmpeg -framerate %s -i %s/frame_%%05d.png"
                  " -vf scale=1000:-1:flags=lanczos %s.gif\n" % (fps, rel, take))
        return self.send_json({"ok": True, "frame": int(index)})

    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def serve_tile(self):
        try:
            _, _, name, z, x, y = self.path.split("?")[0].split("/", 5)
            y = y.split(".")[0]
            z, x, y = int(z), int(x), int(y)
        except ValueError:
            return self.send_error(400, "expected /tiles/<source>/<z>/<x>/<y>")

        src = (self.cfg.get("rasters") or {}).get(name)
        if not src:
            return self.send_error(404, f"no raster source '{name}'")

        # Cache under the source's real format. OSM serves PNG; storing that
        # as .jpg and announcing image/jpeg leaves the decoder guessing.
        ext = str(src.get("format") or "jpg").lstrip(".")
        path = TILES / name / str(z) / str(x) / f"{y}.{ext}"
        if not path.exists():
            try:
                url = tile_url(src, z, x, y)
            except ValueError as exc:
                return self.send_error(400, str(exc))
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            blob = None
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=30) as r:
                        blob = r.read()
                    break
                except Exception as exc:  # noqa: BLE001
                    last = exc
                    time.sleep(0.4 * (attempt + 1))
            if blob is None:
                with _lock:
                    _stats["fail"] += 1
                # A transparent 1px keeps the animation running past a gap
                # instead of stalling on one dead tile. Not written to disk and
                # not cached by the browser, so the next pass tries again.
                print(f"    ! tile {name}/{z}/{x}/{y}: {last}")
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(BLANK_PNG)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                return self.wfile.write(BLANK_PNG)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
            with _lock:
                _stats["miss"] += 1
        else:
            blob = path.read_bytes()
            with _lock:
                _stats["hit"] += 1

        self.send_response(200)
        self.send_header("Content-Type",
                         mimetypes.types_map.get(f".{ext}", "image/jpeg"))
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(blob)


def tls_context():
    """Wrap the listener in TLS when the shared dev certificate is on disk."""
    cert, key = CERT_DIR / "cert.pem", CERT_DIR / "key.pem"
    if not (cert.exists() and key.exists()):
        return None
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    return ctx


def cmd_discover(name):
    """List layers under an ArcGIS services root, so you can fill in sources.yaml."""
    cfg = config()
    src = (cfg.get("rasters") or {}).get(name)
    if not src or not src.get("url"):
        sys.exit(f"no raster source '{name}' with a url")
    url = f"{src['url'].rstrip('/')}?f=json"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            data = json.load(r)
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"{name}: {exc}\n"
                 "Provincial endpoints sit behind a WAF that blocks datacentre\n"
                 "egress. From a home connection this normally resolves.")
    for s in data.get("services", []):
        print(f"  service  {s.get('name')}  ({s.get('type')})")
    for lyr in data.get("layers", []):
        print(f"  layer    {lyr.get('id')}  {lyr.get('name')}")
    for f in data.get("folders", []):
        print(f"  folder   {f}")


def main():
    # A long render is usually left running with stdout redirected to a file,
    # and the ffmpeg line printed at the end of it is the point of the run.
    sys.stdout.reconfigure(line_buffering=True)
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", nargs="?", default="serve", choices=["serve", "discover"])
    ap.add_argument("target", nargs="?")
    ap.add_argument("--port", type=int, default=3033)
    ap.add_argument("--host", default="0.0.0.0",
                    help="interface to bind (default: all, so the LAN name resolves)")
    ap.add_argument("--http", action="store_true",
                    help="serve plain HTTP even if the dev certificate is present")
    args = ap.parse_args()

    if args.command == "discover":
        if not args.target:
            sys.exit("usage: ./serve.py discover <raster-source>")
        return cmd_discover(args.target)

    Handler.cfg = config()
    TILES.mkdir(parents=True, exist_ok=True)
    socketserver.TCPServer.allow_request_reuse = True

    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

        def handle_error(self, request, client_address):
            exc = sys.exc_info()[1]
            # A viewer scrubbing the timeline aborts tile and image requests
            # by the dozen, and each abort surfaces here. They are not server
            # errors, and a stack trace apiece buries the ffmpeg output.
            if isinstance(exc, (BrokenPipeError, ConnectionResetError,
                                ConnectionAbortedError, ssl.SSLEOFError,
                                TimeoutError)):
                return
            super().handle_error(request, client_address)

    ctx = None if args.http else tls_context()
    with Server((args.host, args.port), Handler) as httpd:
        if ctx:
            httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https" if ctx else "http"
        print(f"viewer   {scheme}://{HOSTNAME}:{args.port}/")
        if not ctx:
            print(f"         no certificate in {CERT_DIR} -- serving plain HTTP")
        print(f"tiles    cached to {TILES.relative_to(ROOT)}/")
        print("ctrl-c to stop\n")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print(f"\ntiles: {_stats['hit']} from cache, "
                  f"{_stats['miss']} fetched, {_stats['fail']} failed")


if __name__ == "__main__":
    main()
