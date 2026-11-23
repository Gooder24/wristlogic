# Getting data out of every watch and ring

Research of 18 November 2026, translated from Slovak. Stars: how likely we get the data without the vendor's
permission. Vendor and API facts drift; check them again before relying on them.

## Four ways to the data

There is no universal Bluetooth profile for health data: each brand has its own protocol. There are four ways:

1. **File**: the watch as a USB drive (Garmin FIT). Reliable; this is what `wristlogic` does.
2. **Direct Bluetooth (BLE)**: an official SDK (Polar) or a reverse-engineered protocol (Gadgetbridge, Colmi). The
   only standard is the BLE Heart Rate Service 0x180D: heart rate, and RR intervals on chest straps; most sports
   watches can broadcast it ("HR broadcast").
3. **An own app on the watch**: Garmin Connect IQ, Wear OS / Samsung, Zepp OS, Bangle.js. Gives rawer data than the
   vendor's app (RR intervals, accelerometer), but only while it runs. Decided: compute nothing on the watch
   (battery; vendors compute on the phone too). A watch app may only collect raw data for the phone, and only where
   no other way exists.
4. **Cloud or phone**: Apple HealthKit, Android Health Connect, vendor APIs (Oura, Whoop, Polar, Garmin,
   Ultrahuman). Only processed numbers, never the raw signal, and the terms keep tightening.

**Recognising a device:** BLE scan → company ID in the manufacturer data (Bluetooth SIG list), advertised services
and the name pattern ("Instinct 2", "R02_…"). Gadgetbridge has exactly such a catalogue for 528 models from 74
vendors; its list (and name patterns) is the best start for a device database.

## Brands

| Brand | Best way | What we get | Chance |
|---|---|---|---|
| **Polar** | official Polar BLE SDK (Android, iOS) | raw PPG, PPI (beats), accelerometer: Verity Sense, H10, OH1, Vantage V3, Pacer Pro | ★★★ |
| **Garmin** | USB FIT (built) · Gadgetbridge (BLE) · own Connect IQ app | everything the watch writes; Connect IQ adds RR intervals and 25 Hz accelerometer to FIT | ★★★ |
| **Cheap rings** (Colmi R02/R09 and similar) | open, unencrypted BLE protocol, Python client exists | HR, SpO₂, steps, sleep, accelerometer | ★★★ |
| **Bangle.js 2, PineTime** | open firmware | fully raw PPG and accelerometer | ★★★ |
| **Amazfit / Xiaomi / Huawei** | Gadgetbridge (some need an auth key) | HR, sleep, SpO₂, stress, PAI | ★★☆ |
| **Samsung Galaxy Watch** | own Wear OS app with the Samsung Health Sensor SDK · Health Connect | raw PPG, ECG, 25 Hz accelerometer; distribution only after approval in the Samsung Partner Program | ★★☆ |
| **Apple Watch** | iPhone HealthKit (own iOS app) or export.xml | HR, HRV (SDNN), sleep stages, SpO₂, temperature; no raw PPG | ★★☆ |
| **Coros, Suunto** | Gadgetbridge (Coros Pace 3 experimental) · partner APIs | basic data | ★☆☆ |
| **Pixel Watch / Fitbit** | Health Connect on the phone | processed data; the Fitbit Web API was switched off on 2 Nov 2026, the Google Health API has "restricted" access and was not taking new projects | ★☆☆ |
| **Oura** | cloud API v2 | processed only; 10 users without approval, AI restrictions from June 2026 | ★☆☆ |
| **Whoop** | API v2 · HR broadcast over BLE | summaries (recovery, sleep, workouts), no continuous HR | ★☆☆ |
| **Ultrahuman, RingConn** | API on request / not found | – | ★☆☆ |

## Test on devices, or is documentation enough?

- **Official SDKs and APIs** (Polar, HealthKit, Health Connect, Oura, Whoop): documentation is enough; they have test
  environments. Only check that the numbers match.
- **Reverse-engineered protocols** (Gadgetbridge, rings, Garmin over BLE): documentation is not enough. They are
  community notes, and a firmware update can break them. Gadgetbridge itself keeps a device "experimental" until an
  owner confirms it.
- **For a beta:** each device carries a label **Tested** (on our own unit) / **Community** (a beta tester confirmed
  it) / **By documentation** (nobody yet). A tester sends a recording (FIT file, BLE log) with one button, and it
  becomes a test that runs without the device, like `tests/fake_watch.py`. The list grows without buying every device.
- **A few cheap units cover all four ways:** a Garmin watch, Colmi R02 (~20 €), Polar Verity Sense (~90 €),
  Bangle.js 2 (~100 €), an older second-hand Amazfit (~30 €).

## What already exists (do not build it again)

- **Gadgetbridge** (AGPL-3.0): the Bluetooth layer for hundreds of devices. Reading its export or database is fine;
  reusing its code makes the app AGPL too.
- **Open Wearables** (Momentum, MIT, self-hosted): one API over vendor clouds (Garmin, Whoop, Oura, Polar, Suunto,
  Strava, Fitbit, Ultrahuman) and HealthKit/Health Connect, with its own health scores. The closest competitor: the
  cloud layer can come from them; the value here is in raw data and trustworthy metrics.

## Order of betas

1. **Beta 1:** Garmin (USB + Gadgetbridge), Polar SDK, Health Connect, Apple export. Covers most people.
2. **Beta 2:** cheap rings; an own Connect IQ app only as an RR-interval collector, if measured to cost almost no battery.
3. **Beta 3:** apply to the Samsung Partner Program, own Wear OS app; cloud APIs through Open Wearables.
4. A device moves from "By documentation" to "Community" only after the first recording from a tester.
