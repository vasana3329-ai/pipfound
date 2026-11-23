#!/usr/bin/env python3
"""Hermetic macro/fundamental regressions; all economic rows are fixtures.

No network, app import, notifications, live cache writes or personal data.
Run normally for the full suite, or --repros-only against the pre-fix modules
via PF_MACRO_TEST_SOURCE_DIR to demonstrate the original defects.
"""
import sys
sys.dont_write_bytecode = True
import copy
import datetime as D
import importlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import time
import types
import unittest
from typing import Any
from unittest import mock

HERE = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get("PF_MACRO_TEST_SOURCE_DIR", str(HERE)))
sys.path.insert(0, str(SOURCE))
M = importlib.import_module("macro_context")
F = importlib.import_module("fundamental")
UTC = D.timezone.utc
SCRATCH = Path(os.environ.get("PF_MACRO_TEST_TMPDIR") or Path.home() / ".hermes/cache/scratch")
SCRATCH.mkdir(parents=True, exist_ok=True)


def event(at, title="CPI m/m", impact="High", ccy="USD", **extra) -> dict[str, Any]:
    row = {"date": D.datetime.fromtimestamp(at, UTC).isoformat(),
           "title": title, "impact": impact, "country": ccy,
           "forecast": "0.2%", "previous": "0.1%"}
    row.update(extra)
    return row


def actual(at, title="cpi mom", value="0.3%", ccy="USD", **extra) -> dict[str, Any]:
    dt = D.datetime.fromtimestamp(at, UTC)
    row = {"date": dt.date().isoformat(), "minute": dt.hour * 60 + dt.minute,
           "event": title, "ccy": ccy, "actual": value, "forecast": "0.2%"}
    row.update(extra)
    return row


class Response:
    def __init__(self, data):
        self.data = data if isinstance(data, bytes) else json.dumps(data).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self.data


class MacroTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="macro-fixtures-", dir=SCRATCH)
        self.root = Path(self.tmp.name)
        self.clock = D.datetime(2026, 11, 18, 13, 0, tzinfo=UTC).timestamp()
        self.real_now_et = M.now_et
        self.patches = [
            mock.patch.object(M, "CACHE", str(self.root / "ff.json")),
            mock.patch.object(M, "TE_CACHE", str(self.root / "te.json")),
            mock.patch.object(M.time, "time", side_effect=lambda: self.clock),
            mock.patch.object(M, "now_et", side_effect=lambda: D.datetime.fromtimestamp(self.clock, UTC).astimezone(F.ET)),
            mock.patch.object(M.urllib.request, "urlopen", side_effect=AssertionError("real network forbidden")),
        ]
        for p in self.patches: p.start()
        M.clear_memo()
        self.threads = []
        self.releases = []

    def tearDown(self):
        for e in self.releases: e.set()
        for t in self.threads:
            t.join(3)
            self.assertFalse(t.is_alive(), "fetch thread leaked")
        M.clear_memo()
        for p in reversed(self.patches): p.stop()
        self.tmp.cleanup()

    def disk(self, path, data, at):
        Path(path).write_text(json.dumps(data), encoding="utf-8")
        os.utime(path, (at, at))

    def serve(self, data):
        return mock.patch.object(M.urllib.request, "urlopen", return_value=Response(data))

    def thread(self, fn, name="leader"):
        out = {}
        def run():
            try: out["data"] = fn()
            except Exception as e: out["error"] = e
        t = threading.Thread(target=run, name=name, daemon=True)
        self.threads.append(t)
        t.start()
        return t, out

    def frozen_fundamental(self):
        clock = self.clock
        class Frozen(D.datetime):
            @classmethod
            def now(cls, tz=None):
                dt = D.datetime.fromtimestamp(clock, UTC)
                return dt.astimezone(tz) if tz else dt.replace(tzinfo=None)
        return mock.patch.object(F, "datetime", types.SimpleNamespace(
            datetime=Frozen, timezone=D.timezone, timedelta=D.timedelta, date=D.date, time=D.time))

    def test_calendar_failure_retries_after_cooldown(self):
        old = [event(self.clock - 10 * 86400)]
        self.disk(M.CACHE, old, self.clock - 10 * 86400)
        with mock.patch.object(M, "FF_URLS", ["https://fixture.invalid/calendar"]):
            with mock.patch.object(M.urllib.request, "urlopen", side_effect=OSError("offline")) as fetch:
                self.assertEqual(M.get_calendar(attempts=1), old)
                self.assertEqual(fetch.call_count, 1)
            self.clock += M.DOWN_COOLDOWN + 1
            fresh = [event(self.clock + 20 * 60)]
            with self.serve(fresh) as fetch:
                self.assertEqual(M.get_calendar(attempts=1), fresh)
                self.assertEqual(fetch.call_count, 1, "stale fallback suppressed recovery for 3h")

    def test_actuals_failure_retries_after_cooldown(self):
        old = [actual(self.clock - 10 * 86400)]
        self.disk(M.TE_CACHE, {"at": self.clock - 10 * 86400, "rows": old}, self.clock - 10 * 86400)
        with mock.patch.object(M.urllib.request, "urlopen", side_effect=OSError("offline")):
            self.assertEqual(M.get_actuals(), old)
        self.clock += M.DOWN_COOLDOWN + 1
        fresh = [actual(self.clock)]
        with self.serve(b"fixture"), mock.patch.object(M, "_parse_te_calendar", return_value=fresh) as parse:
            self.assertEqual(M.get_actuals(), fresh)
            self.assertEqual(parse.call_count, 1, "stale actuals suppressed recovery for 1h")

    def test_calendar_disk_age_is_not_restamped(self):
        rows = [event(self.clock + 3600)]
        self.disk(M.CACHE, rows, self.clock - 100)
        self.assertEqual(M.get_calendar(), rows)
        self.clock += 3 * 3600 - 99
        with self.serve(rows) as fetch:
            M.get_calendar()
            self.assertEqual(fetch.call_count, 1, "disk-to-memory extended original TTL")

    def test_actuals_disk_embedded_at_beats_fresh_mtime(self):
        rows = [actual(self.clock)]
        original = self.clock - 3700
        self.disk(M.TE_CACHE, {"at": original, "rows": rows}, self.clock)
        with mock.patch.object(M.urllib.request, "urlopen", side_effect=OSError("offline")) as fetch:
            result = M.get_actuals()
        self.assertEqual(fetch.call_count, 1, "touching a cache must not refresh its data")
        self.assertEqual(M.actuals_quality(result, now=self.clock)["fetched_at"], original)
        self.assertFalse(M.actuals_quality(result, now=self.clock)["ok"])

    def test_calendar_copy_isolation(self):
        rows = [event(self.clock + 3600, details={"items": ["original"]})]
        with self.serve(rows): first = M.get_calendar()
        first[0]["title"] = "poisoned"
        first[0]["details"]["items"].append("poisoned")
        first.append(event(self.clock))
        self.assertEqual(M.get_calendar(), rows)

    def test_actuals_copy_isolation(self):
        rows = [actual(self.clock)]
        expected = copy.deepcopy(rows)
        with self.serve(b"fixture"), mock.patch.object(M, "_parse_te_calendar", return_value=rows):
            first = M.get_actuals()
        first[0]["actual"] = "999%"
        first.clear()
        self.assertEqual(M.get_actuals(), expected)

    def blocked_fetch(self, kind):
        entered, release = threading.Event(), threading.Event()
        self.releases.append(release)
        calls = []
        data = [event(self.clock + 1200)] if kind == "cal" else [actual(self.clock)]
        def fetch(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                entered.set()
                if not release.wait(3): raise TimeoutError("fixture leader not released")
            return Response(data if kind == "cal" else b"fixture")
        return entered, release, calls, data, fetch

    def follower_timeout(self, kind):
        entered, release, calls, rows, fetch = self.blocked_fetch(kind)
        fn = M.get_calendar if kind == "cal" else M.get_actuals
        old_flock = M._flock
        with mock.patch.object(M.urllib.request, "urlopen", side_effect=fetch), \
             mock.patch.object(M, "_parse_te_calendar", return_value=rows), \
             mock.patch.object(M, "_flock", side_effect=lambda key, *a, **k: old_flock(key, wait=0.02)):
            t, out = self.thread(fn)
            self.assertTrue(entered.wait(1))
            try: follower = fn()
            except RuntimeError: follower = []
            self.assertEqual(len(calls), 1, "timed-out follower became a second fetcher")
            self.assertEqual(follower, [], "unfinished flight must not invent fresh rows")
            release.set()
            t.join(2)
            self.assertNotIn("error", out)
            self.assertEqual(out["data"], rows)

    def test_calendar_follower_timeout_never_fetches(self): self.follower_timeout("cal")
    def test_actuals_follower_timeout_never_fetches(self): self.follower_timeout("te")

    def publish_before_unlock(self, kind):
        rows = [event(self.clock + 1200)] if kind == "cal" else [actual(self.clock)]
        path = M.CACHE if kind == "cal" else M.TE_CACHE
        Path(path).mkdir()  # real disk-write failure, without touching any live file
        fn = M.get_calendar if kind == "cal" else M.get_actuals
        old_unlock = M._funlock
        seen, inside = [], [False]
        def unlock(key, ev):
            old_unlock(key, ev)
            if not inside[0]:
                inside[0] = True
                seen.append(fn())  # exact waiter schedule, before leader returns
                inside[0] = False
        with self.serve(rows if kind == "cal" else b"fixture") as fetch, \
             mock.patch.object(M, "_parse_te_calendar", return_value=rows), \
             mock.patch.object(M, "_funlock", side_effect=unlock):
            self.assertEqual(fn(), rows)
            self.assertEqual(seen, [rows])
            self.assertEqual(fetch.call_count, 1, "unlock preceded result publication")

    def test_actuals_publish_before_unlock_on_disk_failure(self): self.publish_before_unlock("te")
    def test_calendar_publish_before_unlock_on_disk_failure(self): self.publish_before_unlock("cal")

    def shared_flight(self, follower_age):
        entered, release, calls, rows, fetch = self.blocked_fetch("te")
        follower_entered = threading.Event()
        original = M._flock
        def flock(key, *args, **kwargs):
            if threading.current_thread().name == "follower": follower_entered.set()
            return original(key, *args, **kwargs)
        with mock.patch.object(M.urllib.request, "urlopen", side_effect=fetch), \
             mock.patch.object(M, "_parse_te_calendar", return_value=rows), \
             mock.patch.object(M, "_flock", side_effect=flock):
            lead, lead_out = self.thread(lambda: M.get_actuals(max_age=0))
            self.assertTrue(entered.wait(1))
            follow, follow_out = self.thread(lambda: M.get_actuals(max_age=follower_age), "follower")
            self.assertTrue(follower_entered.wait(1))
            time.sleep(0.03)
            release.set()
            lead.join(2); follow.join(2)
            self.assertNotIn("error", lead_out)
            self.assertNotIn("error", follow_out)
            self.assertEqual(len(calls), 1, "max_age is policy, not source/flight identity")
            self.assertEqual(follow_out["data"], rows)

    def test_cross_max_age_actuals_share_one_flight(self): self.shared_flight(3600)
    def test_zero_max_age_followers_share_completed_flight(self): self.shared_flight(0)

    def test_clear_memo_does_not_abandon_running_leader(self):
        entered, release, calls, rows, fetch = self.blocked_fetch("cal")
        original = M._flock
        with mock.patch.object(M.urllib.request, "urlopen", side_effect=fetch), \
             mock.patch.object(M, "_flock", side_effect=lambda key, *a, **k: original(key, wait=0.02)):
            t, out = self.thread(M.get_calendar)
            self.assertTrue(entered.wait(1))
            M.clear_memo()
            try: M.get_calendar()
            except RuntimeError: pass
            self.assertEqual(len(calls), 1)
            release.set(); t.join(2)
            self.assertEqual(out.get("data"), rows)

    def test_failure_without_disk_retries_after_cooldown(self):
        with mock.patch.object(M.urllib.request, "urlopen", side_effect=OSError("offline")) as fetch:
            self.assertEqual(M.get_actuals(), [])
            self.assertEqual(M.get_actuals(), [])
            self.assertEqual(fetch.call_count, 1)
        self.clock += M.DOWN_COOLDOWN + 1
        rows = [actual(self.clock)]
        with self.serve(b"fixture") as fetch, mock.patch.object(M, "_parse_te_calendar", return_value=rows):
            self.assertEqual(M.get_actuals(), rows)
            self.assertEqual(fetch.call_count, 1)

    def test_stale_metadata_survives_cooldown_and_copy(self):
        original = self.clock - 20000
        rows = [event(self.clock + 1200)]
        self.disk(M.CACHE, rows, original)
        with mock.patch.object(M.urllib.request, "urlopen", side_effect=OSError("offline")):
            a = M.get_calendar()
            b = M.get_calendar()
        for result in (a, b, copy.deepcopy(a)):
            q = M.calendar_quality(result, now=self.clock)
            self.assertFalse(q["ok"])
            self.assertEqual(q["fetched_at"], original)
            self.assertEqual(M.news_gate(result, {"USD"}, now=self.clock)[0], "UNKNOWN")
        a.metadata["fetched_at"] = self.clock
        self.assertEqual(M.calendar_quality(b, now=self.clock)["fetched_at"], original)

    def test_previous_week_with_fresh_mtime_is_not_green(self):
        rows = [event(self.clock - 10 * 86400)]
        self.disk(M.CACHE, rows, self.clock)
        with mock.patch.object(M, "FF_URLS", ["https://fixture.invalid"]), \
             mock.patch.object(M.urllib.request, "urlopen", side_effect=OSError("offline")) as fetch:
            result = M.get_calendar(attempts=1)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(M.news_gate(result, {"USD"}, now=self.clock)[0], "UNKNOWN")
        self.assertFalse(M.calendar_quality(rows, now=self.clock)["coverage_ok"])

    def test_invalid_calendar_response_preserves_old_cache(self):
        rows = [event(self.clock)]
        self.disk(M.CACHE, rows, self.clock - 20000)
        before = Path(M.CACHE).read_bytes()
        with mock.patch.object(M, "FF_URLS", ["https://fixture.invalid"]), self.serve({"error": "blocked"}):
            result = M.get_calendar(attempts=1)
        self.assertEqual(result, rows)
        self.assertFalse(M.calendar_quality(result, now=self.clock)["ok"])
        self.assertEqual(Path(M.CACHE).read_bytes(), before)

    def test_corrupt_disk_is_replaced_only_by_valid_data(self):
        Path(M.CACHE).write_text('{"broken":', encoding="utf-8")
        rows = [event(self.clock + 1200)]
        with self.serve(rows): result = M.get_calendar()
        self.assertEqual(result, rows)
        self.assertTrue(M.calendar_quality(result, now=self.clock)["ok"])
        saved = json.loads(Path(M.CACHE).read_text())
        self.assertEqual(saved["rows"], rows)
        self.assertEqual(saved["at"], self.clock)

    def test_empty_te_parse_is_source_failure_not_fresh_success(self):
        rows = [actual(self.clock)]
        self.disk(M.TE_CACHE, {"at": self.clock - 4000, "rows": rows}, self.clock - 4000)
        before = Path(M.TE_CACHE).read_bytes()
        with self.serve(b"<html>access denied</html>") as fetch:
            result = M.get_actuals()
            M.get_actuals()
            self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result, rows)
        self.assertFalse(M.actuals_quality(result, now=self.clock)["ok"])
        self.assertEqual(Path(M.TE_CACHE).read_bytes(), before)

    def test_quality_expires_at_exact_source_ttl(self):
        with self.serve([event(self.clock + 20000)]): cal = M.get_calendar()
        self.assertTrue(M.calendar_quality(cal, now=self.clock + 10799)["ok"])
        self.assertFalse(M.calendar_quality(cal, now=self.clock + 10800)["ok"])

    def test_live_fetch_cannot_validate_historical_decision(self):
        with self.serve([event(self.clock + 1200)]): cal = M.get_calendar()
        q = M.calendar_quality(cal, now=self.clock - 1)
        self.assertFalse(q["ok"])
        self.assertEqual(M.news_gate(cal, {"USD"}, now=self.clock - 1)[0], "UNKNOWN")

    def test_raw_fixtures_remain_two_argument_compatible(self):
        cal = [event(self.clock + 1200)]
        gate = M.news_gate(cal, {"USD"})
        self.assertEqual(len(gate), 3)
        self.assertEqual(gate[0], "RED")
        self.assertTrue(M.calendar_quality(cal, now=self.clock)["ok"])
        self.assertEqual(M.news_gate([event(self.clock + 3 * 3600)], {"USD"})[0], "GREEN")
        self.assertEqual(M.news_gate([], {"USD"})[0], "UNKNOWN")

    def test_macro_build_keeps_contract_when_source_unavailable(self):
        with mock.patch.object(M, "get_calendar", side_effect=RuntimeError("offline")):
            report = M.build("EURUSD")
        self.assertEqual(report["news_gate"]["status"], "UNKNOWN")
        for key in ("active_sessions", "today_events_filtered", "upcoming_high_impact_48h", "symbol"):
            self.assertIn(key, report)
        self.assertFalse(report["calendar_quality"]["ok"])

    def test_atomic_replace_failure_keeps_target_and_cleans_temp(self):
        path = self.root / "atomic.json"
        path.write_text('{"original":true}', encoding="utf-8")
        with mock.patch.object(M.os, "replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError): M._atomic_write(path, {"new": [1, 2, 3]})
        self.assertEqual(path.read_text(), '{"original":true}')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["atomic.json"])
        with self.assertRaises(ValueError): M._atomic_write(path, {"bad": float("nan")})
        self.assertEqual(path.read_text(), '{"original":true}')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["atomic.json"])

    def test_atomic_concurrent_readers_never_observe_partial_json(self):
        path = self.root / "atomic.json"
        M._atomic_write(path, {"n": 0, "rows": [0] * 100})
        done, errors = threading.Event(), []
        def reader():
            while not done.is_set():
                try:
                    d = json.loads(path.read_text())
                    if d["rows"] != [d["n"]] * 100: errors.append("torn payload")
                except Exception as e: errors.append(str(e))
        t = threading.Thread(target=reader, daemon=True)
        self.threads.append(t); t.start()
        try:
            for n in range(1, 30): M._atomic_write(path, {"n": n, "rows": [n] * 100})
        finally: done.set(); t.join(2)
        self.assertEqual(errors, [])

    def test_ny_winter_and_summer_offsets(self):
        winter = D.datetime(2026, 1, 15, 13, 30, tzinfo=UTC).astimezone(F.ET)
        summer = D.datetime(2026, 7, 15, 12, 30, tzinfo=UTC).astimezone(F.ET)
        self.assertEqual((winter.hour, winter.minute, winter.utcoffset()), (8, 30, D.timedelta(hours=-5)))
        self.assertEqual((summer.hour, summer.minute, summer.utcoffset()), (8, 30, D.timedelta(hours=-4)))
        self.assertEqual(self.real_now_et(winter.timestamp()).hour, 8)
        self.assertEqual(self.real_now_et(summer.timestamp()).hour, 8)

    def test_spring_dst_transition_gate_uses_elapsed_minutes(self):
        now = D.datetime(2026, 3, 8, 6, 50, tzinfo=UTC)
        release = D.datetime(2026, 3, 8, 7, 10, tzinfo=UTC)
        gate = M.news_gate([event(release.timestamp())], {"USD"}, now=now)
        self.assertEqual(gate[0], "RED")
        self.assertEqual(gate[2][0][0], 20)
        self.assertEqual(now.astimezone(F.ET).strftime("%H:%M"), "01:50")
        self.assertEqual(release.astimezone(F.ET).strftime("%H:%M"), "03:10")

    def test_fall_dst_fold_gate_uses_elapsed_minutes(self):
        now = D.datetime(2026, 11, 1, 5, 50, tzinfo=UTC)
        release = D.datetime(2026, 11, 1, 6, 10, tzinfo=UTC)
        gate = M.news_gate([event(release.timestamp())], {"USD"}, now=now)
        self.assertEqual(gate[0], "RED")
        self.assertEqual(gate[2][0][0], 20)
        self.assertEqual(now.astimezone(F.ET).strftime("%H:%M"), "01:50")
        self.assertEqual(release.astimezone(F.ET).strftime("%H:%M"), "01:10")

    def test_gate_epoch_aware_and_naive_utc_datetime_agree(self):
        cal = [event(self.clock + 1200)]
        aware = D.datetime.fromtimestamp(self.clock, UTC)
        self.assertEqual(M.news_gate(cal, {"USD"}, now=self.clock), M.news_gate(cal, {"USD"}, now=aware))
        self.assertEqual(M.news_gate(cal, {"USD"}, now=self.clock),
                         M.news_gate(cal, {"USD"}, now=aware.replace(tzinfo=None)))
        for bad in (float("nan"), float("inf"), True):
            self.assertEqual(M.news_gate(cal, {"USD"}, now=bad)[0], "UNKNOWN")

    def test_naive_calendar_time_uses_est_and_rejects_dst_ambiguity(self):
        dt = M.parse_event_time("2026-01-15T08:30:00")
        self.assertEqual(dt, D.datetime(2026, 1, 15, 13, 30, tzinfo=UTC))
        for text in ("2026-03-08T02:30:00", "2026-11-01T01:30:00", "2026-01-15", "nonsense"):
            self.assertIsNone(M.parse_event_time(text), text)
        cal = [event(self.clock + 500), event(self.clock + 1000, date="nonsense")]
        self.assertEqual(M.news_gate(cal, {"USD"}, now=self.clock)[0], "UNKNOWN")

    def test_te_minutes_reject_invalid_hour_minute_and_meridiem(self):
        table = [("12:00", "AM", 0), ("12:00", "PM", 720), ("1:05", "PM", 785),
                 ("00:30", "AM", None), ("13:00", "PM", None), ("11:60", "AM", None),
                 ("9:15", "XX", None), ("9:-1", "AM", None), ("9:1", "AM", None)]
        for hhmm, ampm, want in table:
            self.assertEqual(M._te_minutes(hhmm, ampm), want, (hhmm, ampm))

    def test_te_parser_handles_quotes_entities_and_rejects_bad_rows(self):
        page = '''<tr data-url="/us/cpi" data-event="cpi mom" class=' 2026-11-18'>
          <td id="calendar-date-1">01:30 PM</td><td class="calendar-iso">US</td>
          <span id='actual'>0.3%</span><a id='forecast'>0.2%</a></tr>
          <tr data-event='retail sales mom' data-url='/gb/retail' class=" 2026-11-18">
          <td id='calendar-date-2'>12:00 AM</td><td class='calendar-iso'>GB</td>
          <span id="actual">1.2&nbsp;M</span><a id="forecast">1.1M</a></tr>
          <tr data-url="/us/bad" data-event="bad" class=' 2026-11-18'>
          <td id="calendar-date-3">13:99 PM</td><td class="calendar-iso">US</td>
          <span id='actual'>1</span></tr>'''
        rows = M._parse_te_calendar(page)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["minute"], 810)
        self.assertEqual(rows[1]["minute"], 0)
        self.assertEqual(rows[1]["actual"].replace("\xa0", " "), "1.2 M")

    def test_today_and_upcoming_convert_source_dates_to_new_york(self):
        self.clock = D.datetime(2026, 1, 15, 0, 30, tzinfo=UTC).timestamp()
        cal = [event(self.clock + 1800), event(self.clock + 5 * 3600)]
        self.assertEqual(M.today_events(cal)[0]["time"], "20:00 ET")
        self.assertEqual(len(M.today_events(cal)), 1)
        self.assertIn("20:00 ET", M.upcoming_high_impact(cal)[0]["when"])

    def test_gate_exact_before_after_boundaries(self):
        for seconds, expected in ((3600, "RED"), (3601, "GREEN"), (-1800, "RED"), (-1801, "GREEN")):
            self.assertEqual(M.news_gate([event(self.clock + seconds)], {"USD"}, now=self.clock)[0], expected)

    def test_number_parser_only_accepts_finite_well_formed_values(self):
        good = [(0, 0.0), (3.5, 3.5), ("195K", 195000.0), ("1,234K", 1234000.0),
                ("-2.5%", -2.5), ("1.2 M", 1200000.0), ("0", 0.0)]
        for value, want in good: self.assertEqual(F._num(value), want, value)
        for value in ("NaN", "inf", "-inf", "1e309", float("nan"), float("inf"), True,
                      "1,2", "3%%", "--2", [], {}, "195Kjunk", "4.25-4.50%"):
            self.assertIsNone(F._num(value), repr(value))

    def test_nan_cannot_produce_as_expected_verdict(self):
        v = F._verdict("NaN", "5%", "4%", "normal", "USD")
        self.assertFalse(v["found"])
        self.assertEqual(v["outcome"], "")
        self.assertEqual(v["effect"]["pairs"], [])

    def test_rate_ranges_compare_only_unambiguous_intervals(self):
        v = F._verdict("4.25-4.50%", "4.75-5.00%", "5.00-5.25%", "normal", "USD")
        self.assertTrue(v["found"])
        self.assertEqual(v["dir"], "ضعیف‌تر")
        equal = F._verdict("4.25–4.50%", "4.25-4.50%", "", "normal", "USD")
        self.assertEqual(equal["outcome"], "خنثی")
        for a, f in (("4.25-4.50%", "4.50%"), ("4-6%", "5-7%"), ("4.50%", "4.25-4.50%")):
            v = F._verdict(a, f, "", "normal", "USD")
            self.assertTrue(v["found"])
            self.assertEqual(v["dir"], "")
            self.assertEqual(v["status"], "UNKNOWN")
            self.assertEqual(v["effect"]["pairs"], [])

    def test_units_and_unknown_classification_do_not_invent_direction(self):
        for a, f in (("195", "180K"), ("3.5%", "3.4"), ("1.2M", "1.1%")):
            v = F._verdict(a, f, "", "normal", "USD")
            self.assertTrue(v["found"])
            self.assertEqual(v["dir"], "")
            self.assertEqual(v["effect"]["pairs"], [])
        self.assertEqual(F._classify("Federal Funds Rate", "USD")[2], "normal")
        for title in ("Fed Chair Powell Speaks", "Mystery Indicator", "BOC Rate Statement"):
            mode = F._classify(title, "USD")[2]
            self.assertEqual(mode, "unknown")
            self.assertEqual(F._verdict("2", "1", "", mode, "USD")["dir"], "")

    def test_titles_reject_period_core_region_and_survey_conflicts(self):
        for a, b in (("cpi yoy", "CPI m/m"), ("cpi mom", "Core CPI m/m"),
                     ("core cpi yoy", "CPI y/y"), ("adp employment change", "Non-Farm Employment Change"),
                     ("ism manufacturing pmi", "ISM Services PMI"), ("german cpi mom", "French CPI m/m"),
                     ("", "CPI m/m"), ("consumer confidence", "Consumer Credit")):
            self.assertFalse(F._titles_match(a, b), (a, b))
        for a, b in (("ppi yoy", "Manufacturing PPI y/y"), ("non farm payrolls", "Non-Farm Employment Change"),
                     ("cpi mom", "CPI m/m"), ("fed interest rate decision", "Federal Funds Rate")):
            self.assertTrue(F._titles_match(a, b), (a, b))

    def attach(self, events, rows):
        with mock.patch.object(M, "get_actuals", return_value=rows):
            return F._attach_verdicts(events)

    def test_simultaneous_conflicting_matches_remain_unknown(self):
        ev = event(self.clock - 600)
        payload = dict(ev, iso=ev["date"])
        rows = [actual(self.clock - 600), actual(self.clock - 600, value="0.1%")]
        self.attach([payload], rows)
        self.assertFalse(payload["verdict"]["found"])
        self.assertEqual(payload["verdict"]["status"], "UNKNOWN")
        self.assertEqual(payload["verdict"]["effect"]["pairs"], [])

    def test_match_requires_title_and_distinguishes_core_from_headline(self):
        ev = event(self.clock - 600, title="Core CPI m/m")
        for title in ("", "cpi mom", "cpi yoy"):
            payload = dict(ev, iso=ev["date"])
            self.attach([payload], [actual(self.clock - 600, title=title)])
            self.assertFalse(payload["verdict"]["found"], title)

    def test_matching_handles_midnight_without_date_guess(self):
        at = D.datetime(2026, 11, 18, 0, 3, tzinfo=UTC).timestamp()
        ev = event(at)
        payload = dict(ev, iso=ev["date"])
        self.attach([payload], [actual(at - 300)])
        self.assertTrue(payload["verdict"]["found"])

    def test_malformed_actual_rows_do_not_crash_or_produce_verdict(self):
        ev = event(self.clock - 600)
        for bad in ("not a row", {"date": "2026-11-18", "minute": "NaN", "ccy": "USD", "event": "cpi mom"},
                    actual(self.clock - 600, minute=1440), actual(self.clock - 600, minute=True)):
            payload = dict(ev, iso=ev["date"])
            self.attach([payload], [bad])
            self.assertFalse(payload["verdict"]["found"])

    def test_stale_actuals_are_not_directional_confirmation(self):
        ev = event(self.clock - 600)
        self.disk(M.TE_CACHE, {"at": self.clock - 4000, "rows": [actual(self.clock - 600)]}, self.clock - 4000)
        with mock.patch.object(M.urllib.request, "urlopen", side_effect=OSError("offline")):
            rows = M.get_actuals()
        payload = dict(ev, iso=ev["date"])
        self.assertFalse(self.attach([payload], rows))
        self.assertFalse(payload["verdict"]["found"])
        self.assertEqual(payload["verdict"]["source_quality"]["status"], "UNKNOWN")

    def test_feed_and_archive_keep_quality_and_winter_display(self):
        self.clock = D.datetime(2026, 1, 15, 13, 0, tzinfo=UTC).timestamp()
        cal = [event(self.clock + 1800), event(self.clock - 600)]
        with self.frozen_fundamental(), mock.patch.object(M, "get_calendar", return_value=cal), \
             mock.patch.object(M, "get_actuals", return_value=[]):
            feed = F.build_feed(hours=24)
            report = F.build(hours=24)
            arc = F.archive(hours=6)
        upcoming = next(e for e in feed if not e["passed"])
        self.assertIn("08:30", upcoming["et"])
        self.assertEqual(report["source_ok"], False)
        self.assertEqual(arc["source_ok"], False)
        self.assertIn("calendar_quality", report)
        self.assertIn("source_quality", arc)
        for e in feed:
            if e.get("passed"):
                self.assertNotIn("analysis", e)
                self.assertEqual(e["verdict"]["status"], "UNKNOWN")


REPRO_NAMES = (
    "test_calendar_failure_retries_after_cooldown",
    "test_actuals_failure_retries_after_cooldown",
    "test_calendar_disk_age_is_not_restamped",
    "test_calendar_copy_isolation",
    "test_actuals_copy_isolation",
    "test_calendar_follower_timeout_never_fetches",
    "test_actuals_follower_timeout_never_fetches",
    "test_actuals_publish_before_unlock_on_disk_failure",
    "test_cross_max_age_actuals_share_one_flight",
    "test_failure_without_disk_retries_after_cooldown",
    "test_ny_winter_and_summer_offsets",
    "test_te_minutes_reject_invalid_hour_minute_and_meridiem",
    "test_nan_cannot_produce_as_expected_verdict",
    "test_match_requires_title_and_distinguishes_core_from_headline",
)

if __name__ == "__main__":
    repros = "--repros-only" in sys.argv
    if repros: sys.argv.remove("--repros-only")
    suite = (unittest.TestSuite(MacroTests(n) for n in REPRO_NAMES) if repros
             else unittest.defaultTestLoader.loadTestsFromTestCase(MacroTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("Hermetic fixtures only; real network calls: 0; tests=%d failures=%d errors=%d" %
          (result.testsRun, len(result.failures), len(result.errors)))
    sys.exit(not result.wasSuccessful())
