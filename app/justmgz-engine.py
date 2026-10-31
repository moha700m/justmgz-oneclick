#!/usr/bin/env python3
"""
justmgz engine bridge
---------------------
واجهة محلية تشغّل محرّك tr4mpass الحقيقي وتنقل مخرجاته كما هي.
لا يوجد محاكي، ولا نجاح مزيّف: كل سطر يظهر هنا خرج فعلي من المحرّك.
"""
import http.server, socketserver, subprocess, os, sys, json, time, re, shutil, threading, webbrowser

BASE = os.path.dirname(os.path.abspath(__file__))

def _resolve_engine():
    cands = [os.environ.get("TR4MPASS_DIR", ""),
             os.path.join(BASE, "tr4mpass"),
             os.path.join(os.path.dirname(BASE), "tr4mpass"),
             os.path.expanduser("~/tr4mpass"),
             "/tmp/tr4mpass"]
    for c in cands:
        if c and os.access(os.path.join(c, "tr4mpass"), os.X_OK):
            return c
    return cands[1] if not os.environ.get("TR4MPASS_DIR") else os.environ["TR4MPASS_DIR"]

ENGINE_DIR = _resolve_engine()
BIN = os.path.join(ENGINE_DIR, "tr4mpass")
PORT = int(os.environ.get("JUSTMGZ_PORT", "8099"))

MODES = {
    "detect":   ["-d"],
    "dry":      ["-n", "-v"],
    "pathA":    ["-a", "-v"],
    "pathB":    ["-b", "-v"],
    "activate": ["--activate-only", "-v"],
    "probe":    ["--probe-albert", "-v"],
}

def git_commit():
    try:
        return subprocess.run(["git", "-C", ENGINE_DIR, "log", "-1", "--format=%h %s"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""

def engine_version():
    try:
        out = subprocess.run([BIN, "--help"], capture_output=True, text=True, timeout=10).stdout
        m = re.search(r"tr4mpass v([0-9.]+)", out)
        return m.group(1) if m else "unknown"
    except Exception:
        return ""

def missing_libs():
    try:
        out = subprocess.run(["ldd", BIN], capture_output=True, text=True, timeout=5).stdout
        return [l.strip() for l in out.splitlines() if "not found" in l]
    except Exception:
        return []

def usb_apple_count():
    for cmd in (["lsusb"],):
        if shutil.which(cmd[0]):
            try:
                out = subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout.lower()
                return sum(1 for l in out.splitlines() if "apple" in l)
            except Exception:
                return 0
    return 0

def state():
    exists = os.path.isfile(BIN) and os.access(BIN, os.X_OK)
    return {
        "engine_dir": ENGINE_DIR,
        "binary": BIN,
        "exists": exists,
        "version": engine_version() if exists else "",
        "commit": git_commit(),
        "missing_libs": missing_libs() if exists else [],
        "usb_apple": usb_apple_count(),
        "modes": list(MODES.keys()),
        "platform": sys.platform,
    }

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s\n" % (fmt % args))

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path, ctype):
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/state"):
            return self._json(state())
        if self.path in ("/", "/index.html"):
            return self._file(os.path.join(BASE, "ui.html"), "text/html; charset=utf-8")
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self.path.startswith("/api/run"):
            return self._json({"error": "not found"}, 404)
        q = self.path.split("?", 1)[1] if "?" in self.path else ""
        mode = ""
        for part in q.split("&"):
            if part.startswith("mode="):
                mode = part[5:]
        if mode not in MODES:
            return self._json({"error": "unknown mode"}, 400)
        self.stream_run(MODES[mode])

    def stream_run(self, args):
        st = state()
        if not st["exists"]:
            return self._json({"error": "engine_missing", "detail": st}, 409)

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        t0 = time.time()
        self.wfile.write(("[cmd] %s\n" % " ".join([BIN] + args)).encode()); self.wfile.flush()

        env = dict(os.environ)
        env.setdefault("LC_ALL", "C.UTF-8")
        errors = 0
        try:
            p = subprocess.Popen([BIN] + args, cwd=ENGINE_DIR, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
            deadline = time.time() + 600
            for line in p.stdout:
                if time.time() > deadline:
                    p.kill(); break
                if "[ERROR]" in line or "error" in line.lower() and "0 error" not in line.lower():
                    if "[ERROR]" in line:
                        errors += 1
                self.wfile.write(line.encode()); self.wfile.flush()
            rc = p.wait()
        except Exception as e:
            self.wfile.write(("[bridge-error] %s\n" % e).encode()); self.wfile.flush()
            rc, errors = -1, errors + 1

        secs = round(time.time() - t0, 1)
        # حكم صادق مبني على المخرجات لا على رمز الخروج (المحرك يرجع 0 حتى عند الفشل)
        verdict = "fail" if errors else ("ok" if rc == 0 else "fail")
        meta = {"__meta__": {"rc": rc, "errors": errors, "seconds": secs, "verdict": verdict}}
        self.wfile.write(("\n" + json.dumps(meta) + "\n").encode()); self.wfile.flush()

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

if __name__ == "__main__":
    st = state()
    print("=" * 56)
    print("  justmgz · bridge to tr4mpass engine")
    print("  engine:", st["binary"])
    print("  status:", "FOUND v" + st["version"] if st["exists"] else "MISSING")
    print("  commit:", st["commit"] or "-")
    print("  http://127.0.0.1:%d" % PORT)
    print("=" * 56)
    if len(sys.argv) > 1 and sys.argv[1] == "--open":
        threading.Timer(1.0, lambda: webbrowser.open("http://127.0.0.1:%d" % PORT)).start()
    try:
        srv = Server(("127.0.0.1", PORT), Handler)
    except OSError as e:
        # المنفذ مشغول: لو فيه نسخة شغالة فعلاً، نطلع بهدوء
        import urllib.request
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/api/state" % PORT, timeout=3) as r:
                if r.status == 200:
                    print("  already running on port %d -- using existing instance" % PORT)
                    raise SystemExit(0)
        except SystemExit:
            raise
        except Exception:
            print("  port %d busy by another program: %s" % (PORT, e))
            raise SystemExit(2)
    with srv:
        srv.serve_forever()
