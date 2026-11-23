#!/usr/bin/env python3
"""Deterministic trading-logic regressions; all candles/news here are TEST fixtures.

No live market/news data, profitability claims, app import, or personal writes.
Run: PIPFOUND_NOTIFY=0 python3 trading_logic_test.py
PIPFOUND_LOGIC_SOURCE may point at an untouched source snapshot for before/after
reproduction. Tests deliberately use the real scorer/core except where a unit
is testing order scheduling independently of signal discovery.
"""
import copy
import datetime
import os
import socket
import sys
import unittest
import urllib.request
from unittest.mock import patch

SOURCE = os.environ.get("PIPFOUND_LOGIC_SOURCE", os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SOURCE)
NET_ATTEMPTS = []


def no_network(*args, **kwargs):
    NET_ATTEMPTS.append(repr(args[:1]))
    raise AssertionError("network forbidden in trading logic fixtures")


socket.getaddrinfo = no_network
socket.create_connection = no_network
urllib.request.urlopen = no_network

import confluence as C
import backtest as B
import gap_query as G
import smt as S
import smc_engine as E

UTC = datetime.timezone.utc
T0 = int(datetime.datetime(2026, 6, 10, 12, tzinfo=UTC).timestamp())


def event_at(ts, impact="High"):
    return {"title": "TEST scheduled release", "country": "USD", "impact": impact,
            "date": datetime.datetime.fromtimestamp(ts, UTC).isoformat(),
            "forecast": "1", "previous": "1"}


def coverage(ts=T0):
    return {"historical": True, "source": "TEST archived fixture",
            "from": ts - 7 * 86400, "to": ts + 7 * 86400}


class CalendarFixture:
    """Optional-quality-free provider; proves backwards-compatible capabilities."""
    def __init__(self, status="GREEN"):
        self.status = status
        self.get_calls = 0
        self.times = []

    def get_calendar(self):
        self.get_calls += 1
        return []

    def symbol_ccys(self, symbol):
        return {"USD"}

    def news_gate(self, cal, ccys, now=None):
        self.times.append(now)
        if now is None:
            return self.status, "TEST", []
        near = [r for r in cal if -1800 <=
                datetime.datetime.fromisoformat(r["date"]).timestamp() - now <= 3600]
        status = "RED" if any(r["impact"] == "High" for r in near) else "AMBER" if near else "GREEN"
        return status, "TEST", near


class LegacyCalendarFixture:
    def get_calendar(self):
        return []

    def symbol_ccys(self, symbol):
        return []

    def news_gate(self, cal, ccys):
        return "GREEN", "TEST", []


def score_block(trend="up"):
    return {"trend": trend, "BOS": ["bullish_BOS", 102, 35],
            "CHoCH": ["bullish_CHoCH", 102, 35], "last_price": 103.0,
            "data": {"state": "open", "forming": False},
            "premium_discount": {"range_top": 110.0, "range_bottom": 100.0,
                                 "zone": "discount", "price_pct": 30, "equilibrium": 105.0},
            "liquidity": {"buyside_eqh": [110.0], "sellside_eql": [100.0],
                          "range_high": 110.0, "range_low": 100.0},
            "liquidity_sweeps": [{"type": "bullish_sweep", "level": 102.0,
                                  "idx": 39, "bar_from_end": 2}],
            "sequence_ok": True,
            "displacement": {"present": True, "direction": "bullish", "body_x_avg": 2},
            "order_blocks": [{"type": "bullish", "bottom": 102.0, "top": 104.0}],
            "FVG_unfilled": [], "killzone": "New York AM KZ"}


def scored(tfs=None, **kwargs):
    tfs = tfs or ["1d", "4h", "1h", "15m"]
    return C.score("BTCUSDT", tfs, d={tf: score_block() for tf in tfs}, **kwargs)


def candles(n=100, start=T0, seconds=60):
    return [{"t": start + i * seconds, "o": 100.0, "h": 100.2,
             "l": 99.8, "c": 100.0} for i in range(n)]


def plan(entry_type="market", entry=100.0, sl=99.0, tp=103.0):
    return {"direction": "صعودی", "entry": entry, "sl": sl, "tp": tp,
            "rr": 3.0, "entry_type": entry_type}


def run_orders(bars, chosen_plan=None, **kwargs):
    """Scheduling unit fixture; scoring/core parity is verified separately."""
    calls = []
    chosen_plan = plan() if chosen_plan is None else chosen_plan

    def fake_score(symbol, tfs, d=None, **kw):
        now = kw.get("now")
        idx = next((i for i, bar in enumerate(bars) if bar["t"] + 60 == now), None)
        calls.append((idx, kw))
        # Baseline does not pass now: use d's fixture index to reproduce it too.
        if idx is None:
            idx = d["_idx"]
            calls[-1] = (idx, kw)
        return {"grade": "A", "plan": copy.deepcopy(chosen_plan) if idx == 60 else None,
                "entry_stamp": {"stamped": False}, "news_gate": "UNKNOWN",
                "data": {"state": "open", "forming": False}}

    def build(series, tfs, timestamp, **kw):
        return {"_idx": next(i for i, bar in enumerate(bars) if bar["t"] == timestamp)}

    with patch.object(E, "fetch", return_value=("TEST", "BTCUSDT", "BTCUSDT", bars)), \
            patch.object(B, "_build_d", side_effect=build), patch.object(C, "score", side_effect=fake_score):
        result = B.backtest("BTCUSDT", tfs=["1m"], walk=100, **kwargs)
    return result, calls


class ScoreTests(unittest.TestCase):
    def setUp(self):
        self.macro = CalendarFixture()
        self.guard = patch.object(C, "M", self.macro)
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def test_red_blocks_entry_and_stamp_without_destroying_structure(self):
        green = scored()
        self.macro.status = "RED"
        red = scored()
        self.assertIsNotNone(red["plan"])
        self.assertFalse(red["plan"]["executable_now"])
        self.assertFalse(red["entry_stamp"]["stamped"])
        self.assertEqual(red["execution_gate"]["status"], "RED")
        self.assertFalse(red["execution_gate"]["allowed"])
        self.assertEqual(red["technical_grade"], green["technical_grade"])
        self.assertIn("ممنوع", red["verdict"])

    def test_unknown_is_not_confirmed_green(self):
        self.macro.status = "UNKNOWN"
        result = scored()
        self.assertEqual(result["news_gate"], "UNKNOWN")
        self.assertFalse(result["execution_gate"]["allowed"])
        self.assertFalse(result["entry_stamp"]["stamped"])
        self.assertFalse(result["plan"]["executable_now"])

    def test_intermediate_timeframe_conflict_is_consumed(self):
        tfs = ["1d", "4h", "1h", "15m"]
        blocks = {tf: score_block() for tf in tfs}
        blocks["1h"].update(trend="down", CHoCH=None, BOS=None)
        result = C.score("BTCUSDT", tfs, d=blocks)
        row = next(c for c in result["checklist"] if c["name"] == "هم‌راستاییِ چند تایم‌فریم")
        self.assertEqual(row["got"], 0)
        self.assertEqual(result["grade"], "B")
        self.assertFalse(result["entry_stamp"]["stamped"])

    def test_intermediate_neutral_is_not_full_alignment(self):
        tfs = ["1d", "4h", "1h", "15m"]
        blocks = {tf: score_block() for tf in tfs}
        blocks["1h"].update(trend="range", CHoCH=None, BOS=None)
        row = next(c for c in C.score("BTCUSDT", tfs, d=blocks)["checklist"]
                   if c["name"] == "هم‌راستاییِ چند تایم‌فریم")
        self.assertEqual(row["got"], 1)

    def test_historical_score_never_fetches_current_calendar(self):
        result = scored(now=T0)
        self.assertEqual(self.macro.get_calls, 0)
        self.assertEqual(result["news_gate"], "UNKNOWN")
        self.assertFalse(result["news_coverage"]["available"])
        self.assertEqual(result, scored(now=T0))

    def test_archived_gate_uses_exact_decision_timestamp(self):
        cal = [event_at(T0 + 7200)]
        a = scored(now=T0, calendar=cal, calendar_coverage=coverage())
        b = scored(now=T0 + 5400, calendar=cal, calendar_coverage=coverage())
        self.assertEqual((a["news_gate"], b["news_gate"]), ("GREEN", "RED"))
        self.assertEqual(self.macro.times, [T0, T0 + 5400])
        self.assertEqual(self.macro.get_calls, 0)

    def test_current_week_calendar_cannot_validate_an_older_period(self):
        result = scored(now=T0, calendar=[event_at(T0 + 100 * 86400)],
                        calendar_coverage=coverage())
        self.assertEqual(result["news_gate"], "UNKNOWN")
        self.assertEqual(self.macro.times, [])

    def test_unproven_archive_coverage_is_unknown(self):
        result = scored(now=T0, calendar=[event_at(T0)], calendar_coverage=None)
        self.assertEqual(result["news_gate"], "UNKNOWN")
        self.assertEqual(self.macro.times, [])

    def test_legacy_provider_needs_no_new_optional_helper(self):
        with patch.object(C, "M", LegacyCalendarFixture()):
            self.assertTrue(scored()["execution_gate"]["allowed"])
            self.assertEqual(scored(now=T0, calendar=[event_at(T0)],
                                    calendar_coverage=coverage())["news_gate"], "UNKNOWN")

    def test_stale_quality_overrides_a_green_provider(self):
        self.macro.calendar_quality = lambda cal, now=None: {"status": "UNKNOWN", "fresh": False}
        result = scored()
        self.assertEqual(result["news_gate"], "UNKNOWN")
        self.assertFalse(result["execution_gate"]["allowed"])

    def test_delayed_data_cannot_receive_entry_stamp(self):
        blocks = {"15m": score_block()}
        blocks["15m"]["data"]["state"] = "delayed"
        result = C.score("BTCUSDT", ["15m"], d=blocks)
        self.assertFalse(result["execution_gate"]["allowed"])
        self.assertFalse(result["entry_stamp"]["stamped"])

    def test_stamp_rejects_price_beyond_poi(self):
        result = C._entry_stamp(1, dict(plan(), poi_bottom=102.0, poi_top=104.0), 101.0,
                                1.0, True, {"present": True, "direction": "bullish"},
                                None, None, False, False)
        self.assertFalse(result["stamped"])

    def test_stamp_rejects_missing_poi_boundaries(self):
        result = C._entry_stamp(1, plan(), 103.0, 1.0, True,
                                {"present": True, "direction": "bullish"}, None, None, False, False)
        self.assertFalse(result["stamped"])

    def test_score_rejects_nonfinite_and_malformed_stacks(self):
        for tfs in ([], ["15m", "1h"], ["15m", "15m"], ["15m", "3m"]):
            with self.subTest(tfs=tfs), self.assertRaises((ValueError, TypeError)):
                C.score("BTCUSDT", tfs, d={})
        for bad in (float("nan"), float("inf"), -float("inf")):
            blocks = {"15m": score_block()}
            blocks["15m"]["last_price"] = bad
            with self.subTest(value=bad), self.assertRaises(ValueError):
                C.score("BTCUSDT", ["15m"], d=blocks)
            self.assertIsNone(C.ote_zone({"range_top": bad, "range_bottom": 100}, 1, 103))

    def test_core_prefix_is_invariant_to_future_ohlc(self):
        tfs = ["4h", "1h", "15m"]
        series = {"_disp": "BTCUSDT"}
        for tf in tfs:
            sec = E.tf_seconds(tf)
            series[tf] = candles(80, start=T0 - 59 * sec, seconds=sec)
        poisoned = copy.deepcopy(series)
        decision = T0 + E.tf_seconds("15m")
        for tf in tfs:
            for bar in poisoned[tf]:
                if bar["t"] + E.tf_seconds(tf) > decision:
                    bar.update(o=10000.0, h=10001.0, l=9999.0, c=10000.0)
        a = B._build_d(series, tfs, T0)
        b = B._build_d(poisoned, tfs, T0)
        self.assertEqual(a, b)
        self.assertTrue(all(x["data"]["last_bar_ts"] + E.tf_seconds(tf) <= decision
                            for tf, x in a.items()))
        self.assertIs(B.CF.score, C.score)
        self.assertIs(B.EG.analyze_bars, E.analyze_bars)


class BacktestTests(unittest.TestCase):
    def setUp(self):
        self.macro = CalendarFixture()
        self.guard = patch.object(C, "M", self.macro)
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def test_filled_open_trade_is_retained_and_prevents_overlap(self):
        result, calls = run_orders(candles())
        self.assertEqual(result["trades"], 1)
        self.assertEqual(result["open_trades"], 1)
        self.assertEqual(result["closed_trades"], 0)
        self.assertEqual([i for i, kw in calls], [60])
        self.assertIsNone(result["trade_log"][0]["r"])
        self.assertIsNone(result["trade_log"][0]["exit_time"])
        self.assertFalse(result["news_coverage"]["fully_news_filtered"])
        self.assertEqual(self.macro.get_calls, 0)
        self.assertIn("اسپرد", B._fmt_fa(result))

    def test_pending_unfilled_order_reserves_its_entire_window(self):
        result, calls = run_orders(candles(), plan("limit_ote", 90, 89, 93), fill_window=3)
        self.assertEqual([i for i, kw in calls][:2], [60, 64])
        self.assertEqual(result["trades"], 0)
        self.assertEqual(len(result["order_log"]), 1)

    def test_max_hold_censors_without_inventing_exit_or_overlap(self):
        result, calls = run_orders(candles(), max_hold=1)
        self.assertEqual(len(calls), 1)
        trade = result["trade_log"][0]
        self.assertEqual(trade["censor_reason"], "max_hold")
        self.assertEqual(trade["bars_held"], 1)
        self.assertIsNone(trade["exit_time"])

    def test_fill_gate_rechecks_news_at_confirmation_not_signal(self):
        bars = candles()
        bars[62].update(o=100.0, h=100.6, l=99.95, c=100.4)
        signal = bars[60]["t"] + 60
        cal = [event_at(signal + 3660)]
        # Scheduling fixture's signal is UNKNOWN, so use a real historical gate
        # in this score fixture to distinguish GREEN-at-signal from RED-at-fill.
        def score(symbol, tfs, d=None, now=None, **kw):
            status = C._news_context(symbol, now=now, **kw)["status"]
            return {"grade": "A", "plan": plan("limit_ote", 100, 99, 104) if now == signal else None,
                    "news_gate": status, "data": {"state": "open"}}
        with patch.object(E, "fetch", return_value=("TEST", "BTCUSDT", "BTCUSDT", bars)), \
                patch.object(B, "_build_d", return_value={}), patch.object(C, "score", side_effect=score):
            result = B.backtest("BTCUSDT", tfs=["1m"], calendar=cal,
                                calendar_coverage=coverage(), date_from=signal, date_to=signal)
        self.assertEqual(result["trades"], 0)
        self.assertEqual(len(result["order_log"]), 1)
        self.assertIn("ممنوع", result["order_log"][0]["reason"])
        self.assertIn(bars[62]["t"] + 60, self.macro.times)
        self.assertEqual(self.macro.get_calls, 0)

    def test_silver_bullet_decision_gate_has_summer_and_winter_boundaries(self):
        for month, opening in ((1, 14), (6, 13)):
            for hour, minute, accepted in ((opening - 1, 59, False),
                                           (opening, 0, True), (opening + 2, 0, False)):
                decision = int(datetime.datetime(2026, month, 15, hour, minute, tzinfo=UTC).timestamp())
                bars = candles(start=decision - 61 * 60)
                result, calls = run_orders(bars, style="sb_ny", date_from=decision, date_to=decision)
                with self.subTest(month=month, hour=hour, minute=minute):
                    self.assertNotIn("error", result)
                    self.assertEqual(result["trades"], int(accepted))
                    self.assertEqual(len(calls), int(accepted))
                    if accepted:
                        self.assertEqual(calls[0][1]["now"], decision)

    def test_silver_bullet_fill_outside_window_is_cancelled(self):
        decision = int(datetime.datetime(2026, 6, 15, 14, 59, tzinfo=UTC).timestamp())
        bars = candles(start=decision - 61 * 60)
        bars[62].update(o=100.0, h=100.6, l=99.95, c=100.4)
        result, calls = run_orders(bars, plan("limit_ote", 100, 99, 104), style="sb_ny",
                                  date_from=decision, date_to=decision)
        self.assertEqual(result["trades"], 0)
        self.assertIn("پنجره", result["order_log"][0]["reason"])

    def test_date_range_selects_decision_close_not_bar_open(self):
        bars = candles()
        decision = bars[60]["t"] + 60
        result, calls = run_orders(bars, date_from=decision, date_to=decision)
        self.assertEqual([i for i, kw in calls], [60])
        self.assertEqual(result["trade_log"][0]["signal_time"], decision)

    def test_metrics_separate_open_inventory_and_disclose_zero_costs(self):
        closed = [{"time": "TEST", "r": 2.0, "result": "win"},
                  {"time": "TEST", "r": -1.0, "result": "loss"}]
        opened = {"time": "TEST", "r": None, "result": "open", "booked_R": 0.5, "unrealized_R": 0.25}
        result = B._summarize("TEST", "day", ["15m"], closed + [opened])
        self.assertEqual((result["trades"], result["closed_trades"], result["open_trades"]), (3, 2, 1))
        self.assertEqual(result["winrate_pct"], 50.0)
        self.assertEqual(result["expectancy_R"], 0.5)
        self.assertEqual(result["total_R"], 1.0)
        self.assertEqual(result["open_booked_R"], 0.5)
        self.assertEqual(result["costs"]["basis"], "gross_R")
        self.assertFalse(result["costs"]["included"])

    def test_actual_fill_rejects_reversed_stop_or_target(self):
        for stop, target in ((101, 103), (99, 95)):
            self.assertIsNone(B._simulate(candles(3), 0, 1, 100, stop, target, "market"))

    def test_actual_fill_respects_explicit_minimum_rr(self):
        self.assertIsNone(B._simulate(candles(3), 0, 1, 100, 99, 101.5, "market", min_rr=2))

    def test_stop_first_when_both_extremes_are_touched(self):
        bars = candles(2)
        bars[1].update(o=100.0, h=104.0, l=98.0, c=102.0)
        result = B._simulate(bars, 0, 1, 100, 99, 103, "market")
        self.assertEqual((result[0], result[2]), ("loss", -1.0))

    def test_new_breakeven_stop_is_not_ignored_on_tp1_bar(self):
        bars = candles(3)
        bars[1].update(o=100.0, h=101.2, l=99.5, c=101.0)
        bars[2].update(o=101.3, h=103.2, l=101.2, c=103.0)
        result = B._simulate(bars, 0, 1, 100, 99, 103, "market")
        self.assertEqual(result[2], 0.5)
        self.assertEqual(result[3], 1)

    def test_nonfinite_backtest_controls_fail_before_fetch(self):
        for kwargs in ({"walk": float("inf")}, {"walk": float("nan")},
                       {"max_hold": 0}, {"fill_window": -1}, {"date_from": float("nan")},
                       {"date_from": T0 + 1, "date_to": T0}, {"tfs": []}, {"side": "invalid"}):
            with self.subTest(kwargs=kwargs), patch.object(E, "fetch", side_effect=AssertionError("must not fetch")):
                self.assertIn("error", B.backtest("BTCUSDT", **kwargs))


BEAR_SWEEP = [(-6, 6), (3, 4), (-4, 4), (6, 6), (-5, 5), (4, 4), (-3, 4), (8, 6), (-3, 4)]
BEAR_HOLD = [(-6, 6), (3, 4), (-4, 4), (6, 6), (-5, 5), (4, 4), (-3, 4), (12, 6), (-6, 6), (2, 4), (-3, 4)]


def zigzag(level, moves):
    output = []
    for amplitude, count in moves:
        for _ in range(count):
            level += amplitude / count
            output.append(round(level, 3))
    return [{"t": T0 + i * 3600, "o": close, "h": close + 0.4,
             "l": close - 0.4, "c": close} for i, close in enumerate(output)]


class SmtTests(unittest.TestCase):
    def setUp(self):
        self.a = zigzag(100, BEAR_SWEEP)
        self.b = zigzag(200, BEAR_HOLD)

    def test_normal_fixture_still_diverges(self):
        self.assertTrue(S.smt_divergence("A", self.a, "B", self.b, -1)["diverged"])

    def test_disjoint_partner_dates_are_not_same_phase(self):
        shifted = [dict(row, t=row["t"] + 100 * 86400) for row in self.b]
        self.assertFalse(S.smt_divergence("A", self.a, "B", shifted, -1)["diverged"])

    def test_nonfinite_or_unordered_bars_are_rejected_without_exception(self):
        for key in ("t", "h", "l", "c"):
            bad = copy.deepcopy(self.a)
            bad[0][key] = float("nan")
            with self.subTest(key=key):
                self.assertFalse(S.smt_divergence("A", bad, "B", self.b, -1)["diverged"])
        self.assertFalse(S.smt_divergence("A", list(reversed(self.a)), "B", self.b, -1)["diverged"])

    def test_default_fetch_invokes_real_engine_api_shape(self):
        def fetch(symbol, tf, limit):
            return "TEST", symbol, symbol, self.a if symbol == "EURUSD" else self.b
        with patch.object(E, "fetch", side_effect=fetch) as spy:
            result = S.check_for("EURUSD", -1)
        self.assertTrue(result["checked"]["diverged"])
        self.assertEqual([call.args[1:] for call in spy.call_args_list], [("1h", 120), ("1h", 120)])

    def test_three_argument_injected_fetch_is_supported(self):
        def fetch(symbol, tf, limit):
            return self.a if symbol == "EURUSD" else self.b
        self.assertTrue(S.check_for("EURUSD", -1, fetch_fn=fetch)["checked"]["diverged"])

    def test_lower_high_is_labelled_lh_not_ll(self):
        result = S.smt_divergence("A", self.b, "B", self.a, -1)
        self.assertEqual(result["last_two"]["A"]["label"], "LH")



def gap_bars():
    bars = candles(57, start=T0, seconds=900)
    for row in bars:
        row.update(h=100.02, l=99.98)
    bars += [{"t": T0 + 57 * 900, "o": 99.92, "h": 99.95, "l": 99.90, "c": 99.92},
             {"t": T0 + 58 * 900, "o": 99.95, "h": 104.1, "l": 99.94, "c": 104.0},
             {"t": T0 + 59 * 900, "o": 100.08, "h": 100.1, "l": 100.05, "c": 100.05}]
    return bars


def gap_block():
    return {"data": {"state": "open", "forming": False}, "trend": "up", "sequence_ok": True,
            "liquidity_sweeps": [{"type": "bullish_sweep", "idx": 56, "level": 99.90}],
            "premium_discount": {"equilibrium": 200.0},
            "order_blocks": [{"type": "bullish", "bottom": 99.90, "top": 100.10}],
            "liquidity": {}, "FVG_unfilled": []}


class GapTests(unittest.TestCase):
    def setUp(self):
        self.guard = patch.object(C, "M", CalendarFixture())
        self.guard.start()
        self.addCleanup(self.guard.stop)

    def test_engine_up_down_bias_matches_live_scorer(self):
        for trend, expected in (("up", 1), ("down", -1)):
            self.assertEqual(G._bias({"trend": trend}), expected)
            self.assertEqual(G._bias({"trend": trend}), C._bias(trend, None, None))

    def test_forming_or_unknown_freshness_is_not_green(self):
        self.assertEqual(G._data_gate({"data": {"state": "open", "forming": True}})[0], "C")
        self.assertEqual(G._data_gate({})[0], "B")

    def test_raw_future_candle_cannot_bypass_core_with_injected_analysis(self):
        bars = gap_bars()
        result = G.gap_verdict(bars, "15m", 99.95, 100.05, d=gap_block(),
                               now=bars[-1]["t"] + 30)
        self.assertFalse(result["ok"])

    def test_proximal_half_is_directionally_correct(self):
        gap = {"bottom": 100.0, "mid": 102.0, "top": 104.0}
        long = G._levels(gap, {}, "bullish", 1, 105)
        short = G._levels(gap, {}, "bearish", -1, 99)
        self.assertEqual((long["entry_low"], long["entry_high"]), (102.0, 104.0))
        self.assertEqual((short["entry_low"], short["entry_high"]), (100.0, 102.0))

    def test_birth_sequence_cannot_use_a_later_unrelated_mss(self):
        bars = gap_bars()
        bars += [{"t": T0 + k * 900, "o": 115.0, "h": 115.2, "l": 114.8, "c": 115.0}
                 for k in range(60, 80)]
        now = bars[-1]["t"] + 900
        data = E.analyze_bars(bars, "15m", disp="BTCUSDT", sym="BTCUSDT", now=now)
        data["sequence_ok"] = True  # TEST unrelated present-time confirmation
        with patch.object(E, "analyze_bars", wraps=E.analyze_bars) as core:
            result = G.gap_verdict(bars, "15m", 99.95, 100.05, d=data, now=now)
        sequence = next(row for row in result["checks"] if "توالیِ" in row["name"])
        self.assertNotEqual(sequence["status"], "✓")
        self.assertTrue(core.called)
        self.assertEqual(len(core.call_args.args[0]), 60)
        self.assertEqual(core.call_args.kwargs["now"], bars[59]["t"] + 900)

    def test_nonfinite_addresses_fail_without_loading_prices(self):
        for lo, hi in ((float("nan"), 101), (100, float("inf")), (100, None)):
            with patch.object(G, "load", side_effect=AssertionError("must not load")):
                self.assertFalse(G.query("BTCUSDT", "15m", lo, hi)["ok"])

    def test_news_permission_is_separate_from_structural_gap_grade(self):
        bars = gap_bars()
        now = T0 + 70 * 900
        data, htf = gap_block(), gap_block()
        base = dict(d=data, d_htf=htf, htf="1h", now=now, sym="BTCUSDT", calendar_coverage=coverage())
        green = G.gap_verdict(bars, "15m", 99.95, 100.05,
                              calendar=[event_at(now + 7200)], **base)
        red = G.gap_verdict(bars, "15m", 99.95, 100.05,
                            calendar=[event_at(now)], **base)
        self.assertEqual(red["grade"], green["grade"])
        self.assertEqual(red["execution_gate"]["status"], "RED")
        self.assertFalse(red["execution_gate"]["allowed"])
        self.assertFalse(red["executable_now"])
        self.assertFalse(red["levels"]["executable_now"])


class HermeticTests(unittest.TestCase):
    def test_no_network_attempts(self):
        self.assertEqual(NET_ATTEMPTS, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
