# zdravie

Sleep and health from Karchi's Garmin Instinct 2, local only (no Garmin Connect). Plugged into asus, the
watch is mounted over MTP, every FIT file it has is kept in `~/.local/share/zdravie/fit/` (the watch deletes
sleep and monitoring files after a Connect sync), and each night becomes an event in the Kalendarix
calendar „Spánok“, subscribed from `http://100.110.180.15:8791/spanok.ics`.

Each event carries Garmin's own staging and sleep score, and what `metrics.py` computes from the raw data
with published methods: resting heart rate, sleep need and debt, Sleep Regularity Index, a recovery estimate
against the personal baseline, an illness flag, daily strain (TRIMP) and the fitness-fatigue model. The
docstring of `metrics.py` names each method.

    zdravie              last night and today
    zdravie dni 14       a table of the last days
    zdravie import [DIR] from the watch, or from a folder of FIT files (e.g. a Garmin export)

Setup on asus: `sudo ./install.sh root` once (jmtpfs, mtools, udev rule), then `./install.sh`. Settings in
`~/.config/zdravie/config.json`: `need_hours` (8), `birth_year` (for maximum heart rate; otherwise the
highest one seen, at least 195).

Tests: `.venv/bin/pip install -r requirements-test.txt && .venv/bin/python -m unittest discover tests`
(a fake watch written by `tests/fake_watch.py`).
