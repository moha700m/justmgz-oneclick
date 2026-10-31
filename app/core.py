#!/usr/bin/env python3
"""justmgz bridge v3 — event bus + SSE + simulator + 5 detection backends."""
import http.server, socketserver, subprocess, os, sys, json, time, re, shutil, threading, queue
from collections import deque

BASE = os.path.dirname(os.path.abspath(__file__))

def _resolve_engine():
    for c in [os.environ.get("TR4MPASS_DIR", ""), os.path.join(BASE, "tr4mpass"),
              os.path.join(os.path.dirname(BASE), "tr4mpass"), os.path.expanduser("~/tr4mpass"),
              "/opt/justmgz/eng", "/tmp/tr4mpass"]:
        if c and os.access(os.path.join(c, "tr4mpass"), os.X_OK):
            return c
    return os.environ.get("TR4MPASS_DIR") or "/opt/justmgz/eng"

ENGINE_DIR = _resolve_engine()
BIN = os.path.join(ENGINE_DIR, "tr4mpass")
PORT = int(os.environ.get("JUSTMGZ_PORT", "8099"))

MODES = {"detect": ["-d"], "dry": ["-n", "-v"], "pathA": ["-a", "-v"],
         "pathB": ["-b", "-v"], "activate": ["--activate-only", "-v"], "probe": ["--probe-albert", "-v"]}

# ───────────── event bus ─────────────
class Bus:
    def __init__(self, backlog=400, qmax=800):
        self.lock = threading.Lock()
        self.subs = []
        self.backlog = deque(maxlen=backlog)
        self.seq = 0

    def publish(self, kind, **data):
        with self.lock:
            self.seq += 1
            ev = {"id": self.seq, "t": round(time.time(), 3), "kind": kind}
            ev.update(data)
            self.backlog.append(ev)
            subs = list(self.subs)
        for q in subs:
            try:
                q.put_nowait(ev)
            except queue.Full:
                pass
        return ev

    def subscribe(self, replay=0):
        q = queue.Queue(maxsize=800)
        with self.lock:
            self.subs.append(q)
            items = list(self.backlog)[-replay:] if replay else []
        for ev in items:
            q.put_nowait(ev)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.subs:
                self.subs.remove(q)

BUS = Bus()

# ───────────── chip + model maps ─────────────
CPID_CHIP = {"8960": "A7", "7000": "A8", "7001": "A8", "8000": "A9", "8003": "A9X",
             "8010": "A10", "8011": "A10X", "8015": "A11", "8020": "A12", "8027": "A12X/A12Z",
             "8030": "A13", "8101": "A14", "8110": "A15", "8120": "A16", "8130": "A17",
             "8140": "A18", "8028": "A12X", "8103": "A14"}
A_CHIPS = {"A7", "A8", "A9", "A9X", "A10", "A10X", "A11"}

NAMES = json.loads(open(os.path.join(BASE, "names.json"), encoding="utf-8").read()) if os.path.exists(os.path.join(BASE, "names.json")) else {}

def chip_name(cpid):
    if not cpid:
        return ""
    key = cpid.lower().replace("0x", "").zfill(4)
    return CPID_CHIP.get(key, "")

def parse_serial(text):
    out = {}
    for key, pat in (("cpid", r"CPID:\s*(0x)?([0-9A-Fa-f]+)"),
                     ("ecid", r"ECID:\s*(0x)?([0-9A-Fa-f]+)"),
                     ("serial", r"Serial:\s*(\S+)"),
                     ("product", r"Product Type:\s*(\S+)"),
                     ("ios", r"iOS Version:\s*(\S+)"),
                     ("name", r"Device Name:\s*(.+)")):
        m = re.search(pat, text)
        if m:
            out[key] = m.group(m.lastindex) if key in ("cpid", "ecid") else m.group(1).strip()
    return out

# ───────────── detection backends ─────────────
def _cmd(args, timeout=20):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()
    except FileNotFoundError:
        return 127, "not found"
    except Exception as e:
        return 1, str(e)

def backend_pyusb():
    try:
        import usb.core
    except Exception:
        return {"backend": "pyusb", "ok": False, "note": "غير مثبت"}
    try:
        devs = list(usb.core.find(find_all=True, idVendor=0x05AC) or [])
        return {"backend": "pyusb", "ok": bool(devs), "count": len(devs)}
    except Exception as e:
        return {"backend": "pyusb", "ok": False, "note": str(e)[:60]}

def backend_pnp():
    ps = ("Get-PnpDevice -PresentOnly | Where-Object { $_.FriendlyName -match 'Apple' } "
          "| Select-Object -First 4 Status,FriendlyName | Out-String")
    rc, out = _cmd(["powershell.exe", "-NoProfile", "-Command", ps], timeout=25)
    if rc == 127:
        return {"backend": "pnp", "ok": False, "note": "powershell غير متاح"}
    return {"backend": "pnp", "ok": "apple" in out.lower(), "note": out.strip()[:120]}

def backend_usbipd():
    rc, out = _cmd(["usbipd.exe", "list"], timeout=20)
    if rc == 127:
        return {"backend": "usbipd", "ok": False, "note": "غير مثبت"}
    apple = [l.split()[0] for l in out.splitlines() if "apple" in l.lower() and l.split()]
    return {"backend": "usbipd", "ok": bool(apple), "busids": apple, "note": ""}

def backend_pmd3():
    rc, out = _cmd(["python3", "-c", "import pymobiledevice3,sys;print('ok')"], timeout=15)
    if rc != 0:
        return {"backend": "pymobiledevice3", "ok": False, "note": "غير مثبت"}
    rc2, out2 = _cmd(["pymobiledevice3", "usbmux", "list"], timeout=20)
    return {"backend": "pymobiledevice3", "ok": rc2 == 0 and "udid" in out2.lower(), "note": out2.strip()[:120]}

def backend_libimobiledevice():
    rc, out = _cmd(["idevice_id", "-l"], timeout=15)
    if rc == 127:
        return {"backend": "libimobiledevice", "ok": False, "note": "الأداة غير مثبتة"}
    ids = [l for l in out.splitlines() if l.strip()]
    return {"backend": "libimobiledevice", "ok": bool(ids), "count": len(ids)}

def detect_backends():
    fns = [backend_pyusb, backend_pnp, backend_usbipd, backend_pmd3, backend_libimobiledevice]
    res = []
    for fn in fns:
        try:
            res.append(fn())
        except Exception as e:
            res.append({"backend": fn.__name__, "ok": False, "note": str(e)[:60]})
    return res

# ───────────── simulator ─────────────
SIM_STATES = {
    "no_device": None,
    "dfu_a9": {"mode": "DFU", "fields": {"Product Type": "iPhone9,1", "Chip ID": "A10 Fusion",
               "iOS Version": "15.8", "CPID": "0x8010", "ECID": "0x1A2B3C4D5E", "Serial": "F2LXSIM01",
               "Device Name": "تجربة — DFU A9"}},
    "dfu_a12": {"mode": "DFU", "fields": {"Product Type": "iPhone11,8", "Chip ID": "A12 Bionic",
                "iOS Version": "17.5", "CPID": "0x8020", "ECID": "0x9F8E7D6C5B", "Serial": "G0SIM00042",
                "Device Name": "تجربة — DFU A12"}},
    "recovery_a14": {"mode": "Recovery", "fields": {"Product Type": "iPhone13,2", "Chip ID": "A14 Bionic",
                     "iOS Version": "18.3", "CPID": "0x8101", "ECID": "0x1122334455", "Serial": "H7SIM00099",
                     "Device Name": "تجربة — Recovery A14"}},
}

def sim_state():
    s = os.environ.get("TR4MPASS_SIM", "")
    if s in ("", "0", "off"):
        return None
    return s if s in SIM_STATES else "no_device"

def sim_enabled():
    return os.environ.get("TR4MPASS_SIM", "") not in ("", "0", "off")

# ───────────── engine helpers ─────────────
def git_commit():
    rc, out = _cmd(["git", "-C", ENGINE_DIR, "log", "-1", "--format=%h %s"], timeout=5)
    return out.strip() if rc == 0 else ""

def engine_version():
    if not (os.path.isfile(BIN) and os.access(BIN, os.X_OK)):
        return ""
    rc, out = _cmd([BIN, "--help"], timeout=10)
    m = re.search(r"tr4mpass v([0-9.]+)", out or "")
    return m.group(1) if m else ""

def missing_libs():
    if not os.path.isfile(BIN):
        return []
    rc, out = _cmd(["ldd", BIN], timeout=5)
    return [l.strip() for l in out.splitlines() if "not found" in l]

def usb_apple_count():
    rc, out = _cmd(["lsusb"], timeout=5)
    return sum(1 for l in out.lower().splitlines() if "apple" in l)

def state():
    exists = os.path.isfile(BIN) and os.access(BIN, os.X_OK)
    return {"engine_dir": ENGINE_DIR, "binary": BIN, "exists": exists,
            "version": engine_version() if exists else "", "commit": git_commit(),
            "missing_libs": missing_libs() if exists else [], "usb_apple": usb_apple_count(),
            "modes": list(MODES.keys()), "platform": sys.platform,
            "sim": sim_enabled(), "sim_state": sim_state() or ""}

DEV_CACHE = {"t": 0.0, "v": None}

def probe_device(force=False):
    now = time.time()
    if not force and DEV_CACHE["v"] is not None and now - DEV_CACHE["t"] < 2.0:
        return DEV_CACHE["v"]

    if sim_enabled():
        st = SIM_STATES.get(sim_state() or "no_device")
        if st:
            res = {"connected": True, "mode": st["mode"], "fields": st["fields"],
                   "simulated": True, "chip": chip_name(st["fields"].get("CPID", "")),
                   "name": NAMES.get(st["fields"].get("Product Type", ""), ""),
                   "backends": [{"backend": "simulator", "ok": True, "note": st["mode"]}]}
        else:
            res = {"connected": False, "mode": "", "fields": {}, "simulated": True,
                   "error": "no device (sim)", "backends": [{"backend": "simulator", "ok": False, "note": "no_device"}]}
        DEV_CACHE.update(t=now, v=res)
        BUS.publish("device", connected=res["connected"], name=res.get("name", ""), mode=res.get("mode", ""))
        return res

    result = {"connected": False, "mode": "", "fields": {}, "error": "", "simulated": False,
              "backends": [], "chip": "", "name": ""}
    if not (os.path.isfile(BIN) and os.access(BIN, os.X_OK)):
        result["error"] = "engine missing"
        DEV_CACHE.update(t=now, v=result)
        return result

    rc, out = _cmd([BIN, "-d"], timeout=25)
    result["backends"] = detect_backends()
    if "--- Device Information ---" in out:
        result["connected"] = True
        for line in out.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                k = k.strip()
                if k and not k.startswith("[") and len(k) < 30:
                    result["fields"][k] = v.strip()
        result["mode"] = "DFU" if ("DFU" in out and "No DFU device" not in out) else "عادي"
        result["chip"] = chip_name(result["fields"].get("CPID", ""))
        result["name"] = NAMES.get(result["fields"].get("Product Type", ""), "")
    else:
        low = out.lower()
        result["error"] = "no device" if ("no devices found" in low or "no device detected" in low) else "unknown"

    DEV_CACHE.update(t=now, v=result)
    BUS.publish("device", connected=result["connected"], name=result.get("name", ""), mode=result.get("mode", ""))
    return result

# ───────────── usbipd ─────────────
def usbipd_path():
    for c in (r"C:\Program Files\usbipd-win\usbipd.exe",):
        if os.path.isfile(c):
            return c
    rc, _ = _cmd(["where", "usbipd"], timeout=5) if sys.platform == "win32" else (127, "")
    if rc == 0:
        return "usbipd"
    if shutil.which("usbipd.exe") or shutil.which("usbipd"):
        return "usbipd.exe" if shutil.which("usbipd.exe") else "usbipd"
    return None

def wsl_distro():
    rc, out = _cmd(["wsl.exe", "-e", "bash", "-lc", "echo $WSL_DISTRO_NAME"], timeout=15)
    return out.strip() if rc == 0 else ""

def do_attach():
    p = usbipd_path()
    if not p:
        BUS.publish("attach", ok=False, reason="usbipd غير مثبت")
        return {"ok": False, "reason": "usbipd غير مثبت", "steps": []}
    steps = []
    rc, out = _cmd([p, "list"], timeout=20)
    busids = [l.split()[0] for l in out.splitlines() if "apple" in l.lower() and l.split()]
    steps.append({"cmd": "list", "rc": rc, "apple": busids})
    if not busids:
        BUS.publish("attach", ok=False, reason="ما فيه جهاز آبل في ويندوز")
        return {"ok": False, "reason": "ما فيه جهاز آبل في ويندوز", "steps": steps, "raw": out}
    busid = busids[0]
    d = wsl_distro()
    for cmd in ([p, "bind", "--busid", busid],
                [p, "attach", "--wsl"] + (["--distribution", d] if d else []) + ["--busid", busid]):
        rc, out = _cmd(cmd, timeout=40)
        steps.append({"cmd": " ".join(cmd[1:]), "rc": rc, "out": out[:200]})
    rc, out = _cmd([p, "list"], timeout=20)
    attached = any(busid in l and "attached" in l.lower() for l in out.splitlines())
    steps.append({"cmd": "list-after", "rc": rc, "attached": attached})
    BUS.publish("attach", ok=attached, busid=busid, distro=d)
    return {"ok": attached, "busid": busid, "distro": d, "steps": steps}

def do_detach():
    p = usbipd_path()
    if not p:
        return {"ok": False, "reason": "usbipd غير مثبت"}
    rc, out = _cmd([p, "list"], timeout=20)
    busids = [l.split()[0] for l in out.splitlines() if "apple" in l.lower() and l.split()]
    if not busids:
        return {"ok": False, "reason": "ما فيه جهاز"}
    rc, out = _cmd([p, "detach", "--busid", busids[0]], timeout=30)
    BUS.publish("detach", ok=rc == 0, busid=busids[0])
    return {"ok": rc == 0, "busid": busids[0], "out": out[:200]}

# ───────────── diagnostics ─────────────
def diag():
    items = []
    def add(key, label, status, detail, fix=""):
        items.append({"key": key, "label": label, "status": status, "detail": detail, "fix": fix})

    st = state()
    add("engine", "محرك الفتح", "ok" if st["exists"] else "fail",
        ("موجود · v" + st["version"]) if st["exists"] else "غير موجود: " + BIN,
        "" if st["exists"] else "شغّل justmgz.exe بصلاحيات مسؤول لين يبنيه")

    add("libs", "مكتبات النظام", "ok" if not st["missing_libs"] else "fail",
        "كلها موجودة" if not st["missing_libs"] else "%d ناقصة" % len(st["missing_libs"]))

    add("python", "بايثون", "ok", sys.version.split()[0])

    if sim_enabled():
        add("sim", "وضع المحاكاة", "warn", "مفعّل — كل النتائج تجريبية", "أطفئه بـ TR4MPASS_SIM=0")

    be = detect_backends()
    names = {"pyusb": "USB مباشر", "pnp": "تعريف ويندوز", "usbipd": "تمرير USB",
             "pymobiledevice3": "pymobiledevice3", "libimobiledevice": "libimobiledevice"}
    for b in be:
        add(b["backend"], names.get(b["backend"], b["backend"]),
            "ok" if b["ok"] else ("warn" if b.get("note") else "fail"),
            b.get("note") or ("وجد جهاز" if b["ok"] else "ما وجد جهاز"),
            "" if b["ok"] else "شغّل justmgz.exe بصلاحيات مسؤول، وتأكد من الكيبل و Trust")

    d = probe_device(force=True)
    if d["connected"]:
        f = d["fields"]
        add("read", "قراءة الجهاز", "ok",
            "%s · %s · iOS %s" % (f.get("Device Name", "?"), f.get("Product Type", "?"), f.get("iOS Version", "?")))
    else:
        add("read", "قراءة الجهاز", "fail", "المحرك ما قرأ جهاز",
            "افتح شاشة الجهاز واضغط Trust، ثم أعد الفحص")

    add("panel", "لوحة التحكم", "ok", "تعمل على المنفذ %d" % PORT)
    return {"ok": all(i["status"] in ("ok", "unknown", "warn") for i in items), "items": items}

# ───────────── HTTP ─────────────
class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _text(self, txt, ctype="text/plain; charset=utf-8"):
        body = txt.encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _sse_open(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        self.wfile.flush()

    def _sse_loop(self):
        q = BUS.subscribe(replay=0)
        try:
            self.wfile.write(b": connected\n\n"); self.wfile.flush()
            last = time.time()
            while True:
                try:
                    ev = q.get(timeout=15)
                    self.wfile.write(("data: " + json.dumps(ev, ensure_ascii=False) + "\n\n").encode())
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b": ping\n\n"); self.wfile.flush()
                if time.time() - last > 3600:
                    break
        except Exception:
            pass
        finally:
            BUS.unsubscribe(q)
            self.close_connection = True

    def do_GET(self):
        p = self.path.split("?")[0]
        if p in ("/", "/index.html"):
            return self._text(BUILTIN_HTML, "text/html; charset=utf-8")
        if p == "/health":
            return self._text("ok")
        if p == "/api/state":
            return self._json(state())
        if p == "/api/device":
            return self._json(probe_device())
        if p == "/api/diag":
            return self._json(diag())
        if p == "/api/usbipd":
            up = usbipd_path()
            rc, out = _cmd([up, "list"], timeout=20) if up else (127, "")
            return self._json({"installed": bool(up), "path": up, "list": out})
        if p == "/api/sim":
            return self._json({"enabled": sim_enabled(), "state": sim_state() or "", "states": list(SIM_STATES)})
        if p == "/api/routes":
            return self._json({"get": ["/", "/health", "/api/state", "/api/device", "/api/diag",
                                      "/api/usbipd", "/api/sim", "/api/routes", "/api/events", "/api/log-stream"],
                               "post": ["/api/run", "/api/attach", "/api/detach", "/api/sim", "/api/build"]})
        if p in ("/api/events", "/api/log-stream"):
            self._sse_open()
            return self._sse_loop()
        self._json({"error": "not found", "path": p}, 404)

    def do_POST(self):
        p = self.path.split("?")[0]
        q = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = dict(x.split("=", 1) for x in q.split("&") if "=" in x)

        if p == "/api/run":
            mode = params.get("mode", "")
            if mode not in MODES:
                return self._json({"error": "unknown mode"}, 400)
            return self.stream_run(MODES[mode], mode)

        if p == "/api/attach":
            res = do_attach(); DEV_CACHE["v"] = None
            return self._json(res)

        if p == "/api/detach":
            return self._json(do_detach())

        if p == "/api/sim":
            s = params.get("state", "")
            if s in SIM_STATES:
                os.environ["TR4MPASS_SIM"] = s
                DEV_CACHE["v"] = None
                BUS.publish("sim", state=s)
                return self._json({"ok": True, "state": s})
            if s in ("off", "0"):
                os.environ["TR4MPASS_SIM"] = "0"
                DEV_CACHE["v"] = None
                return self._json({"ok": True, "state": "off"})
            return self._json({"error": "unknown state", "states": list(SIM_STATES)}, 400)

        if p == "/api/build":
            BUS.publish("build", phase="start")
            rc, out = _cmd(["make", "-j4"], timeout=900)
            BUS.publish("build", phase="done", rc=rc)
            return self._json({"rc": rc, "out": out[-2000:]})

        self._json({"error": "not found"}, 404)

    def stream_run(self, args, mode):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        t0 = time.time()
        errors = 0
        BUS.publish("run", phase="start", mode=mode)
        head = "[cmd] %s %s\n" % (BIN, " ".join(args))
        self.wfile.write(head.encode()); self.wfile.flush()

        if sim_enabled():
            st = SIM_STATES.get(sim_state() or "no_device")
            lines = ["[SIM] محاكاة — ليست قراءة حقيقية"]
            if st:
                lines += ["[INFO] mode: " + st["mode"],
                          "[SIM] %s · %s" % (st["fields"].get("Product Type"), st["fields"].get("CPID")),
                          "[SIM] تحليل فقط — لا يوجد فتح فعلي"]
            else:
                lines += ["[ERROR] No devices found (sim)"]
                errors += 1
            for ln in lines:
                self.wfile.write((ln + "\n").encode()); self.wfile.flush()
                BUS.publish("log", line=ln)
                time.sleep(0.15)
            rc = 0
        else:
            try:
                p = subprocess.Popen([BIN] + args, cwd=ENGINE_DIR, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True, bufsize=1)
                deadline = time.time() + 900
                for line in p.stdout:
                    if "[ERROR]" in line:
                        errors += 1
                    self.wfile.write(line.encode()); self.wfile.flush()
                    BUS.publish("log", line=line.rstrip())
                    if time.time() > deadline:
                        p.kill(); break
                rc = p.wait()
            except Exception as e:
                msg = "[bridge-error] %s\n" % e
                self.wfile.write(msg.encode()); self.wfile.flush()
                rc, errors = -1, errors + 1

        secs = round(time.time() - t0, 1)
        verdict = "fail" if errors else ("ok" if rc == 0 else "fail")
        if sim_enabled():
            verdict = "sim"
        meta = {"rc": rc, "errors": errors, "seconds": secs, "verdict": verdict, "simulated": sim_enabled()}
        BUS.publish("run", phase="done", mode=mode, **meta)
        self.wfile.write(("\n" + json.dumps({"__meta__": meta}) + "\n").encode()); self.wfile.flush()

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

if __name__ == "__main__":
    st = state()
    print("=" * 56)
    print("  justmgz bridge v3")
    print("  engine:", st["binary"], "| v" + st["version"] if st["exists"] else "| missing")
    print("  sim   :", "ON (%s)" % (st["sim_state"] or "-") if st["sim"] else "off")
    print("  http  : http://127.0.0.1:%d" % PORT)
    print("=" * 56)
    try:
        srv = Server(("127.0.0.1", PORT), Handler)
    except OSError:
        import urllib.request
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/api/state" % PORT, timeout=3)
            print("  already running")
            raise SystemExit(0)
        except SystemExit:
            raise
        except Exception as e:
            print("  port busy:", e)
            raise SystemExit(2)
    with srv:
        srv.serve_forever()
