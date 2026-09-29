// Real BrowserOS + Wayland input, with a disposable browser profile.
// CDP reads the test fields; a Wayland virtual keyboard exercises Fcitx's grab.
import { spawn, execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, openSync, closeSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createServer } from 'node:http';

const root = resolve(fileURLToPath(new URL('..', import.meta.url)));
const excluded = process.argv.includes('--excluded');
const reopen = process.argv.includes('--reopen');
const startupOnly = process.argv.includes('--startup-only');
const appId = excluded ? 'AutocorrectExcluded' : 'BrowserOS';
const run = (bin, args) => execFileSync(bin, args, { encoding: 'utf8', timeout: 10000 }).trim();
const control = (...args) => JSON.parse(run(join(root, '.venv/bin/python'), ['-m', 'autocorrect_core.control', ...args]));
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
async function waitFor(callback, timeout = 10000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    try { const result = await callback(); if (result) return result; } catch {}
    await sleep(100);
  }
  throw new Error('Timeout waiting for BrowserOS');
}
async function connect(url) {
  const ws = new WebSocket(url);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let next = 0;
  const pending = new Map();
  ws.onmessage = event => {
    const value = JSON.parse(event.data);
    const callback = pending.get(value.id);
    if (callback) { pending.delete(value.id); value.error ? callback.reject(value.error) : callback.resolve(value.result); }
  };
  return { close: () => ws.close(), send: (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++next;
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 10000);
    pending.set(id, { resolve: value => { clearTimeout(timer); resolve(value); }, reject: error => { clearTimeout(timer); reject(error); } });
    ws.send(JSON.stringify({ id, method, params }));
  }) };
}

const original = control('status');
if (!original.connected) throw new Error('Start autocorrect.service first');
const originalMethod = run('fcitx5-remote', ['-n']);
const previousWindow = JSON.parse(run('hyprctl', ['-j', 'activewindow'])).address;
const profile = mkdtempSync(join(tmpdir(), 'autocorrect-browseros-'));
const logPath = join(profile, 'wayland.log');
const log = openSync(logPath, 'w');
let browser, cdp, typist, typingGuard;
const results = [];
const server = createServer((request, response) => {
  response.writeHead(200, {'Content-Type': 'text/html; charset=utf-8'});
  response.end(readFileSync(join(root, 'probes/browseros.html')));
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
try {
  // Automated undo/edits must not change the user's feedback memory.
  const configured = control('set', 'learn_enabled', 'false');
  if (!configured.ok) throw new Error(JSON.stringify(configured));
  const args = [
    `--class=${appId}`,
    `--user-data-dir=${profile}`, '--remote-debugging-port=0', '--no-first-run',
    `--wayland-text-input-version=${process.env.AUTOCORRECT_TEXT_INPUT_VERSION || '3'}`,
    '--no-default-browser-check', ...(!reopen ? [`--load-extension=${join(root, 'shell/browseros')}`] : []), '--disable-background-networking',
    'about:blank',
  ];
  const launch = () => spawn(join(process.env.HOME, '.local/bin/browseros'), args,
    { detached: true, stdio: ['ignore', log, log], env: { ...process.env, WAYLAND_DEBUG: 'client' } });
  browser = launch();
  let port = await waitFor(() => readFileSync(join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0], 25000);
  let base = `http://127.0.0.1:${port}`;
  let version = await (await fetch(`${base}/json/version`)).json();
  if (reopen) {
    const first = await connect(version.webSocketDebuggerUrl);
    // Reopen without a test-only extension flag: the normal installed wrapper
    // must load the bridge, just as it does for the everyday browser profile.
    await first.send('Browser.close');
    await waitFor(() => browser.exitCode !== null, 10000);
    first.close();
    rmSync(join(profile, 'DevToolsActivePort'), {force: true});
    browser = launch();
    port = await waitFor(() => readFileSync(join(profile, 'DevToolsActivePort'), 'utf8').split('\n')[0], 25000);
    base = `http://127.0.0.1:${port}`;
    version = await (await fetch(`${base}/json/version`)).json();
  }
  // BrowserOS's first-run tabs can open asynchronously in a fresh profile.
  await sleep(4000);
  const browserCdp = await connect(version.webSocketDebuggerUrl);
  const target = await browserCdp.send('Target.createTarget', { url: `http://127.0.0.1:${server.address().port}/browseros.html` });
  browserCdp.close();
  const page = await waitFor(async () => (await (await fetch(`${base}/json/list`)).json()).find(p => p.id === target.targetId));
  cdp = await connect(page.webSocketDebuggerUrl);
  const evaluate = async expression => {
    const result = await cdp.send('Runtime.evaluate', { expression, returnByValue: true });
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  await waitFor(() => evaluate('document.getElementById("normal") !== null'));
  const title = `Autocorrect BrowserOS verification ${process.pid}`;
  await evaluate(`document.title = ${JSON.stringify(title)}`);
  await cdp.send('Page.bringToFront');
  const window = await waitFor(() => JSON.parse(run('hyprctl', ['-j', 'clients'])).find(w => w.title.includes(title)));
  if (window.xwayland || window.class !== appId) throw new Error(`Unexpected transport: ${JSON.stringify(window)}`);
  const address = `address:${window.address}`;
  run('hyprctl', ['dispatch', `hl.dsp.focus({window=${JSON.stringify(address)}})`]);
  await evaluate('document.getElementById("normal").focus()');
  const expectedMethod = excluded ? 'keyboard-us' : 'autocorrect-probe-surrounding';
  await waitFor(() => run('fcitx5-remote', ['-n']) === expectedMethod);
  results.push({test: excluded ? 'excluded_app_not_autoactivated' : (reopen ? 'reopened_browser_autoactivated' : 'new_browser_autoactivated'), passed: true, method: expectedMethod});
  function assertFocus() {
    const contexts = JSON.parse(run('busctl', ['--user', '--json=short', 'call', 'org.fcitx.Fcitx5',
      '/controller', 'org.fcitx.Fcitx.Controller1', 'DebugInfo'])).data[0];
    const waylandFocus = (contexts.split('Group [wayland:]')[1] || '').split('Group [')[0]
      .split('\n').filter(line => line.includes('focus:1'));
    if (JSON.parse(run('hyprctl', ['-j', 'activewindow'])).address !== window.address ||
        (waylandFocus.length && !waylandFocus.some(line => line.includes(`program:${appId} frontend:wayland_v2`))))
      throw new Error('BrowserOS test field lost focus; stopping keyboard input');
  }
  function startTyping(args) {
    assertFocus();
    typist = spawn('wtype', args);
    let focusError;
    typingGuard = setInterval(() => {
      try { assertFocus(); } catch (error) { focusError = error; typist?.kill(); }
    }, 50);
    const done = new Promise((resolve, reject) => {
      typist.once('error', reject);
      typist.once('exit', code => {
        clearInterval(typingGuard); typingGuard = null; typist = null;
        if (focusError) reject(focusError);
        else if (code) reject(new Error(`wtype exited ${code}`));
        else resolve();
      });
    });
    // The sequence tests inspect intermediate states before awaiting completion.
    done.catch(() => {});
    return done;
  }
  async function key(key, mods = '') {
    await startTyping([...(mods ? ['-M', mods.toLowerCase()] : []), '-k', key,
                   ...(mods ? ['-m', mods.toLowerCase()] : []), '-s', '200']);
    await sleep(100);
  }
  async function text(value) {
    await startTyping(['-d', '100', value, '-s', '300']);
    await sleep(100);
  }
  const getText = id => evaluate(`(() => { const f=document.getElementById(${JSON.stringify(id)}); return f.value ?? f.textContent; })()`);
  async function field(id) {
    await evaluate(`(() => { const f=document.getElementById(${JSON.stringify(id)}); f.focus(); if ('value' in f) f.value=''; else f.textContent=''; })()`);
    await sleep(300);
  }
  async function check(name, id, expected) {
    try { await waitFor(async () => (await getText(id)) === expected, 2000); }
    catch {
      const actual = await getText(id);
      results.push({ test: name, passed: false, expected, actual });
      throw new Error(`${name}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
    }
    results.push({ test: name, passed: true, text: expected });
  }
  await field('normal');
  if (startupOnly) {
    await evaluate('document.getElementById("normal").removeAttribute("spellcheck")');
    await waitFor(() => evaluate('document.getElementById("normal").getAttribute("spellcheck") === "true"'));
    results.push({test: 'installed_field_bridge_loaded_after_restart', passed: true});
  } else if (excluded) {
    await text('quesot '); await check('unapproved_application_preserved', 'normal', 'quesot ');
  } else {
    // Keep one virtual keyboard/keymap alive across correction, undo and space.
    const firstSequence = startTyping(['-d', '100', 'quesot ', '-s', '1000', '-k', 'BackSpace', '-s', '1000', ' ', '-s', '1000']);
    await check('correction_on_space', 'normal', 'questo ');
    await check('undo', 'normal', 'quesot');
    await check('undo_not_reapplied', 'normal', 'quesot ');
    await firstSequence;
    for (const [input, expected] of [['una piza ', 'una pizza '], ['sono stao ', 'sono stato ']]) {
      await field('normal'); await text(input); await check(`context_${input.trim()}`, 'normal', expected);
    }
    await field('normal');
    await cdp.send('Input.insertText', { text: 'è ' });
    await sleep(200);
    await text('quesot '); await check('unicode_prefix_offsets', 'normal', 'è questo ');
    // Chromium represents a trailing editable-space as NBSP in the DOM, but
    // exposes an ordinary space to the input method's surrounding-text API.
    await field('rich'); await text('quesot '); await check('contenteditable', 'rich', 'questo\u00a0');
    await key('BackSpace'); await check('contenteditable_undo', 'rich', 'quesot');
    await field('password'); await text('quesot '); await check('password_preserved', 'password', 'quesot ');
    await field('code'); await text('quesot '); await check('spellcheck_false_preserved', 'code', 'quesot ');
    await evaluate('document.getElementById("normal").removeAttribute("spellcheck")');
    await field('normal'); await text('quesot ');
    await check('inherited_spellcheck_bridge', 'normal', 'questo ');
    control('set', 'suggestions_enabled', 'true');
    for (const [shortcut, expected] of [['1', 'domani '], ['2', 'donna '], ['3', 'romani ']]) {
      await field('normal'); await text('domnai ');
      await check(`candidate_${shortcut}_abstention`, 'normal', 'domnai ');
      await key(shortcut, 'alt');
      await check(`candidate_alt_${shortcut}`, 'normal', expected);
      await key('BackSpace');
      await check(`candidate_alt_${shortcut}_undo`, 'normal', 'domnai');
    }
    // Record keys at the page boundary without opening Chromium's help page.
    await evaluate(`document.addEventListener('keydown', e => {
      if (e.key === 'F1' || (e.altKey && e.key === '1')) {
        document.testLastKey = e.key; e.preventDefault();
      }
    })`);
    await field('normal'); await text('domnai '); await key('F1');
    if (await evaluate('document.testLastKey') !== 'F1') throw new Error('F1 was intercepted');
    await check('f1_reaches_browser_without_selecting', 'normal', 'domnai ');
    await field('normal'); await key('1', 'alt');
    if (await evaluate('document.testLastKey') !== '1') throw new Error('Alt+1 swallowed without candidates');
    await check('alt_1_without_candidates_reaches_browser', 'normal', '');
  }
  console.log(JSON.stringify({ browser: version.Browser, xwayland: window.xwayland, tests: results, all_passed: true }, null, 2));
} catch (error) {
  console.error(JSON.stringify({ error: String(error), stack: error.stack, tests: results }, null, 2));
  const lines = readFileSync(logPath, 'utf8').split('\n').filter(line => /text_input_v[13].*(enable|surrounding|content_type|commit_string|done)/.test(line));
  console.error(lines.slice(-60).join('\n'));
  console.error(readFileSync(logPath, 'utf8').split('\n').filter(line => /Gtk|GTK|fcitx|Failed to load|ERROR/.test(line)).slice(-20).join('\n'));
  console.error(run('busctl', ['--user', 'call', 'org.fcitx.Fcitx5', '/controller', 'org.fcitx.Fcitx.Controller1', 'DebugInfo']));
  console.error(run('journalctl', ['--user', '-u', 'omarchy-fcitx5.service', '-n', '35', '--no-pager']));
  process.exitCode = 1;
} finally {
  server.close();
  clearInterval(typingGuard);
  typist?.kill();
  cdp?.close();
  if (browser) {
    try { process.kill(-browser.pid, 'SIGTERM'); } catch {}
    await sleep(1000);
    try { process.kill(-browser.pid, 'SIGKILL'); } catch {}
  }
  closeSync(log);
  control('set', 'learn_enabled', JSON.stringify(original.settings.learn_enabled));
  control('set', 'suggestions_enabled', JSON.stringify(original.settings.suggestions_enabled));
  run('fcitx5-remote', ['-s', originalMethod]);
  if (previousWindow) run('hyprctl', ['dispatch', `hl.dsp.focus({window="address:${previousWindow}"})`]);
  rmSync(profile, { recursive: true, force: true });
}
