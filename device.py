"""The Garmin watch on USB: find it, open its files, copy its FIT files.

The Instinct 2 is a small FAT disk: mtools reads it straight from the block device (read-only, never mounted,
so nothing can write to the watch). Watches that speak MTP are mounted with jmtpfs instead."""
import os, shutil, subprocess, tempfile, time
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

def disk():
    """/dev path of a Garmin USB disk, if one is plugged in."""
    for block in Path("/sys/block").glob("sd*"):
        node = block.resolve()
        while node != node.parent:
            vendor = node / "idVendor"
            if vendor.exists():
                if vendor.read_text().strip() == GARMIN:
                    return f"/dev/{block.name}"
                break
            node = node.parent
    return None

@contextmanager
def opened(where):
    """A folder holding the watch's GARMIN/ tree, for as long as the block runs."""
    # The disk appears a few seconds after the USB device.
    for _ in range(10):
        dev = disk()
        if dev: break
        time.sleep(2)
    if not dev:
        with mounted(where) as root:
            yield root
        return
    tmp = Path(tempfile.mkdtemp(prefix="garmin-", dir=Path(where).parent))
    try:
        p = subprocess.run(["mcopy", "-s", "-n", "-m", "-i", dev, "::/GARMIN", str(tmp)], capture_output=True, text=True,
                           env={**os.environ, "MTOOLS_SKIP_CHECK": "1"})
        if not (tmp / "GARMIN").is_dir():
            raise RuntimeError(f"mtools could not read {dev}: {(p.stderr or p.stdout).strip()[-300:]}")
        yield tmp
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

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
