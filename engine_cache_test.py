#!/usr/bin/env python3
"""Deterministic, offline candle/spot cache and deadline regression tests.

No sleeps, live prices, DNS, app imports, or user data. Flight schedules use Events
that record follower entry before the source is released. Run this script in an
isolated HOME with PIPFOUND_NOTIFY=0 and a scratch-directory TMPDIR.
"""
import copy
import datetime
import io
import json
import math
import socket
import sys
import threading
import types
import unittest
from unittest.mock import patch, Mock
from typing import Any

import smc_engine as E


class Clock:
    def __init__(self, wall=100.0, mono=1000.0):
        self.wall, self.mono = wall, mono

    def advance(self, seconds):
        self.wall += seconds
        self.mono += seconds

    def time(self):
        return self.wall

    def monotonic(self):
        return self.mono


def bar(t, c=100.0):
    return {"t": t, "o": c, "h": c + 1.0, "l": c - 1.0, "c": c, "v": 10.0}


def bars(n=5, c=100.0, secs=60):
    return [bar(-(n - i) * secs, c) for i in range(n)]


def yahoo_response(rows):
    quote = {name: [b[key] for b in rows] for name, key in
             (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"), ("volume", "v"))}
    return {"chart": {"result": [{"timestamp": [b["t"] for b in rows],
                                  "indicators": {"quote": [quote]}}]}}


class ProbeEvent:
    """Record wait entry; no arbitrary sleeps are needed to arrange races."""
    def __init__(self, expected):
        self.inner = threading.Event()
        self.ready = threading.Event()
        self.lock = threading.Lock()
        self.expected = expected
        self.waits = []

    def wait(self, timeout=None):
        with self.lock:
            self.waits.append(timeout)
            if len(self.waits) >= self.expected:
                self.ready.set()
        return self.inner.wait(timeout)

    def set(self):
        self.inner.set()


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.net_attempts = []
        self.patches = []
        self.probes = []
        self.probe_lock = threading.Lock()
        self.apply_patch(E.time, "time", self.clock.time)
        self.apply_patch(E.time, "monotonic", self.clock.monotonic)
        self.apply_patch(socket, "getaddrinfo", self.no_network)
        self.apply_patch(socket, "create_connection", self.no_network)
        self.apply_patch(E.urllib.request, "urlopen", self.no_network)
        E.clear_candles()
        E.clear_spot_prices()
        E.clear_host_penalties()

    def tearDown(self):
        try:
            self.assertFalse(E._CANDLE_FLIGHTS, "leaked candle flight")
            self.assertFalse(E._SPOT_FLIGHTS, "leaked spot flight")
            self.assertEqual(self.net_attempts, [], "unexpected real network attempt")
        finally:
            E.clear_candles()
            E.clear_spot_prices()
            for mock in reversed(self.patches):
                mock.stop()

    def no_network(self, *args, **kwargs):
        self.net_attempts.append(str(args[0]) if args else "network")
        raise AssertionError("offline guard: real network is forbidden")

    def apply_patch(self, target, name, replacement):
        mock = patch.object(target, name, replacement)
        self.patches.append(mock)
        return mock.start()

    def key(self, sym="BTCUSDT", tf="1m", src="binance"):
        return (src, sym, tf, False)

    def put(self, rows=None, tf="1m", sym="BTCUSDT", **kwargs):
        rows = bars() if rows is None else rows
        return E._candles_put("binance", sym, tf, len(rows), rows, **kwargs)

    def get(self, n=5, tf="1m", sym="BTCUSDT") -> Any:
        return E._candles_get("binance", sym, tf, n)

    def install_probe(self, expected):
        original = E._FetchFlight

        def make(generation):
            flight: Any = original(generation)
            flight.event = ProbeEvent(expected)
            with self.probe_lock:
                self.probes.append(flight)
            return flight

        self.apply_patch(E, "_FetchFlight", make)

    def start_worker(self, fn, results, index):
        def run():
            try:
                results[index] = (fn(), None)
            except BaseException as exc:
                results[index] = (None, exc)
        thread = threading.Thread(target=run, name=f"cache-test-{index}", daemon=True)
        thread.start()
        return thread

    def join_workers(self, threads):
        for thread in threads:
            thread.join(5)
        self.assertTrue(all(not t.is_alive() for t in threads), "worker did not finish")

    def group(self, target, source, call, n=4, before_release=None):
        entered, release = threading.Event(), threading.Event()
        calls, results, threads = [], {}, []
        self.install_probe(n - 1)

        def blocked(*args):
            calls.append(args)
            entered.set()
            if not release.wait(5):
                raise AssertionError("source release missing")
            return source(*args)

        with patch.object(E, target, blocked):
            try:
                threads.append(self.start_worker(call, results, 0))
                self.assertTrue(entered.wait(3), "leader did not enter source")
                for i in range(1, n):
                    threads.append(self.start_worker(call, results, i))
                self.assertTrue(self.probes[0].event.ready.wait(3), "followers did not join flight")
                self.assertEqual(len(calls), 1, "parallel same-key downloads")
                if before_release:
                    before_release()
            finally:
                release.set()
                self.join_workers(threads)
        return calls, results

    def seed_spot(self, age=0.0, price=130.0, key="XAU"):
        E._SPOT_CACHE[key] = (self.clock.wall - age, price, self.clock.mono - age)

    def test_candle_ttl_existing_policy(self):
        for tf, ttl in (("1m", 7), ("5m", 37), ("15m", 90), ("4h", 90), ("1w", 90)):
            with self.subTest(tf=tf):
                self.assertEqual(E.candle_ttl(tf), ttl)

    def test_forming_119_is_not_promoted_at_121(self):
        self.clock.wall = 119.0
        calls = []

        def source(sym, tf, limit):
            calls.append(self.clock.wall)
            return ([bar(0, 10.0), bar(60, 999.0)] if len(calls) == 1
                    else [bar(60, 101.0), bar(120, 999.0)])

        with patch.object(E, "fetch_binance", source):
            first = E.fetch("BTCUSDT", "1m", 2)[3]
            self.clock.advance(2)
            second = E.fetch("BTCUSDT", "1m", 2)[3]
        self.assertEqual(calls, [119.0, 121.0])
        self.assertEqual(first[-1], bar(0, 10.0))
        self.assertEqual(second[-1], bar(60, 101.0))

    def test_cache_expires_exactly_at_intraday_boundary(self):
        for tf in E.TF_SECONDS:
            if tf == "1w":
                continue
            with self.subTest(tf=tf):
                E.clear_candles()
                secs = E.tf_seconds(tf)
                self.clock.wall = secs * 4 - 1.0
                self.assertTrue(self.put(bars(secs=secs), tf=tf))
                self.assertEqual(E._CANDLES[self.key(tf=tf)][0], secs * 4)
                self.clock.advance(1)
                self.assertIsNone(self.get(tf=tf))
                self.assertNotIn(self.key(tf=tf), E._CANDLES)

    def test_weekly_boundary_is_monday_not_epoch_thursday(self):
        monday = datetime.datetime(2026, 11, 23, tzinfo=datetime.timezone.utc).timestamp()
        self.clock.wall = monday - 1
        self.assertEqual(E._next_candle_boundary("1w", self.clock.wall), monday)
        self.put(bars(secs=E.tf_seconds("1w")), tf="1w")
        self.assertEqual(E._CANDLES[self.key(tf="1w")][0], monday)
        self.clock.advance(1)
        self.assertIsNone(self.get(tf="1w"))
        self.assertEqual(E._next_candle_boundary("1w", monday), monday + E.tf_seconds("1w"))

    def test_weekly_thursday_is_not_a_false_expiry_boundary(self):
        thursday = datetime.datetime(2026, 11, 26, tzinfo=datetime.timezone.utc).timestamp()
        self.clock.wall = thursday - 1
        self.put(bars(secs=E.tf_seconds("1w")), tf="1w")
        self.assertEqual(E._CANDLES[self.key(tf="1w")][0], self.clock.wall + 90)
        self.clock.advance(2)
        self.assertIsNotNone(self.get(tf="1w"))

    def test_off_grid_forming_close_also_limits_expiry(self):
        self.put([bar(39), bar(41)])   # t=41 closes at 101, before UTC boundary 120
        self.assertEqual(E._CANDLES[self.key()][0], 101.0)
        self.clock.advance(1)
        self.assertIsNone(self.get(n=2))

    def test_short_refresh_does_not_renew_large_payload(self):
        self.put(bars(30))
        original = copy.deepcopy(E._CANDLES[self.key()])
        self.clock.advance(2)
        self.assertFalse(self.put(bars(10, 120.0)))
        self.assertEqual(E._CANDLES[self.key()], original)
        self.clock.advance(6)
        self.assertIsNone(self.get(n=30))
        self.assertNotIn(self.key(), E._CANDLES)

    def test_older_larger_response_cannot_replace_newer_snapshot(self):
        old_wall, old_mono = self.clock.wall, self.clock.mono
        self.clock.advance(1)
        self.put(bars(5, 120.0))
        self.clock.advance(1)
        self.assertFalse(self.put(bars(30, 90.0), observed_at=old_wall, observed_mono=old_mono))
        self.assertEqual(self.get()[0]["c"], 120.0)

    def test_put_copy_is_deeply_isolated(self):
        raw = bars()
        raw[0]["metadata"] = {"notes": ["source"]}
        self.put(raw)
        raw[0]["c"] = -99.0
        raw[0]["metadata"]["notes"].append("changed")
        self.assertEqual(self.get()[0]["c"], 100.0)
        self.assertEqual(self.get()[0]["metadata"]["notes"], ["source"])

    def test_get_copy_is_deeply_isolated(self):
        raw = bars()
        raw[0]["metadata"] = {"notes": ["source"]}
        self.put(raw)
        first = self.get()
        first[0]["h"] = -99.0
        first[0]["metadata"]["notes"].clear()
        self.assertEqual(self.get()[0]["h"], 101.0)
        self.assertEqual(self.get()[0]["metadata"]["notes"], ["source"])

    def test_fetch_copy_does_not_alias_source_or_cache(self):
        raw = bars()
        with patch.object(E, "fetch_binance", return_value=raw) as source:
            first = E.fetch("BTCUSDT", "1m", 5)[3]
            first[-1]["c"] = 999.0
            raw[-1]["c"] = 777.0
            second = E.fetch("BTCUSDT", "1m", 5)[3]
        self.assertEqual(source.call_count, 1)
        self.assertEqual(second[-1]["c"], 100.0)

    def test_larger_payload_answers_smaller_request_with_same_trim(self):
        raw = bars(4) + [bar(60, 999.0)]
        with patch.object(E, "fetch_binance", return_value=raw) as source:
            first = E.fetch("BTCUSDT", "1m", 5)[3]
            second = E.fetch("BTCUSDT", "1m", 3)[3]
        self.assertEqual(source.call_count, 1)
        self.assertEqual(len(first), 4)
        self.assertEqual(second, raw[-3:-1])

    def test_exhausted_provider_window_does_not_refetch_same_limit(self):
        with patch.object(E, "fetch_binance", return_value=bars()) as source:
            self.assertEqual(len(E.fetch("BTCUSDT", "1m", 20)[3]), 5)
            self.assertEqual(len(E.fetch("BTCUSDT", "1m", 20)[3]), 5)
        self.assertEqual(source.call_count, 1)

    def test_expired_get_prunes_payload(self):
        self.put()
        self.clock.advance(7)
        self.assertIsNone(self.get())
        self.assertFalse(E._CANDLES)

    def test_get_miss_prunes_other_expired_keys(self):
        self.put(sym="OLDUSDT")
        self.put(tf="1d", sym="FRESHUSDT")
        self.clock.advance(8)
        self.assertIsNone(self.get(sym="MISSINGUSDT"))
        self.assertEqual(set(E._CANDLES), {self.key("FRESHUSDT", "1d")})

    def test_put_prunes_other_expired_keys(self):
        self.put(sym="OLDUSDT")
        self.clock.advance(8)
        self.put(sym="NEWUSDT")
        self.assertEqual(set(E._CANDLES), {self.key("NEWUSDT")})

    def test_total_bar_budget_is_enforced_with_8000_bar_payloads(self):
        raw = bars(8000)
        for i in range(9):
            self.put(raw, sym=f"CACHE{i}USDT")
        total = sum(len(entry[1]) for entry in E._CANDLES.values())
        self.assertLessEqual(total, E._CANDLES_MAX_BARS)
        self.assertLessEqual(len(E._CANDLES), E._CANDLES_MAX)
        self.assertGreater(total, 0)

    def test_oversized_payload_is_not_cached(self):
        with patch.object(E, "_CANDLES_MAX_BARS", 4):
            self.assertFalse(self.put())
        self.assertFalse(E._CANDLES)

    def test_entry_cap_is_enforced_without_waiting_for_twenty_excess_keys(self):
        with patch.object(E, "_CANDLES_MAX", 3):
            for i in range(5):
                self.put(bars(1), sym=f"KEY{i}USDT")
            self.assertLessEqual(len(E._CANDLES), 3)

    def test_wall_clock_rollback_invalidates_snapshot(self):
        self.put()
        self.clock.wall -= 1
        self.assertIsNone(self.get())
        self.assertFalse(E._CANDLES)

    def test_monotonic_ttl_expires_when_wall_clock_stalls(self):
        self.put()
        self.clock.mono += 7
        self.assertIsNone(self.get())
        self.assertFalse(E._CANDLES)

    def test_late_response_cannot_start_a_new_ttl(self):
        observed, mono = self.clock.wall, self.clock.mono
        self.clock.advance(8)
        self.assertFalse(self.put(observed_at=observed, observed_mono=mono))
        self.assertFalse(E._CANDLES)

    def test_empty_payload_is_not_cached(self):
        self.assertFalse(self.put([]))
        self.assertFalse(E._CANDLES)

    def test_unclosed_is_uncached_and_does_not_modify_closed_cache(self):
        raw = bars(4) + [bar(60, 999.0)]
        with patch.object(E, "fetch_binance", return_value=raw) as source:
            closed = E.fetch("BTCUSDT", "1m", 5)[3]
            cached = copy.deepcopy(E._CANDLES)
            self.assertEqual(E.fetch("BTCUSDT", "1m", 5, unclosed=True)[3][-1]["c"], 999.0)
            self.assertEqual(E.fetch("BTCUSDT", "1m", 5, True)[3][-1]["c"], 999.0)
            self.assertEqual(E._CANDLES, cached)
        self.assertEqual(len(closed), 4)
        self.assertEqual(source.call_count, 3)

    def test_aliases_share_cache_but_preserve_display_identifier(self):
        with patch.object(E, "fetch_yahoo", return_value=bars()) as source, patch.object(E, "_spot_price", return_value=None):
            first = E.fetch("XAUUSD", "1m", 5)
            second = E.fetch("GOLD", "1m", 5)
        self.assertEqual(source.call_count, 1)
        self.assertEqual(first[:3], ("yahoo", "GC=F", "XAUUSD"))
        self.assertEqual(second[:3], ("yahoo", "GC=F", "GOLD"))

    def test_basis_shift_uses_new_quote_without_mutating_futures_cache(self):
        raw = bars(secs=3600)
        with patch.object(E, "fetch_yahoo", return_value=raw) as source, patch.object(E, "http_get", side_effect=[{"price": 130}, {"price": 140}]) as spot:
            first = E.fetch("XAUUSD", "1h", 5)[3]
            self.clock.advance(61)
            second = E.fetch("XAUUSD", "1h", 5)[3]
        self.assertEqual(source.call_count, 1)
        self.assertEqual(spot.call_count, 2)
        self.assertEqual(first[-1]["c"], 130.0)
        self.assertEqual(second[-1]["c"], 140.0)
        self.assertEqual(E._CANDLES[self.key("GC=F", "1h", "yahoo")][1], raw)

    def test_same_key_candle_misses_share_one_download(self):
        calls, result = self.group("fetch_binance", lambda *a: bars(), lambda: E.fetch("BTCUSDT", "1m", 5))
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(error is None for _, error in result.values()))
        self.assertTrue(all(value[3] == bars() for value, _ in result.values()))
        result[0][0][3][0]["c"] = 999.0
        self.assertEqual(result[1][0][3][0]["c"], 100.0)
        self.assertEqual(self.get()[0]["c"], 100.0)

    def test_same_key_empty_response_is_shared_but_not_cached(self):
        calls, result = self.group("fetch_binance", lambda *a: [], lambda: E.fetch("BTCUSDT", "1m", 5))
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(value[3] == [] and error is None for value, error in result.values()))
        self.assertFalse(E._CANDLES)

    def test_same_key_failure_is_shared_and_releases_ownership(self):
        def fail(*args):
            raise OSError("fixed source outage")
        calls, result = self.group("fetch_binance", fail, lambda: E.fetch("BTCUSDT", "1m", 5))
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(isinstance(error, OSError) for _, error in result.values()))
        self.assertFalse(E._CANDLES)
        with patch.object(E, "fetch_binance", return_value=bars()):
            self.assertEqual(E.fetch("BTCUSDT", "1m", 5)[3], bars())

    def test_larger_follower_waits_then_fetches_serially(self):
        entered, release = threading.Event(), threading.Event()
        calls, result, active, peak = [], {}, [0], [0]
        self.install_probe(1)

        def source(sym, tf, limit):
            calls.append(limit)
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            try:
                entered.set()
                if not release.wait(5):
                    raise AssertionError("source release missing")
                return bars(limit)
            finally:
                active[0] -= 1

        threads = []
        with patch.object(E, "fetch_binance", source):
            try:
                threads.append(self.start_worker(lambda: E.fetch("BTCUSDT", "1m", 2), result, 0))
                self.assertTrue(entered.wait(3))
                threads.append(self.start_worker(lambda: E.fetch("BTCUSDT", "1m", 5), result, 1))
                self.assertTrue(self.probes[0].event.ready.wait(3))
                self.assertEqual(calls, [2])
            finally:
                release.set()
                self.join_workers(threads)
        self.assertEqual(calls, [2, 5])
        self.assertEqual(peak[0], 1)
        self.assertEqual(len(result[0][0][3]), 2)
        self.assertEqual(len(result[1][0][3]), 5)

    def test_candle_follower_timeout_does_not_duplicate_or_steal_flight(self):
        entered, release = threading.Event(), threading.Event()
        calls, result = [], {}
        self.install_probe(1)

        def source(*args):
            calls.append(args)
            entered.set()
            if not release.wait(5):
                raise AssertionError("source release missing")
            return bars()

        with patch.object(E, "fetch_binance", source):
            thread = self.start_worker(lambda: E.fetch("BTCUSDT", "1m", 5), result, 0)
            try:
                self.assertTrue(entered.wait(3))
                for _ in range(2):
                    with self.assertRaises(TimeoutError):
                        E.fetch("BTCUSDT", "1m", 5, timeout=0.01)
                self.assertEqual(len(calls), 1)
                self.assertIs(E._CANDLE_FLIGHTS[self.key()], self.probes[0])
                self.assertTrue(all(0 < timeout <= 0.01 for timeout in self.probes[0].event.waits))
            finally:
                release.set()
                self.join_workers([thread])
        self.assertIsNone(result[0][1])

    def test_expired_leader_does_not_publish_after_returning_from_io(self):
        def source(*args):
            self.clock.advance(6)
            return bars()
        with patch.object(E, "fetch_binance", side_effect=source) as mock:
            with self.assertRaises(TimeoutError):
                E.fetch("BTCUSDT", "1m", 5, timeout=5)
        self.assertEqual(mock.call_count, 1)
        self.assertFalse(E._CANDLES)
        self.assertFalse(E._CANDLE_FLIGHTS)

    def test_boundary_crossed_during_download_refetches_finalized_bar(self):
        self.clock.wall = 119.0
        calls = []

        def source(*args):
            calls.append(self.clock.wall)
            if len(calls) == 1:
                self.clock.advance(2)
                return [bar(0, 10.0), bar(60, 999.0)]
            return [bar(60, 101.0), bar(120, 999.0)]

        with patch.object(E, "fetch_binance", source):
            result = E.fetch("BTCUSDT", "1m", 2)[3]
        self.assertEqual(calls, [119.0, 121.0])
        self.assertEqual(result, [bar(60, 101.0)])
        self.assertEqual(E._CANDLES[self.key()][3], 121.0)

    def test_download_past_ttl_is_shared_without_renewing_cache(self):
        def source(*args):
            self.clock.advance(8)
            return bars()
        calls, result = self.group("fetch_binance", source, lambda: E.fetch("BTCUSDT", "1m", 5))
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(error is None and value[3] == bars() for value, error in result.values()))
        self.assertFalse(E._CANDLES)

    def test_clear_during_download_prevents_old_publication_and_overlap(self):
        count = [0]

        def source(*args):
            count[0] += 1
            return bars(c=100.0 if count[0] == 1 else 200.0)

        calls, result = self.group("fetch_binance", source, lambda: E.fetch("BTCUSDT", "1m", 5),
                                   before_release=E.clear_candles)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(error is None and value[3][-1]["c"] == 200.0 for value, error in result.values()))
        self.assertEqual(self.get()[-1]["c"], 200.0)

    def test_old_generation_put_is_rejected(self):
        generation = E._CANDLES_GENERATION
        E.clear_candles()
        self.assertFalse(self.put(generation=generation))
        self.assertFalse(E._CANDLES)

    def test_different_keys_can_fetch_without_a_global_io_lock(self):
        both, release = threading.Event(), threading.Event()
        result, entered, lock = {}, [], threading.Lock()

        def source(sym, *args):
            with lock:
                entered.append(sym)
                if len(entered) == 2:
                    both.set()
            if not release.wait(5):
                raise AssertionError("source release missing")
            return bars()

        with patch.object(E, "fetch_binance", source):
            threads = [self.start_worker(lambda s=s: E.fetch(s, "1m", 5), result, i)
                       for i, s in enumerate(("BTCUSDT", "ETHUSDT"))]
            try:
                self.assertTrue(both.wait(3), "cache lock held across I/O")
            finally:
                release.set()
                self.join_workers(threads)
        self.assertTrue(all(error is None for _, error in result.values()))

    def test_spot_unsupported_symbol_never_fetches(self):
        with patch.object(E, "http_get") as source:
            self.assertIsNone(E._spot_price("EURUSD"))
        source.assert_not_called()

    def test_spot_fresh_aliases_share_quote(self):
        with patch.object(E, "http_get", return_value={"price": 130.0}) as source:
            self.assertEqual(E._spot_price("XAUUSD"), 130.0)
            self.assertEqual(E._spot_price("GOLD"), 130.0)
        self.assertEqual(source.call_count, 1)

    def test_same_key_spot_misses_share_one_download(self):
        calls, result = self.group("http_get", lambda *a: {"price": 130}, lambda: E._spot_price("XAUUSD"))
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(value == 130.0 and error is None for value, error in result.values()))
        self.assertEqual(E._SPOT_CACHE["XAU"], (100.0, 130.0, 1000.0))

    def test_same_key_spot_outage_is_shared(self):
        self.seed_spot(age=61)
        original = E._SPOT_CACHE["XAU"]

        def fail(*args):
            raise OSError("fixed outage")
        calls, result = self.group("http_get", fail, lambda: E._spot_price("XAUUSD"))
        self.assertEqual(len(calls), 1)
        self.assertTrue(all(value == 130.0 and error is None for value, error in result.values()))
        self.assertEqual(E._SPOT_CACHE["XAU"], original)

    def test_spot_follower_timeout_does_not_duplicate_fetch(self):
        entered, release = threading.Event(), threading.Event()
        calls, result = [], {}
        self.install_probe(1)

        def source(*args):
            calls.append(args)
            entered.set()
            if not release.wait(5):
                raise AssertionError("source release missing")
            return {"price": 130}

        with patch.object(E, "http_get", source):
            thread = self.start_worker(lambda: E._spot_price("XAUUSD"), result, 0)
            try:
                self.assertTrue(entered.wait(3))
                self.assertIsNone(E._spot_price("GOLD", timeout=0.01))
                self.assertEqual(len(calls), 1)
                self.assertIs(E._SPOT_FLIGHTS["XAU"], self.probes[0])
            finally:
                release.set()
                self.join_workers([thread])
        self.assertEqual(result[0], (130.0, None))

    def test_spot_outage_fallback_has_a_hard_age_limit(self):
        with patch.object(E, "http_get", side_effect=OSError("outage")):
            for age, expected in ((61.0, 130.0), (119.9, 130.0), (120.0, None), (1000000000.0, None)):
                with self.subTest(age=age):
                    self.seed_spot(age)
                    self.assertEqual(E._spot_price("XAUUSD"), expected)
                    if expected is None:
                        self.assertNotIn("XAU", E._SPOT_CACHE)

    def test_spot_outage_does_not_promote_age_or_suppress_next_retry(self):
        self.seed_spot(age=61)
        original = E._SPOT_CACHE["XAU"]
        with patch.object(E, "http_get", side_effect=OSError("outage")) as source:
            self.assertEqual(E._spot_price("XAUUSD"), 130.0)
            self.clock.advance(1)
            self.assertEqual(E._spot_price("XAUUSD"), 130.0)
        self.assertEqual(source.call_count, 2)
        self.assertEqual(E._SPOT_CACHE["XAU"], original)

    def test_spot_rejects_nonfinite_zero_and_negative_prices(self):
        for price in (math.nan, math.inf, -math.inf, 0, -1):
            with self.subTest(price=price), patch.object(E, "http_get", return_value={"price": price}):
                self.assertIsNone(E._spot_price("XAUUSD"))
                self.assertNotIn("XAU", E._SPOT_CACHE)

    def test_spot_uses_monotonic_age_when_wall_clock_stalls(self):
        self.seed_spot()
        self.clock.mono += 120
        with patch.object(E, "http_get", side_effect=OSError("outage")):
            self.assertIsNone(E._spot_price("XAUUSD"))
        self.assertNotIn("XAU", E._SPOT_CACHE)

    def test_spot_wall_clock_rollback_invalidates_quote(self):
        self.seed_spot()
        self.clock.wall -= 1
        with patch.object(E, "http_get", side_effect=OSError("outage")):
            self.assertIsNone(E._spot_price("XAUUSD"))

    def test_spot_late_response_is_not_published(self):
        def source(*args):
            self.clock.advance(6)
            return {"price": 130}
        with patch.object(E, "http_get", source):
            self.assertIsNone(E._spot_price("XAUUSD", timeout=5))
        self.assertFalse(E._SPOT_CACHE)

    def test_spot_success_age_starts_before_io(self):
        def source(*args):
            self.clock.advance(2)
            return {"price": 130}
        with patch.object(E, "http_get", source):
            self.assertEqual(E._spot_price("XAUUSD"), 130.0)
        self.assertEqual(E._SPOT_CACHE["XAU"], (100.0, 130.0, 1000.0))

    def test_clear_spot_during_download_prevents_old_publication(self):
        count = [0]

        def source(*args):
            count[0] += 1
            return {"price": 130 if count[0] == 1 else 140}
        calls, result = self.group("http_get", source, lambda: E._spot_price("XAUUSD"),
                                   before_release=E.clear_spot_prices)
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(value == 140.0 and error is None for value, error in result.values()))
        self.assertEqual(E._SPOT_CACHE["XAU"][1], 140.0)

    def test_nested_request_budgets_cannot_extend_outer_deadline(self):
        with E._request_budget(5) as outer:
            with E._request_budget(60) as inner:
                self.assertEqual(inner, outer)
            self.assertEqual(E._REQUEST_CONTEXT.deadline, outer)
        self.assertIsNone(E._REQUEST_CONTEXT.deadline)

    def test_absolute_deadline_can_shorten_timeout(self):
        with E._request_budget(60, deadline=self.clock.mono + 2) as end:
            self.assertEqual(end, self.clock.mono + 2)
            self.assertEqual(E._remaining(), 2)

    def test_invalid_or_infinite_timeout_is_rejected(self):
        with patch.object(E, "fetch_binance") as source:
            for timeout in (0, -1, math.nan, math.inf):
                with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                    E.fetch("BTCUSDT", "1m", 5, timeout=timeout)
        source.assert_not_called()

    def test_expired_absolute_deadline_does_not_start_io(self):
        with patch.object(E, "fetch_binance") as source:
            with self.assertRaises(TimeoutError):
                E.fetch("BTCUSDT", "1m", 5, deadline=self.clock.mono)
        source.assert_not_called()

    def test_fetch_validates_limit_before_io(self):
        with patch.object(E, "fetch_binance") as source:
            for limit in (0, -1, 1.5, True):
                with self.subTest(limit=limit), self.assertRaises(ValueError):
                    E.fetch("BTCUSDT", "1m", limit)
        source.assert_not_called()

    def test_http_timeout_is_finite_and_clamped_to_total_budget(self):
        response = io.BytesIO(b'{"ok": true}')
        with patch.object(E.urllib.request, "urlopen", return_value=response) as source:
            self.assertEqual(E.http_get("https://example.invalid/test", timeout=2), {"ok": True})
        self.assertEqual(source.call_args.kwargs["timeout"], 2)
        self.assertTrue(response.closed)

    def test_trickling_http_body_cannot_renew_deadline(self):
        clock = self.clock

        class Response(io.BytesIO):
            reads = 0

            def read1(self, size: int | None = -1):
                self.reads += 1
                clock.advance(2)
                return b'{"ok":' if self.reads == 1 else b'true}'

        response = Response()
        with patch.object(E.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(TimeoutError):
                E.http_get("https://example.invalid/test", timeout=3)
        self.assertEqual(response.reads, 2)
        self.assertTrue(response.closed)

    def test_each_http_socket_read_uses_remaining_budget(self):
        clock = self.clock
        sock = Mock()

        class Response(io.BytesIO):
            reads = 0
            fp: Any

            def read1(self, size: int | None = -1):
                self.reads += 1
                if self.reads == 1:
                    clock.advance(1)
                    return b'{"ok": true}'
                return b''

        response = Response()
        response.fp = types.SimpleNamespace(raw=types.SimpleNamespace(_sock=sock))
        with patch.object(E.urllib.request, "urlopen", return_value=response):
            self.assertEqual(E.http_get("https://example.invalid/test", timeout=2), {"ok": True})
        self.assertEqual([call.args[0] for call in sock.settimeout.call_args_list], [2, 1])

    def test_host_retry_does_not_start_after_total_deadline(self):
        calls = []

        def source(url):
            calls.append(url)
            self.clock.advance(6)
            raise OSError("slow host outage")

        with patch.object(E, "http_get", source):
            with self.assertRaises(TimeoutError):
                E.fetch_binance("BTCUSDT", "1m", 5, timeout=5)
        self.assertEqual(len(calls), 1)

    def test_pagination_does_not_start_after_total_deadline(self):
        calls = []

        def source(url):
            calls.append(url)
            self.clock.advance(6)
            return [[i * 60000, "100", "101", "99", "100", "10"] for i in range(1000)]

        with patch.object(E, "http_get", source):
            with self.assertRaises(TimeoutError):
                E.fetch_binance("BTCUSDT", "1m", 2000, timeout=5)
        self.assertEqual(len(calls), 1)

    def test_host_penalty_behavior_is_preserved(self):
        calls = []

        def source(url):
            calls.append(url)
            if "api.binance.com" in url:
                raise OSError("fixed blocked host")
            return [[0, "100", "101", "99", "100", "10"]]

        with patch.object(E, "http_get", source):
            self.assertEqual(E.fetch_binance("BTCUSDT", "1m", 1), [bar(0)])
        self.assertEqual(len(calls), 2)
        self.assertIn("api.binance.us", calls[1])
        ordered = E._ordered_hosts(["https://api.binance.com", "https://api.binance.us"])
        self.assertEqual(ordered, ["https://api.binance.us", "https://api.binance.com"])

    def test_binance_existing_timestamp_deduplication_is_preserved(self):
        raw = [[0, "100", "101", "99", "100", "10"],
               [0, "110", "111", "109", "110", "10"],
               [60000, "120", "121", "119", "120", "10"]]
        with patch.object(E, "http_get", return_value=raw):
            self.assertEqual(E.fetch_binance("BTCUSDT", "1m", 2), [bar(0, 110), bar(60, 120)])

    def test_yahoo_nonfinite_ohlc_is_rejected(self):
        raw = bars(1)
        raw[0]["h"], raw[0]["c"] = math.nan, math.inf
        with patch.object(E, "http_get", return_value=yahoo_response(raw)):
            with self.assertRaisesRegex(RuntimeError, "نامعتبر"):
                E.fetch_yahoo("EURUSD=X", "1h", 3)

    def test_yahoo_duplicates_are_rejected(self):
        with patch.object(E, "http_get", return_value=yahoo_response([bar(0), bar(0)])):
            with self.assertRaisesRegex(RuntimeError, "تکراری"):
                E.fetch_yahoo("EURUSD=X", "1h", 3)

    def test_invalid_source_is_never_cached(self):
        for raw in ([bar(0), bar(0)], [dict(bar(0), c=math.nan)]):
            with self.subTest(raw=raw), patch.object(E, "fetch_binance", return_value=raw):
                with self.assertRaises(RuntimeError):
                    E.fetch("BTCUSDT", "1m", 2)
                self.assertFalse(E._CANDLES)
                self.assertFalse(E._CANDLE_FLIGHTS)

    def test_resample_duplicate_cannot_fill_a_missing_hour(self):
        raw = [bar(t) for t in (0, 3600, 3600, 10800)]
        with self.assertRaisesRegex(RuntimeError, "تکراری"):
            E.resample(raw, 4, tf_sec=14400)

    def test_resample_nonfinite_ohlc_is_rejected(self):
        raw = [bar(i * 3600) for i in range(4)]
        raw[2]["c"] = math.inf
        with self.assertRaisesRegex(RuntimeError, "نامعتبر"):
            E.resample(raw, 4, tf_sec=14400)

    def test_resample_valid_ohlcv_is_unchanged(self):
        raw = [bar(i * 3600, 100 + i) for i in range(4)]
        self.assertEqual(E.resample(raw, 4, tf_sec=14400),
                         [{"t": 0, "o": 100, "h": 104, "l": 99, "c": 103, "v": 40}])

    def test_analyze_accepts_optional_budget_without_changing_kernel(self):
        raw = bars(40, secs=3600)
        with patch.object(E, "fetch_binance", return_value=raw):
            result = E.analyze("BTCUSDT", "1h", 40, timeout=5, deadline=self.clock.mono + 3)
        self.assertEqual(result["bars"], 40)
        self.assertEqual(result["last_price"], 100.0)
        self.assertFalse(result["data"]["forming"])


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(CacheTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print("ENGINE_CACHE_RESULT " + json.dumps({"tests": result.testsRun,
                                               "failures": len(result.failures),
                                               "errors": len(result.errors),
                                               "skipped": len(result.skipped)}, sort_keys=True))
    sys.exit(0 if result.wasSuccessful() else 1)
