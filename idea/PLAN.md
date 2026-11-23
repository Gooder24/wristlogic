# Plan: Ownbeat, a universal app for what wearables measure

Written 18–20 November 2026, translated from Slovak. "The author's data" means one Garmin Instinct 2 Solar worn for
a few weeks; it is an example, not a study.

## 1. In one sentence

An app that reads any watch, ring or strap, shows which sensors it has, and computes from them everything that
published methods allow. Every number has a source and a confidence. Where the data does not suffice, it shows
nothing and says what is missing.

## 2. Starting point (the `wristlogic` engine)

- The author's database: 13 nights, 53 activities, heart rate since August 2025 (from activities).
- Stress and breathing are stored every minute, heart rate every 1–2 min. Steps are written only when they change
  (median gap 7 min), which is coarser than an accelerometer for circadian measures.
- The nightly HRV summary exists for 10 nights, but the files hold 889 five-minute `hrv_value` records. Battery
  (`battery`, 791 records) is written only during activities on this model. Both are read since phase 0.
- SpO₂: 0 samples (the pulse oximeter was off).
- Three numbers the engine computed have no published method in that form, and were moved to "Experimental":
  - recovery 0–100: the z-scores are fine, the weights 0.45/0.25/0.10/0.25 are ours;
  - strain 0–21: `7·ln(1+TRIMP/25)` is our scale; only TRIMP is published;
  - TRIMP over a whole day with heart-rate-reserve zones: Edwards defined it for training and % of maximum.

## 3. Onboarding, screen by screen

Everything works from the keyboard; the main action is preselected and runs on Enter. No account, no sign-in.

| # | Screen | What you see | What happens by itself |
|---|---|---|---|
| 1 | **Connect a source** | USB watch, folder/export, Gadgetbridge, Health Connect, Apple Health, account (Oura, Whoop, Polar, Fitbit) | A connected Garmin is found and import starts without a click |
| 2 | **What I found** | "13 nights, 53 activities, heart rate since 9 Aug 2025" and what could not be read and why | Files are copied into an archive; the watch is not touched |
| 3 | **Your device** | The device card (section 4) | The model comes from the data (`device_info`), not from a question |
| 4 | **How much to measure** | Levels (section 5) with cost and what they unlock; the current level is already marked from the data | Nothing is asked if you change nothing |
| 5 | **Today** | Today's numbers. Locked tiles are visible with the reason: "HRV band: 4 more nights" | – |

A second device goes through screen 1 again; then screen **Who measures what** (section 7) replaces screen 4.

## 4. Device card

One card per device, three columns: **sensor → signal → what it gives**.

Example for the author's Instinct 2 Solar (from the data, not the brochure):

| Sensor | Signal and density | Vendor app shows | We add | Not possible |
|---|---|---|---|---|
| Optical heart rate (PPG) | HR every 1–2 min, 1 s during activity; stress and breathing every 1 min; HRV every 5 min at night | HR, resting HR, stress, breathing, HRV status, VO₂max | HRV band and night curve, nocturnal HR dip, time of HR minimum, HR recovery after exercise | ECG, blood pressure |
| Pulse oximeter | **off**, 0 samples | SpO₂ | night mean and minimum | apnoea (that is a diagnosis) |
| Accelerometer | steps on change (median 7 min), sleep stages | steps, sleep, sleep score | regularity (SRI), circadian rhythm, chronotype, social jetlag | – |
| Skin temperature | **no sensor** | – | – | cycle, temperature trend |

Rules:

- Density is measured from the user's files, not described from documentation.
- "Vendor shows / does not show" is a claim about someone else's product: each row links the official manual and the
  date it was checked, or it is not shown. Always about the feature, never about people ("the app does not show").
- A switched-off sensor shows what it would unlock and what it costs (link to section 5).
- A missing sensor is stated plainly. Nothing is estimated from it.
- The device database is one file per device in the repo (`devices/<vendor>-<model>.json`): a new device is a new
  file, not new code.

## 5. "Measure more → unlock"

The level is what the user does; the app recognises it from the data. Battery cost is never guessed. The Instinct 2
writes battery to FIT only during activities, so its daily drain cannot be measured from its files. Where a device
logs battery all the time, show the real drain a week before and after; elsewhere say it is unknown.

| Level | What you do | Cost | What unlocks | Data needed |
|---|---|---|---|---|
| 0 Training | watch only for sport | none | training TRIMP, zones, HR recovery, VO₂max check | 1 session; ACWR 28 days |
| 1 Daytime | 12+ h a day on the wrist | wearing it | steps, active minutes vs WHO, daily load, fitness/fatigue/form | at once; form 28 days |
| 2 At night | sleep with it | comfort, charging in the day | sleep, efficiency, resting HR | 1 night |
| | | | 7-day sleep debt | 4 of 7 nights |
| | | | recovery components, deviation signal | 5 nights, stable from 14 |
| | | | SRI, nocturnal HR dip, time of minimum, HRV curve | 7 nights |
| | | | HRV band, circadian measures, chronotype, social jetlag | 14 nights (2 weekends) |
| | | | HR above steps (CuSum) | 28 days |
| 3 Pulse ox in sleep | switch it on | battery (vendor says noticeable); judge by time between charges where not logged | night SpO₂ (mean, minimum), altitude effect | 1 night; trend 7 |
| 4 Second device | chest strap, ring or second watch | price, more charging | device comparison, HRV from RR intervals (strap), temperature (ring), higher confidence | 7 shared nights |
| 5 Tags | 5 s a day: alcohol, illness, late caffeine | attention | "after alcohol your HRV is X lower" on your own nights | 5 tagged + 14 normal nights |

The **Unlock** screen:

- One row per locked metric: what is missing, what to do, how much longer ("9 of 14 nights").
- Each level has "worth it?": what it adds against what it costs. After unlocking, show what it actually brought
  (made-up example: "14 nights of SpO₂: mean 95 %, minimum 91 %, nothing unusual: you can switch it off").
- A way back: leaving a level keeps the history; metrics lock again only when the data really runs out.
- No badges, streaks or confetti. Unlocking is a new chart, not a reward.

## 6. Metric catalogue

✔ built in `wristlogic`, ▸ next, ○ later. Confidence: **A** published method on the input it was validated for;
**B** published method on a substitute input; **C** our own estimate (hidden by default).

| Metric | Inputs | Method and source | Shows | Hidden when |
|---|---|---|---|---|
| ✔ Sleep stages and score | watch | vendor; stage accuracy vs PSG 60–80 % (Chinoy 2021) | always, as "the vendor says" | never passed off as ours |
| ✔ Sleep efficiency | sleep window, stages | sleep / time in bed (AASM) · A | 1 night | no window |
| ✔ Need, fulfilment, 7-day debt | sleep | need by age: Watson 2015, Paruthi 2016 · A (debt is a sum, B) | 1 night | fewer than 4 of 7 nights |
| ✔ Resting HR | HR in sleep | lowest 30-min mean · A | 5+ samples in window | sparse HR |
| ✔ Regularity (SRI) | sleep/wake per minute | Phillips 2017 · A | 3+ day pairs, better 7 | days not worn |
| ✔ Recovery components | HRV, resting HR, breathing | z-scores vs 30 nights · A | 5th night | no baseline |
| ✔ Recovery 0–100 | same + sleep | our weights · **C** | "Experimental" only | by default |
| ✔ Deviation signal | resting HR, breathing | z-score thresholds; breathing: Miller 2020 · B | 5th night | no baseline |
| ✔ TRIMP | HR, max HR | Edwards 1993 · A for training, B for a whole day | training / 12 h worn | less wear |
| ✔ Strain 0–21 | TRIMP | our scale · **C** | "Experimental" only | by default |
| ✔ Fitness, fatigue, form | daily TRIMP | Banister 1975, windows 42/7 days · B | 28 days of 12 h | gaps in wear |
| ▸ HRV band and variability | nightly HRV | 7-day mean of ln and CV: Plews 2013, Kiviniemi 2007 · B (vendor mean, not RR) | 14 nights | fewer than 4 of last 7 |
| ▸ Night HRV curve | 5-min HRV | description, no score · A | night with 80 % coverage | gaps |
| ▸ Nocturnal HR dip | HR day/night | dip < 10 % as a marker: Ben-Dov 2007 · A | 12 h day + night | day not worn |
| ▸ Time of HR minimum, "night after alcohol" | HR in sleep | late minimum and higher HR: Pietilä 2018 · B | 7 nights of baseline | short night (< 4 h) |
| ▸ HR above steps | HR, steps | RHR-Diff and CuSum: Mishra 2020 · A | 28 days of baseline | < 12 h worn |
| ▸ Circadian rhythm | steps, HR | cosinor: Cornelissen 2014; IS/IV/RA: Van Someren 1999, pyActigraphy · B (steps, not acceleration) | 7 whole days | days under 20 h |
| ▸ Chronotype, social jetlag | sleep, free/work days | MCTQ: Roenneberg 2003; Wittmann 2006 · A | 2 weekends | free days unknown |
| ▸ ACWR | daily TRIMP | Gabbett 2016; descriptive only, critique Impellizzeri 2020 · B | 28 days | gaps |
| ▸ HR recovery after exercise | 1 s HR after the end | drop in 60 s: Cole 1999 · A | recording runs 60 s after effort | HR sparser than 10 s |
| ▸ VO₂max check, fitness age | watch VO₂max, age, resting HR, activity | HUNT: Nes 2011, 2014 · B | VO₂max + profile | age or waist missing |
| ○ Active minutes vs WHO | HR | 150–300 min a week: Bull 2020 · A | 7 days | fewer than 5 days worn |
| ○ Night SpO₂ | oximeter | mean, minimum · A | level 3 | – |
| ○ HRV from RR, thresholds from DFA α1 | chest strap | RMSSD (Task Force 1996); Rogers 2021 · A | level 4 | artefacts above 5 % |
| ○ Your own effect of a tag | tags + any metric | difference of tagged and normal nights, with an interval · B | 5 + 14 nights | fewer |

Free days for the chronotype can come from the user's calendar instead of a question.

## 7. Several devices: who measures what

- **One signal, one source at a time.** Devices are never silently averaged.
- **The default source is chosen automatically**: better sensor type (ECG strap > PPG on a finger at night > PPG on
  the wrist), then density, then coverage. The reason is written beside each signal.
- **Settings → Sources**: a signal × device table; reorder with the arrow keys; separately for day and night.
- **Overlap**: the main source feeds the metrics, the second is a thin second line in the chart, with the
  difference underneath: "3 beats on average, 95 % of readings within ±6" (Bland & Altman 1986).
- **Disagreement over a threshold**: the metric gets a mark and lower confidence; nothing is hidden or corrected.
- **Gaps** are filled from a second source only if the user allows it, and the filled part looks different.
- **Baselines are per device.** After a watch change the baseline starts again; the old one carries over only after
  7 shared nights, when the offset between devices is known.
- **Vendor scores** (sleep score, Body Battery, Readiness) stay with their device as "the vendor says".

## 8. Trust and verification

1. **Source beside the number.** Each metric has a citation, inputs and an A/B/C class in code; the same is one key
   press away in the app.
2. **Gates.** A metric declares what it needs (signal, density, day coverage, nights of baseline). If the gate fails,
   the result is "locked: reason", not a number.
3. **Check against the vendor.** Where the watch gives its own value, compare: resting HR, sleep length and wake,
   nightly HRV (ours from 5-min values vs its summary), VO₂max. A **Trust** screen shows the mean difference over
   30 days. A large difference is a bug on our side or a different definition; either is stated.
4. **Check against reference code.** SRI and IS/IV/RA against pyActigraphy on the same data, cosinor against a
   published example, as tests in the repo.
5. **C is hidden.** Our own unpublished estimates show only with "Experimental" switched on, always labelled.
6. **Independent review** of each metric before release.

Not promised: sleep staging better than the device, numbers from a sensor that is not there, any diagnosis.

## 9. Architecture

```
adapters ──> common schema (SQLite) ──> metric register ──> health.json ──> app, CLI, calendar
```

- **Adapters** (one file per source, returning schema rows; raw files always archived):
  - FIT over USB and from a folder: built (`device.py`, `fitimport.py`).
  - Gadgetbridge: its SQLite database export.
  - Apple Health: `export.zip` from the iPhone.
  - Health Connect: data lives only on the phone; needs an export or a small Android app. Not checked which path is
    easiest today.
  - Oura, Whoop, Polar, Fitbit: official APIs with the user's own token; read each developer agreement before release
    (the Garmin Health API is for companies only, hence FIT).
- **Schema**: `device` (vendor, model, serial, sensors); `stream` (device, signal, sensor, unit, raw or vendor,
  nominal period); `sample (stream, ts, value)`, `span (stream, start, end, value)` for sleep stages;
  `coverage (stream, day, median period, % coverage)` computed at import; `vendor_score`, `tag`, `file` (origin of
  each row). Phase 0 built a smaller version: `samples (device, kind, ts, value, src)`, `devices`, `coverage`.
- **Metric register**: a metric is a function plus a declaration (inputs, minimum density and coverage, nights of
  baseline, citation, class). The catalogue, the Unlock screen and the "we add" column of the device card are all
  generated from that one declaration.
- **Cost**: computed only at import (seconds today); no daemon.

## 10. Privacy

The author's rule (19 Nov 2026): everything is computed locally on the phone. The app asks the device only for the
data the enabled metrics need. Values never leave the phone, neither to us nor to Google or Apple. We only learn which
kinds of data and metrics people are interested in, never their numbers.

- No account, no server of ours holding anyone's data.
- **The only thing sent:** an anonymous count of which metrics and devices are on ("HRV band: on, Instinct 2"). No
  values, times, device IDs or location. Shown before the first send, and it can be switched off.
- **Without the vendor's cloud where possible:** direct Bluetooth or a file first; the vendor's cloud (Oura, Whoop)
  only when there is no other way, and the app says so.
- Cloud adapters download with the user's own token straight to the user.
- Out: export the whole database and archive in one step. Gone: deleting a device deletes its data and files.
- Health data is a special category under GDPR (Art. 9). Self-hosted, there is no data controller; a hosted
  version for others would change that, so none is planned.

## 11. Legal position (EU; not legal advice)

Show it once to someone who does MDR work before a public release.

- **Wellness, not a medical device.** Under the MDR (2017/745) lifestyle and well-being software is not a device;
  the intended purpose we state decides it (MDCG 2019-11 rev. 1, June 2025).
- **So nowhere:** "detects illness", "diagnoses", "warns of", disease names beside a number, apnoea.
- **The deviation signal** for other people says only "resting heart rate and breathing are above your usual range",
  or is off.
- **Comparisons with vendors** must be factual and verifiable (Directive 2006/114/EC): feature, source, date. Brand
  names only to name a device, no logos.
- **Each vendor's API terms** before turning its adapter on.

## 12. Phases

| Phase | What | Done when |
|---|---|---|
| **0 Base** | schema with device and density, migration of existing data; 5-min HRV, battery and `device_info`; metric register with gates; `wristlogic odomkni` in the terminal | **built** (Nov 2026): same numbers as before + a list of locked metrics with reason and countdown |
| **1 Demo** | local web: Today, Your device, Unlock; HRV band, HRV curve, nocturnal dip, time of minimum | you open an address and see the device card and what each metric still needs |
| **2 Trust** | Trust screen, HR above steps, circadian measures, chronotype, ACWR, HR recovery, VO₂max; tags | every number has a source, a class and a vendor comparison where one exists |
| **3 Second device** | one more adapter and the Who-measures-what screen, tested on a real second device | two devices side by side, difference in the chart, source choice works |
| **4 For others** | name, site, one-command install, device database with contributions, remaining adapters, legal check | a stranger gets it running without the author |

## 13. Decisions taken (20 Nov 2026)

1. **Name: Ownbeat.** Before going public: search TMview (classes 9, 42, 44) and weigh the similarity to "Own
   Health"; `ownbeat.app` was free, `.com` taken.
2. **Audience:** the author first, public in phase 4.
3. **Recovery 0–100 and strain 0–21** live under "Experimental"; the main view shows the components (HRV, resting
   HR, breathing against your usual) and TRIMP.
4. **First extra adapter: Gadgetbridge** (its database export). One adapter covers hundreds of devices without the
   vendor's cloud, including the Colmi R02 ring and Garmin over Bluetooth. Health Connect right after; Apple Health
   and Oura when a first user has them.
5. **Form:** a phone app that computes everything locally; nothing on the watch that drains its battery. The local
   web stays a demo.
6. **Pulse oximeter:** test it for 14 nights as the first real "measure more".
7. **Deviation signal for others:** the neutral sentence, no word "illness".
8. **Licence:** AGPL-3.0-or-later when public, so a health-data app stays open in modified and hosted copies, and
   Gadgetbridge (AGPL) code can be reused.
9. **The "metrics per sensor" table** goes into marketing only once every row has a source.
