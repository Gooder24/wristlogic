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

def resting(c):
    if not c["last"]: return first_night(c)
    return Gate(True) if c["last"].get("rhr") else Gate(False, "v noci málo tepu (treba 5 vzoriek za 30 min)")

def debt(c):
    if not c["last"]: return first_night(c)
    have = c["last"].get("debt_nights", 0)
    return Gate(True) if have >= 4 else nights_left(have, 4, "nocí za posledných 7")

def regularity(c):
    if c["last"] and c["last"].get("sri") is not None: return Gate(True)
    return Gate(False, "treba aspoň 3 dni za posledných 7 s hodinkami na ruke aj v noci")

def baseline(*keys):
    def gate(c):
        last = c["last"]
        if last and any((last.get("base") or {}).get(k) is not None for k in keys): return Gate(True)
        have = sum(1 for n in c["mains"] if any(n.get(k) is not None for k in keys))
        if have >= NIGHTS_FOR_BASE and last and all(last.get(k) is None for k in keys):
            return Gate(False, "posledná noc nemá túto hodnotu")
        return nights_left(min(have, NIGHTS_FOR_BASE - 1), NIGHTS_FOR_BASE)
    return gate

def deviation(c):
    base = (c["last"] or {}).get("base") or {}
    if base.get("rhr") is not None and base.get("resp") is not None: return Gate(True)
    return baseline("resp" if base.get("rhr") is not None else "rhr")(c)

def worn_day(c):
    full = [d for d in c["days"][:-1] if d["worn_h"] >= 12]  # today is not over yet
    if full: return Gate(True)
    best = max((d["worn_h"] for d in c["days"][:-1]), default=0)
    return Gate(False, f"žiadny celý deň s 12 h na ruke (najviac {best:.0f} h)".replace(".", ","))

def form(c):
    if c["days"] and c["days"][-1].get("form") is not None: return Gate(True)
    have = sum(1 for d in c["days"] if d["worn_h"] >= 12)
    return nights_left(have, 28, "dní s 12 h na ruke")

def signal(kind, why):
    return lambda c: Gate(True) if c["samples"].get(kind) else Gate(False, why, 0, 1)

def garmin_score(c):
    if any((n.get("garmin") or {}).get("overall_sleep_score") is not None for n in c["mains"][-7:]): return Gate(True)
    return Gate(False, "hodinky za posledných 7 nocí skóre nezapísali")

METRICS = [
    Metric("stages", "Fázy spánku", "hodinky; proti PSG 60–80 % (Chinoy 2021)", "výrobca", first_night),
    Metric("sleep_score", "Skóre spánku Garmin", "hodinky", "výrobca", garmin_score),
    Metric("efficiency", "Efektivita spánku", "spánok / čas na hodinkách (AASM)", "A", first_night),
    Metric("need", "Potreba a splnenie", "potreba podľa veku: Watson 2015, Paruthi 2016", "A", first_night),
    Metric("debt", "Spánkový dlh za 7 dní", "súčet chýbajúceho spánku", "B", debt),
    Metric("rhr", "Kľudový tep", "najnižší 30-min priemer v spánku", "A", resting),
    Metric("sri", "Pravidelnosť spánku (SRI)", "Phillips 2017", "A", regularity),
    Metric("parts", "Zložky zotavenia proti tvojmu bežnému", "z-skóre proti 30 nociam", "A", baseline("rhr", "hrv", "resp")),
    Metric("deviation", "Signál odchýlky (kľudový tep a dych)", "prahy z-skóre; dych: Miller 2020", "B", deviation),
    Metric("trimp", "TRIMP (denná záťaž)", "Edwards 1993, zóny z rezervy tepu", "B", worn_day),
    Metric("form", "Kondícia, únava, forma", "Banister 1975, okná 42/7 dní", "B", form),
    Metric("vo2max", "VO₂max", "hodinky", "výrobca", signal("vo2max", "hodinky ho ešte neodhadli: treba beh alebo chôdzu vonku s GPS")),
    Metric("hrv", "Nočné HRV", "hodinky (priemer noci)", "výrobca", signal("hrv", "hodinky ho zatiaľ nezapísali")),
    Metric("spo2", "Nočné SpO₂", "priemer a minimum", "A",
           signal("spo2", "pulzný oxymeter je vypnutý: zapni ho v hodinkách na spánok (úroveň 3)")),
    Metric("recovery", "Zotavenie 0–100", "naše váhy zložiek", "C", baseline("rhr", "hrv", "resp")),
    Metric("strain", "Záťaž 0–21", "naša škála z TRIMP", "C", worn_day),
]

def status(nights, days, samples):
    """[(metric, gate)] in the order of METRICS."""
    c = context(nights, days, samples)
    return [(m, m.gate(c)) for m in METRICS]
