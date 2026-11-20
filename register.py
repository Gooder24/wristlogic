"""Every metric wristlogic shows: what it needs (its gate), the method and how far to trust it.

Trust: A a published method on the input it was validated for; B a published method on a stand-in input;
C our own estimate, shown only with "experimental": true in config.json; "výrobca" the watch's own number.
A gate reads what metrics.py computed, so a metric is open exactly when its number exists; it adds why it is
not there yet and how much is left. `wristlogic odomkni` prints them all."""
from collections import namedtuple

Metric = namedtuple("Metric", "id name method trust gate")
Gate = namedtuple("Gate", "open why have need", defaults=(None, None, None))

NIGHTS_FOR_BASE = 5  # the baseline needs 4 earlier nights, so the 5th night is the first compared

def context(nights, days, samples):
    """What the gates look at: main nights, days and the number of samples of each signal."""
    mains = [n for n in nights if n.get("main")]
    return {"mains": mains, "last": mains[-1] if mains else None, "days": days, "samples": samples}

def nights_left(have, need, what="nocí"):
    return Gate(False, f"{have} z {need} {what}: ešte {need - have}", have, need)

def first_night(c):
    return Gate(True) if c["last"] else Gate(False, "zatiaľ žiadna noc: spi s hodinkami", 0, 1)

def last_night(key, why):
    """Open when the last night has the value, as the night's text shows it."""
    def gate(c):
        if not c["last"]: return first_night(c)
        return Gate(True) if c["last"].get(key) is not None else Gate(False, why)
    return gate

def debt(c):
    if not c["last"]: return first_night(c)
    have = c["last"].get("debt_nights", 0)
    return Gate(True) if have >= 4 else nights_left(have, 4, "nocí za posledných 7")

def regularity(c):
    if c["last"] and c["last"].get("sri") is not None: return Gate(True)
    return Gate(False, "treba aspoň 3 dni za posledných 7 s hodinkami na ruke aj v noci")

def compared(keys, need_all=False):
    """Open when the last night shows the value against its baseline („bežne“) for one of `keys` (all with need_all)."""
    def gate(c):
        last = c["last"]
        if not last: return first_night(c)
        ok = [bool(last.get(k)) and (last.get("base") or {}).get(k) is not None for k in keys]
        if all(ok) if need_all else any(ok): return Gate(True)
        missing = [k for k, o in zip(keys, ok) if not o and not last.get(k)]
        if missing and (need_all or len(missing) == len(keys)):
            return Gate(False, "posledná noc nemá " + " ani ".join(NAMES[k] for k in missing))
        has = all if need_all else any
        have = min(sum(1 for n in c["mains"] if has(n.get(k) for k in keys)), NIGHTS_FOR_BASE - 1)
        return nights_left(have, NIGHTS_FOR_BASE)
    return gate

NAMES = {"rhr": "kľudový tep", "hrv": "HRV", "resp": "dych"}

def yesterday(c):
    """The whole day before the last night's waking, which the night's text shows as „Včera“."""
    if c["last"]:
        from metrics import local
        from datetime import timedelta
        key = (local(c["last"]["wake"]).date() - timedelta(days=1)).isoformat()
        day = next((d for d in c["days"] if d["date"] == key), None)
    else:
        day = c["days"][-2] if len(c["days"]) > 1 else None
    if day and day["full_day"]: return Gate(True)
    worn = day["worn_h"] if day else 0
    return Gate(False, f"včera len {worn:.1f} h na ruke, treba 12 h".replace(".", ","))

def form(c):
    if c["days"] and c["days"][-1].get("form") is not None: return Gate(True)
    have = sum(1 for d in c["days"] if d["full_day"])
    return nights_left(have, 28, "dní s 12 h na ruke")

def ever(kind, why):
    return lambda c: Gate(True) if c["samples"].get(kind) else Gate(False, why, 0, 1)

def garmin_score(c):
    if not c["last"]: return first_night(c)
    if (c["last"].get("garmin") or {}).get("overall_sleep_score") is not None: return Gate(True)
    return Gate(False, "hodinky k poslednej noci skóre nezapísali")

def spo2(c):
    if c["last"] and c["last"].get("spo2"): return Gate(True)
    if not c["samples"].get("spo2"):
        return Gate(False, "pulzný oxymeter je vypnutý: zapni ho v hodinkách na spánok (úroveň 3), potom stačí 1 noc", 0, 1)
    return Gate(False, "posledná noc bez SpO₂ (oxymeter bol v noci vypnutý)", 0, 1)

METRICS = [
    Metric("stages", "Fázy spánku", "hodinky; proti PSG 60–80 % (Chinoy 2021)", "výrobca", first_night),
    Metric("sleep_score", "Skóre spánku Garmin", "hodinky", "výrobca", garmin_score),
    Metric("efficiency", "Efektivita spánku", "spánok / čas na hodinkách (AASM)", "A", first_night),
    Metric("need", "Potreba a splnenie", "potreba podľa veku: Watson 2015, Paruthi 2016", "A", first_night),
    Metric("debt", "Spánkový dlh za 7 dní", "súčet chýbajúceho spánku", "B", debt),
    Metric("rhr", "Kľudový tep", "najnižší 30-min priemer v spánku", "A",
           last_night("rhr", "v noci málo tepu (treba 5 vzoriek za 30 min)")),
    Metric("sri", "Pravidelnosť spánku (SRI)", "Phillips 2017", "A", regularity),
    Metric("parts", "Zložky zotavenia proti tvojmu bežnému", "z-skóre proti 30 nociam", "A", compared(("rhr", "hrv", "resp"))),
    Metric("deviation", "Signál odchýlky (kľudový tep a dych)", "prahy z-skóre; dych: Miller 2020", "B",
           compared(("rhr", "resp"), need_all=True)),
    Metric("trimp", "TRIMP (denná záťaž)", "Edwards 1993, zóny z rezervy tepu", "B", yesterday),
    Metric("form", "Kondícia, únava, forma", "Banister 1975, okná 42/7 dní", "B", form),
    Metric("vo2max", "VO₂max", "hodinky", "výrobca", ever("vo2max", "hodinky ho ešte neodhadli: treba beh alebo chôdzu vonku s GPS")),
    Metric("hrv", "Nočné HRV", "hodinky (priemer noci)", "výrobca", last_night("hrv", "hodinky ho k poslednej noci nezapísali")),
    Metric("spo2", "Nočné SpO₂", "priemer a minimum", "A",
           spo2),
    Metric("recovery", "Zotavenie 0–100", "naše váhy zložiek", "C",
           last_night("recovery", "chýba tvoje bežné (od 5. noci)")),
    Metric("strain", "Záťaž 0–21", "naša škála z TRIMP", "C", yesterday),
]

def status(nights, days, samples):
    """[(metric, gate)] in the order of METRICS."""
    c = context(nights, days, samples)
    return [(m, m.gate(c)) for m in METRICS]
