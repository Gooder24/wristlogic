"""The Garmin watch on USB: find it, mount it over MTP (jmtpfs), copy its FIT files, unmount."""
import subprocess, time
from contextlib import contextmanager
from pathlib import Path

GARMIN = "091e"  # Garmin's USB vendor id

def plugged():
    """Serial numbers of the Garmin devices on USB (an empty string when one has none)."""
    found = []
    for dev in Path("/sys/bus/usb/devices").glob("*"):
        try:
            if (dev / "idVendor").read_text().strip() == GARMIN:
                serial = dev / "serial"
                found.append(serial.read_text().strip() if serial.exists() else "")
        except OSError:
            pass
    return found

@contextmanager
def mounted(where):
    where = Path(where)
    where.mkdir(parents=True, exist_ok=True)
    subprocess.run(["fusermount3", "-u", "-q", str(where)], check=False)  # left over from a killed run
    # The watch needs a few seconds after plugging in before it answers MTP.
    for attempt in range(6):
        p = subprocess.run(["jmtpfs", str(where)], capture_output=True, text=True)
        if p.returncode == 0 and any(where.iterdir()):
            break
        subprocess.run(["fusermount3", "-u", "-q", str(where)], check=False)
        time.sleep(5)
    else:
        raise RuntimeError(f"jmtpfs could not open the watch: {(p.stderr or p.stdout).strip()[-300:]}")
    try:
        yield where
    finally:
        subprocess.run(["fusermount3", "-u", str(where)], check=False)

def fit_files(root):
    """(path, path relative to GARMIN/) of every FIT file on the mounted watch."""
    root = Path(root)
    for garmin in list(root.glob("GARMIN")) + list(root.glob("*/GARMIN")):
        for path in garmin.rglob("*"):
            if path.suffix.lower() == ".fit" and path.is_file():
                yield path, path.relative_to(garmin)
