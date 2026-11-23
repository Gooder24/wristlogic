# Ownbeat: an idea up for adoption

**Your watch knows more than its app tells you.** A local-first health app that reads any watch, ring or
chest strap, shows which sensors it really has, and computes every metric that published research supports from
those sensors. Every number carries its method, its source and a confidence class. Where the data cannot back a
number, the app shows none and says what is missing.

The author stopped working on it in November 2026. The research and the plan are here for anyone who wants to
build it. Take what you like, no permission needed.

## Why it could matter

- Wearables record far more than their apps show. The author's Garmin Instinct 2 wrote 889 five-minute HRV values
  in two weeks; its app shows one number a night.
- Vendor "readiness", "recovery" and "body battery" scores are unpublished formulas. People cannot tell a
  measurement from a guess.
- Nobody tells you what a sensor you already own would unlock if you switched it on or wore the device at night,
  and what that costs in battery or comfort.
- Health data is the most sensitive data people have. This design never sends it anywhere.

## What sets it apart

1. **Device card:** sensor → signal → what can be computed from it, with the density measured from the user's own
   files, not copied from a brochure.
2. **"Measure more → unlock":** each locked metric says what it needs ("9 of 14 nights") and what that costs.
   No streaks, no badges.
3. **Trust classes:** A = published method on the input it was validated for; B = published method on a substitute
   input; C = our own estimate, hidden by default.
4. **Several devices, never silently averaged:** one source per signal at a time, the other shown as a second line
   with a Bland–Altman difference.
5. **Local only:** no account, no server holding anyone's data; computed on the phone.

## What is in this folder

| File | What |
|---|---|
| [PLAN.md](PLAN.md) | The product plan: onboarding, device card, unlock levels, a metric catalogue with citations, multi-device rules, trust, architecture, privacy, the EU legal position (MDR), phases |
| [DEVICES.md](DEVICES.md) | Research: how to get data out of each brand (Polar, Garmin, cheap rings, Bangle.js, Amazfit, Samsung, Apple, Oura, Whoop and more) without the vendor's permission |
| [BRAND.md](BRAND.md) | Name candidates and what was checked, tagline, tone of voice, sample copy, visual direction |

## What already exists

The repository around this folder is `wristlogic`, a working Python engine (phase 0 of the plan):

- reads Garmin FIT files straight from the watch over USB (MTP), archives every file, and never writes to the watch;
- SQLite store with samples per device (by serial number) and the density of each signal per day;
- metrics with published methods: sleep efficiency, sleep need and debt, resting heart rate, Sleep Regularity Index,
  HRV / resting heart rate / breathing against a personal baseline, TRIMP, the Banister fitness-fatigue model;
- a metric register with gates (`wristlogic odomkni` lists locked metrics with the reason and a countdown);
- an `.ics` calendar of nights; 31 tests with a fake watch that writes real FIT files.

The user interface text is Slovak. Phases 1–4 (local web demo, trust screen, a second device through Gadgetbridge,
a phone app for other people) were never started.

## If you take it over

- Start with PLAN.md, section 12 (phases) and section 6 (metric catalogue).
- The cheapest second device for a desk test is a Colmi R02 ring (about 20 €, only the variant that pairs with the
  QRing app is supported by Gadgetbridge).
- Facts about vendors and APIs were checked in November 2026 and will drift. Check them again before you rely on them.
- The name "Ownbeat" was not checked in any trademark register. "Own Health" is an existing health app with a
  similar name.
- Nothing here is medical advice, and the plan keeps the app a wellness product: no disease names, no detection
  claims.
