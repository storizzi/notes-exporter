// notes-exporter web UI: plain JS, no build step. The session token is kept in
// sessionStorage (this tab only) and sent as a Bearer header, never in a URL.
'use strict';

const FORMATS = [
  ['html', 'HTML (with images)'], ['md', 'Markdown'], ['pdf', 'PDF'], ['docx', 'Word'],
  ['epub', 'EPUB'], ['text', 'Plain text (always)'], ['raw', 'Raw HTML (always)'],
];
const ALWAYS = new Set(['raw', 'text']);
const $ = (sel) => document.querySelector(sel);
let token = null;
let me = null;
let watching = null;   // {runId, after, timer}

function getToken() { try { return sessionStorage.getItem('ne_token'); } catch { return null; } }
function setToken(t) { token = t; try { t ? sessionStorage.setItem('ne_token', t) : sessionStorage.removeItem('ne_token'); } catch { /* private mode */ } }

async function api(method, path, body, raw) {
  const headers = {};
  if (token) headers.Authorization = 'Bearer ' + token;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const res = await fetch('/api' + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (res.status === 401 && token) { setToken(null); start(); throw new Error('signed out'); }
  if (raw) return res;
  const text = await res.text();
  const data = text ? (() => { try { return JSON.parse(text); } catch { return text; } })() : null;
  if (!res.ok) {
    const d = data && data.detail;
    throw new Error(Array.isArray(d) ? d.map((x) => x.msg).join('; ') : (d || res.statusText));
  }
  return data;
}

function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') e.className = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const k of kids) e.append(k instanceof Node ? k : document.createTextNode(k ?? ''));
  return e;
}
const when = (iso) => (iso ? new Date(iso).toLocaleString() : '—');
const show = (id, on) => { $(id).hidden = !on; };

async function start() {
  token = getToken();
  show('#app', false); show('#login', false); show('#setup', false); show('#logout', false);
  $('#who').textContent = '';
  if (token) {
    try { me = await api('GET', '/auth/me'); return enterApp(); } catch { setToken(null); }
  }
  const setup = await api('GET', '/setup');
  if (setup.needed && setup.allowed_here) show('#setup', true);
  else {
    show('#login', true);
    if (setup.needed) $('#login-error').textContent = 'No account yet: open this page on the Mac running the service to set it up.';
  }
}

async function enterApp() {
  show('#app', true); show('#logout', true);
  $('#who').textContent = `${me.username} (${me.role})`;
  document.querySelectorAll('.admin-only').forEach((b) => { b.hidden = !me.scopes.includes('admin'); });
  selectTab('status');
}

function selectTab(name) {
  document.querySelectorAll('.tab').forEach((b) => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.panel').forEach((p) => { p.hidden = p.id !== 'tab-' + name; });
  ({ status: loadStatus, settings: loadSettings, users: loadUsers, keys: loadKeys })[name]();
}

// ---- status + runs ----
async function loadStatus() {
  const s = await api('GET', '/status');
  const dl = $('#status-list'); dl.replaceChildren();
  const add = (k, v) => dl.append(el('dt', {}, k), el('dd', {}, v));
  const last = s.last_run;
  add('Running', s.running_run_id ? 'yes' : 'no');
  add('Last run', last ? `${last.status} — ${when(last.finished_at)}${last.message ? ' — ' + last.message : ''}` : 'never');
  add('Next run', s.next_run_at ? when(s.next_run_at) : (s.schedule.enabled ? '—' : 'not scheduled'));
  add('Export folder', `${s.export_root} ${s.export_root_ok ? '' : '(not there yet / not writable)'}`);
  add('Formats', s.formats.join(', '));
  const auto = s.permission.automation || '';
  const askable = auto === 'prompt' || auto === 'not-running' || auto.startsWith('unknown');
  add('Notes automation', auto + (askable ? ' — ask for access below, while at the Mac' : '')
    + (auto === 'denied' ? ' — turn it on in System Settings → Privacy & Security → Automation' : ''));
  $('#permission-row').hidden = !(askable && me.scopes.includes('admin'));
  add('Full Disk Access', s.permission.full_disk_access === null ? 'unknown' : (s.permission.full_disk_access ? 'yes' : 'no (only needed for tags)'));
  $('#run-now').hidden = !!s.running_run_id || !me.scopes.includes('run');
  $('#run-cancel').hidden = !s.running_run_id || !me.scopes.includes('run');
  $('#run-cancel').dataset.run = s.running_run_id || '';
  const { runs } = await api('GET', '/runs?limit=15');
  const tb = $('#runs tbody'); tb.replaceChildren();
  for (const r of runs) {
    tb.append(el('tr', { class: 'clickable', onclick: () => watch(r.id) },
      el('td', {}, when(r.started_at || r.created_at)), el('td', { class: 'status-' + r.status }, r.status),
      el('td', {}, r.trigger), el('td', {}, String(r.counts.notes ?? '')), el('td', {}, String(r.counts.changed ?? '')),
      el('td', {}, r.message || '')));
  }
  if (s.running_run_id) watch(s.running_run_id);
  else if (!watching && runs[0]) watch(runs[0].id);
}

async function askPermission() {
  const btn = $('#ask-permission');
  btn.disabled = true;
  $('#permission-note').textContent = 'macOS will show a dialog on this Mac — click Allow';
  try {
    const r = await api('POST', '/admin/permission/request');
    $('#permission-note').textContent = r.automation === 'allowed' ? 'Allowed.' : `Still ${r.automation}.`;
    await loadStatus();
  } catch (e) {
    $('#permission-note').textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

function describe(ev) {
  const t = ev.time ? ev.time.slice(11, 19) + ' ' : '';
  switch (ev.type) {
    case 'progress': return `${t}${ev.stage}: ${ev.done}/${ev.total} ${ev.unit || ''}${ev.folder ? ' — ' + ev.folder : ''}`;
    case 'stage': return `${t}${ev.stage} ${ev.status}`;
    case 'result': return `${t}result: ${ev.status} (exit ${ev.exit_code})${ev.message ? ' — ' + ev.message : ''}`;
    case 'manifest': return `${t}manifest: ${ev.notes} notes, ${ev.changed} changed, ${ev.deleted_this_run} deleted this run`;
    case 'message': return `${t}${ev.level}: ${ev.message}`;
    case 'note_error': return `${t}note error (${ev.stage}): ${ev.message || ev.filename || ''}`;
    default: return `${t}${ev.type}`;
  }
}

function watch(runId) {
  if (watching && watching.runId === runId) return;
  if (watching) clearTimeout(watching.timer);
  watching = { runId, after: 0, timer: null };
  $('#events').textContent = ''; $('#progress').textContent = '';
  $('#log-run').textContent = runId.slice(0, 8);
  poll();
}

async function poll() {
  const w = watching; if (!w) return;
  try {
    const res = await api('GET', `/runs/${w.runId}/events?after=${w.after}`, undefined, true);
    if (!res.ok) return;
    const text = await res.text();
    w.after = Number(res.headers.get('X-Next-After') || w.after);
    const status = res.headers.get('X-Run-Status');
    const pre = $('#events');
    for (const line of text.split('\n').filter(Boolean)) {
      try {
        const ev = JSON.parse(line);
        if (ev.type === 'progress') $('#progress').textContent = describe(ev);
        if (ev.type !== 'progress' || ev.done === ev.total) pre.append(describe(ev) + '\n');
      } catch { /* partial line */ }
    }
    pre.scrollTop = pre.scrollHeight;
    if (status === 'running' || status === 'queued') w.timer = setTimeout(poll, 1000);
    else if (w === watching) { $('#progress').textContent = 'Finished: ' + status; refreshStatusSoon(); }
  } catch { /* signed out */ }
}
let refreshTimer = null;
function refreshStatusSoon() { clearTimeout(refreshTimer); refreshTimer = setTimeout(() => { if (!$('#tab-status').hidden) loadStatus(); }, 300); }

async function runNow() {
  $('#run-error').textContent = '';
  try {
    const { run } = await api('POST', '/runs', { mode: $('#run-mode').value, trigger: 'ui' });
    watching = null; watch(run.id); loadStatus();
  } catch (e) { $('#run-error').textContent = e.message; }
}

async function cancelRun() {
  const id = $('#run-cancel').dataset.run; if (!id) return;
  try { await api('POST', `/runs/${id}/cancel`); } catch (e) { $('#run-error').textContent = e.message; }
  setTimeout(loadStatus, 500);
}

// ---- settings ----
async function loadSettings() {
  const s = await api('GET', '/admin/settings');
  const f = $('#settings-form');
  f.export_root.value = s.export_root;
  const fs = $('#formats'); fs.querySelectorAll('label').forEach((l) => l.remove());
  for (const [id, label] of FORMATS) {
    const box = el('input', { type: 'checkbox', name: 'format', value: id });
    box.checked = ALWAYS.has(id) || s.formats.includes(id);
    if (ALWAYS.has(id)) box.disabled = true;
    fs.append(el('label', { class: 'check' }, box, ' ' + label));
  }
  for (const k of ['folder_hierarchy', 'prune_deleted', 'html_wrap', 'tags', 'tags_in_content']) f[k].checked = !!s[k];
  f.exclude_folders.value = (s.exclude_folders || []).join('\n');
  f.image_format.value = s.image_format || '';
  if (f.epub_books) {
    f.epub_books.value = s.epub_books || 'none';
    f.epub_book_order.value = s.epub_book_order || 'modified';
    f.epub_book_subfolders.value = s.epub_book_subfolders || 'separate';
  }
  f.schedule_enabled.checked = !!s.schedule.enabled;
  f.schedule_kind.value = s.schedule.interval_minutes ? 'interval' : 'daily';
  f.daily_at.value = s.schedule.daily_at || '';
  f.interval_minutes.value = s.schedule.interval_minutes || '';
}

async function saveSettings(ev) {
  ev.preventDefault();
  const f = ev.target; $('#settings-error').textContent = ''; $('#settings-ok').textContent = '';
  const formats = [...f.querySelectorAll('input[name=format]:checked')].map((b) => b.value).filter((x) => !ALWAYS.has(x));
  const interval = f.schedule_kind.value === 'interval';
  const body = {
    export_root: f.export_root.value.trim(),
    formats: formats.length ? formats : ['html'],
    folder_hierarchy: f.folder_hierarchy.checked, prune_deleted: f.prune_deleted.checked,
    html_wrap: f.html_wrap.checked, tags: f.tags.checked, tags_in_content: f.tags_in_content.checked,
    exclude_folders: f.exclude_folders.value.split('\n').map((x) => x.trim()).filter(Boolean),
    image_format: f.image_format.value || null,
    schedule: {
      enabled: f.schedule_enabled.checked,
      daily_at: interval ? null : (f.daily_at.value.trim() || null),
      interval_minutes: interval ? (Number(f.interval_minutes.value) || null) : null,
    },
  };
  if (f.epub_books) Object.assign(body, {
    epub_books: f.epub_books.value, epub_book_order: f.epub_book_order.value, epub_book_subfolders: f.epub_book_subfolders.value,
  });
  try { await api('PUT', '/admin/settings', body); $('#settings-ok').textContent = 'Saved.'; loadSettings(); } catch (e) { $('#settings-error').textContent = e.message; }
}

// ---- users ----
async function loadUsers() {
  const { users } = await api('GET', '/admin/users');
  const tb = $('#users tbody'); tb.replaceChildren();
  for (const u of users) {
    const role = el('select', { onchange: async (e) => {
      try { await api('PATCH', `/admin/users/${u.id}`, { role: e.target.value }); } catch (err) { alert(err.message); }
      loadUsers();
    } }, el('option', { value: 'reader' }, 'reader'), el('option', { value: 'admin' }, 'admin'));
    role.value = u.role;
    tb.append(el('tr', {}, el('td', {}, u.username), el('td', {}, role), el('td', {}, when(u.created_at)),
      el('td', {},
        el('button', { class: 'link', onclick: async () => {
          const pw = prompt(`New password for ${u.username}`); if (!pw) return;
          try { await api('PATCH', `/admin/users/${u.id}`, { password: pw }); alert('Password changed.'); } catch (err) { alert(err.message); }
        } }, 'Reset password'), ' ',
        el('button', { class: 'danger', onclick: async () => {
          if (!confirm(`Remove ${u.username} and their API keys?`)) return;
          try { await api('DELETE', `/admin/users/${u.id}`); } catch (err) { alert(err.message); }
          loadUsers();
        } }, 'Remove'))));
  }
}

async function addUser(ev) {
  ev.preventDefault(); const f = ev.target; $('#user-error').textContent = '';
  try { await api('POST', '/admin/users', { username: f.username.value, password: f.password.value, role: f.role.value }); f.reset(); loadUsers(); } catch (e) { $('#user-error').textContent = e.message; }
}

// ---- API keys ----
async function loadKeys() {
  const [{ api_keys: keys }, { users }] = await Promise.all([api('GET', '/admin/api-keys'), api('GET', '/admin/users')]);
  const names = Object.fromEntries(users.map((u) => [u.id, u.username]));
  const tb = $('#keys tbody'); tb.replaceChildren();
  for (const k of keys) {
    tb.append(el('tr', {}, el('td', {}, k.name), el('td', {}, el('code', {}, k.prefix + '…')), el('td', {}, k.scopes.join(', ')),
      el('td', {}, names[k.owner_user_id] || '?'), el('td', {}, when(k.last_used_at)), el('td', {}, k.expires_at ? when(k.expires_at) : 'never'),
      el('td', {}, el('button', { class: 'danger', onclick: async () => {
        if (!confirm(`Revoke ${k.name}? Clients using it stop working.`)) return;
        await api('DELETE', `/admin/api-keys/${k.id}`); loadKeys();
      } }, 'Revoke'))));
  }
}

async function addKey(ev) {
  ev.preventDefault(); const f = ev.target; $('#key-error').textContent = '';
  const scopes = [...f.querySelectorAll('input[name=scope]:checked')].map((b) => b.value);
  const body = { name: f.name.value, scopes };
  if (f.expires_at.value) body.expires_at = new Date(f.expires_at.value + 'T23:59:59').toISOString();
  try {
    const r = await api('POST', '/admin/api-keys', body);
    $('#new-key-value').textContent = r.key; show('#new-key', true); f.reset(); loadKeys();
  } catch (e) { $('#key-error').textContent = e.message; }
}

async function copyKey() {
  const text = $('#new-key-value').textContent;
  try { await navigator.clipboard.writeText(text); $('#copy-key').textContent = 'Copied'; } catch {
    const r = document.createRange(); r.selectNodeContents($('#new-key-value'));
    const s = getSelection(); s.removeAllRanges(); s.addRange(r); $('#copy-key').textContent = 'Press ⌘C';
  }
}

// ---- wiring ----
document.addEventListener('DOMContentLoaded', () => {
  $('#login-form').addEventListener('submit', async (ev) => {
    ev.preventDefault(); const f = ev.target; $('#login-error').textContent = '';
    try { const r = await api('POST', '/auth/login', { username: f.username.value, password: f.password.value }); setToken(r.token); f.reset(); start(); } catch (e) { $('#login-error').textContent = e.message; }
  });
  $('#setup-form').addEventListener('submit', async (ev) => {
    ev.preventDefault(); const f = ev.target; $('#setup-error').textContent = '';
    try { const r = await api('POST', '/setup', { username: f.username.value, password: f.password.value }); setToken(r.token); start(); } catch (e) { $('#setup-error').textContent = e.message; }
  });
  $('#logout').addEventListener('click', async () => { try { await api('POST', '/auth/logout'); } catch { /* */ } setToken(null); watching = null; start(); });
  document.querySelectorAll('.tab').forEach((b) => b.addEventListener('click', () => selectTab(b.dataset.tab)));
  $('#run-now').addEventListener('click', runNow);
  $('#run-cancel').addEventListener('click', cancelRun);
  $('#ask-permission').addEventListener('click', askPermission);
  $('#settings-form').addEventListener('submit', saveSettings);
  $('#user-form').addEventListener('submit', addUser);
  $('#key-form').addEventListener('submit', addKey);
  $('#copy-key').addEventListener('click', copyKey);
  start();
});
