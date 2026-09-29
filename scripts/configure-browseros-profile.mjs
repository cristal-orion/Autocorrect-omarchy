// Configure a running BrowserOS profile through its local CDP endpoint.
// Existing browser preferences are updated by the browser, never overwritten.
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

const endpoint = new URL(process.argv[2] || 'http://127.0.0.1:0');
if (endpoint.protocol !== 'http:' || endpoint.hostname !== '127.0.0.1' || !endpoint.port || endpoint.port === '0')
  throw new Error('Usage: node scripts/configure-browseros-profile.mjs http://127.0.0.1:PORT');
const base = endpoint.origin;
const extensionPath = join(homedir(), '.local/share/autocorrect/browser-ime');
const script = readFileSync(join(extensionPath, 'ime-fields.js'), 'utf8');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function connect(url) {
  const ws = new WebSocket(url);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let id = 0;
  const pending = new Map();
  ws.onmessage = event => {
    const value = JSON.parse(event.data), entry = pending.get(value.id);
    if (!entry) return;
    pending.delete(value.id); clearTimeout(entry.timer);
    value.error ? entry.reject(value.error) : entry.resolve(value.result);
  };
  return { close: () => ws.close(), send: (method, params = {}) => new Promise((resolve, reject) => {
    const next = ++id;
    const timer = setTimeout(() => { pending.delete(next); reject(new Error(`${method} timed out`)); }, 10000);
    pending.set(next, { resolve, reject, timer });
    ws.send(JSON.stringify({ id: next, method, params }));
  }) };
}

const version = await (await fetch(`${base}/json/version`, { signal: AbortSignal.timeout(5000) })).json();
const browser = await connect(version.webSocketDebuggerUrl);
let target, settings;
try {
  target = await browser.send('Target.createTarget', { url: 'chrome://settings/languages', background: true });
  const tabs = await (await fetch(`${base}/json/list`)).json();
  settings = await connect(tabs.find(tab => tab.id === target.targetId).webSocketDebuggerUrl);
  const evaluate = async expression => {
    const result = await settings.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
    return result.result.value;
  };
  for (let i = 0; i < 40; ++i) {
    if (await evaluate('!!chrome.settingsPrivate && !!chrome.languageSettingsPrivate')) break;
    await sleep(100);
  }
  const get = key => evaluate(`new Promise(r => chrome.settingsPrivate.getPref(${JSON.stringify(key)}, r))`);
  const set = async (key, value) => {
    if (!await evaluate(`new Promise(r => chrome.settingsPrivate.setPref(${JSON.stringify(key)}, ${JSON.stringify(value)}, '', r))`))
      throw new Error(`Preference rejected: ${key}`);
  };
  const keys = ['spellcheck.dictionaries', 'browser.enable_spellchecking', 'intl.selected_languages'];
  const previous = await Promise.all(keys.map(get));
  const backupRoot = join(homedir(), '.local/state/autocorrect/browser-backups');
  mkdirSync(backupRoot, { recursive: true, mode: 0o700 });
  const backup = mkdtempSync(join(backupRoot, 'languages-'));
  writeFileSync(join(backup, 'preferences.json'), JSON.stringify(previous, null, 2) + '\n', { mode: 0o600 });
  await set('spellcheck.dictionaries', [...new Set(['it', 'en-US', ...previous[0].value])]);
  await set('browser.enable_spellchecking', true);
  await set('intl.selected_languages', [...new Set(['it', ...previous[2].value.split(',')])].join(','));
  const extension = await browser.send('Extensions.loadUnpacked', { path: extensionPath });
  let dictionaries;
  for (let i = 0; i < 40; ++i) {
    dictionaries = await evaluate('new Promise(r => chrome.languageSettingsPrivate.getSpellcheckDictionaryStatuses(r))');
    if (dictionaries.some(d => d.languageCode === 'it' && d.isReady)) break;
    await sleep(500);
  }
  // Apply the same hint-only bridge to existing documents, preserving their
  // text/drafts. The installed extension covers future navigations/restarts.
  const current = await (await fetch(`${base}/json/list`)).json();
  let updated = 0;
  for (const tab of current.filter(tab => tab.type === 'page' && /^https?:\/\//.test(tab.url))) {
    const page = await connect(tab.webSocketDebuggerUrl);
    try {
      const tree = await page.send('Page.getFrameTree');
      const world = await page.send('Page.createIsolatedWorld', {
        frameId: tree.frameTree.frame.id, worldName: 'autocorrect-ime-live', grantUniveralAccess: false,
      });
      const result = await page.send('Runtime.evaluate', {
        contextId: world.executionContextId, expression: script,
      });
      if (!result.exceptionDetails) updated++;
    } finally { page.close(); }
  }
  console.log(JSON.stringify({ extension_id: extension.id, spellcheck_enabled: (await get(keys[1])).value,
    dictionaries, existing_pages_updated: updated, backup }, null, 2));
} finally {
  settings?.close();
  if (target) await browser.send('Target.closeTarget', { targetId: target.targetId });
  browser.close();
}
