#!/usr/bin/env python3
"""Offline storage/risk edge regressions; all writes stay in temporary dirs.

Run with scratch HOME/TMPDIR and PIPFOUND_NOTIFY=0. No application server is
started: the gap worker's real functions are loaded from its AST with a fixed
market fixture. Spawned writers use barriers, not probabilistic sleep races.
"""
import ast
import concurrent.futures
import copy
import datetime
import json
import multiprocessing
import os
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest import mock

os.environ['PIPFOUND_NOTIFY'] = '0'
import autobackup as AB
import backup as BK
import risk as RK

NOW = datetime.datetime(2026, 9, 20, 10, 0)
ST = dict(RK.DEFAULTS, usd_per_quote={})
PLAN = {'entry': 1.1, 'sl': 1.095, 'rr': 3, 'direction': 'long'}
FIELDS = ['id', 'datetime', 'symbol', 'direction', 'entry', 'sl', 'tp', 'rr',
          'risk_pct', 'status', 'result', 'realized_r', 'notes']
KEY = '100|bullish|1.08|1.09'
NEW_KEY = '200|bullish|1.1|1.11'
HIT = {'at': '2026-09-20 09:00:00', 'key': KEY, 'symbol': 'EURUSD', 'tf': '15m',
       'grade': 'A', 'state_fa': 'دست‌نخورده', 'bottom': 1.08, 'top': 1.09,
       'percent': 80.0, 'why': 'گپِ تازه'}
WATCH = {'id': '7', 'symbol': 'EURUSD', 'mode': 'gap', 'direction': None,
         'style': 'day', 'active': True, 'triggered': False,
         'created': '2026-09-20 08:00:00', 'last_price': 1.105, 'tf': '15m',
         'seeded': True, 'seen': [KEY], 'hits': [HIT], 'alerts': 1,
         'last_scan': '2026-09-20 09:00:00', 'scanned': 1, 'reliable_now': 1}
BAD_NUMBERS = (True, False, float('nan'), float('inf'), -float('inf'),
               'NaN', 'Inf', '-Infinity', '1e10000', 10 ** 1000, [], {})


def bundle(alarm=None, settings=None):
    return BK.build([], FIELDS, [copy.deepcopy(WATCH if alarm is None else alarm)],
                    copy.deepcopy(ST if settings is None else settings), now='fixed')


def journal_row(status='closed', realized_r='-1', risk_pct='1', **extra):
    r = {'status': status, 'realized_r': realized_r, 'risk_pct': risk_pct,
         'datetime': '2026-09-20 09:00', 'symbol': 'EURUSD', 'direction': 'long'}
    r.update(extra)
    return r


def strict_json(value):
    return json.dumps(value, allow_nan=False)


class FixedGapMarket:
    """Declared test fixture, not a fetched/synthesized production response."""
    TF_LADDER = {'15m': '1h', '1h': '4h'}
    RELIABLE_GRADES = ('A+', 'A')

    @staticmethod
    def tf_above(tf):
        return FixedGapMarket.TF_LADDER.get(tf)

    @staticmethod
    def load(sym, tf, limit):
        gaps = [{'born_ts': 100, 'type': 'bullish', 'bottom': 1.08, 'top': 1.09},
                {'born_ts': 200, 'type': 'bullish', 'bottom': 1.1, 'top': 1.11}]
        return [{'c': 1.115}], {'FVG_unfilled': gaps}

    @staticmethod
    def gap_verdict(bars, tf, bottom, top, **kw):
        gp = next(g for g in kw['d']['FVG_unfilled'] if g['bottom'] == bottom)
        return {'ok': True, 'found': True, 'gap': gp, 'grade': 'A',
                'state_fa': 'دست‌نخورده', 'score': {'percent': 80.0}}


def load_gap_worker():
    source = Path(__file__).with_name('app.py').read_text(encoding='utf-8')
    wanted = {'_gap_key', '_gapwatch_grades', 'gap_watch_decide', '_gap_watch_once'}
    tree = ast.parse(source)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert len(nodes) == len(wanted), 'real gap-worker functions must all be present'
    import time
    ns = {'G': FixedGapMarket, 'time': time, 'GAP_WATCH_HITS_MAX': 20}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'real-app-gap-worker', 'exec'), ns)
    return ns['_gap_watch_once']


def state_writer_worker(path, barrier, result_queue):
    """Force both writers to finish their temp write before publication."""
    original = AB.os.replace
    def publish(src, dst):
        barrier.wait(timeout=15)
        return original(src, dst)
    try:
        AB.os.replace = publish
        AB._write_json(path, {'writer': os.getpid(), 'payload': 'x' * 4096})
        result_queue.put({'ok': True})
    except Exception as exc:
        result_queue.put({'ok': False, 'error': repr(exc)})
    finally:
        AB.os.replace = original


def snapshot_worker(directory, barrier, result_queue, prune=False):
    """Force the old check-then-write naming race; exclusive publish needs none."""
    exists = AB.os.path.exists
    waited = False
    base = AB.filename(NOW)
    def exists_together(path):
        nonlocal waited
        answer = exists(path)
        if not waited and os.path.basename(path) == base and not answer:
            waited = True
            barrier.wait(timeout=15)
        return answer
    try:
        AB.os.path.exists = exists_together
        barrier.wait(timeout=15)
        paths = []
        for seq in range(4 if prune else 1):
            doc = {'kind': BK.KIND, 'version': BK.VERSION, 'writer': os.getpid(), 'seq': seq}
            if prune:
                r = AB.snapshot(doc, dir=directory, keep=3, now=NOW)
                if r['bytes'] <= 0:
                    raise AssertionError('published snapshot returned zero bytes')
                paths.append(r['file'])
            else:
                paths.append(AB.write_snapshot(doc, dir=directory, now=NOW))
        result_queue.put({'ok': True, 'paths': paths})
    except Exception as exc:
        result_queue.put({'ok': False, 'error': repr(exc)})
    finally:
        AB.os.path.exists = exists


class BackupEdges(unittest.TestCase):
    def test_complete_gap_state_roundtrip_and_worker_continuity(self):
        doc = bundle()
        self.assertEqual(BK.validate(doc, FIELDS), [])
        restored, added, skipped = BK.merge_alarms([], doc['alarms'])
        self.assertEqual((added, skipped), (1, 0))
        self.assertEqual(restored[0], WATCH)
        patch, hits = load_gap_worker()(restored[0])
        self.assertIsNotNone(patch, 'missing tf makes restored watcher inert')
        self.assertEqual([h['key'] for h in hits], [NEW_KEY])
        self.assertEqual(patch['alerts'], 2)
        self.assertEqual(len(patch['hits']), 2)
        self.assertEqual(patch['seen'], sorted([KEY, NEW_KEY]))
        again, a, s = BK.merge_alarms(restored, doc['alarms'])
        self.assertEqual((a, s, again), (0, 1, restored))

    def test_unseeded_watcher_remains_silent_on_first_scan(self):
        watcher = dict(WATCH, seeded=False, seen=[], hits=[], alerts=0)
        doc = bundle(watcher)
        restored, _, _ = BK.merge_alarms([], doc['alarms'])
        patch, hits = load_gap_worker()(restored[0])
        self.assertIsNotNone(patch)
        self.assertEqual(hits, [])
        self.assertTrue(patch['seeded'])
        self.assertEqual(patch['alerts'], 0)

    def test_legacy_v1_price_ote_and_numeric_strings(self):
        alarms = [{'id': 9, 'symbol': 'XAUUSD', 'mode': 'price', 'target': '2500',
                   'cross': 'up', 'last_price': None, 'old_extension': 'ignored'},
                  {'id': '10', 'symbol': 'EURUSD', 'mode': 'ote', 'low': '1.08', 'high': '1.1'}]
        doc = BK.build([], FIELDS, alarms, ST)
        self.assertEqual(doc['version'], 1)
        self.assertEqual(BK.validate(doc, FIELDS), [])
        out, added, _ = BK.merge_alarms([], doc['alarms'])
        self.assertEqual(added, 2)
        self.assertEqual(out[0]['target'], '2500')
        self.assertNotIn('old_extension', out[0])

    def test_nested_state_is_detached_from_live_mutations(self):
        watcher = copy.deepcopy(WATCH)
        doc = BK.build([], FIELDS, [watcher], ST)
        watcher['seen'].append(NEW_KEY)
        watcher['hits'][0]['why'] = 'changed live'
        self.assertEqual(doc['alarms'][0]['seen'], [KEY])
        self.assertEqual(doc['alarms'][0]['hits'][0]['why'], HIT['why'])
        restored, _, _ = BK.merge_alarms([], doc['alarms'])
        restored[0]['hits'][0]['why'] = 'changed import'
        self.assertEqual(doc['alarms'][0]['hits'][0]['why'], HIT['why'])

    def test_unknown_modes_are_rejected(self):
        for mode in ('nonsense', 'PRICE', '', None, 7, [], {}):
            with self.subTest(mode=mode):
                d = bundle(); d['alarms'][0]['mode'] = mode
                self.assertTrue(BK.validate(d, FIELDS))

    def test_gap_timeframe_is_required_and_literal(self):
        for tf in (None, '', '2m', '15M', True, [], {}):
            with self.subTest(tf=tf):
                d = bundle(); d['alarms'][0]['tf'] = tf
                self.assertTrue(BK.validate(d, FIELDS))
        d = bundle(); del d['alarms'][0]['tf']
        self.assertTrue(BK.validate(d, FIELDS))

    def test_nonfinite_or_nested_alarm_prices_are_rejected(self):
        for field in ('target', 'low', 'high', 'last_price'):
            for value in BAD_NUMBERS:
                with self.subTest(field=field, value=repr(value)[:80]):
                    d = bundle(); d['alarms'][0][field] = value
                    self.assertTrue(BK.validate(d, FIELDS))

    def test_alarm_flags_counters_identifiers_and_state_shapes(self):
        bad = {'active': 'false', 'triggered': 1, 'seeded': 'yes',
               'alerts': -1, 'scanned': 1.5, 'reliable_now': True,
               'id': {'nested': 1}, 'symbol': ['EURUSD'], 'seen': [[KEY]],
               'hits': 'not a list', 'last_scan': {'at': 'bad'}}
        for field, value in bad.items():
            with self.subTest(field=field):
                d = bundle(); d['alarms'][0][field] = value
                self.assertTrue(BK.validate(d, FIELDS))

    def test_gap_hit_known_fields_are_validated(self):
        for field, value in (('tf', '2m'), ('grade', 'B'), ('bottom', float('nan')),
                             ('top', True), ('percent', 101), ('why', [])):
            with self.subTest(field=field):
                d = bundle(); d['alarms'][0]['hits'][0][field] = value
                self.assertTrue(BK.validate(d, FIELDS))

    def test_nested_work_and_length_bounds(self):
        for field, value in (('seen', [KEY] * (getattr(BK, 'MAX_SEEN', 5000) + 1)),
                             ('hits', [HIT] * (getattr(BK, 'MAX_HITS', 1000) + 1)),
                             ('hit_reason', 'x' * (getattr(BK, 'MAX_TEXT', 65536) + 1))):
            with self.subTest(field=field):
                d = bundle(); d['alarms'][0][field] = value
                self.assertTrue(BK.validate(d, FIELDS))
        deep = 0
        for _ in range(40):
            deep = {'x': deep}
        d = bundle(); d['alarms'][0]['extension'] = deep
        self.assertTrue(BK.validate(d, FIELDS))

    def test_settings_rates_currency_codes_and_supported_accounts(self):
        for changes in ({'account_ccy': 'XYZ'}, {'account_ccy': 'USDD'},
                        {'account_ccy': '۱۲۳'}, {'usd_per_quote': {'JPYY': 0.1}},
                        {'usd_per_quote': {'JPY': float('inf')}},
                        {'usd_per_quote': {'USD': 2}}, {'usd_per_quote': []}):
            with self.subTest(changes=changes):
                self.assertTrue(BK.validate(bundle(settings=dict(ST, **changes)), FIELDS))
        self.assertEqual(BK.validate(bundle(settings=dict(ST, account_ccy='SEK',
                                                        usd_per_quote={'SEK': 0.1})), FIELDS), [])

    def test_journal_financial_fields_reject_bad_present_values(self):
        for field, value in (('risk_pct', '-1'), ('risk_pct', True),
                             ('realized_r', 'NaN'), ('rr', 'Infinity'), ('entry', [])):
            with self.subTest(field=field):
                d = bundle(); d['journal'] = [{'symbol': 'EURUSD', field: value}]
                d['counts']['journal'] = 1
                self.assertTrue(BK.validate(d, FIELDS))

    def test_error_reports_are_capped(self):
        d = bundle(); d['alarms'] = [{'mode': 'bad'}] * 100
        self.assertTrue(BK.validate(d, FIELDS))
        self.assertLessEqual(len(BK.validate(d, FIELDS)), BK.MAX_PROBLEMS + 1)


class StorageEdges(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='pf-storage-edge-')
        self.addCleanup(self.tmp.cleanup)
        self.directory = self.tmp.name

    def run_processes(self, target, *args, workers=4):
        ctx = multiprocessing.get_context('spawn')
        barrier = ctx.Barrier(workers)
        results = ctx.Queue()
        children = [ctx.Process(target=target, args=(*args, barrier, results)) for _ in range(workers)]
        try:
            for child in children:
                child.start()
            output = [results.get(timeout=25) for _ in children]
            for child in children:
                child.join(timeout=15)
                self.assertEqual(child.exitcode, 0)
            self.assertTrue(all(r['ok'] for r in output), output)
            return output
        finally:
            for child in children:
                if child.is_alive():
                    child.terminate()
                    child.join(timeout=5)
            results.close()
            results.join_thread()

    def test_threaded_state_and_risk_writes_publish_whole_documents(self):
        for writer in (AB._write_json, RK.save_settings):
            with self.subTest(writer=writer.__name__):
                path = os.path.join(self.directory, writer.__name__ + '.json')
                barrier = threading.Barrier(2)
                original = os.replace
                def publish(src, dst):
                    barrier.wait(timeout=10)
                    return original(src, dst)
                docs = [dict(ST, balance=n, usd_per_quote={'JPY': 0.0068}) for n in (12345, 23456)]
                def run(doc):
                    return writer(path, doc) if writer is AB._write_json else writer(doc, path=path)
                with mock.patch.object(AB.os, 'replace', side_effect=publish):
                    with concurrent.futures.ThreadPoolExecutor(2) as pool:
                        output = list(pool.map(run, docs))
                data = json.loads(Path(path).read_text())
                self.assertIn(data['balance'], (12345, 23456))
                self.assertEqual(data['usd_per_quote'], {'JPY': 0.0068})
                self.assertFalse(any(n.endswith('.tmp') for n in os.listdir(self.directory)))

    def test_multiprocess_state_writes_have_no_shared_temp_path(self):
        path = os.path.join(self.directory, 'state.json')
        self.run_processes(state_writer_worker, path, workers=2)
        self.assertEqual(json.loads(Path(path).read_text())['payload'], 'x' * 4096)
        self.assertFalse(any(n.endswith('.tmp') for n in os.listdir(self.directory)))

    def test_multiprocess_same_second_snapshots_are_unique(self):
        results = self.run_processes(snapshot_worker, self.directory)
        paths = [p for r in results for p in r['paths']]
        self.assertEqual(len(set(paths)), 4)
        self.assertEqual(len(AB.list_backups(self.directory)), 4)
        self.assertEqual(len({json.loads(Path(p).read_text())['writer'] for p in paths}), 4)

    def test_threaded_snapshot_prune_is_one_serial_operation(self):
        start = threading.Barrier(12)
        def run(marker):
            start.wait(timeout=15)
            return AB.snapshot({'kind': BK.KIND, 'version': 1, 'marker': marker},
                               dir=self.directory, keep=4, now=NOW)
        with concurrent.futures.ThreadPoolExecutor(12) as pool:
            reports = list(pool.map(run, range(12)))
        self.assertEqual(len({r['name'] for r in reports}), 12)
        self.assertTrue(all(r['bytes'] > 0 for r in reports), reports)
        self.assertEqual(len(AB.list_backups(self.directory)), 4)
        self.assertFalse(any(n.endswith('.tmp') for n in os.listdir(self.directory)))

    def test_multiprocess_snapshot_prune_keeps_exact_retention(self):
        ctx = multiprocessing.get_context('spawn')
        barrier, result_queue = ctx.Barrier(4), ctx.Queue()
        children = [ctx.Process(target=snapshot_worker,
                                args=(self.directory, barrier, result_queue, True)) for _ in range(4)]
        try:
            for child in children:
                child.start()
            results = [result_queue.get(timeout=30) for _ in children]
            for child in children:
                child.join(timeout=15)
                self.assertEqual(child.exitcode, 0)
            self.assertTrue(all(r['ok'] for r in results), results)
            paths = [p for r in results for p in r['paths']]
            self.assertEqual(len(set(paths)), 16)
            self.assertEqual(len(AB.list_backups(self.directory)), 3)
        finally:
            for child in children:
                if child.is_alive():
                    child.terminate(); child.join(timeout=5)
            result_queue.close(); result_queue.join_thread()

    def test_same_second_prune_keeps_newest_not_old_base_or_lexical_suffix(self):
        for marker in range(12):
            AB.snapshot({'kind': BK.KIND, 'version': 1, 'marker': marker},
                        dir=self.directory, keep=3, now=NOW)
        markers = [json.loads(Path(b['file']).read_text())['marker'] for b in AB.list_backups(self.directory)]
        self.assertEqual(markers, [11, 10, 9])
        legacy = os.path.join(self.directory, 'legacy'); os.mkdir(legacy)
        base = AB.filename(NOW)
        for suffix in ('', '-2', '-10'):
            name = base[:-5] + suffix + '.json'
            Path(legacy, name).write_text(json.dumps({'kind': BK.KIND, 'version': 1}))
        self.assertEqual([b['name'] for b in AB.list_backups(legacy)],
                         [base[:-5] + '-10.json', base[:-5] + '-2.json', base])
        self.assertEqual(AB.prune(dir=legacy, keep=1)['kept'], [base[:-5] + '-10.json'])

    def test_prune_and_listing_ignore_symlinks_directories_and_unrelated_files(self):
        notes = Path(self.directory, 'notes.txt'); notes.write_text('keep me')
        link = Path(self.directory, 'pipfound-backup-20990101-000000.json')
        link.symlink_to(notes)
        broken = Path(self.directory, 'pipfound-backup-20990101-000001.json')
        broken.symlink_to('absent')
        folder = Path(self.directory, 'pipfound-backup-20990101-000002.json'); folder.mkdir()
        tmp = Path(self.directory, 'leftover.json.tmp'); tmp.write_text('unrelated')
        AB.snapshot({'kind': BK.KIND, 'version': 1}, dir=self.directory, keep=1, now=NOW)
        report = AB.prune(dir=self.directory, keep=1)
        self.assertEqual(len(AB.list_backups(self.directory)), 1)
        self.assertTrue(link.is_symlink()); self.assertTrue(broken.is_symlink())
        self.assertTrue(folder.is_dir()); self.assertEqual(notes.read_text(), 'keep me')
        self.assertEqual(tmp.read_text(), 'unrelated')
        self.assertNotIn(link.name, report['kept'] + report['deleted'])

    def test_legacy_shared_temp_symlink_is_never_opened(self):
        path = Path(self.directory, 'settings.json')
        notes = Path(self.directory, 'notes.txt'); notes.write_text('original')
        Path(str(path) + '.tmp').symlink_to(notes)
        AB._write_json(str(path), {'ok': True})
        self.assertEqual(notes.read_text(), 'original')
        self.assertTrue(Path(str(path) + '.tmp').is_symlink())
        self.assertEqual(json.loads(path.read_text()), {'ok': True})

    def test_failed_serialization_does_not_publish_or_leave_temp_files(self):
        path = os.path.join(self.directory, 'state.json')
        AB._write_json(path, {'original': True})
        for value in (object(), float('nan'), float('inf')):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises((TypeError, ValueError)):
                    AB._write_json(path, {'value': value})
                self.assertEqual(json.loads(Path(path).read_text()), {'original': True})
                self.assertFalse(any(n.endswith('.tmp') for n in os.listdir(self.directory)))

    def test_backup_filename_validation_is_ascii_full_match(self):
        self.assertFalse(AB.is_backup_name('pipfound-backup-20260920-100000.json\n'))
        self.assertFalse(AB.is_backup_name('pipfound-backup-۲۰۲۶۰۹۲۰-۱۰۰۰۰۰.json'))


class RiskEdges(unittest.TestCase):
    def assert_blocked_finite(self, settings=ST, rows=(), plan=PLAN):
        value = RK.evaluate('EURUSD', plan, settings, rows, now=NOW)
        self.assertTrue(value['blocked'], value)
        self.assertTrue(value['block_reason'])
        strict_json(value)
        return value

    def test_number_parser_accepts_only_finite_scalars_not_bools(self):
        for value in BAD_NUMBERS:
            with self.subTest(value=repr(value)[:80]):
                self.assertIsNone(RK._num(value))
        self.assertEqual(RK._num('۱٬۰۰۰'), 1000)
        self.assertEqual(RK._num(' -2.5 '), -2.5)

    def test_bad_plan_fields_never_size_or_allow(self):
        for field in ('entry', 'sl', 'rr'):
            for value in BAD_NUMBERS:
                with self.subTest(field=field, value=repr(value)[:80]):
                    plan = dict(PLAN, **{field: value})
                    self.assertFalse(RK.size_for('EURUSD', plan, ST)['ok'])
                    self.assert_blocked_finite(plan=plan)
        for plan in ('not a plan', [1], True):
            with self.subTest(plan=plan):
                self.assertFalse(RK.size_for('EURUSD', plan, ST)['ok'])
                self.assert_blocked_finite(plan=plan)

    def test_bad_settings_do_not_fall_back_to_a_false_allow(self):
        for field in ('balance', 'risk_pct', 'daily_loss_limit_pct', 'max_open_risk_pct'):
            for value in BAD_NUMBERS + (-1,):
                with self.subTest(field=field, value=repr(value)[:80]):
                    self.assert_blocked_finite(settings=dict(ST, **{field: value}))
        self.assert_blocked_finite(settings=dict(ST, balance=0))
        self.assert_blocked_finite(settings=dict(ST, risk_pct=0))
        for value in ([1], 'bad', True):
            with self.subTest(settings=value):
                self.assert_blocked_finite(settings=value)

    def test_invalid_rates_and_unknown_accounts_do_not_assume_one_to_one(self):
        for account in ('XYZ', 'USDD', '۱۲۳', ['USD'], {'ccy': 'USD'}):
            with self.subTest(account=account):
                settings = dict(ST, account_ccy=account)
                self.assertFalse(RK.size_for('EURUSD', PLAN, settings)['ok'])
                self.assert_blocked_finite(settings=settings)
        for rate in BAD_NUMBERS + (0, -1):
            with self.subTest(rate=repr(rate)[:80]):
                settings = dict(ST, account_ccy='EUR', usd_per_quote={'EUR': rate})
                self.assert_blocked_finite(settings=settings)
        self.assert_blocked_finite(settings=dict(ST, usd_per_quote={'USD': 2}))
        self.assert_blocked_finite(settings=dict(ST, usd_per_quote={'JPYY': 0.1}))

    def test_custom_account_conversion_and_same_currency_cancellation(self):
        settings = dict(ST, account_ccy='SEK', usd_per_quote={'SEK': 0.1})
        sized = RK.size_for('EURUSD', PLAN, settings)
        self.assertTrue(sized['ok'], sized)
        self.assertEqual(sized['size'], 0.02)
        self.assertEqual(sized['risk_per_lot'], 5000)
        self.assertEqual(sized['actual_risk_amount'], 100)
        self.assertFalse(sized['approx'])
        settings = dict(ST, account_ccy='JPY', usd_per_quote={'JPY': 1e-200})
        sized = RK.size_for('USDJPY', dict(PLAN, entry=150, sl=149.5), settings)
        self.assertTrue(sized['ok'], sized)
        self.assertEqual(sized['risk_per_lot'], 50000)

    def test_extreme_finite_math_never_crashes_or_returns_nonfinite(self):
        cases = [(dict(PLAN, entry=1e308, sl=-1e308), ST),
                 (PLAN, dict(ST, balance=1e308, risk_pct=1e308)),
                 (dict(PLAN, rr=1e308), dict(ST, balance=1e308)),
                 (dict(PLAN, entry=1e-320, sl=0), dict(ST, balance=1e308)),
                 (PLAN, dict(ST, account_ccy='EUR', usd_per_quote={'EUR': 1e-320}))]
        for plan, settings in cases:
            with self.subTest(plan=plan, settings=settings):
                sized = RK.size_for('EURUSD', plan, settings)
                self.assertFalse(sized['ok'], sized)
                strict_json(sized)
                self.assert_blocked_finite(settings=settings, plan=plan)

    def test_bad_journal_numbers_and_shapes_fail_closed(self):
        for status in ('open', 'closed'):
            for value in BAD_NUMBERS + (-1,):
                with self.subTest(status=status, risk_pct=repr(value)[:80]):
                    self.assert_blocked_finite(rows=[journal_row(status=status, risk_pct=value)])
        for value in BAD_NUMBERS:
            with self.subTest(realized_r=repr(value)[:80]):
                self.assert_blocked_finite(rows=[journal_row(realized_r=value)])
        for rows in ([None], ['row'], {'status': 'open'}, 'bad'):
            with self.subTest(rows=rows):
                self.assert_blocked_finite(rows=rows)
        self.assert_blocked_finite(rows=[journal_row(status='unknown')])
        self.assert_blocked_finite(rows=[journal_row(datetime='not a date')])
        self.assert_blocked_finite(rows=[journal_row(realized_r='', result='unknown')])

    def test_finite_daily_overflow_and_cancellation_are_checked(self):
        self.assert_blocked_finite(rows=[journal_row(realized_r='1e308', risk_pct='1e308')])
        rows = [journal_row(realized_r='1e100'), journal_row(realized_r='-3.1'),
                journal_row(realized_r='-1e100')]
        evaluated = RK.evaluate('EURUSD', PLAN, ST, rows, now=NOW)
        self.assertTrue(evaluated['blocked'], evaluated)
        self.assertEqual(evaluated['daily']['realized_pct'], -3.1)
        strict_json(evaluated)

    def test_booked_r_percent_and_account_money_are_distinct(self):
        rows = [journal_row(realized_r='-1', risk_pct='2'),
                journal_row(realized_r='2', risk_pct='0.5')]
        day = RK.daily_state(rows, dict(ST, account_ccy='EUR'), now=NOW)
        self.assertEqual(day['realized_r'], 1)
        self.assertEqual(day['realized_pct'], -1)
        self.assertEqual(day['realized_amount'], -100)
        self.assertFalse(day['breached'])
        strict_json(day)

    def test_fx_pips_are_not_raw_quote_movements_or_account_money(self):
        eur = RK.size_for('EURUSD', PLAN, ST)
        jpy = RK.size_for('USDJPY', dict(PLAN, entry=150, sl=149.5), ST)
        self.assertEqual((eur['stop_distance'], eur['stop_pips'], eur['value_per_point']),
                         (0.005, 50.0, 10.0))
        self.assertEqual(jpy['stop_pips'], 50)
        self.assertEqual(jpy['point'], 0.01)
        self.assertAlmostEqual(jpy['value_per_point'], 6.6667, places=4)
        self.assertEqual((eur['size_units'], eur['risk_amount']), (20000, 100))

    def test_hard_limits_use_unrounded_percent_values(self):
        rows = [journal_row(realized_r='-1', risk_pct='2.99999')]
        self.assertFalse(RK.evaluate('EURUSD', PLAN, ST, rows, now=NOW)['daily']['breached'])
        rows = [journal_row(realized_r='-1', risk_pct='3.00001')]
        self.assertTrue(RK.evaluate('EURUSD', PLAN, ST, rows, now=NOW)['daily']['breached'])
        rows = [journal_row(status='open', realized_r='', risk_pct='4.99999')]
        self.assert_blocked_finite(rows=rows)  # proposed 1% would exceed 5%
        rows = [journal_row(status='open', realized_r='', risk_pct='4')]
        self.assertFalse(RK.evaluate('EURUSD', PLAN, ST, rows, now=NOW)['blocked'])

    def test_legacy_blank_row_risk_and_result_fallbacks_still_work(self):
        rows = [journal_row(risk_pct='', realized_r='', result='loss')]
        self.assertEqual(RK.daily_state(rows, dict(ST, risk_pct=2), now=NOW)['realized_pct'], -2)
        rows = [journal_row(realized_r='', result='win', rr='2.5'),
                journal_row(realized_r='', result='be')]
        self.assertEqual(RK.daily_state(rows, ST, now=NOW)['realized_r'], 2.5)
        value = RK.evaluate('EURUSD', None, ST, [], now=NOW)
        self.assertFalse(value['blocked']); strict_json(value)

    def test_corrupt_saved_settings_keep_diagnostics_and_block(self):
        with tempfile.TemporaryDirectory(prefix='pf-settings-edge-') as directory:
            path = os.path.join(directory, 'risk.json')
            for data in ({'daily_loss_limit_pct': 'Infinity'}, {'risk_pct': True},
                         {'account_ccy': 'USDD'}, {'usd_per_quote': {'JPY': -1}}):
                with self.subTest(data=data):
                    Path(path).write_text(json.dumps(data))
                    self.assert_blocked_finite(settings=RK.load_settings(path))
            Path(path).write_text('{not json')
            self.assert_blocked_finite(settings=RK.load_settings(path))


if __name__ == '__main__':
    unittest.main(verbosity=2)
