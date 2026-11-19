#!/usr/bin/env python3
"""wristlogic: sleep and health from Karchi's Garmin watch, local only.

    wristlogic import [DIR]   copy the FIT files from the plugged-in watch (or read them from DIR) and publish
    wristlogic                last night and today
    wristlogic dni [N]        the last N days (14)
    wristlogic publish        write spanok.ics and health.json again

Data: ~/.local/share/wristlogic (fit/ is every file the watch ever had). Settings: ~/.config/wristlogic/config.json,
e.g. {"need_hours": 8.5, "birth_year": 2008}. Kalendarix subscribes to http://<asus>:8791/spanok.ics.
"""
import fcntl, json, os, statistics, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import device, fitimport, metrics

DATA = Path(os.environ.get("WRISTLOGIC_DATA", Path.home() / ".local/share/wristlogic"))
CONFIG = Path(os.environ.get("WRISTLOGIC_CONFIG", Path.home() / ".config/wristlogic/config.json"))

def config():
    try: return json.loads(CONFIG.read_text())
    except FileNotFoundError: return {}

def db():
    DATA.mkdir(parents=True, exist_ok=True)
    return fitimport.connect(DATA / "wristlogic.db")

def hm(secs):
    secs = int(round(secs / 60)) * 60
    h, m = divmod(secs // 60, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"

def num(v, digits=0):
    return "–" if v is None else f"{v:.{digits}f}".replace(".", ",")

def compute(con):
    cfg = config()
    nights = metrics.nights(con, cfg.get("need_hours", 8.0))
    rests = [n["rhr"] for n in nights if n["main"] and n["rhr"]][-30:]
    days = metrics.days(con, cfg.get("birth_year"), statistics.median(rests) if rests else 60)
    return nights, days

# ------------------------------------------------------------------ text

STAGE_NAMES = {metrics.DEEP: "hlboký", metrics.LIGHT: "ľahký", metrics.REM: "REM", metrics.AWAKE: "bdenie", 0: "nemerané"}
RUNS = 24      # at most this many stretches in the course of a night (a watch that writes a level every minute)
SHORT = 5 * 60 # stretches shorter than this merge into the one before when there are more

def stage_lines(n):
    """The stages of one sleep: totals with their share of the time asleep, then the night stretch by stretch."""
    share = lambda k: f" ({round(100 * n[k] / max(1, n['asleep']))} %)"
    woke = (n.get("garmin") or {}).get("awakenings_count", n["awakenings"])
    lines = [f"Fázy: hlboký {hm(n['deep'])}{share('deep')} · ľahký {hm(n['light'])}{share('light')} · "
             f"REM {hm(n['rem'])}{share('rem')} · bdenie {hm(n['awake'])}" + (f" ({woke}× prebudený)" if woke else "")]
    runs = []
    for ts, lv, secs in n.get("spans") or []:
        if runs and (runs[-1][1] == int(lv) or (len(n["spans"]) > RUNS and secs < SHORT)): runs[-1][2] += secs
        else: runs.append([ts, int(lv), secs])
    while len(runs) > RUNS:  # still too many: the shortest stretch goes into the one before it
        i = min(range(1, len(runs)), key=lambda i: runs[i][2])
        runs[i - 1][2] += runs.pop(i)[2]
        if i < len(runs) and runs[i][1] == runs[i - 1][1]: runs[i - 1][2] += runs.pop(i)[2]
    if runs:
        lines.append("Priebeh: " + " → ".join(f"{metrics.local(ts):%H:%M} {STAGE_NAMES.get(lv, '?')} {hm(secs)}"
                                               for ts, lv, secs in runs))
    return lines

def night_lines(n, day=None):
    t = metrics.local
    lines = [*stage_lines(n),
             f"Spánok {hm(n['asleep'])} z {hm(n['end'] - n['start'])} na hodinkách "
             f"(zaspatie {t(n['onset']):%H:%M}, prebudenie {t(n['wake']):%H:%M}, "
             f"efektivita {round(100 * n['asleep'] / max(1, n['end'] - n['start']))} %)"]
    g = n.get("garmin") or {}
    if g.get("overall_sleep_score") is not None:
        sub = [f"{name} {g[k]}" for k, name in (("sleep_quality_score", "kvalita"), ("sleep_recovery_score", "zotavenie"))
               if g.get(k) is not None]
        lines.append(f"Garmin skóre spánku {g['overall_sleep_score']}" + (f" ({', '.join(sub)})" if sub else ""))
    if n.get("need"):
        lines.append(f"Potreba {hm(n['need'])} · splnené {n['performance']} % · spánkový dlh za 7 dní {hm(n['debt'])}")
    body = []
    if n["rhr"]: body.append(f"kľudový tep {round(n['rhr'])}" + (f" (bežne {round(n['base']['rhr'])})" if n.get("base", {}).get("rhr") else ""))
    if n["hrv"]: body.append(f"HRV {round(n['hrv'])} ms" + (f" (bežne {round(n['base']['hrv'])})" if n.get("base", {}).get("hrv") else ""))
    if n["resp"]: body.append(f"dych {num(n['resp'], 1)}/min" + (f" (bežne {num(n['base']['resp'], 1)})" if n.get("base", {}).get("resp") else ""))
    if n["stress"] is not None: body.append(f"stres v spánku {round(n['stress'])}")
    if n["spo2"]: body.append(f"SpO₂ {round(n['spo2'])} %")
    if body:
        text = ", ".join(body)
        lines.append(text[0].upper() + text[1:])
    if n.get("main"):
        rec = n.get("recovery")
        lines.append(f"Zotavenie {rec} % (odhad podľa tvojho priemeru)" if rec is not None
                     else "Zotavenie: ukážem od 5. noci, keď poznám tvoj priemer")
        if n.get("sri") is not None: lines.append(f"Pravidelnosť spánku za 7 dní (SRI) {n['sri']} zo 100")
        if n.get("ill"): lines.append("Pozor: kľudový tep aj dych sú výrazne nad tvojím priemerom (býva to pred chorobou alebo po alkohole)")
    if day:
        lines.append(f"Včera: {num(day['steps'])} krokov, záťaž {num(day['strain'], 1)}/21 (TRIMP {day['trimp']}), "
                     f"pohyb {day['moderate_min']} min stredne + {day['vigorous_min']} min intenzívne"
                     + (f", kondícia {day['fitness']}, forma {day['form']:+d}" if day["form"] is not None else ""))
    return lines

DAYS = ["Po", "Ut", "St", "Št", "Pi", "So", "Ne"]

def report(nights, days, count=1):
    out = []
    mains = [n for n in nights if n["main"]]
    by_day = {d["date"]: d for d in days}
    if not nights:
        return "Zatiaľ žiadny spánok: pripoj hodinky k asusu (a pred tým ich nesynchronizuj s Garmin Connect)."
    for n in mains[-count:]:
        wake = metrics.local(n["wake"])
        prev = (wake.date().toordinal() - 1)
        day = by_day.get(datetime.fromordinal(prev).date().isoformat())
        out.append(f"{DAYS[wake.weekday()]} {wake.day}. {wake.month}.  " + "\n  ".join(night_lines(n, day)))
    if days:
        d = days[-1]
        out.append(f"Dnes {d['date']}: {num(d['steps'])} krokov, záťaž {num(d['strain'], 1)}/21, stres {num(d['stress'])}, "
                   f"VO₂max {num(d['vo2max'])}, nosené {num(d['worn_h'], 1)} h")
    return "\n\n".join(out)

def table(nights, days, count):
    by_wake = {metrics.local(n["wake"]).date().isoformat(): n for n in nights if n["main"]}
    rows = ["deň          spánok   hlb  REM  skóre  tep  dych  zotav  kroky  záťaž  forma"]
    for d in days[-count:]:
        n = by_wake.get(d["date"]) or {}
        g = (n.get("garmin") or {}).get("overall_sleep_score")
        rows.append(f"{d['date']}  {hm(n['asleep']) if n else '–':>8} {round(n['deep'] / 60) if n else '–':>4} "
                    f"{round(n['rem'] / 60) if n else '–':>4} {num(g):>6} {num(n.get('rhr')):>4} {num(n.get('resp'), 1):>5} "
                    f"{num(n.get('recovery')):>6} {num(d['steps']):>6} {num(d['strain'], 1):>6} {'–' if d['form'] is None else f"{d['form']:+d}":>6}")
    return "\n".join(rows)

# ------------------------------------------------------------------ calendar

def esc(text):
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

def fold(line):
    out, raw = [], line.encode()
    while len(raw) > 73:
        cut = 73
        while (raw[cut] & 0xC0) == 0x80: cut -= 1  # never split a UTF-8 character
        out.append(raw[:cut].decode()); raw = raw[cut:]
    out.append(raw.decode())
    return "\r\n ".join(out)

def utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y%m%dT%H%M%SZ")

NAME = "wristlogic"

def entries(nights, days):
    """One calendar entry per sleep: (uid, start, end, title, description)."""
    by_day = {d["date"]: d for d in days}
    for n in nights:
        wake = metrics.local(n["wake"]).date()
        day = by_day.get(datetime.fromordinal(wake.toordinal() - 1).date().isoformat()) if n["main"] else None
        score = (n.get("garmin") or {}).get("overall_sleep_score")
        title = ("Spánok " if n["main"] else "Šlofík ") + hm(n["asleep"]).replace(" min", "")
        if score is not None: title += f" · {score}"
        elif n.get("recovery") is not None: title += f" · zotavenie {n['recovery']} %"
        yield f"spanok-{n['start']}@{NAME}", n["start"], n["end"], title, "\n".join(night_lines(n, day))

def ics(nights, days):
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:-//Karchi//{NAME}//SK", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:Spánok", "X-WR-TIMEZONE:Europe/Bratislava"]
    stamp = utc(int(datetime.now().timestamp()))
    for uid, start, end, title, text in entries(nights, days):
        lines += ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}", f"DTSTART:{utc(start)}", f"DTEND:{utc(end)}",
                  fold(f"SUMMARY:{esc(title)}"), fold(f"DESCRIPTION:{esc(text)}"), "TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"

# Weft's calendar on asus (github.com/Gooder24/weft server/calendar/kalendar.py), which Kalendarix syncs too.
# Empty WEFT_CALENDAR: leave it alone (the tests).
WEFT = os.environ.get("WEFT_CALENDAR", str(Path.home() / "matrix-spike/calendar"))
CAL_ID = f"{NAME}-spanok"  # with uids ending in @NAME, Weft keeps the calendar read-only: this program owns it
COLOR = "#6f7bd8"

def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

# Kalendarix's earlier subscription to the feed: this calendar replaces it, so it is taken out of Weft's calendar
# (the merge then takes it out of Kalendarix on x270 as well) and the nights do not show twice.
FEED = "http://100.110.180.15:8791/spanok.ics"

def to_weft(nights=None, days=()):
    """Puts the calendar Spánok into Weft's calendar through its three-way merge, so Karchi's own changes
    (its colour, hiding it) and other writers' edits made meanwhile stay. Without nights it only takes the old
    subscription out. Returns a reason when it did not write."""
    if not WEFT: return "off"
    try: master = json.loads((Path(WEFT) / "data/calendars.json").read_text())
    except FileNotFoundError: return "no Weft calendar"
    cals = [c for c in master.get("calendars") or [] if c.get("sourceUrl") != FEED]
    if nights is not None:
        old = next((c for c in cals if c.get("id") == CAL_ID), None)
        events = [{"uid": uid, "title": title, "description": text, "notes": text, "location": "", "start": iso(start),
                   "end": iso(end), "allDay": False, "rrule": None, "exdates": [], "alarmMinutes": ""}
                  for uid, start, end, title, text in entries(nights, days)]
        cal = {**(old or {"id": CAL_ID, "name": "Spánok", "color": COLOR, "customColor": COLOR, "visible": True}), "events": events}
        cals = [cal if c is old else c for c in cals] + ([] if old else [cal])
    if cals == master.get("calendars"): return None
    p = subprocess.run(["python3", "-I", str(Path(WEFT) / "kalendar.py"), "merge"], capture_output=True, text=True,
                       input=json.dumps({"base": master, "local": {**master, "calendars": cals}}, ensure_ascii=False), timeout=120)
    return f"Weft calendar: {(p.stderr or p.stdout).strip()[-300:]}" if p.returncode else None

def write(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)

def publish(con):
    nights, days = compute(con)
    public = DATA / "public"
    public.mkdir(parents=True, exist_ok=True)
    write(public / "spanok.ics", ics(nights, days))
    plain = [{k: v for k, v in n.items() if k != "spans"} for n in nights]
    write(public / "health.json", json.dumps({"nights": plain, "days": days}, ensure_ascii=False))
    if (why := to_weft(nights, days)) and why != "off": print(why, file=sys.stderr)
    return nights, days

# ------------------------------------------------------------------ import

def import_watch(con):
    serials = device.plugged()
    if not serials:
        return None
    archive = DATA / "fit" / (serials[0] or "garmin")
    kept = []
    with device.opened(DATA / "mnt") as root:
        for src, rel in device.fit_files(root):
            kept.append((fitimport.keep_copy(src, archive, rel)[1], f"{archive.name}/{rel}"))
    return fitimport.import_files(con, kept)

def main(argv):
    cmd = argv[0] if argv else "dnes"
    con = db()
    if cmd == "import":
        with open(DATA / ".lock", "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if len(argv) > 1:
                root = Path(argv[1]).resolve()
                new = fitimport.import_files(con, sorted((p, str(p)) for p in root.rglob("*") if p.suffix.lower() == ".fit"))
            else:
                new = import_watch(con)
                if new is None:
                    if (why := to_weft()) and why != "off": print(why, file=sys.stderr)
                    print("Hodinky nie sú pripojené."); return 0
            nights, days = publish(con)
            bad = {p: c for p, c in new.items() if "error" in c}
            print(f"Nových súborov {len(new) - len(bad)}, spánkov spolu {len(nights)}"
                  + (f", nečitateľných {len(bad)}: " + "; ".join(f"{Path(p).name}: {c['error']}" for p, c in bad.items()) if bad else ""))
            totals = {}
            for c in new.values():
                for k, v in c.items():
                    if k != "error": totals[k] = totals.get(k, 0) + v
            known = {k.removesuffix("_mesgs"): v for k, v in totals.items() if not k.isdigit()}
            if known: print("Správy: " + ", ".join(f"{k} {v}" for k, v in sorted(known.items())))
        return 0
    if cmd == "publish":
        publish(con); return 0
    nights, days = compute(con)
    if cmd == "dni":
        print(table(nights, days, int(argv[1]) if len(argv) > 1 else 14)); return 0
    if cmd in ("dnes", "noc"):
        print(report(nights, days)); return 0
    print(__doc__); return 2

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
