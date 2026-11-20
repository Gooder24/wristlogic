#!/usr/bin/env python3
"""wristlogic: sleep and health from Karchi's Garmin watch, local only.

    wristlogic import [DIR]   copy the FIT files from the plugged-in watch (or read them from DIR) and publish
    wristlogic                last night and today
    wristlogic dni [N]        the last N days (14)
    wristlogic odomkni        the watch, its signals, and which metrics are open, which locked and why
    wristlogic publish        write spanok.ics and health.json again

Data: ~/.local/share/wristlogic (fit/ is every file the watch ever had). Settings: ~/.config/wristlogic/config.json,
e.g. {"need_hours": 8.5, "birth_year": 2008, "experimental": true} (experimental: also recovery 0-100 and strain
0-21, our own estimates). Kalendarix subscribes to http://<asus>:8791/spanok.ics.
"""
import fcntl, json, os, statistics, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import device, fitimport, metrics, register

DATA = Path(os.environ.get("WRISTLOGIC_DATA", Path.home() / ".local/share/wristlogic"))
CONFIG = Path(os.environ.get("WRISTLOGIC_CONFIG", Path.home() / ".config/wristlogic/config.json"))

def config():
    try: return json.loads(CONFIG.read_text())
    except FileNotFoundError: return {}

def db():
    """The database. One of an older shape is built again from the files it had read, then published, so the
    calendar and health.json follow at once (the old file stays beside it)."""
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / "wristlogic.db"
    stale = DATA / ".publish"  # an upgrade not yet published: publish on the next run, also after a crash
    with open(DATA / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if fitimport.outdated(path):
            stale.touch()
            old = fitimport.upgrade(path, DATA / "fit")
            print(f"Databáza má novú podobu: prečítal som znova archív {DATA / 'fit'} (stará je {old.name}).", file=sys.stderr)
        con = fitimport.connect(path)
        if stale.exists():
            publish(con)
            stale.unlink()
    return con

EXPERIMENTAL = False  # config "experimental": recovery 0-100 and strain 0-21, our own estimates (register.py)

def hm(secs):
    secs = int(round(secs / 60)) * 60
    h, m = divmod(secs // 60, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"

def num(v, digits=0):
    return "–" if v is None else f"{v:.{digits}f}".replace(".", ",")

def compute(con):
    global EXPERIMENTAL
    cfg = config()
    EXPERIMENTAL = bool(cfg.get("experimental"))
    nights = metrics.nights(con, cfg.get("need_hours", 8.0))
    rests = [n["rhr"] for n in nights if n["main"] and n["rhr"]][-30:]
    days = metrics.days(con, cfg.get("birth_year"), statistics.median(rests) if rests else 60)
    return nights, days

# ------------------------------------------------------------------ text

STAGE_NAMES = {metrics.DEEP: "hlboký", metrics.LIGHT: "ľahký", metrics.REM: "REM", metrics.AWAKE: "bdenie", 0: "nemerané"}
RUNS = 40      # at most this many stretches in the course of a night (a watch that writes a level every minute)
SHORT = 5 * 60 # stretches shorter than this merge into the one before when there are more

def stage_lines(n):
    """The stages of one sleep: totals with their share of the time asleep, then the night stretch by stretch."""
    share = lambda k: f" ({round(100 * n[k] / max(1, n['asleep']))} %)"
    woke = (n.get("garmin") or {}).get("awakenings_count", n["awakenings"])
    lines = [f"Fázy: hlboký {hm(n['deep'])}{share('deep')} · ľahký {hm(n['light'])}{share('light')} · "
             f"REM {hm(n['rem'])}{share('rem')} · bdenie {hm(n['awake'])}" + (f" ({woke}× prebudený)" if woke else "")]
    runs = []
    for ts, lv, secs in n.get("spans") or []:
        if runs and runs[-1][1] == int(lv): runs[-1][2] += secs
        else: runs.append([ts, int(lv), secs])
    if len(runs) > RUNS:  # whole stretches shorter than SHORT go into the one before, then equal neighbours join
        kept = runs[:1]
        for r in runs[1:]:
            if r[2] < SHORT: kept[-1][2] += r[2]
            elif kept[-1][1] == r[1]: kept[-1][2] += r[2]
            else: kept.append(r)
        runs = kept
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
    stages, *course = stage_lines(n)
    lines = [stages,
             f"Spánok {hm(n['asleep'])} z {hm(n['end'] - n['start'])} na hodinkách "
             f"(zaspatie {t(n['onset']):%H:%M}, prebudenie {t(n['wake']):%H:%M}, "
             f"efektivita {round(100 * n['asleep'] / max(1, n['end'] - n['start']))} %)"]
    g = n.get("garmin") or {}
    if g.get("overall_sleep_score") is not None:
        sub = [f"{name} {g[k]}" for k, name in (("sleep_quality_score", "kvalita"), ("sleep_recovery_score", "zotavenie"))
               if g.get(k) is not None]
        lines.append(f"Garmin skóre spánku {g['overall_sleep_score']}" + (f" ({', '.join(sub)})" if sub else ""))
    if n.get("need"):
        lines.append(f"Potreba {hm(n['need'])} · splnené {n['performance']} %"
                     + (f" · spánkový dlh za 7 dní {hm(n['debt'])}" if n.get("debt_nights", 0) >= 4 else ""))
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
        if not any((n.get("base") or {}).get(k) for k in ("rhr", "hrv", "resp")):
            lines.append("Porovnanie s tvojím bežným: od 5. noci")
        elif EXPERIMENTAL and rec is not None:
            lines.append(f"Zotavenie {rec} % (experimentálne: naše váhy zložiek)")
        if n.get("sri") is not None: lines.append(f"Pravidelnosť spánku za 7 dní (SRI) {n['sri']} zo 100")
        if n.get("ill"): lines.append("Pozor: kľudový tep aj dych sú výrazne nad tvojím priemerom (býva to pred chorobou alebo po alkohole)")
    if day:
        # TRIMP and minutes of movement come from heart rate over the whole day: shown only after 12 h on the wrist.
        moved = (f"TRIMP {day['trimp']}" + (f" (záťaž {num(day['strain'], 1)}/21, experimentálne)" if EXPERIMENTAL else "")
                 + f", pohyb {day['moderate_min']} min stredne + {day['vigorous_min']} min intenzívne"
                 if day["full_day"] else f"na ruke len {num(min(day['worn_h'], 11.9), 1)} h, TRIMP a pohyb až po 12 h")
        lines.append(f"Včera: {num(day['steps'])} krokov, {moved}"
                     + (f", kondícia {day['fitness']}, forma {day['form']:+d}" if day["form"] is not None else ""))
    return lines + course  # the course is long: last, under the numbers

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
        out.append(f"Dnes {d['date']}: {num(d['steps'])} krokov, TRIMP zatiaľ {d['trimp']}, stres {num(d['stress'])}, "
                   f"VO₂max {num(d['vo2max'])}, nosené {num(d['worn_h'], 1)} h")
    return "\n\n".join(out)

def table(nights, days, count):
    by_wake = {metrics.local(n["wake"]).date().isoformat(): n for n in nights if n["main"]}
    rows = ["deň          spánok   hlb  REM  skóre  tep  dych   hrv  kroky  trimp  forma" + ("  zotav  záťaž" if EXPERIMENTAL else "")]
    for d in days[-count:]:
        n = by_wake.get(d["date"]) or {}
        g = (n.get("garmin") or {}).get("overall_sleep_score")
        rows.append(f"{d['date']}  {hm(n['asleep']) if n else '–':>8} {round(n['deep'] / 60) if n else '–':>4} "
                    f"{round(n['rem'] / 60) if n else '–':>4} {num(g):>6} {num(n.get('rhr')):>4} {num(n.get('resp'), 1):>5} "
                    f"{num(n.get('hrv')):>5} {num(d['steps']):>6} {num(d['trimp'] if d['full_day'] else None):>6} {'–' if d['form'] is None else f"{d['form']:+d}":>6}"
                    + (f" {num(n.get('recovery')):>6} {num(d['strain'] if d['full_day'] else None, 1):>6}" if EXPERIMENTAL else ""))
    return "\n".join(rows)

# ------------------------------------------------------------------ unlock

def sample_counts(con):
    return dict(con.execute("select kind, count(*) from samples group by kind"))

def devices(con):
    return [dict(zip(("serial", "manufacturer", "model", "software", "first_seen", "last_seen"), r))
            for r in con.execute("select serial, manufacturer, model, software, first_seen, last_seen from devices "
                                 "where serial != 'unknown' order by last_seen desc")]

SIGNALS = [("hr", "tep"), ("stress", "stres"), ("resp", "dych"), ("hrv5", "HRV po 5 min"), ("spo2", "SpO₂"),
           ("cycles:walking", "kroky"), ("battery", "batéria")]

def every(secs):
    return f"{secs // 60} min" + (f" {secs % 60} s" if secs % 60 else "") if secs >= 60 else f"{secs} s"

def unlock(con, nights, days):
    """The watch, how dense each of its signals is over the last 7 days, and each metric: open, locked and why."""
    out = []
    for d in devices(con):
        model = (d["model"] or "?").replace("_", " ").title()
        since = metrics.local(d["first_seen"]).date() if d["first_seen"] else None
        out.append(f"{model} · sériové č. {d['serial']}" + (f" · softvér {num(d['software'], 2)}" if d["software"] else "")
                   + (f" · súbory od {since.day}. {since.month}. {since.year}" if since else ""))
        week = (datetime.now(metrics.TZ).date().toordinal() - 7)
        first = datetime.fromordinal(week).date().isoformat()
        out.append("Signály za posledných 7 dní:")
        for kind, name in SIGNALS:
            rows = con.execute("select n, period, covered from coverage where device = ? and kind = ? and day > ?",
                               (d["serial"], kind, first)).fetchall()
            if not rows:
                out.append(f"  {name:<14} nič" + (" (pulzný oxymeter je vypnutý)" if kind == "spo2" else "")); continue
            period = sorted(r[1] for r in rows)[len(rows) // 2]
            covered = round(100 * sum(r[2] for r in rows) / 7)
            out.append(f"  {name:<14} {sum(r[0] for r in rows)} vzoriek, zvyčajne každých {every(period)}, pokrytie {covered} % času")
        out.append("")
    gates = register.status(nights, days, sample_counts(con))
    shown = [(m, g) for m, g in gates if m.trust != "C"]
    for title, part in (("Odomknuté", [x for x in shown if x[1].open]), ("Zamknuté", [x for x in shown if not x[1].open])):
        out.append(f"{title} ({len(part)}):")
        for m, g in part:
            out.append(f"  {'✔' if g.open else '✗'} {m.name} · {m.trust} · {m.method}" + ("" if g.open else f"\n      {g.why}"))
    out.append("Experimentálne (C, naše odhady): " + ", ".join(m.name for m, _ in gates if m.trust == "C")
               + (" · zapnuté" if EXPERIMENTAL else " · zapneš ich \"experimental\": true v ~/.config/wristlogic/config.json"))
    return "\n".join(out)

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
        elif EXPERIMENTAL and n.get("recovery") is not None: title += f" · zotavenie {n['recovery']} %"
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
    # Our own estimates (trust C) leave only with "experimental": true.
    hidden = {"spans"} | (set() if EXPERIMENTAL else {"recovery", "strain"})
    plain = [{k: v for k, v in n.items() if k not in hidden} for n in nights]
    daily = [{k: v for k, v in d.items() if k not in hidden} for d in days]
    gates = [{"id": m.id, "name": m.name, "method": m.method, "trust": m.trust, "shown": m.trust != "C" or EXPERIMENTAL,
              "open": g.open, "why": g.why, "have": g.have, "need": g.need}
             for m, g in register.status(nights, days, sample_counts(con))]
    write(public / "health.json", json.dumps({"devices": devices(con), "metrics": gates, "nights": plain, "days": daily},
                                             ensure_ascii=False))
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
    if cmd == "odomkni":
        print(unlock(con, nights, days)); return 0
    if cmd == "dni":
        print(table(nights, days, int(argv[1]) if len(argv) > 1 else 14)); return 0
    if cmd in ("dnes", "noc"):
        print(report(nights, days)); return 0
    print(__doc__); return 2

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
