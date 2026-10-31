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
        win = detect_windows_pnp()
        if win:
            result.update({"connected": True, "mode": win["mode"], "via": "windows",
                           "chip": win["chip"], "name": win["product"],
                           "fields": {"Product Type": "", "Chip ID": win["chip"],
                                      "CPID": win["cpid"], "ECID": win["ecid"],
                                      "Serial": win["serial"], "Device Name": win["product"]},
                           "note": "مقروء من ويندوز مباشرة — بدون تمرير USB"})

    DEV_CACHE.update(t=now, v=result)
    BUS.publish("device", connected=result["connected"], name=result.get("name", ""), mode=result.get("mode", ""))
    return result


PS_QUERY = ("Get-PnpDevice -PresentOnly -ErrorAction SilentlyContinue | "
            "Where-Object { $_.InstanceId -like 'USB\\VID_05AC*' } | "
            "Select-Object -First 6 InstanceId,FriendlyName,Status | ConvertTo-Json -Compress")
PID_MODE = {"1227": "DFU", "1281": "Recovery", "12a8": "عادي", "12ab": "عادي"}
GENERIC_NAME = re.compile(r"apple mobile device|usb driver|composite|generic", re.I)

def detect_windows_pnp():
    """يقرأ سيريال USB من ويندوز — سيريال DFU يحمل CPID/ECID بدون أي تمرير."""
    rc, out = _cmd(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", PS_QUERY], timeout=20)
    if rc != 0 or not out.strip():
        return None
    try:
        data = json.loads(out)
    except Exception:
        return None
    if isinstance(data, dict):
        data = [data]
    for item in data:
        inst = str((item or {}).get("InstanceId") or "")
        m = re.search(r"PID_([0-9A-Fa-f]{4})", inst)
        if not m:
            continue
        pid = m.group(1).lower()
        mode = PID_MODE.get(pid)
        if not mode:
            continue
        serial = inst.split("\\")[-1]
        info = parse_serial(serial)
        friendly = str(item.get("FriendlyName") or "").strip()
        product = friendly[:40] if friendly and not GENERIC_NAME.search(friendly) else ""
        return {"present": True, "mode": mode, "pid": pid, "serial": serial,
                "cpid": info.get("cpid", ""), "ecid": info.get("ecid", ""),
                "chip": chip_name(info.get("cpid", "")), "product": product}
    return None

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


BUILTIN_HTML = r"""<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>justmgz — تشغيل تلقائي</title>
<link href="https://fonts.googleapis.com/css2?family=Tajawal:wght@400;500;700;800&display=swap" rel="stylesheet">
<style>
:root{
  --bg:#0A0E13; --card:#101821; --card2:#0D141B; --line:#1E2A36;
  --txt:#EAF1F7; --mut:#9DADBC; --acc:#38BDF8; --ok:#34D399; --warn:#F5B84D; --bad:#F87171;
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px;
  --r:16px;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:radial-gradient(900px 480px at 88% -12%,#132435 0%,transparent 62%),var(--bg);
  color:var(--txt);font-family:'Tajawal',system-ui,-apple-system,sans-serif;
  font-size:15px;line-height:1.65;-webkit-font-smoothing:antialiased;
}
.wrap{max-width:720px;margin:0 auto;padding:var(--s5) var(--s4) var(--s6)}
/* ---------- header ---------- */
.brand{display:flex;align-items:center;gap:var(--s3);margin-bottom:var(--s5)}
.mark{width:44px;height:44px;border-radius:13px;background:#122130;border:2px solid #1f4a63;
  display:grid;place-items:center;color:var(--acc);font-weight:800;font-size:20px}
.brand .txt{display:flex;flex-direction:column;gap:2px}
.wordmark{font-size:19px;font-weight:800;letter-spacing:.5px;direction:ltr;unicode-bidi:isolate;line-height:1.1}
.brand small{color:var(--mut);font-size:12.5px}
.state{margin-inline-start:auto;display:flex;align-items:center;gap:var(--s2);font-size:13px;font-weight:700;
  padding:9px 13px;border-radius:999px;border:1px solid var(--line);background:#0f1a22;white-space:nowrap}
.state .dot{width:9px;height:9px;border-radius:50%;background:var(--mut);flex:none}
.state.on .dot{background:var(--ok);box-shadow:0 0 0 4px rgba(52,211,153,.15)}
.state.off .dot{background:var(--bad);box-shadow:0 0 0 4px rgba(248,113,113,.15)}
/* ---------- big button ---------- */
.start{
  width:100%;min-height:64px;border:0;border-radius:18px;cursor:pointer;
  background:linear-gradient(180deg,#42c8fb,#1f9fd8);color:#04212e;
  font-family:inherit;font-size:19px;font-weight:800;letter-spacing:.2px;
  display:flex;align-items:center;justify-content:center;gap:var(--s2);
  box-shadow:0 18px 40px -22px #38bdf8;transition:transform .12s,filter .15s;
}
.start:hover:not(:disabled){filter:brightness(1.07)}
.start:active:not(:disabled){transform:translateY(1px)}
.start:disabled{opacity:.45;cursor:not-allowed;box-shadow:none}
.start .num{background:#04212e22;border-radius:8px;padding:1px 8px;font-size:15px}
.hint{text-align:center;color:var(--mut);font-size:13px;margin:var(--s2) 0 var(--s5)}
/* ---------- numbers ---------- */


.dh{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.dh h2{margin:0;flex:1}
.mini{font-size:12px;padding:7px 12px;border-radius:9px;border:1px solid var(--line);
  background:#0b1219;color:var(--txt);font-family:inherit;font-weight:700;cursor:pointer}
.mini:hover{border-color:#2a6b8a}
.dl{display:flex;flex-direction:column;gap:9px}
.di{display:flex;gap:10px;align-items:flex-start;padding:9px 10px;border-radius:11px;background:#0b1219;border:1px solid #16212b}
.di .ic{width:22px;height:22px;border-radius:50%;display:grid;place-items:center;font-size:13px;font-weight:800;flex:none}
.di.ok .ic{background:#0f3327;color:#4ade9c}
.di.warn .ic{background:#332a12;color:#f5c66b}
.di.fail .ic{background:#331717;color:#f08c8c}
.di .l{font-size:13.5px;font-weight:700;line-height:1.4}
.di .d{font-size:12px;color:var(--mut);line-height:1.5}
.di .fx{font-size:12px;color:#f5c66b;line-height:1.5;margin-top:2px}


.live{display:inline-flex;align-items:center;gap:6px;font-size:11px;color:var(--mut);
  margin-inline-start:8px}
.live .d{width:7px;height:7px;border-radius:50%;background:#6b7280}
.live.on .d{background:var(--ok);box-shadow:0 0 0 3px rgba(52,211,153,.18)}
.btn2{font-size:12.5px;padding:9px 12px;border-radius:10px;border:1px solid var(--line);
  background:#0b1219;color:var(--txt);font-family:inherit;font-weight:700;cursor:pointer}
.btn2:hover{border-color:#2a6b8a}
.simbar{display:none;margin:0 0 12px;padding:10px 12px;border-radius:12px;font-size:12.5px;
  background:#221c0e;border:1px solid #5c4a1c;color:#f3d9a4}
.simbar.on{display:block}

.dev{display:flex;align-items:center;gap:14px;background:var(--card);border:1px solid var(--line);
  border-radius:16px;padding:14px 16px;margin:0 0 14px;transition:border-color .2s}
.dev.on{border-color:#1c5c45;background:#0d2119}
.dev.off{border-color:#3a2222;background:#1a1010}
.dev .st{width:10px;height:10px;border-radius:50%;background:#8b97a5;flex:none}
.dev.on .st{background:var(--ok);box-shadow:0 0 0 4px rgba(52,211,153,.15)}
.dev.off .st{background:var(--bad);box-shadow:0 0 0 4px rgba(248,113,113,.15)}
.dev .t{flex:1;min-width:0}
.dev b{display:block;font-size:16px;font-weight:800;line-height:1.3}
.dev span{display:block;font-size:12.5px;color:var(--mut);line-height:1.5}
.dev .mode{font-size:11.5px;font-weight:800;padding:5px 10px;border-radius:999px;border:1px solid var(--line);
  color:var(--mut);white-space:nowrap}
.dev.on .mode{border-color:#1c5c45;color:#a9f0d2}

.nums{display:grid;grid-template-columns:repeat(4,1fr);gap:var(--s2);margin-bottom:var(--s4)}
.card{margin-top:0}
.num-card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:var(--s3);text-align:center}
.num-card span{display:block;font-size:11.5px;color:#A9B8C7;font-weight:600;margin-bottom:2px}
.num-card b{display:block;font-size:25px;font-weight:800;line-height:1.15;font-variant-numeric:tabular-nums}

/* ---------- steps ---------- */
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:var(--s4);margin-bottom:var(--s4)}
.card h2{font-size:14px;margin:0 0 var(--s3);color:var(--mut);font-weight:700}
.steps{list-style:none;margin:0;padding:0}
.steps li{display:flex;align-items:center;gap:var(--s3);padding:13px 0;border-bottom:1px solid #16212b}
.steps li:last-child{border:0;padding-bottom:0}
.steps .ic{width:34px;height:34px;border-radius:11px;border:1.5px solid var(--line);background:#0b1219;
  display:grid;place-items:center;flex:none;color:var(--mut);font-weight:800;font-size:14px}
.steps .t{font-size:14.5px;font-weight:500}
.steps .s{margin-inline-start:auto;font-size:12px;color:var(--mut);white-space:nowrap}
.steps li.run .ic{border-color:var(--acc);color:var(--acc);animation:pulse 1.2s ease-in-out infinite}
.steps li.run .s{color:var(--acc)}
.steps li.ok .ic{border-color:var(--ok);color:var(--ok);background:#0d2119}
.steps li.ok .s{color:var(--ok)}
.steps li.err .ic{border-color:var(--bad);color:var(--bad);background:#221111}
.steps li.err .s{color:var(--bad)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.45}}
/* ---------- verdict ---------- */
.verdict{display:none;align-items:flex-start;gap:var(--s3);border-radius:14px;padding:var(--s4);margin-bottom:var(--s4);border:1.5px solid}
.verdict.show{display:flex}
.verdict.ok{background:#0d2119;border-color:#1c5c45}
.verdict.err{background:#221111;border-color:#5c2323}
.verdict.warn{background:#221c0e;border-color:#5c4a1c}
.verdict .big{font-size:17px;font-weight:800;margin:0 0 3px}
.verdict p{margin:0;font-size:13.5px;color:#d9e6f0}
.verdict .ico{flex:none;margin-top:2px}
/* ---------- log ---------- */
details.log{background:var(--card2);border:1px solid var(--line);border-radius:14px;padding:0;overflow:hidden}
details.log summary{cursor:pointer;padding:13px var(--s4);font-size:13.5px;font-weight:700;color:var(--mut);
  list-style:none;display:flex;align-items:center;gap:var(--s2)}
details.log summary::-webkit-details-marker{display:none}
details.log summary .cnt{margin-inline-start:auto;font-size:11.5px;background:#0b1219;border:1px solid var(--line);
  border-radius:999px;padding:2px 9px;font-variant-numeric:tabular-nums}
pre{margin:0;padding:var(--s3) var(--s4) var(--s4);max-height:300px;overflow:auto;background:#070b10;
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12px;line-height:1.6;
  direction:ltr;text-align:left;white-space:pre-wrap;color:#c3d3e0;border-top:1px solid var(--line)}
pre .e{color:#ff9b9b} pre .w{color:#f5c66b} pre .i{color:#82d5ff} pre .k{color:#8ef0c2}
footer{margin-top:var(--s5);padding-top:var(--s3);border-top:1px solid var(--line);
  color:var(--mut);font-size:12px;display:flex;justify-content:space-between;gap:var(--s2);flex-wrap:wrap}
:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
@media(max-width:420px){ .nums{grid-template-columns:repeat(2,1fr)} }
</style>
</head>
<body>
<div class="wrap">

  <div class="brand">
    <div class="mark">j</div>
    <div class="txt"><span class="wordmark" dir="ltr">justmgz</span><small>فاتح قفل iCloud — تشغيل تلقائي</small></div>
    <div class="state" id="state"><span class="dot"></span><span id="stateTxt">جاري الفحص…</span></div>
  </div>

  <div class="simbar" id="simbar">وضع المحاكاة مفعّل — كل الأرقام تجريبية ولا تعني قراءة جهاز حقيقي.</div>

  <div class="dev off" id="dev">
    <span class="st"></span>
    <div class="t">
      <b id="devName">ما فيه جهاز موصول</b>
      <span id="devSub">وصّل الآيفون بالكيبل — يكشفه لحاله</span>
    </div>
    <span class="mode" id="devMode">—</span>
  </div>
  <div style="display:flex;gap:8px;margin:-6px 0 14px">
    <button class="btn2" id="attachBtn" type="button">تمرير الجهاز الآن</button>
    <button class="btn2" id="detachBtn" type="button">فصل</button>
    <span class="live" id="live"><span class="d"></span>بث حي</span>
  </div>

  <div class="card" id="diagCard">
    <div class="dh">
      <h2>فحص شامل</h2>
      <button class="mini" id="diagBtn" type="button">أعد الفحص</button>
    </div>
    <div class="dl" id="diagList"><div class="di">جاري الفحص…</div></div>
  </div>

  <button class="start" id="start" disabled>
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
    ابدأ — وخله علينا
  </button>
  <p class="hint">وصّل الجهاز بالكيبل، واضغط الزر. البرنامج يكشفه ويختار الطريقة الصح بنفسه.</p>

  <div class="nums">
    <div class="num-card"><span>أجهزة موصولة</span><b id="nUsb">0</b></div>
    <div class="num-card"><span>من ٤ خطوات</span><b id="nStep">0</b></div>
    <div class="num-card"><span>أخطاء</span><b id="nErr">0</b></div>
    <div class="num-card"><span>ثانية</span><b id="nSec">0</b></div>
  </div>

  <div class="card">
    <h2>الخطوات</h2>
    <ol class="steps" id="steps">
      <li data-k="1"><div class="ic">١</div><div class="t">نشوف الجهاز موصول</div><div class="s">بانتظار</div></li>
      <li data-k="2"><div class="ic">٢</div><div class="t">نكشف الموديل والوضع</div><div class="s">بانتظار</div></li>
      <li data-k="3"><div class="ic">٣</div><div class="t">نختار الطريقة الصح</div><div class="s">بانتظار</div></li>
      <li data-k="4"><div class="ic">٤</div><div class="t">نشغّل الفتح</div><div class="s">بانتظار</div></li>
    </ol>
  </div>

  <div class="verdict" id="verdict">
    <div class="ico" id="vIco"></div>
    <div><p class="big" id="vT"></p><p id="vD"></p></div>
  </div>

  <details class="log" id="logBox">
    <summary>سجل التشغيل الحقيقي <span class="cnt" id="nLines">0 سطر</span></summary>
    <pre id="out">— ما فيه تشغيل بعد —</pre>
  </details>

  <footer>
    <span>كل شي حقيقي — مخرج المحرك نفسه</span>
    <span id="fEng">-</span>
  </footer>
</div>

<script>
var S = {
  ok:false, busy:false, errs:0, lines:0, t0:0, timer:null,
  el:{
    state:document.getElementById("state"), stateTxt:document.getElementById("stateTxt"),
    start:document.getElementById("start"), out:document.getElementById("out"),
    nUsb:document.getElementById("nUsb"), nStep:document.getElementById("nStep"),
    nErr:document.getElementById("nErr"), nSec:document.getElementById("nSec"),
    nLines:document.getElementById("nLines"), steps:document.getElementById("steps"), logBox:document.getElementById("logBox"),
    verdict:document.getElementById("verdict"), vT:document.getElementById("vT"),
    vD:document.getElementById("vD"), vIco:document.getElementById("vIco"),
    fEng:document.getElementById("fEng")
  }
};
var ICON_OK = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#34D399" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>';
var ICON_ERR = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#F87171" stroke-width="2.4" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>';
var ICON_WARN = '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#F5B84D" stroke-width="2.2" stroke-linecap="round"><path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9L2 18a2 2 0 001.7 3h16.6a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z"/></svg>';

function step(k, cls, note){
  var li = S.el.steps.querySelector('li[data-k="'+k+'"]');
  if(!li) return;
  li.className = cls || "";
  if(note) li.querySelector(".s").textContent = note;
  S.el.nStep.textContent = Math.max(parseInt(S.el.nStep.textContent)||0, cls==="ok"?k:k-1);
}
function resetSteps(){
  [].forEach.call(S.el.steps.children, function(li){ li.className=""; li.querySelector(".s").textContent="بانتظار"; });
  S.el.nStep.textContent = "0";
}
function verdict(kind, title, desc){
  S.el.verdict.className = "verdict show " + kind;
  S.el.vT.textContent = title;
  S.el.vD.textContent = desc;
  S.el.vIco.innerHTML = kind==="ok"?ICON_OK:(kind==="warn"?ICON_WARN:ICON_ERR);
}
function clearVerdict(){ S.el.verdict.className = "verdict"; }

function paint(line){
  S.lines++;
  S.el.nLines.textContent = S.lines + " سطر";
  var cls = "";
  if(line.indexOf("[ERROR]")>-1) cls="e";
  else if(line.indexOf("[WARN")>-1) cls="w";
  else if(line.indexOf("[INFO]")>-1) cls="i";
  else if(line.indexOf("[OK]")>-1) cls="k";
  var sp=document.createElement("span");
  if(cls) sp.className=cls;
  sp.textContent=line+"\n";
  S.el.out.appendChild(sp);
  S.el.out.scrollTop=S.el.out.scrollHeight;
}

function startTimer(){
  S.t0=Date.now(); clearInterval(S.timer);
  S.timer=setInterval(function(){ S.el.nSec.textContent = ((Date.now()-S.t0)/1000).toFixed(1); },100);
}
function stopTimer(){ clearInterval(S.timer); if(S.t0) S.el.nSec.textContent = ((Date.now()-S.t0)/1000).toFixed(1); }

function setBusy(v){
  S.busy=v; S.el.start.disabled = v || !S.ok;
  S.el.start.style.opacity = v? .7 : 1;
}

function runMode(mode){
  return fetch("/api/run?mode="+mode,{method:"POST"}).then(function(res){
    if(!res.ok) throw new Error("HTTP "+res.status);
    var rd=res.body.getReader(), dec=new TextDecoder(), buf="", meta=null;
    function pump(){
      return rd.read().then(function(c){
        if(c.done) return meta;
        buf += dec.decode(c.value,{stream:true});
        var parts = buf.split("\n"); buf = parts.pop();
        parts.forEach(function(l){
          if(l.indexOf('"__meta__"')>-1){ try{ meta=JSON.parse(l).__meta__; }catch(e){} return; }
          if(l) paint(l);
        });
        return pump();
      });
    }
    return pump();
  });
}

function refreshState(){
  return fetch("/api/state").then(function(r){return r.json()}).then(function(s){
    S.ok = !!s.exists;
    S.el.fEng.textContent = s.engine_dir || "-";
    S.el.nUsb.textContent = s.usb_apple || 0;
    S.el.state.className = "state " + (S.ok?"on":"off");
    S.el.stateTxt.textContent = S.ok ? ("جاهز · v"+s.version) : "المحرك مو موجود";
    if(!S.ok){
      verdict("err","ما لقينا المحرك","مسار المحرك غلط أو ما تم بناؤه: "+s.binary);
    }
    S.el.start.disabled = !S.ok || S.busy;
    return s;
  });
}

function start(){
  if(S.busy || !S.ok) return;
  setBusy(true); clearVerdict(); resetSteps();
  S.errs=0; S.lines=0; S.el.nErr.textContent="0"; S.el.nLines.textContent="0 سطر";
  S.el.out.textContent=""; startTimer();

  step(1,"run","نفحص…");
  refreshState().then(function(s){
    if((s.usb_apple||0) > 0){ step(1,"ok","موصول"); }
    else { step(1,"err","ما فيه جهاز"); throw {step:1}; }

    step(2,"run","نكشف…");
    return runMode("detect").then(function(meta){
      if(!meta || meta.verdict!=="ok"){ throw {step:2, meta:meta}; }
      step(2,"ok","تم الكشف"); return meta;
    });
  }).then(function(){
    step(3,"run","نختار…");
    // المحرك يقرر المسار بنفسه حسب الشريحة؛ نجرب فحص جاف أول عشان نطبع بيئة التشغيل
    return runMode("dry").then(function(meta){
      step(3,"ok","تلقائي"); return meta;
    });
  }).then(function(){
    step(4,"run","يشتغل…");
    return runMode("pathA").then(function(meta){
      if(meta && meta.verdict==="ok"){ return meta; }
      // لو مسار A ما نفع، نجرب B تلقائياً (A12+)
      paint("[auto] مسار A ما نفع — ننتقل لمسار B");
      return runMode("pathB");
    });
  }).then(function(meta){
    stopTimer();
    if(meta && meta.verdict==="ok"){
      step(4,"ok","خلص");
      verdict("ok","تم الفتح","الجهاز فكّ القفل. شيّك بنفسك قبل ما تسلّمه.");
      S.el.nStep.textContent="4";
    } else {
      throw {step:4, meta:meta};
    }
  }).catch(function(e){
    stopTimer(); setBusy(false);
    var meta = e && e.meta;
    S.errs = meta ? meta.errors : (S.errs||1);
    S.el.nErr.textContent = S.errs;
    if(e && e.step) step(e.step,"err");
    if(!S.ok) return;
    var msg = {
      1: ["الجهاز مو موصول","تأكد من ثلاث: كيبل أصلي، شاشة الجهاز تولّع، وتضغط «Trust / ثقة» لما يطلع لك. وعلى الكمبيوتر لازم usbipd attach — شغّل justmgz.exe مرة ثانية وهو يسويها."],
      2: ["شبكناه بس ما انكشف","جرّب تحطه على وضع DFU: اضغط زر الطاقة وزر خفض الصوت مع بعض ١٠ ثواني، بعدين كمل التعليمات."],
      3: ["ما قدرنا نختار الطريقة","المحرك ما رجّع معلومات الشريحة. أعد التوصيل واضغط «ابدأ» من جديد."],
      4: ["الفتح ما كمّل","الجهاز انكشف لكن العملية توقفت. افتح السجل تحت وشوف آخر سطر — وأرسله لي لو احتجت."]
    }[e && e.step] || ["ما ضبط","جرّب مرة ثانية، وإذا تكرر افتح السجل تحت."];
    verdict("err", msg[0], msg[1]);
    S.el.logBox.open = true;
  }).then(function(){ setBusy(false); });
}


var DEV = {timer:null, last:null};
var NAMES = {"iPhone8,1": "iPhone 6s", "iPhone8,2": "iPhone 6s Plus", "iPhone8,4": "iPhone SE 1", "iPhone9,1": "iPhone 7", "iPhone9,3": "iPhone 7", "iPhone9,2": "iPhone 7 Plus", "iPhone9,4": "iPhone 7 Plus", "iPhone10,1": "iPhone 8", "iPhone10,4": "iPhone 8", "iPhone10,2": "iPhone 8 Plus", "iPhone10,5": "iPhone 8 Plus", "iPhone10,3": "iPhone X", "iPhone10,6": "iPhone X", "iPhone11,2": "iPhone XS", "iPhone11,4": "iPhone XS Max", "iPhone11,6": "iPhone XS Max", "iPhone11,8": "iPhone XR", "iPhone12,1": "iPhone 11", "iPhone12,3": "iPhone 11 Pro", "iPhone12,5": "iPhone 11 Pro Max", "iPhone12,8": "iPhone SE 2", "iPhone13,1": "iPhone 12 mini", "iPhone13,2": "iPhone 12", "iPhone13,3": "iPhone 12 Pro", "iPhone13,4": "iPhone 12 Pro Max", "iPhone14,4": "iPhone 13 mini", "iPhone14,5": "iPhone 13", "iPhone14,2": "iPhone 13 Pro", "iPhone14,3": "iPhone 13 Pro Max", "iPhone14,6": "iPhone SE 3", "iPhone14,7": "iPhone 14", "iPhone14,8": "iPhone 14 Plus", "iPhone15,2": "iPhone 14 Pro", "iPhone15,3": "iPhone 14 Pro Max", "iPhone15,4": "iPhone 15", "iPhone15,5": "iPhone 15 Plus", "iPhone16,1": "iPhone 15 Pro", "iPhone16,2": "iPhone 15 Pro Max", "iPhone17,3": "iPhone 16", "iPhone17,4": "iPhone 16 Plus", "iPhone17,1": "iPhone 16 Pro", "iPhone17,2": "iPhone 16 Pro Max", "iPhone17,5": "iPhone 16e", "iPad4,1": "iPad Air", "iPad4,2": "iPad Air", "iPad4,3": "iPad Air", "iPad4,4": "iPad mini 2", "iPad4,5": "iPad mini 2", "iPad4,7": "iPad mini 3", "iPad4,8": "iPad mini 3", "iPad5,3": "iPad Air 2", "iPad5,4": "iPad Air 2", "iPad5,1": "iPad mini 4", "iPad5,2": "iPad mini 4", "iPad6,3": "iPad Pro 9.7", "iPad6,4": "iPad Pro 9.7", "iPad6,7": "iPad Pro 12.9", "iPad6,8": "iPad Pro 12.9", "iPad6,11": "iPad 5", "iPad6,12": "iPad 5", "iPad7,1": "iPad Pro 12.9 (2)", "iPad7,2": "iPad Pro 12.9 (2)", "iPad7,3": "iPad Pro 10.5", "iPad7,4": "iPad Pro 10.5", "iPad7,5": "iPad 6", "iPad7,6": "iPad 6", "iPad7,11": "iPad 7", "iPad7,12": "iPad 7", "iPad11,1": "iPad mini 5", "iPad11,2": "iPad mini 5", "iPad11,3": "iPad Air 3", "iPad11,4": "iPad Air 3", "iPad12,1": "iPad 9", "iPad12,2": "iPad 9", "iPad13,1": "iPad Air 4", "iPad13,2": "iPad Air 4", "iPad13,18": "iPad 10", "iPad13,19": "iPad 10", "iPad14,1": "iPad mini 6", "iPad14,2": "iPad mini 6", "iPad14,8": "iPad Air 5 (M1)", "iPad14,9": "iPad Air 5 (M1)"};
function chipVerdict(cpid){
  if(!cpid) return "";
  var c=parseInt(cpid,16);
  if(isNaN(c)) return "";
  if(c<=0x8015){
    if(c===0x8960||c===0x7000||c===0x7001) return "مسار A · تفتح بدون شبكة";
    return "مسار A · تفتح والشبكة تعمل";
  }
  if(c>=0x8020) return "مسار B · تحتاج إنترنت";
  return "";
}


function devRender(d){
  var box=document.getElementById("dev"), nm=document.getElementById("devName"),
      sub=document.getElementById("devSub"), md=document.getElementById("devMode");
  if(!d || !d.connected){
    box.className="dev off";
    nm.textContent="ما فيه جهاز موصول";
    sub.textContent="وصّل الآيفون بالكيبل، واضغط Trust على شاشته";
    md.textContent="—";
    return;
  }
  box.className="dev on";
  var pt=d.fields["Product Type"]||"";
  var nice=NAMES[pt]||d.fields["Device Name"]||(d.chip?("جهاز "+d.chip):"")||pt||"جهاز آبل";
  nm.textContent=nice;
  var bits=[];
  if(pt) bits.push(pt);
  if(d.fields["iOS Version"]) bits.push("iOS "+d.fields["iOS Version"]);
  if(d.fields["Chip ID"]) bits.push(d.fields["Chip ID"]);
  if(d.mode) bits.push(d.mode);
  if(d.via==="windows") bits.push("من ويندوز مباشرة");
  var v=chipVerdict(d.fields["CPID"]||"");
  if(v) bits.push(v);
  sub.textContent=bits.join(" · ")||"متصل";
  md.textContent=d.mode||"متصل";
}

function devPoll(){
  fetch("/api/device",{cache:"no-store"}).then(function(r){return r.json()})
    .then(function(d){ DEV.last=d; devRender(d); })
    .catch(function(){ devRender(null); });
}

devPoll(); setInterval(devPoll, 3000);

// ---- SSE live events ----
(function(){
  var live=document.getElementById("live");
  function setLive(on){ live.className="live"+(on?" on":""); }
  try{
    var es=new EventSource("/api/events");
    es.onopen=function(){ setLive(true); };
    es.onerror=function(){ setLive(false); };
    es.onmessage=function(m){
      var ev; try{ ev=JSON.parse(m.data); }catch(e){ return; }
      if(ev.kind==="device"){ devPoll(); }
      if(ev.kind==="attach"){ devPoll(); runDiag(); }
    };
  }catch(e){ setLive(false); }
})();

document.getElementById("attachBtn").addEventListener("click", function(){
  var b=this; b.disabled=true; b.textContent="جاري التمرير...";
  fetch("/api/attach",{method:"POST"}).then(function(r){return r.json()})
    .then(function(d){
      b.textContent = d.ok ? "تم التمرير" : "ما تم — شوف الفحص";
      devPoll(); runDiag();
    })
    .catch(function(){ b.textContent="فشل"; })
    .then(function(){ setTimeout(function(){ b.disabled=false; b.textContent="تمرير الجهاز الآن"; },2500); });
});

document.getElementById("detachBtn").addEventListener("click", function(){
  fetch("/api/detach",{method:"POST"}).then(function(){ devPoll(); });
});

fetch("/api/state").then(function(r){return r.json()}).then(function(s){
  if(s.sim){ document.getElementById("simbar").className="simbar on"; }
});


function diagRender(items){
  var box=document.getElementById("diagList");
  box.innerHTML="";
  items.forEach(function(it){
    var d=document.createElement("div");
    d.className="di "+it.status;
    var icon = it.status==="ok" ? "✓" : (it.status==="fail" ? "✕" : "!");
    var h = '<div class="ic">'+icon+'</div><div><div class="l">'+it.label+'</div>';
    if(it.detail) h += '<div class="d">'+it.detail+'</div>';
    if(it.fix && it.status!=="ok") h += '<div class="fx">'+it.fix+'</div>';
    h += '</div>';
    d.innerHTML=h;
    box.appendChild(d);
  });
}

function runDiag(){
  var box=document.getElementById("diagList");
  box.innerHTML='<div class="di diisabled">جاري الفحص…</div>';
  fetch("/api/diag",{cache:"no-store"}).then(function(r){return r.json()})
    .then(function(d){ diagRender(d.items||[]); })
    .catch(function(){ box.innerHTML='<div class="di fail"><div class="ic">✕</div><div><div class="l">ما قدرنا نفحص</div><div class="d">الجسر ما رد</div></div></div>'; });
}

document.getElementById("diagBtn").addEventListener("click", runDiag);
runDiag();
setInterval(runDiag, 15000);


S.el.start.addEventListener("click", start);
refreshState().catch(function(){ verdict("err","الجسر ما اشتغل","تأكد إن البرنامج شغال على 127.0.0.1."); });
</script>
</body>
</html>
"""

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
