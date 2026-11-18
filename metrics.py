"""Nights and days computed from zdravie.db, with published methods only.

Sleep stages and Garmin's sleep score come from the watch. On top of them:

- resting heart rate: the lowest 30-minute mean heart rate while asleep (as Oura and Whoop measure it)
- sleep need, performance and 7-day debt (Whoop's model; need from the AASM consensus, 8 h by default)
- Sleep Regularity Index over 7 days (Phillips et al. 2017, as in pyActigraphy): the chance of being in the
  same state (asleep or awake) 24 hours apart, scaled to -100..100
- recovery 0-100: tonight against the personal 30-night baseline (z-scores of overnight HRV, or of Garmin's
  HRV-based stress when the watch has no HRV, of resting heart rate, respiration and sleep performance), in
  the spirit of Whoop's recovery; an estimate, not Whoop's proprietary formula
- daily load: Edwards' TRIMP (minutes in five zones weighted 1-5), with the zones taken from heart rate
  reserve (50-60-70-80-90 %, Karvonen) because it runs over the whole day and not one workout; strain on a
  0-21 scale as a log of it; Banister's fitness-fatigue model: fitness (42-day mean), fatigue (7-day), form =
  the difference, shown once the watch was worn at least 12 hours on 28 days
- an illness flag when resting heart rate and respiration both rise well above baseline (Mishra et al. 2020,
  Nature Biomedical Engineering; Whoop and Oura use the same signals)
"""
import json, math, statistics
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Bratislava")
AWAKE, LIGHT, DEEP, REM = 1, 2, 3, 4
SPLIT = 12 * 3600      # a sleep level never stands longer than this
NAP_MIN = 20 * 60      # shorter sleeps are not shown
CAP = 5 * 60           # a sample stands for at most this long when the next one is late
AWAKENING = 6 * 60     # shorter awake stretches are not counted as waking up

def local(ts):
    return datetime.fromtimestamp(ts, TZ)

def series(db, kind, start=None, end=None):
    q, args = "select ts, value from samples where kind = ?", [kind]
    if start is not None: q += " and ts >= ?"; args.append(start)
    if end is not None: q += " and ts < ?"; args.append(end)
    return db.execute(q + " order by ts", args).fetchall()

def weighted(points, end=None, cap=CAP):
    """(ts, value, seconds) with each sample standing until the next one, at most `cap`."""
    out = []
    for i, (ts, v) in enumerate(points):
        nxt = points[i + 1][0] if i + 1 < len(points) else (end if end is not None else ts + 60)
        out.append((ts, v, max(0, min(nxt - ts, cap))))
    return out

# ------------------------------------------------------------------ sleep

def sleeps(db):
    """Every sleep the watch staged, oldest first.

    A sleep file of the Instinct 2 holds the window the watch slept in (start and stop events) and a sleep level at
    every change of stage; each level holds until the next record or the stop. Files without a window are grouped
    by their samples: dense ones (a level every minute) hold a level for at most two steps and split at half an
    hour with no samples; sparse ones hold it until the next record and split only where another file begins half
    an hour after an awake record, or after half a day."""
    points = db.execute("select ts, value, src from samples where kind = 'sleep' order by ts").fetchall()
    marks = db.execute("select ts, value, src from samples where kind = 'sleep_window' order by ts").fetchall()
    windows = {}
    for ts, v, src in marks:
        if v == 1: windows.setdefault(src, []).append([ts, None])
        elif windows.get(src) and windows[src][-1][1] is None: windows[src][-1][1] = ts
    by_src = {}
    for ts, _, src in points: by_src.setdefault(src, []).append(ts)
    step = {src: int(statistics.median([b - a for a, b in zip(t, t[1:])] or [60])) for src, t in by_src.items()}
    cap = {src: (max(60, 2 * st) if st <= 120 else SPLIT) for src, st in step.items()}
    groups, cur, bounds = [], [], []
    for p in points:
        win = next((w for w in windows.get(p[2], []) if w[1] and w[0] <= p[0] <= w[1]), None)
        if win:
            if not groups or bounds[-1] is not win:
                groups.append([]); bounds.append(win)
            cur = []
            groups[-1].append(p)
            continue
        gap = p[0] - cur[-1][0] if cur else 0
        dense = cur and cap[cur[-1][2]] < SPLIT
        if cur and (gap > SPLIT or (gap > 1800 and (dense or (p[2] != cur[-1][2] and int(cur[-1][1]) == AWAKE)))):
            cur = []
        if not cur:
            groups.append(cur); bounds.append(None)
        cur.append(p)
    out = []
    for g, win in zip(groups, bounds):
        limit = max(cap[src] for _, _, src in g)
        end = win[1] if win else g[-1][0] + min(step[g[-1][2]], 60)
        first = win[0] if win else g[0][0]
        g = [(ts, int(lv)) for ts, lv, _ in g]
        if win:
            # Within a window each record names the stage of the time since the previous one (the last record
            # falls on the stop): read so, awake time and awakenings match Garmin's own assessment.
            spans, prev = [], first
            for ts, lv in g:
                if ts > prev: spans.append((prev, lv, ts - prev))
                prev = ts
        else:
            spans = weighted(g, end, cap=limit)
        stages = {AWAKE: 0, LIGHT: 0, DEEP: 0, REM: 0}
        for ts, level, secs in spans:
            if level in stages: stages[level] += secs
        asleep = stages[LIGHT] + stages[DEEP] + stages[REM]
        if asleep < NAP_MIN: continue
        # In bed for the whole window; time awake before falling asleep and after the last waking counts in bed.
        sleeping = [(ts, secs) for ts, lv, secs in spans if lv in (LIGHT, DEEP, REM)]
        # An awakening is at least AWAKENING awake between two stretches of sleep (Garmin counts only longer ones).
        runs = []
        for ts, lv, secs in spans:
            if runs and runs[-1][1] == lv and runs[-1][0] + runs[-1][2] == ts: runs[-1][2] += secs
            else: runs.append([ts, lv, secs])
        awakenings = sum(1 for ts, lv, secs in runs
                         if lv == AWAKE and secs >= AWAKENING and sleeping[0][0] < ts < sleeping[-1][0])
        onset, wake = sleeping[0][0], sleeping[-1][0] + sleeping[-1][1]
        # A short daytime sleep is a nap; a short sleep at night (a part of the night the watch has) is still the night.
        middle = local((onset + wake) // 2).hour
        out.append({"start": first, "end": end, "asleep": asleep, "awake": stages[AWAKE], "light": stages[LIGHT],
                    "deep": stages[DEEP], "rem": stages[REM], "awakenings": awakenings, "onset": onset, "wake": wake,
                    "spans": spans, "main": asleep >= 3 * 3600 or not 9 <= middle < 20})
    # One night per night: of short night-time sleeps around the same midnight, only the longest is the night.
    night = lambda s: local((s["onset"] + s["wake"]) // 2 - 12 * 3600).date()
    longest = {}
    for s in out:
        if s["main"]:
            key = night(s)
            longest[key] = max(longest.get(key, s), s, key=lambda o: (o["asleep"], o["wake"]))
    for s in out:
        if s["main"] and s["asleep"] < 3 * 3600:
            s["main"] = longest[night(s)] is s
    return out

def lowest_mean(points, window=1800, need=5):
    """Lowest mean over any `window` seconds with at least `need` samples."""
    best, j, total = None, 0, 0.0
    for i in range(len(points)):
        while j < len(points) and points[j][0] < points[i][0] + window:
            total += points[j][1]; j += 1
        n = j - i
        if n >= need:
            m = total / n
            best = m if best is None or m < best else best
        total -= points[i][1]
    return best

def mean(points):
    return sum(v for _, v in points) / len(points) if points else None

def baseline(values, floor):
    """(mean, sd) of the last 30 values, when there are at least 4."""
    values = [v for v in values if v is not None][-30:]
    if len(values) < 4: return None
    return statistics.fmean(values), max(statistics.pstdev(values), floor)

def z(value, base):
    return None if value is None or base is None else (value - base[0]) / base[1]

def phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))

def regularity(db, end, nights):
    """Sleep Regularity Index of the 7 days before `end`. Minutes with no heart rate and no sleep are unknown."""
    start = end - 7 * 86400
    minutes = (end - start) // 60
    state = [None] * minutes
    for ts, _ in series(db, "hr", start - 600, end + 600):
        for m in range(max(0, (ts - start) // 60 - 10), min(minutes, (ts - start) // 60 + 10)):
            state[m] = 0
    for s in nights:
        # The whole sleep, so a stage that began before the 7 days still covers their first minutes.
        for ts, lv, secs in s["spans"]:
            first = (ts - start) // 60
            for m in range(max(0, first), min(minutes, first + max(1, secs // 60))):
                state[m] = 1 if int(lv) in (LIGHT, DEEP, REM) else 0
    pairs = [(a, b) for a, b in zip(state, state[1440:]) if a is not None and b is not None]
    if len(pairs) < 3 * 1440: return None
    return round(200 * sum(a == b for a, b in pairs) / len(pairs) - 100)

def nights(db, need_hours=8.0):
    """Each sleep with its body signals, baseline and recovery."""
    all_sleeps = sleeps(db)
    assess = [(ts, json.loads(d)) for ts, d in db.execute("select ts, data from assess order by ts")]
    out = []
    for s in all_sleeps:
        hr = series(db, "hr", s["onset"], s["wake"])
        n = dict(s)
        n["rhr"] = lowest_mean(hr)
        n["hr_avg"] = mean(hr)
        n["resp"] = mean(series(db, "resp", s["onset"], s["wake"]))
        n["stress"] = mean(series(db, "stress", s["onset"], s["wake"]))
        n["spo2"] = mean(series(db, "spo2", s["onset"], s["wake"]))
        hrv = series(db, "hrv", s["start"], s["end"] + 4 * 3600)
        n["hrv"] = hrv[-1][1] if hrv else None
        a = next((d for ts, d in assess if s["start"] <= ts <= s["end"] + 3600), None)
        n["garmin"] = a
        out.append(n)

    mains = [n for n in out if n["main"]]
    need = need_hours * 3600
    for i, n in enumerate(mains):
        prev = mains[:i]
        n["need"] = need
        n["performance"] = min(100, round(100 * n["asleep"] / need))
        week = [m for m in mains[: i + 1] if m["wake"] > n["wake"] - 7 * 86400]
        n["debt"] = max(0, sum(need - m["asleep"] for m in week))
        n["debt_nights"] = len(week)
        n["sri"] = regularity(db, n["wake"], mains[: i + 1])
        base = {k: baseline([m[k] for m in prev], floor) for k, floor in
                (("rhr", 2.0), ("resp", 0.5), ("stress", 3.0), ("hrv", 5.0))}
        n["base"] = {k: (round(v[0], 1) if v else None) for k, v in base.items()}
        parts = []
        if n["hrv"] is not None and base["hrv"]:
            parts.append((0.45, z(n["hrv"], base["hrv"])))
        elif n["stress"] is not None and base["stress"]:
            parts.append((0.30, -z(n["stress"], base["stress"])))
        if n["rhr"] is not None and base["rhr"]:
            parts.append((0.25, -z(n["rhr"], base["rhr"])))
        if n["resp"] is not None and base["resp"]:
            parts.append((0.10, -max(0.0, z(n["resp"], base["resp"]))))
        if parts:
            parts.append((0.25, (n["performance"] - 85) / 15))
            score = sum(w * v for w, v in parts) / sum(w for w, _ in parts)
            n["recovery"] = round(100 * phi(0.3 + score))
        else:
            n["recovery"] = None  # fewer than 4 earlier nights: no baseline yet
        zr, zb = z(n["rhr"], base["rhr"]), z(n["resp"], base["resp"])
        n["ill"] = bool(zr is not None and zb is not None and zr > 2 and zb > 1.5)
    return out

# ------------------------------------------------------------------ days

def hr_max(db, birth_year=None):
    if birth_year:
        return 208 - 0.7 * (date.today().year - birth_year)  # Tanaka et al. 2001
    hr = sorted(v for _, v in series(db, "hr", int(datetime.now().timestamp()) - 180 * 86400))
    observed = hr[int(len(hr) * 0.999)] if len(hr) > 100 else 0
    return max(195, observed)

def day_bounds(d):
    start = datetime(d.year, d.month, d.day, tzinfo=TZ)
    return int(start.timestamp()), int((start + timedelta(days=1)).timestamp())

def days(db, birth_year=None, rest=60):
    """Each local day with any data: steps, load, strain and the fitness-fatigue model."""
    first = db.execute("select min(ts), max(ts) from samples").fetchone()
    if not first or first[0] is None: return []
    hmax = hr_max(db, birth_year)
    kinds = [k for (k,) in db.execute("select distinct kind from samples where kind like 'cycles:%'")]
    d, last = local(first[0]).date(), local(first[1]).date()
    out, fitness, fatigue, worn_days = [], 0.0, 0.0, 0
    while d <= last:
        a, b = day_bounds(d)
        hr = series(db, "hr", a, b)
        load, moderate, vigorous, worn = 0.0, 0, 0, 0
        for ts, v, secs in weighted(hr, b):
            worn += secs
            hrr = (v - rest) / (hmax - rest)
            if hrr >= 0.5: load += secs / 60 * min(5, int((hrr - 0.5) * 10) + 1)
            if hrr >= 0.6: vigorous += secs
            elif hrr >= 0.4: moderate += secs
        steps = 0
        for k in kinds:
            if k.split(":", 1)[1] in ("walking", "running"):
                row = db.execute("select max(value) from samples where kind = ? and ts >= ? and ts < ?", (k, a, b)).fetchone()
                steps += int(row[0] or 0)
        worn_days += worn >= 12 * 3600  # fitness and form mean something only after four weeks on the wrist
        fitness += (load - fitness) / 42
        fatigue += (load - fatigue) / 7
        stress = [v for _, v in series(db, "stress", a, b)]
        vo2 = db.execute("select value from samples where kind = 'vo2max' and ts < ? order by ts desc limit 1", (b,)).fetchone()
        out.append({"date": d.isoformat(), "steps": steps, "trimp": round(load), "strain": round(min(21, 7 * math.log1p(load / 25)), 1),
                    "moderate_min": round(moderate / 60), "vigorous_min": round(vigorous / 60), "worn_h": round(worn / 3600, 1),
                    "stress": round(statistics.fmean(stress)) if stress else None,
                    **({"fitness": round(fitness), "fatigue": round(fatigue), "form": round(fitness - fatigue)}
                       if worn_days >= 28 else {"fitness": None, "fatigue": None, "form": None}),
                    "vo2max": vo2[0] if vo2 else None, "hr_max": round(hmax)})
        d += timedelta(days=1)
    return out
