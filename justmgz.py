#!/usr/bin/env python3
"""justmgz.exe - one-click installer/launcher for the tr4mpass panel.
No cmd scripting: everything runs through Python subprocess. English console,
Arabic UI in the browser.
"""
import ctypes, os, shutil, subprocess, sys, time, urllib.request, webbrowser
try:
    import webview  # pywebview: native window (WebView2)
except Exception:
    webview = None
from pathlib import Path

APP = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "app"
WSL_ENGINE = "/opt/justmgz/eng"
WSL_APP = "/opt/justmgz/app"
PORT = 8099
RUNSERVER = ("env TR4MPASS_DIR=%s python3 %s/justmgz-engine.py" % (WSL_ENGINE, WSL_APP))

DIAG = []

def log(msg=""):
    print(msg, flush=True)

def note(msg):
    DIAG.append(str(msg))

def write_diag():
    try:
        import datetime
        path = os.path.join(os.path.expanduser("~"), "justmgz-diag.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("justmgz diagnostic log\n")
            f.write("time: %s\n" % datetime.datetime.now().isoformat(timespec="seconds"))
            f.write("=" * 60 + "\n")
            f.write("\n".join(DIAG))
        log("")
        log("  diagnostic file: %s" % path)
        return path
    except Exception as e:
        log("  could not write diagnostic file: %s" % e)
        return ""

def hide_console():
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass

def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def elevate():
    try:
        params = " ".join('"%s"' % a for a in sys.argv[1:])
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        return rc > 32
    except Exception:
        return False

def run(args, timeout=None, quiet=False):
    """Run a command, return (rc, output)."""
    try:
        p = subprocess.run(args, capture_output=True, timeout=timeout)
        out = (p.stdout or b"") + (p.stderr or b"")
        txt = out.decode("utf-8", "ignore").strip()
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except FileNotFoundError:
        return 127, "not found: %s" % args[0]
    except Exception as e:
        return 1, str(e)
    note("> " + " ".join(args))
    note("  rc=%d  out=%s" % (p.returncode, txt[:600].replace("\n", "\\n")))
    if not quiet and txt:
        log(txt)
    return p.returncode, txt

def wsl(*args, timeout=None, quiet=False):
    return run(["wsl.exe"] + list(args), timeout=timeout, quiet=quiet)

def wsl_bash(script, timeout=None, quiet=False):
    return run(["wsl.exe", "-u", "root", "-e", "bash", "-lc", script], timeout=timeout, quiet=quiet)


def usbipd_path():
    for c in (r"C:\Program Files\usbipd-win\usbipd.exe",):
        if os.path.isfile(c):
            return c
    rc, _ = run(["where", "usbipd"], quiet=True)
    return "usbipd" if rc == 0 else None

def usbipd_devices():
    p = usbipd_path()
    if not p:
        return []
    rc, out = run([p, "list"], quiet=True)
    found = []
    for line in out.splitlines():
        if "apple" in line.lower():
            parts = line.split()
            if parts:
                found.append(parts[0])
    return found

def apple_on_windows():
    cmd = ("Get-PnpDevice -PresentOnly | Where-Object { $_.FriendlyName -match 'Apple' } "
           "| Select-Object -First 8 Status,FriendlyName | Format-Table -AutoSize | Out-String")
    rc, out = run(["powershell", "-NoProfile", "-Command", cmd], quiet=True)
    note("apple devices on windows:\n" + out)
    return out.strip()

def ensure_usb(wait=0):
    p = usbipd_path()
    if not p:
        log("  usbipd not installed - installing...")
        run(["winget", "install", "--exact", "--silent",
             "--accept-package-agreements", "--accept-source-agreements",
             "dorssel.usbipd-win"], timeout=900, quiet=True)
        p = usbipd_path()
        if not p:
            log("  could not install usbipd")
            return False

    note("usbipd: " + str(p))
    rc, ver = run([p, "version"], quiet=True)
    note("usbipd version: " + ver)
    rc, lst = run([p, "list"], quiet=True)
    note("usbipd list before:\n" + lst)

    deadline = time.time() + wait
    while True:
        devs = usbipd_devices()
        if devs:
            busid = devs[0]
            rc, bo = run([p, "bind", "--busid", busid], quiet=True)
            note("bind rc=%d out=%s" % (rc, bo))
            attached = False
            for attempt in range(3):
                rc, ao = run([p, "attach", "--wsl", "--busid", busid], quiet=True)
                note("attach try %d rc=%d out=%s" % (attempt + 1, rc, ao))
                time.sleep(2.0)
                rc, out = run([p, "list"], quiet=True)
                note("usbipd list after try %d:\n%s" % (attempt + 1, out))
                for line in out.splitlines():
                    if busid in line and "attached" in line.lower():
                        attached = True
                        break
                if attached:
                    log("  iPhone passed to Ubuntu  (%s)" % busid)
                    return True
                run([p, "detach", "--busid", busid], quiet=True)
                time.sleep(1.0)
            log("  found iPhone on %s but attach failed" % busid)
            log("  open an elevated PowerShell and run: usbipd attach --wsl --busid %s" % busid)
            return False
        if time.time() > deadline:
            return False
        sys.stdout.write(".")
        sys.stdout.flush()
        time.sleep(2)

def step(n, text):
    log("")
    log("Step %d/7 - %s" % (n, text))

def fail(title, hint=""):
    log("")
    log("  [X] " + title)
    if hint:
        log("      " + hint)
    log("")
    input("  Press Enter to close...")
    sys.exit(1)

def health(timeout=3):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False

def selftest():
    log("justmgz selftest")
    log("  python  : %s" % sys.version.split()[0])
    log("  frozen  : %s" % hasattr(sys, "frozen"))
    log("  app dir : %s" % APP)
    log("  files   : %s" % ", ".join(sorted(p.name for p in APP.glob("*"))))
    log("  webview : %s" % ("yes" if webview is not None else "NO"))
    if webview is not None:
        try:
            log("  wv ver  : %s" % getattr(webview, "__version__", "?"))
        except Exception:
            pass
    ok = (APP / "justmgz-engine.py").is_file()
    log("  result  : %s" % ("OK" if ok else "MISSING ENGINE FILE"))
    return 0 if ok else 1

def main():
    log("=" * 52)
    log("  justmgz - one click setup and launch")
    log("=" * 52)

    if "--selftest" in sys.argv:
        return selftest()

    if "--diag" in sys.argv:
        note("mode: diag")
        p = usbipd_path()
        note("usbipd path: %s" % p)
        if p:
            rc, out = run([p, "list"], quiet=True)
            note("usbipd list:\n" + out)
        rc, out = wsl("-u", "root", "-e", "lsusb", quiet=True)
        note("lsusb:\n" + out)
        rc, out = wsl("-u", "root", "-e", "bash", "-lc", "cd %s && ./tr4mpass -d 2>&1 | head -40" % WSL_ENGINE, quiet=True)
        note("tr4mpass -d:\n" + out)
        write_diag()
        input("Press Enter to close...")
        return 0

    if not is_admin():
        log("")
        log("  Asking for administrator rights...")
        if elevate():
            return 0
        fail("Could not get admin rights", "Right click the file and choose 'Run as administrator'.")

    # 1 - WSL
    step(1, "checking WSL")
    rc, _ = run(["where", "wsl"], quiet=True)
    if rc != 0:
        log("  WSL is not installed. Installing Ubuntu (one restart needed)...")
        run(["wsl.exe", "--install", "-d", "Ubuntu"], timeout=1800)
        log("")
        log("  Restart Windows, then run this file again.")
        input("  Press Enter to close...")
        return 0
    rc, _ = wsl("-u", "root", "-e", "true", quiet=True)
    if rc != 0:
        log("  Ubuntu distro missing. Installing...")
        run(["wsl.exe", "--install", "-d", "Ubuntu"], timeout=1800)
        log("  Open Ubuntu once, then run this file again.")
        input("  Press Enter to close...")
        return 0
    log("  ok")

    # 2 - engine present?
    step(2, "checking engine")
    rc, _ = wsl("-u", "root", "-e", "test", "-x", WSL_ENGINE + "/tr4mpass", quiet=True)
    have_engine = (rc == 0)
    log("  engine: %s" % ("present" if have_engine else "missing"))

    if not have_engine:
        step(3, "installing libraries (1-3 min)")
        pkgs = ("build-essential git pkg-config python3 libimobiledevice-dev "
                "libirecovery-1.0-dev libusb-1.0-0-dev libplist-dev libcurl4-openssl-dev "
                "libssl-dev libssh2-1-dev libusbmuxd-dev psmisc curl")
        rc, out = wsl_bash("apt-get update -qq && apt-get install -y " + pkgs, timeout=1800)
        if rc != 0:
            wsl_bash("add-apt-repository -y universe >/dev/null 2>&1; apt-get update -qq", timeout=900, quiet=True)
            rc, out = wsl_bash("apt-get install -y " + pkgs, timeout=1800)
        if rc != 0:
            fail("Library install failed", "Check internet inside Ubuntu: wsl -u root apt-get update")

        step(4, "downloading and building the engine (2-5 min)")
        script = ("set -e; mkdir -p /opt/justmgz; "
                  "if [ ! -d %s/.git ]; then git clone --depth 1 https://github.com/tr4m0ryp/tr4mpass %s; fi; "
                  "cd %s; if [ ! -f .patched ]; then patch -p1 < '%s/fix-build.patch'; touch .patched; fi; make -j4"
                  % (WSL_ENGINE, WSL_ENGINE, WSL_ENGINE, WSL_APP))
        rc, out = wsl_bash(script, timeout=1800)
        if rc != 0:
            fail("Engine build failed", "See the messages above.")
        log("  engine ready")
    else:
        log("  skipping install")

    # 3 - copy app files
    step(5, "copying panel files")
    wsl("-u", "root", "-e", "mkdir", "-p", WSL_APP, quiet=True)
    for f in APP.glob("*"):
        rc, out = run(["wsl.exe", "-u", "root", "cp", "-f", str(f), WSL_APP + "/" + f.name], quiet=True)
        if rc != 0:
            log("  warning: could not copy %s" % f.name)
    log("  ok")

    # 4 - usb passthrough
    step(6, "passing the iPhone to Ubuntu")
    log("  plug your iPhone now if it is not connected (waiting up to 45s)")
    if not ensure_usb(wait=45):
        log("")
        win = apple_on_windows()
        if not win:
            log("  Windows itself does not see any Apple device.")
            log("  Fix: install 'Apple Devices' from the Microsoft Store (it installs the USB driver),")
            log("  or use a different cable/port, then run this file again.")
        else:
            log("  Windows sees: " + win.replace("\n", " | ")[:200])
        log("")
        log("  the panel will still open - plug the phone, then run this file again,")
        log("  or run: usbipd attach --wsl --busid <id>   (after: usbipd list)")
    log("")

    # diagnostics for the device side
    rc, ls = wsl("-u", "root", "-e", "lsusb", quiet=True)
    note("lsusb inside ubuntu:\n" + ls)
    if "apple" not in ls.lower():
        log("  note: no Apple device inside Ubuntu yet")
    rc, dv = wsl("-u", "root", "-e", "bash", "-lc", "cd %s && ./tr4mpass -d 2>&1 | head -40" % WSL_ENGINE, quiet=True)
    note("tr4mpass -d:\n" + dv)

    # 5 - server
    step(7, "starting the panel")
    wsl_bash("fuser -k %d/tcp 2>/dev/null" % PORT, quiet=True)
    time.sleep(1)
    proc = subprocess.Popen(["wsl.exe", "-u", "root", "-e", "bash", "-lc", RUNSERVER],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="ignore", bufsize=1)

    ok = False
    for _ in range(40):
        if health(2):
            ok = True
            break
        if proc.poll() is not None:
            break
        time.sleep(0.5)

    if not ok:
        log("")
        log("  [X] The panel did not answer on port %d." % PORT)
        log("  Output from the bridge:")
        try:
            out = proc.stdout.read(4000) if proc.stdout else ""
            log(out)
        except Exception:
            pass
        log("")
        write_diag()
        log("  Try:  wsl --shutdown   then run this file again")
        input("  Press Enter to close...")
        return 1

    write_diag()
    url = "http://127.0.0.1:%d/" % PORT
    log("")
    log("=" * 52)
    log("  Opening the app window...")
    log("=" * 52)

    if webview is not None:
        hide_console()
        try:
            webview.create_window("justmgz", url, width=440, height=920,
                                  min_size=(380, 620), background_color="#0A0E13")
            webview.start()
        except Exception as ex:
            log("  window failed (%s) - opening in browser" % ex)
            try:
                ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 5)
            except Exception:
                pass
            webbrowser.open(url)
            input("  Press Enter to stop...")
    else:
        webbrowser.open(url)
        log("  keep this window open - closing it stops the panel")
        input("  Press Enter to stop...")
    try:
        for line in proc.stdout:
            print(line.rstrip())
    except KeyboardInterrupt:
        pass
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
    return 0

if __name__ == "__main__":
    sys.exit(main())
