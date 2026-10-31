#!/usr/bin/env python3
"""justmgz.exe - one-click installer/launcher for the tr4mpass panel.
No cmd scripting: everything runs through Python subprocess. English console,
Arabic UI in the browser.
"""
import ctypes, os, shutil, subprocess, sys, time, urllib.request, webbrowser
from pathlib import Path

APP = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "app"
WSL_ENGINE = "/opt/justmgz/eng"
WSL_APP = "/opt/justmgz/app"
PORT = 8099
RUNSERVER = ("env TR4MPASS_DIR=%s python3 %s/justmgz-engine.py" % (WSL_ENGINE, WSL_APP))

def log(msg=""):
    print(msg, flush=True)

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

    deadline = time.time() + wait
    while True:
        devs = usbipd_devices()
        if devs:
            busid = devs[0]
            run([p, "bind", "--busid", busid], quiet=True)
            run([p, "attach", "--wsl", "--busid", busid], quiet=True)
            time.sleep(1.5)
            rc, out = run([p, "list"], quiet=True)
            for line in out.splitlines():
                if busid in line and "attached" in line.lower():
                    log("  iPhone passed to Ubuntu  (%s)" % busid)
                    return True
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
    ok = (APP / "justmgz-engine.py").is_file()
    log("  result  : %s" % ("OK" if ok else "MISSING ENGINE FILE"))
    return 0 if ok else 1

def main():
    log("=" * 52)
    log("  justmgz - one click setup and launch")
    log("=" * 52)

    if "--selftest" in sys.argv:
        return selftest()

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
        log("  no iPhone passed through yet.")
        log("  the panel will still open - plug the phone, then run this file again,")
        log("  or run: usbipd attach --wsl --busid <id>   (after: usbipd list)")
    log("")

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
        log("  Try:  wsl --shutdown   then run this file again")
        input("  Press Enter to close...")
        return 1

    webbrowser.open("http://127.0.0.1:%d/" % PORT)
    log("")
    log("=" * 52)
    log("  Panel is running:  http://127.0.0.1:%d" % PORT)
    log("  KEEP THIS WINDOW OPEN - closing it stops the panel.")
    log("=" * 52)
    log("")
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
