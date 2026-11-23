#!/usr/bin/env python3
"""Offline packaging/PWA regressions: real builds + pure Node fixtures.

No browser, app server, Desktop bundle, notifications, Pillow or installs are
launched by this suite. Browser/CacheStorage fixtures exercise the actual SW
source; they are not real market/API results. Node is a development prerequisite.
"""
import json
import os
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

import make_app
import make_icons

ROOT = Path(__file__).resolve().parent

NODE_CHECK = r'''
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[2], "utf8").replaceAll("__CACHE_REV__", "unit");
const ui = fs.readFileSync(process.argv[3], "utf8");

function fixture(code, state) {
  const records = new Map(), calls = [], listeners = new Map();
  const counts = { skip: 0, claim: 0, fetch: 0 };
  const key = (req) => new URL(typeof req === "string" ? req : req.url, "https://pf.test").href;
  const cache = (name) => ({
    async match(req) { const r = records.get(name)?.get(key(req)); return r?.clone(); },
    async put(req, res) { records.get(name).set(key(req), res.clone()); },
    async addAll(paths) { for (const p of paths) await this.put(p, new Response("install:" + p)); }
  });
  const storage = {
    async keys() { return [...records.keys()]; },
    async open(name) { calls.push(["open", name]); if (!records.has(name)) records.set(name, new Map()); return cache(name); },
    async delete(name) { calls.push(["delete", name]); return records.delete(name); },
    async match(req, options = {}) {
      const names = options.cacheName ? [options.cacheName] : [...records.keys()];
      for (const name of names) {
        calls.push(["match", name]);
        const hit = await cache(name).match(req); if (hit) return hit;
      }
    }
  };
  const self = { caches: storage, location: { origin: "https://pf.test" },
    skipWaiting() { counts.skip++; }, clients: { async claim() { counts.claim++; } },
    addEventListener(type, handler) { listeners.set(type, handler); } };
  const context = vm.createContext({ self, caches: storage, URL, Request, Response,
    console: { warn() {} }, fetch: async () => { counts.fetch++; throw new Error("fixture offline"); } });
  vm.runInContext(code, context);
  const shell = Array.from(vm.runInContext("SHELL", context));
  const own = vm.runInContext("CACHE", context);
  function seed(name, paths, marker) {
    records.set(name, new Map(paths.map((p) => [key(p), new Response(marker + p)])));
  }
  seed("other-app-cache", shell, "foreign:");
  seed("pipfoundish-not-owned", shell, "foreign:");
  const partial = shell.filter((p) => p !== "/icon-192-mask.png");
  seed("pipfound-old", state === "rollback" ? partial : shell, "old:");
  seed(own, state === "healthy" ? shell : ["/"], "own:");
  async function dispatch(type, props = {}) {
    const pending = []; let result;
    listeners.get(type)({ ...props, waitUntil(p) { pending.push(p); }, respondWith(p) { result = p; } });
    await Promise.all(pending); return result ? await result : undefined;
  }
  return { records, calls, counts, shell, own, dispatch,
    run: (s) => vm.runInContext(s, context), key };
}

async function verifySW(code) {
  for (const state of ["healthy", "heal", "rollback"]) {
    const f = fixture(code, state);
    await f.dispatch("activate");
    assert.equal(f.counts.skip, 0, "activation-confirmation: activate must not skip waiting");
    assert.equal(f.counts.claim, 1, "activation must claim after its decision");
    for (const name of ["other-app-cache", "pipfoundish-not-owned"]) {
      assert(f.records.has(name), "cache-namespace: foreign cache deleted");
      assert.equal(await f.records.get(name).get(f.key("/")).clone().text(), "foreign:/",
        "cache-namespace: foreign content changed");
    }
    const healthy = await f.run("shellHealthy(CACHE)");
    assert.equal(healthy, state !== "rollback", "heal/rollback decision");
    assert.equal(f.records.has("pipfound-old"), state === "rollback", "old cache retention");
    if (state === "heal") {
      assert.equal(await (await f.run('fromCache("/icon-192-mask.png")')).text(),
        "old:/icon-192-mask.png", "cache-namespace: heal must use old app shell");
    }
    if (state === "rollback") {
      assert.equal(await f.run('fromCache("/icon-192-mask.png")'), undefined,
        "cache-namespace: missing icon must not come from another app");
    }
    const fallback = await f.dispatch("fetch", { request: new Request("https://pf.test/offline-page") });
    assert.equal(await fallback.text(), "own:/", "cache-namespace: offline page must be app-owned");
    const before = f.calls.length;
    for (const request of [new Request("https://pf.test/api/fundamental"),
      new Request("https://pf.test/api/risk", { method: "POST" }), new Request("https://other.test/")]) {
      assert.equal(await f.dispatch("fetch", { request }), undefined, "API/POST/cross-origin bypass");
    }
    assert.equal(f.calls.length, before, "bypass must not access caches");
    let ack;
    await f.dispatch("message", { data: { type: "PF_WHO" }, source: { postMessage(d) { ack = d; } } });
    assert.equal(ack.kept, state === "rollback" ? 1 : 0, "cache-namespace: kept counts only app caches");
    await f.dispatch("message", { data: { type: "UNKNOWN" } });
    assert.equal(f.counts.skip, 0, "activation-confirmation: unrelated message must not activate");
    await f.dispatch("message", { data: { type: "SKIP_WAITING" } });
    assert.equal(f.counts.skip, 1, "activation-confirmation: confirm must reach skipWaiting");
    assert(!f.calls.some(([, name]) => name.startsWith("other-") || name === "pipfoundish-not-owned"),
      "cache-namespace: no foreign cache content may be touched");
  }
  const install = fixture(code, "healthy");
  await install.dispatch("install");
  assert.equal(install.counts.skip, 0, "activation-confirmation: install must leave updates waiting");
}

async function red(label, code) {
  await assert.rejects(() => verifySW(code), (e) => e.message.includes(label),
    "mutation must fail with its named contract, not a syntax crash");
}

async function verifyFeedSettlement() {
  const marker = "(async () => {";
  assert(ui.includes(marker), "UI helper boundary must exist");
  const events = [], context = vm.createContext({ require, process, URL, console });
  vm.runInContext(ui.slice(0, ui.indexOf(marker)), context);
  const responseMatch = vm.runInContext("feedResponse", context);
  const settle = vm.runInContext("settleFeed", context);
  let predicate;
  responseMatch({ waitForResponse(fn) { predicate = fn; return Promise.resolve({}); } }, 24);
  assert(predicate({ url: () => "https://pf.test/api/fundamental?hours=120&past=24" }));
  assert(!predicate({ url: () => "https://pf.test/api/fundamental?event=x&past=24" }));
  assert(!predicate({ url: () => "https://pf.test/api/fundamental?past=6" }));
  let headersReady, bodyReady, renderReady, complete = false;
  const headers = new Promise((r) => { headersReady = r; });
  const body = new Promise((r) => { bodyReady = r; });
  const render = new Promise((r) => { renderReady = r; });
  const page = { async waitForFunction(fn, options, past) {
    events.push("render-start");
    context.DATA = { past_hours: past, events: [] };
    let text = "در حالِ بارگذاریِ تقویم";
    context.document = { getElementById: () => ({ textContent: text }) };
    assert.equal(fn(past), false, "settlement must reject the loading placeholder");
    text = "fixture rendered";
    assert.equal(fn(past), true);
    await render; events.push("render-end");
  } };
  const response = { ok: () => true, url: () => "https://pf.test/api/fundamental?past=24",
    async json() { events.push("body-start"); const value = await body; events.push("body-end"); return value; } };
  const result = settle(page, headers, 24).then(() => { complete = true; });
  const tick = () => new Promise((r) => setImmediate(r));
  await tick(); assert.equal(complete, false);
  headersReady(response); await tick(); assert.equal(complete, false);
  assert.deepEqual(events, ["body-start"]);
  bodyReady({ past_hours: 24, events: [] }); await tick(); assert.equal(complete, false);
  assert.deepEqual(events, ["body-start", "body-end", "render-start"]);
  renderReady(); await result;
  assert.equal(complete, true);
  await assert.rejects(() => settle(page, Promise.resolve({ ...response,
    json: async () => ({ past_hours: 6 }) }), 24), /پاسخِ معتبر/);
  await assert.rejects(() => settle(page, Promise.resolve({ ok: () => false,
    status: () => 503 }), 24), /HTTP 503/);
}

(async () => {
  await verifySW(source);
  const unscoped = source.replace(/const originCaches = self\.caches;[\s\S]*?(?=const SHELL =)/,
    "const caches = self.caches;\n");
  assert.notEqual(unscoped, source, "namespace mutation anchor");
  await red("cache-namespace", unscoped);
  const unsolicited = source.replace('if (d.type === "SKIP_WAITING")',
    'if (d.type === "SKIP_WAITING" || d.type === "UNKNOWN")');
  assert.notEqual(unsolicited, source, "confirmation mutation anchor");
  await red("activation-confirmation", unsolicited);
  const eager = source.replace(".then((c) => c.addAll(SHELL))",
    ".then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())");
  assert.notEqual(eager, source, "install mutation anchor");
  await red("activation-confirmation", eager);
  const innocent = source.replace('name.startsWith("pipfound-")', 'name.startsWith("pipfound-", 0)');
  assert.notEqual(innocent, source, "innocent mutation anchor");
  await verifySW(innocent);
  await verifyFeedSettlement();
  console.log(JSON.stringify({ sw_states: 3, red_mutations: 3, innocent_mutations: 1,
    feed_settlement: "response + body + render", browser_launched: false }));
})().catch((e) => { console.error(e.stack || e); process.exit(1); });
'''


class PackagingPwaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="pf_packaging_pwa_")
        cls.work = Path(cls.temp.name)
        (cls.work / "home").mkdir()
        (cls.work / "tmp").mkdir()
        cls.env = dict(os.environ, HOME=str(cls.work / "home"), TMPDIR=str(cls.work / "tmp"),
                       PYTHONDONTWRITEBYTECODE="1", PIPFOUND_NOTIFY="0",
                       PIPFOUND_OPEN_BROWSER="0")
        cls.bundle = make_app.build_app(cls.work / "build space ' &" / "pipfound.app",
                                        python=sys.executable, port=9461)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def command(self, args, **kwargs):
        return subprocess.run(args, cwd=ROOT, env=kwargs.pop("env", self.env),
                              text=True, capture_output=True, timeout=120, **kwargs)

    def test_build_is_stdlib_only(self):
        result = self.command([sys.executable, "-S", "-c",
                               "import sys, make_app, make_icons; assert 'PIL' not in sys.modules"])
        self.assertEqual(result.returncode, 0, result.stderr)
        output = self.work / "stdlib-cli.app"
        result = self.command([sys.executable, "-S", str(ROOT / "make_app.py"), "--output", str(output)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((output / "Contents/MacOS/pipfound").is_file())
        self.assertFalse((self.work / "home/Desktop/pipfound.app").exists())

    def test_plist_sources_and_icns(self):
        contents = self.bundle / "Contents"
        with (contents / "Info.plist").open("rb") as stream:
            plist = plistlib.load(stream)
        self.assertEqual(plist["CFBundleExecutable"], "pipfound")
        self.assertEqual(plist["CFBundlePackageType"], "APPL")
        sources = contents / "Resources/app"
        for name in ("app.py", "selfcheck.py", "sw.js", "manifest.webmanifest", "selfcheck-baseline.json"):
            self.assertTrue((sources / name).is_file(), name)
        self.assertFalse((sources / "node_modules").exists())
        data = (contents / "Resources/pipfound.icns").read_bytes()
        self.assertEqual(data[:4], b"icns")
        self.assertEqual(struct.unpack_from(">I", data, 4)[0], len(data))
        self.assertEqual(data[8:12], b"ic09")
        self.assertEqual(struct.unpack_from(">I", data, 12)[0], len(data) - 8)
        self.assertEqual(data[16:], make_icons.checked_png(ROOT / "icon-512.png", 512))

    def test_launcher_shell_and_real_preflight(self):
        launcher = self.bundle / "Contents/MacOS/pipfound"
        result = self.command(["/bin/bash", "-n", str(launcher)])
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self.command(["/bin/bash", str(launcher), "--check"])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("@@", launcher.read_text(encoding="utf-8"))
        self.assertNotIn(".hermes", launcher.read_text(encoding="utf-8").split("PORT=")[1])

    def test_relocated_bundle_and_python_discovery(self):
        relocated = self.work / "relocated ' app" / "pipfound.app"
        relocated.parent.mkdir()
        shutil.copytree(self.bundle, relocated)
        launcher = relocated / "Contents/MacOS/pipfound"
        text = launcher.read_text(encoding="utf-8")
        preferred = next(line for line in text.splitlines() if line.startswith("PREFERRED_PY="))
        launcher.write_text(text.replace(preferred, "PREFERRED_PY=/missing/pipfound-python"), encoding="utf-8")
        env = dict(self.env)
        env.pop("PIPFOUND_PYTHON", None)
        result = self.command(["/bin/bash", str(launcher), "--check"], env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_existing_output_requires_explicit_replace(self):
        sentinel = self.bundle / "keep-user-file"
        sentinel.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "--replace"):
            make_app.build_app(self.bundle)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        with self.assertRaises((ValueError, OSError)):
            make_app.build_app(self.bundle, scripts=self.work / "missing", replace=True)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
        replacement = self.work / "replacement.app"
        make_app.build_app(replacement)
        (replacement / "old-only-file").write_text("old", encoding="utf-8")
        make_app.build_app(replacement, replace=True)
        self.assertFalse((replacement / "old-only-file").exists())
        self.assertTrue((replacement / "Contents/Info.plist").is_file())

    def test_invalid_python_and_destination_fail_before_writes(self):
        bad = self.work / "unsupported-python"
        bad.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        bad.chmod(0o755)
        target = self.work / "unsupported.app"
        with self.assertRaisesRegex(ValueError, "3.11"):
            make_app.build_app(target, python=bad)
        self.assertFalse(target.exists())
        with self.assertRaisesRegex(ValueError, "outside"):
            make_app.build_app(ROOT / "not-built.app")
        with self.assertRaisesRegex(ValueError, "Port"):
            make_app.build_app(target, port=0)
        self.assertFalse(target.exists())

    def test_launcher_failure_is_quiet(self):
        launcher = self.bundle / "Contents/MacOS/pipfound"
        env = dict(self.env, PIPFOUND_PYTHON="/missing/unsupported-python")
        result = self.command(["/bin/bash", str(launcher), "--check"], env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Python 3.11+", result.stderr)
        self.assertFalse((self.work / "home/Library/Logs").exists())

    def test_copy_checked_icons_and_no_write_mode(self):
        output = self.work / "icons"
        result = self.command([sys.executable, "-S", str(ROOT / "make_icons.py"),
                               "--output", str(output), "--check"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(output.exists())
        assets = make_icons.copy_icons(output)
        self.assertEqual(len(assets), len(make_icons.ICONS))
        for name, _ in assets:
            self.assertEqual((output / name).read_bytes(), (ROOT / name).read_bytes())

    def test_corrupt_icons_reject_before_any_replacement(self):
        source, output = self.work / "bad-icons", self.work / "preserved-icons"
        make_icons.copy_icons(source)
        output.mkdir()
        (output / "icon-180.png").write_bytes(b"preserve existing asset")
        data = bytearray((source / "icon-512.png").read_bytes())
        data[29] ^= 1
        (source / "icon-512.png").write_bytes(data)
        with self.assertRaisesRegex(ValueError, "CRC"):
            make_icons.copy_icons(output, source)
        self.assertEqual((output / "icon-180.png").read_bytes(), b"preserve existing asset")
        with self.assertRaises(ValueError):
            make_icons.checked_png(ROOT / "icon-192.png", 512)

    @unittest.skipUnless(sys.platform == "darwin" and shutil.which("iconutil"), "macOS iconutil compatibility smoke")
    def test_native_macos_reads_icns(self):
        output = self.work / "native.iconset"
        result = self.command(["iconutil", "-c", "iconset", str(self.bundle / "Contents/Resources/pipfound.icns"),
                               "-o", str(output)])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(any(output.glob("*.png")))

    def test_browser_dependencies_are_dev_only_and_locked(self):
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))
        self.assertTrue(package["private"])
        self.assertFalse(package.get("dependencies"))
        self.assertEqual(package["engines"]["node"], ">=24 <25")
        self.assertEqual(package["devDependencies"], lock["packages"][""]["devDependencies"])
        for name, version in package["devDependencies"].items():
            self.assertRegex(version, r"^\d+\.\d+\.\d+$")
            self.assertEqual(lock["packages"]["node_modules/" + name]["version"], version)

    def test_pure_node_sw_and_response_settlement(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for PWA development tests (not runtime)")
        result = self.command([node, "-", str(ROOT / "sw.js"), str(ROOT / "ui_visual_check.cjs")], input=NODE_CHECK)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["red_mutations"], 3)
        self.assertEqual(report["innocent_mutations"], 1)
        self.assertFalse(report["browser_launched"])
        print("Pure Node fixtures:", result.stdout.strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
