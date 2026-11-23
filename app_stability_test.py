#!/usr/bin/env python3
"""Hermetic regression tests for HTTP, UI contracts and concurrency."""
import argparse
import base64
import datetime
import concurrent.futures
import csv
import importlib
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import urllib.parse
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from typing import Any

parser = argparse.ArgumentParser()
parser.add_argument('--root', default=str(Path(__file__).parent))
args = parser.parse_args()
ROOT = Path(args.root).resolve()
HOME = tempfile.TemporaryDirectory(prefix='pf-app-stability-')
os.environ['HOME'] = HOME.name
os.environ['PIPFOUND_JOURNAL_CSV'] = str(Path(HOME.name) / 'journal.csv')
os.environ['PIPFOUND_AUTOBACKUP_STATE'] = str(Path(HOME.name) / 'backup-state.json')
os.environ['PIPFOUND_NOTIFY'] = '0'
sys.path.insert(0, str(ROOT))
app = importlib.import_module('app')


class AppStability(unittest.TestCase):
    server: Any
    @classmethod
    def setUpClass(cls):
        cls.server = getattr(app, 'BoundedHTTPServer', ThreadingHTTPServer)(('127.0.0.1', 0), app.Handler)
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(5)

    def setUp(self):
        setattr(app, '_ACCESS_TOKEN', '')
        for p in (Path(app._JR_FILE), Path(app.ALARMS_FILE)):
            if p.exists():
                p.unlink()

    def request(self, path, data=None, headers=None):
        h = {'Content-Type': 'application/json'}
        h.update(headers or {})
        req = urllib.request.Request(self.url + path, data=(json.dumps(data).encode() if data is not None else None), headers=h)
        try:
            r = urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as e:
            r = e
        with r:
            body = r.read().decode()
            return r.status, json.loads(body), dict(r.headers)

    def test_01_finite_alarm_numbers(self):
        for v in ('nan', 'inf', '-inf', float('nan'), True, [], {}):
            with self.subTest(value=str(v)):
                self.assertIsNone(app._alarm_num(v))
        self.assertEqual(app._alarm_num('150.25'), 150.25)

    def test_02_nonfinite_alarm_not_persisted(self):
        code, data, _ = self.request('/api/alarm', {'symbol': 'XAUUSD', 'mode': 'price', 'target': 'nan'})
        self.assertIn('error', data)
        code, data, _ = self.request('/api/alarms')
        self.assertEqual(data, [])

    def test_03_cookie_roundtrip(self):
        setattr(app, '_ACCESS_TOKEN', 'synthetic.test-token:cookie')
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
        with op.open(self.url + '/?token=' + urllib.parse.quote(app._ACCESS_TOKEN), timeout=10) as r:
            self.assertIn('id="go"', r.read().decode())
        req = urllib.request.Request(self.url + '/api/alarm', data=json.dumps({'symbol': 'XAUUSD', 'mode': 'price', 'target': 100}).encode(), headers={'Content-Type': 'application/json'})
        with op.open(req, timeout=10) as r:
            self.assertIn('added', json.loads(r.read()))

    def raw(self, headers):
        with socket.create_connection(('127.0.0.1', self.server.server_port), timeout=5) as s:
            s.sendall(headers)
            s.shutdown(socket.SHUT_WR)
            return s.recv(8192).decode(errors='replace')

    def test_04_bad_content_length_is_controlled(self):
        for value in ('nope', '-1'):
            r = self.raw(('POST /api/import HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: ' + value + '\r\n\r\n').encode())
            self.assertRegex(r, r'HTTP/1\.[01] 400')
        self.assertTrue(self.request('/api/health')[1]['ok'])

    def test_05_body_limit_and_json_shape(self):
        r = self.raw(b'POST /api/risk HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: application/json\r\nContent-Length: 100000000\r\n\r\nx')
        self.assertRegex(r, r'HTTP/1\.[01] 413')
        for data in ([], 'bad', 3):
            code, body, _ = self.request('/api/risk', data)
            self.assertEqual(code, 400)
            self.assertIn('error', body)

    def test_06_journal_concurrency_and_stdout(self):
        writer = app._JournalFallback()
        original = writer._read
        def slow_read(path):
            rows = original(path)
            time.sleep(.04)
            return rows
        writer._read = slow_read
        payload = {'symbol': 'XAUUSD', 'plan': {'direction': 'صعودی', 'entry': 2400, 'sl': 2380, 'tp': 2450, 'rr': 2.5}}
        stdout = sys.stdout
        with patch.object(app, '_JR', writer):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
                out = list(ex.map(lambda _: self.request('/api/journal', payload)[1], range(2)))
        after_stdout = sys.stdout
        sys.stdout = stdout  # Keep baseline failure from corrupting the test runner.
        self.assertEqual({r.get('added') for r in out}, {'1', '2'}, out)
        with open(app._JR_FILE, newline='', encoding='utf-8') as f:
            self.assertEqual(len(list(csv.DictReader(f))), 2)
        self.assertIs(after_stdout, stdout)

    def test_07_alarm_merge_and_one_fetch_per_symbol(self):
        original = [dict(id=str(i), symbol='XAUUSD', mode='price', target=1000, cross='above', active=True, triggered=False) for i in (1, 2)]
        app._save_alarms(original)
        calls = []
        def price(sym):
            calls.append(sym)
            if len(calls) == 1:
                with app._alarms_lock:
                    live = [a for a in app._load_alarms() if a['id'] != '1']
                    live.append(dict(id='new', symbol='EURUSD', mode='price', target=2, cross='above', active=True))
                    app._save_alarms(live)
            return 100
        class StopCycle(BaseException):
            pass
        def stop(_):
            raise StopCycle()
        with patch.object(app, '_live_price', price):
            if hasattr(app, '_alarm_once'):
                app._alarm_once()
            else:
                with patch.object(app.time, 'sleep', stop):
                    try:
                        app._alarm_worker()
                    except StopCycle:
                        pass
        self.assertEqual({a['id'] for a in app._load_alarms()}, {'2', 'new'})
        self.assertEqual(calls, ['XAUUSD'])

    def test_08_setup_lights_honor_blockers(self):
        names = ['بایاسِ تایم‌فریم بالا واضح', 'هم‌راستاییِ چند تایم‌فریم', 'پریمیوم/دیسکانتِ درست', 'ناحیه‌ی OTE (۰.۶۲–۰.۷۹ فیب)', 'سوئیپِ لیکوئیدیتیِ تازه (تریگر)', 'چاکِ ساختاری روی LTF', 'توالیِ سوئیپ→ام‌اس‌اس', 'دیسپلیسمنت (حرکتِ نهادی)', 'نقطه‌ی ورود (اردر بلاک/فیرولیوگپ)', 'کانفلوئنسِ POIِ تایم‌فریم بالا', 'امکانِ RR ≥ ۱:۲']
        result = {'checklist': [dict(name=n, status='✓') for n in names], 'plan': {'executable_now': False, 'blocked_reason': 'خبر یا سقف ریسک'}, 'macro': {'gate': 'RED'}}
        self.assertTrue(all(s['state'] != 'green' for s in app._setup_statuses(result)))

    def test_09_background_thread_bound(self):
        wait = threading.Event()
        ran = []
        def block(i):
            ran.append(i)
            wait.wait(3)
        threads = [app._bg(block, i) for i in range(8)]
        time.sleep(.05)
        wait.set()
        for t in threads:
            if t:
                t.join(5)
        self.assertLessEqual(len(ran), 2)

    def test_10_http_cache_headers(self):
        with urllib.request.urlopen(self.url + '/sw.js', timeout=10) as r:
            self.assertIn('no-cache', r.headers.get('Cache-Control', ''))
            self.assertEqual(r.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertIn('no-store', self.request('/api/health')[2].get('Cache-Control', ''))

    def test_11_client_escape_and_refresh_result(self):
        source = (ROOT / 'app.py').read_text()
        def fn(name):
            m = re.search(r'(?:async )?function ' + name + r'\([^\n]*\)\{.*?\n\}', source, re.S)
            return m.group() if m else ''
        script = """const vm=require('vm');
(async()=>{
const grid={innerHTML:'',querySelectorAll:()=>[]};
const ctx={String,style:'day',document:{getElementById:()=>grid},encodeURIComponent,fetch:async()=>({json:async()=>[{id:'a\\" onclick=x',symbol:'<svg/onload=x>',note:'<img src=x onerror=x>',created:'<b>x</b>'}]}),window:{},symIn:{value:'XAUUSD',focus:()=>{}},goBtn:{},res:{innerHTML:''},ANALYZE_TIMEOUT_MS:100,jfetch:async()=>({error:'network failed'}),render:()=>{},showLiveChart:()=>{}};
vm.createContext(ctx);vm.runInContext(FUNCTIONS,ctx);
await vm.runInContext('loadShots()',ctx);
const failed=await vm.runInContext('run()',ctx);
ctx.jfree=0;ctx.jfetch=async()=>({symbol:'XAUUSD'});
const success=await vm.runInContext('run()',ctx);
console.log(JSON.stringify({escaped:grid.innerHTML.includes('&lt;img')&&!grid.innerHTML.includes('<img src=x onerror=x'),failed,success}));
})().catch(e=>{console.error(e);process.exit(1)});
""".replace('FUNCTIONS', json.dumps(fn('pfEscape') + '\n' + fn('loadShots') + '\n' + fn('run')))
        r = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr)
        result = json.loads(r.stdout)
        self.assertTrue(result['escaped'])
        self.assertIs(result.get('failed'), False)
        self.assertIs(result.get('success'), True)

    def test_12_screenshot_concurrency_and_size(self):
        png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl6Yh0AAAAASUVORK5CYII=')
        payload = {'symbol': 'XAUUSD', 'note': 'test', 'dataurl': 'data:image/png;base64,' + base64.b64encode(png).decode()}
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(lambda _: self.request('/api/screenshot', payload)[1], range(16)))
        ids = [r.get('added') for r in results]
        self.assertTrue(all(ids), results)
        self.assertEqual(len(ids), len(set(ids)))
        # Advertised decoded limit must not be mistakenly applied to base64 JSON.
        payload['dataurl'] = 'data:image/png;base64,' + base64.b64encode(png + b'\0' * (10 * 1024 * 1024)).decode()
        code, result, _ = self.request('/api/screenshot', payload)
        self.assertIn('added', result)

    def test_13_cross_origin_write_rejected(self):
        code, result, _ = self.request('/api/alarm', {'symbol': 'XAUUSD', 'mode': 'price', 'target': 100}, {'Origin': 'https://untrusted.invalid'})
        self.assertEqual(code, 403)
        self.assertIn('error', result)

    def test_14_server_bound_declared(self):
        self.assertTrue(hasattr(app, 'BoundedHTTPServer'))
        self.assertLessEqual(getattr(self.server, 'max_workers', 9999), 16)

    def test_15_socket_worker_ceiling(self):
        sockets = []
        try:
            for _ in range(self.server.max_workers):
                s = socket.create_connection(('127.0.0.1', self.server.server_port), timeout=3)
                s.sendall(b'POST /api/risk HTTP/1.1\r\n')  # Deliberately incomplete headers.
                sockets.append(s)
            end = time.monotonic() + 3
            while self.server._http_slots._value and time.monotonic() < end:
                time.sleep(.01)
            self.assertEqual(self.server._http_slots._value, 0)
            extra = self.raw(b'GET /api/health HTTP/1.1\r\nHost: localhost\r\n\r\n')
            self.assertRegex(extra, r'HTTP/1\.[01] 503')
        finally:
            for s in sockets:
                s.close()
        end = time.monotonic() + 3
        while self.server._http_slots._value != self.server.max_workers and time.monotonic() < end:
            time.sleep(.01)
        self.assertEqual(self.server._http_slots._value, self.server.max_workers)
        self.assertTrue(self.request('/api/health')[1]['ok'])

    def test_16_heavy_request_bound_and_health(self):
        release = threading.Event()
        entered = []
        def work(symbol, style):
            entered.append(symbol)
            release.wait(5)
            return {'synthetic_test': True}
        with patch.object(app, 'analyze', work):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
                jobs = [ex.submit(self.request, '/api/analyze?symbol=XAUUSD') for _ in range(2)]
                try:
                    end = time.monotonic() + 3
                    while len(entered) < 2 and time.monotonic() < end:
                        time.sleep(.01)
                    self.assertEqual(len(entered), 2)
                    code, data, _ = self.request('/api/analyze?symbol=EURUSD')
                    self.assertEqual(code, 503)
                    self.assertIn('error', data)
                    self.assertTrue(self.request('/api/health')[1]['ok'])
                finally:
                    release.set()
                self.assertTrue(all(job.result()[0] == 200 for job in jobs))

    def test_17_bad_host_and_json_constants(self):
        code, body, _ = self.request('/api/health', headers={'Host': 'untrusted.invalid'})
        self.assertEqual(code, 403)
        for raw in (b'{"risk_pct":NaN}', b'{"risk_pct":1e999}'):
            headers = b'POST /api/risk HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: ' + str(len(raw)).encode() + b'\r\n\r\n'
            self.assertRegex(self.raw(headers + raw), r'HTTP/1\.[01] 400')

    def test_18_unicode_token_and_http_bootstrap_cookie(self):
        setattr(app, '_ACCESS_TOKEN', 'آزمون.توکن')
        old_tls = app._TLS_PORT
        setattr(app, '_TLS_PORT', 12345)  # HTTP bootstrap must not inherit HTTPS-only cookie.
        try:
            op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
            with op.open(self.url + '/?token=' + urllib.parse.quote(app._ACCESS_TOKEN), timeout=10) as r:
                self.assertIn('id="go"', r.read().decode())
        finally:
            setattr(app, '_TLS_PORT', old_tls)

    def test_19_dirty_cache_revisions_are_content_based(self):
        with tempfile.TemporaryDirectory(prefix='pf-rev-') as d:
            p = Path(d) / 'app.py'
            old_mem = app._CACHE_REV_MEM.copy()
            try:
                with patch.object(app, 'REV_ROOT', d), patch.object(app, 'REV_TRACKED', ['app.py']), patch.object(app, 'code_rev', lambda: {'disk': {'sha': 'abcdef123456', 'dirty': True}}):
                    p.write_text('first dirty state')
                    app._CACHE_REV_MEM['val'] = None
                    first = app.cache_rev()
                    p.write_text('second distinct dirty state')
                    app._CACHE_REV_MEM['val'] = None
                    second = app.cache_rev()
                    self.assertNotEqual(first, second)
            finally:
                app._CACHE_REV_MEM.clear()
                app._CACHE_REV_MEM.update(old_mem)

    def test_20_missing_smt_keeps_independent_risk(self):
        code = "import builtins,sys; original=builtins.__import__; builtins.__import__=lambda name,*a,**k: (_ for _ in ()).throw(ImportError('synthetic missing SMT')) if name=='smt' else original(name,*a,**k); import app; assert app.RK is not None; assert app.SMT is None; print('optional_imports_ok')"
        r = subprocess.run([sys.executable, '-c', code], cwd=ROOT, env=os.environ, capture_output=True, text=True, timeout=15)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('optional_imports_ok', r.stdout)

    def test_21_missing_market_data_is_error_not_no_trade(self):
        with patch.object(app.C, 'scan', lambda symbol, tfs: {tf: {'error': 'synthetic source failure'} for tf in tfs}):
            with self.assertRaisesRegex(RuntimeError, 'synthetic source failure'):
                app.C.score('BTCUSDT', ['1h', '5m'])

    def test_22_tls_never_disables_peer_verification(self):
        for context in (app.E._CTX, app.M.CTX):
            self.assertTrue(context.check_hostname)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertGreater(context.cert_store_stats()['x509_ca'], 0)

    def test_23_overlap_and_asian_labels_match_real_windows(self):
        for day, hour in ((datetime.date(2026, 1, 13), 15), (datetime.date(2026, 6, 10), 14)):
            stamp=datetime.datetime.combine(day, datetime.time(hour,30), tzinfo=datetime.timezone.utc).timestamp()
            label=app.E.killzone_at(stamp)
            self.assertIn('New York AM', label)
            self.assertIn('London Close', label)
            self.assertIn('کلوزِ لندن', app.C._kz_fa(label))
        stamp=datetime.datetime(2026,1,13,5,30,tzinfo=datetime.timezone.utc).timestamp()
        self.assertIn('19:00-02:00', app.E.killzone_at(stamp))


if __name__ == '__main__':
    try:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(AppStability)
        result = unittest.TextTestRunner(verbosity=2, stream=sys.__stdout__).run(suite)
        raise SystemExit(not result.wasSuccessful())
    finally:
        HOME.cleanup()
