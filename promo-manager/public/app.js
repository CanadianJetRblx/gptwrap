'use strict';
// Admin panel. All user-supplied text is inserted via textContent, never innerHTML.

const $ = (sel) => document.querySelector(sel);
const view = $('#view');
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
let token = sessionStorage.getItem('promo_token') || '';
let me = null;
let currentTab = 'communities';

// Tiny DOM builder: h('div', { class: 'x', onclick: fn }, child, ...)
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'class') el.className = v;
    else if (k === 'value') el.value = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    el.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return el;
}

function notify(message, isError = false) {
  const box = $('#notice');
  box.textContent = message;
  box.className = isError ? 'bad' : '';
  box.hidden = false;
  clearTimeout(notify.timer);
  notify.timer = setTimeout(() => (box.hidden = true), 6000);
}

async function api(method, url, body) {
  const res = await fetch('/api' + url, {
    method,
    headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    signOut();
    throw new Error('Please sign in again.');
  }
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

// Wraps an action: runs it, reports errors, then refreshes the current tab.
const act = (fn, done) => async (event) => {
  event?.preventDefault?.();
  try {
    await fn(event);
    if (done) notify(done);
    await render();
  } catch (err) {
    notify(err.message, true);
  }
};

const isAdmin = () => me?.role === 'admin';
const fmt = (ts) => (ts ? new Date(ts).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—');
const badge = (text, cls) => h('span', { class: 'badge ' + cls }, text);
const field = (label, input, cls) => h('label', { class: cls }, label, input);
const formData = (form) => Object.fromEntries(new FormData(form).entries());

// ---------- Communities ----------
async function renderCommunities() {
  const communities = await api('GET', '/communities');
  const out = [];

  if (isAdmin()) {
    out.push(
      h('details', { class: 'card' },
        h('summary', {}, 'Add a partner community'),
        h('form', { onsubmit: act(async (e) => {
            const d = formData(e.target);
            await api('POST', '/communities', { ...d, min_interval_minutes: Number(d.min_interval_minutes) });
          }, 'Community added.') },
          h('div', { class: 'grid' },
            field('Name', h('input', { name: 'name', required: true, maxlength: 100 })),
            field('Discord server ID', h('input', { name: 'guild_id', required: true, pattern: '\\d{17,20}', inputmode: 'numeric' })),
            field('Timezone (IANA)', h('input', { name: 'timezone', value: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC', required: true })),
            field('Minimum minutes between posts', h('input', { name: 'min_interval_minutes', type: 'number', min: 5, value: 1440, required: true })),
            field('Server rules / partnership notes', h('textarea', { name: 'rules', maxlength: 4000 }), 'wide')
          ),
          h('button', {}, 'Add community')
        )
      )
    );
  }
  if (!communities.length) out.push(h('p', { class: 'muted' }, 'No partner communities yet.'));

  for (const c of communities) {
    const card = h('div', { class: 'card' },
      h('div', { class: 'row between' },
        h('div', { class: 'row' }, h('h2', { style: 'margin:0' }, c.name), c.enabled ? badge('active', 'ok') : badge('paused', 'warn')),
        isAdmin() && h('div', { class: 'row' },
          h('button', { class: 'ghost small', onclick: act(() => api('PUT', `/communities/${c.id}`, { enabled: !c.enabled })) }, c.enabled ? 'Pause' : 'Resume'),
          h('button', { class: 'danger small', onclick: act(async () => {
            if (confirm(`Delete "${c.name}" with its channels and schedules?`)) await api('DELETE', `/communities/${c.id}`);
          }) }, 'Delete')
        )
      ),
      h('p', { class: 'muted' }, `Server ${c.guild_id} · ${c.timezone} · at most one post every ${c.min_interval_minutes} min per channel`),
      c.rules && h('p', { class: 'pre' }, c.rules)
    );

    for (const ch of c.channels) {
      const status = ch.authorized ? badge('authorized', 'ok') : ch.verified_at ? badge('verified, not authorized', 'warn') : badge('not verified', 'bad');
      card.append(
        h('div', { class: 'item row between' },
          h('div', {},
            h('div', { class: 'row' }, h('h3', {}, ch.name), status),
            h('div', { class: 'muted' }, [ch.destination, ch.verify_note, ch.authorized && ch.authorized_note && `approval: ${ch.authorized_note}`].filter(Boolean).join(' · '))
          ),
          isAdmin() && h('div', { class: 'row' },
            h('button', { class: 'ghost small', onclick: act(async () => {
              const r = await api('POST', `/channels/${ch.id}/verify`);
              notify(r.note, !r.verified);
            }) }, 'Verify'),
            ch.authorized
              ? h('button', { class: 'ghost small', onclick: act(() => api('POST', `/channels/${ch.id}/authorize`, { authorized: false })) }, 'Revoke')
              : h('button', { class: 'small', disabled: !ch.verified_at, onclick: act(async () => {
                  if (!confirm(`Confirm that the staff of "${c.name}" approved promotional posts in "${ch.name}".`)) return;
                  const note = prompt('Optional note (who approved it, when):') || '';
                  await api('POST', `/channels/${ch.id}/authorize`, { confirm: true, note });
                }) }, 'Authorize'),
            h('button', { class: 'danger small', onclick: act(async () => {
              if (confirm(`Remove channel "${ch.name}"?`)) await api('DELETE', `/channels/${ch.id}`);
            }) }, 'Remove')
          )
        )
      );
    }

    if (isAdmin()) {
      const kind = h('select', { name: 'kind' }, h('option', { value: 'webhook' }, 'Webhook'), h('option', { value: 'bot', disabled: !me.bot_configured }, me.bot_configured ? 'Bot channel' : 'Bot channel (no bot token configured)'));
      const target = h('input', { name: 'target', required: true, placeholder: 'https://discord.com/api/webhooks/…' });
      kind.addEventListener('change', () => (target.placeholder = kind.value === 'webhook' ? 'https://discord.com/api/webhooks/…' : 'Channel ID'));
      card.append(
        h('details', { class: 'item' },
          h('summary', {}, 'Add a channel'),
          h('form', { onsubmit: act(async (e) => {
              const d = formData(e.target);
              const dest = d.kind === 'webhook' ? { webhook_url: d.target } : { discord_channel_id: d.target };
              await api('POST', `/communities/${c.id}/channels`, { name: d.name, kind: d.kind, ...dest });
            }, 'Channel added. Verify and authorize it before scheduling posts.') },
            h('div', { class: 'grid' },
              field('Label', h('input', { name: 'name', required: true, maxlength: 100 })),
              field('Type', kind),
              field('Webhook URL or channel ID', target, 'wide')
            ),
            h('button', {}, 'Add channel')
          )
        )
      );
    }
    out.push(card);
  }
  return out;
}

// ---------- Content ----------
async function renderContent() {
  const contents = await api('GET', '/contents');
  const fileToBase64 = (file) => new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(',')[1]);
    reader.onerror = () => reject(new Error('Could not read the image file.'));
    reader.readAsDataURL(file);
  });

  const form = h('form', { class: 'card', onsubmit: act(async (e) => {
      const d = formData(e.target);
      const body = { title: d.title, body: d.body, image_url: d.image_url };
      const file = e.target.elements.image.files[0];
      if (file) {
        body.image_url = '';
        body.image_file = (await api('POST', '/uploads', { filename: file.name, data: await fileToBase64(file) })).image_file;
      }
      await api('POST', '/contents', body);
    }, 'Content saved.') },
    h('h2', {}, 'New promotion'),
    h('div', { class: 'grid' },
      field('Internal title', h('input', { name: 'title', required: true, maxlength: 100 })),
      field('Image URL (https, optional)', h('input', { name: 'image_url', type: 'url' })),
      field('Message (up to 2000 characters; mentions never ping)', h('textarea', { name: 'body', maxlength: 2000 }), 'wide'),
      field('Or upload an image (png, jpg, gif, webp; max 8 MB)', h('input', { name: 'image', type: 'file', accept: '.png,.jpg,.jpeg,.gif,.webp' }), 'wide')
    ),
    h('button', {}, 'Save content')
  );

  const list = h('div', { class: 'card' }, h('h2', {}, 'Library'));
  if (!contents.length) list.append(h('p', { class: 'muted' }, 'Nothing saved yet.'));
  for (const c of contents) {
    list.append(
      h('div', { class: 'item' },
        h('div', { class: 'row between' },
          h('h3', {}, c.title),
          h('button', { class: 'danger small', onclick: act(async () => {
            if (confirm(`Delete "${c.title}" and the schedules that use it?`)) await api('DELETE', `/contents/${c.id}`);
          }) }, 'Delete')
        ),
        c.body && h('p', { class: 'pre' }, c.body),
        (c.image_url || c.image_file) && h('p', { class: 'muted' }, c.image_url ? `Image: ${c.image_url}` : 'Image: uploaded file'),
        h('p', { class: 'muted' }, `Updated ${fmt(c.updated_at)}`)
      )
    );
  }
  return [form, list];
}

// ---------- Schedules ----------
async function renderSchedules() {
  const [communities, contents, schedules] = await Promise.all([api('GET', '/communities'), api('GET', '/contents'), api('GET', '/schedules')]);
  const channelOptions = communities.flatMap((c) =>
    c.channels.map((ch) => h('option', { value: ch.id }, `${c.name} → ${ch.name}${ch.authorized ? '' : ' (not authorized)'}`))
  );

  const kind = h('select', { name: 'kind' }, h('option', { value: 'once' }, 'One time'), h('option', { value: 'interval' }, 'Repeat every N minutes'), h('option', { value: 'weekly' }, 'Weekly on chosen days'));
  const whenOnce = field('Date and time (your local time)', h('input', { name: 'run_at', type: 'datetime-local' }));
  const whenInterval = field('Every N minutes (not below the community minimum)', h('input', { name: 'interval_minutes', type: 'number', min: 5, value: 1440 }));
  const whenWeekly = h('div', { class: 'wide' },
    h('div', { class: 'row' }, DAYS.map((d, i) => h('label', {}, h('input', { type: 'checkbox', name: 'weekday', value: i }), d))),
    field("Time of day (in the community's timezone)", h('input', { name: 'time_of_day', type: 'time', value: '18:00' }))
  );
  const sync = () => {
    whenOnce.hidden = kind.value !== 'once';
    whenInterval.hidden = kind.value !== 'interval';
    whenWeekly.hidden = kind.value !== 'weekly';
  };
  kind.addEventListener('change', sync);
  sync();

  const form = h('form', { class: 'card', onsubmit: act(async (e) => {
      const d = formData(e.target);
      const body = { channel_id: Number(d.channel_id), content_id: Number(d.content_id), kind: d.kind };
      if (d.kind === 'once') {
        if (!d.run_at) throw new Error('Pick a date and time.');
        body.run_at = new Date(d.run_at).getTime();
      } else if (d.kind === 'interval') {
        body.interval_minutes = Number(d.interval_minutes);
      } else {
        body.weekdays = new FormData(e.target).getAll('weekday').map(Number);
        body.time_of_day = d.time_of_day;
      }
      await api('POST', '/schedules', body);
    }, 'Schedule created.') },
    h('h2', {}, 'New schedule'),
    channelOptions.length && contents.length
      ? [
          h('div', { class: 'grid' },
            field('Destination', h('select', { name: 'channel_id' }, channelOptions)),
            field('Content', h('select', { name: 'content_id' }, contents.map((c) => h('option', { value: c.id }, c.title)))),
            field('Timing', kind),
            whenOnce, whenInterval, whenWeekly
          ),
          h('button', {}, 'Create schedule'),
        ]
      : h('p', { class: 'muted' }, 'Add at least one channel and one piece of content first.')
  );

  const describe = (s) =>
    s.kind === 'once' ? 'One time'
    : s.kind === 'interval' ? `Every ${s.interval_minutes} min`
    : `${s.weekdays.split(',').map((d) => DAYS[d]).join(', ')} at ${s.time_of_day} (${s.timezone})`;

  const out = [form];
  const groups = new Map();
  for (const s of schedules) groups.set(s.community_name, [...(groups.get(s.community_name) || []), s]);
  if (!schedules.length) out.push(h('p', { class: 'muted' }, 'No schedules yet.'));

  for (const [name, rows] of groups) {
    out.push(
      h('div', { class: 'card' }, h('h2', {}, name),
        h('div', { class: 'scroll' },
          h('table', {},
            h('thead', {}, h('tr', {}, ['Channel', 'Content', 'Timing', 'Next run', 'Last run', ''].map((t) => h('th', {}, t)))),
            h('tbody', {}, rows.map((s) =>
              h('tr', {},
                h('td', {}, s.channel_name, ' ', !s.channel_authorized && badge('not authorized', 'bad')),
                h('td', {}, s.content_title),
                h('td', {}, describe(s)),
                h('td', {}, s.enabled ? fmt(s.next_run_at) : badge(s.kind === 'once' && s.last_run_at ? 'done' : 'paused', 'warn')),
                h('td', {}, fmt(s.last_run_at)),
                h('td', {}, h('div', { class: 'row' },
                  h('button', { class: 'ghost small', onclick: act(async () => {
                    if (!confirm(`Post "${s.content_title}" to ${name} → ${s.channel_name} now?`)) return;
                    const r = await api('POST', `/schedules/${s.id}/run-now`);
                    notify(r.status === 'sent' ? 'Posted.' : `${r.status}: ${r.error}`, r.status !== 'sent');
                  }) }, 'Post now'),
                  !(s.kind === 'once' && s.last_run_at) && h('button', { class: 'ghost small', onclick: act(() => api('POST', `/schedules/${s.id}/toggle`, { enabled: !s.enabled })) }, s.enabled ? 'Pause' : 'Resume'),
                  h('button', { class: 'danger small', onclick: act(async () => {
                    if (confirm('Delete this schedule?')) await api('DELETE', `/schedules/${s.id}`);
                  }) }, 'Delete')
                ))
              )
            ))
          )
        )
      )
    );
  }
  return out;
}

// ---------- History ----------
let historyFilter = '';
async function renderHistory() {
  const data = await api('GET', `/deliveries?limit=200${historyFilter ? `&status=${historyFilter}` : ''}`);
  const filter = h('select', { 'aria-label': 'Filter by status', style: 'width:auto;margin:0', onchange: (e) => { historyFilter = e.target.value; render(); } },
    [['', 'All'], ['sent', 'Sent'], ['failed', 'Failed'], ['skipped', 'Skipped']].map(([v, t]) => h('option', { value: v, selected: v === historyFilter }, t))
  );
  const cls = { sent: 'ok', failed: 'bad', skipped: 'warn' };
  return [
    h('div', { class: 'card' },
      h('div', { class: 'row between' },
        h('div', { class: 'row' }, ['sent', 'failed', 'skipped'].map((s) => badge(`${s}: ${data.totals[s] || 0}`, cls[s]))),
        h('div', { class: 'row' }, filter, h('button', { class: 'ghost small', onclick: () => render() }, 'Refresh'))
      ),
      data.rows.length
        ? h('div', { class: 'scroll', style: 'margin-top:12px' },
            h('table', {},
              h('thead', {}, h('tr', {}, ['Time', 'Community', 'Channel', 'Content', 'Trigger', 'Status', 'Details'].map((t) => h('th', {}, t)))),
              h('tbody', {}, data.rows.map((r) =>
                h('tr', {},
                  h('td', {}, fmt(r.created_at)),
                  h('td', {}, r.community_name || '—'),
                  h('td', {}, r.channel_name || '—'),
                  h('td', {}, r.content_title || '—'),
                  h('td', {}, r.trigger),
                  h('td', {}, badge(r.status, cls[r.status])),
                  h('td', { class: 'muted' }, [r.error, r.http_status && `HTTP ${r.http_status}`, r.attempts > 1 && `${r.attempts} attempts`, r.message_id && `message ${r.message_id}`].filter(Boolean).join(' · '))
                )
              ))
            )
          )
        : h('p', { class: 'muted' }, 'No deliveries recorded.')
    ),
  ];
}

// ---------- Network settings ----------
async function renderSettings() {
  const s = await api('GET', '/settings');
  return [
    h('form', { class: 'card', onsubmit: act(async (e) => {
        const d = formData(e.target);
        await api('PUT', '/settings', { proxy_url: d.proxy_url, timeout_ms: Number(d.timeout_ms), max_attempts: Number(d.max_attempts) });
      }, 'Network settings saved.') },
      h('h2', {}, 'Network'),
      h('p', { class: 'muted' }, 'Optional. Use an outbound proxy if this server cannot reach Discord directly. Retries apply to rate limits and temporary failures only, and always wait as long as Discord asks.'),
      h('div', { class: 'grid' },
        field('Outbound HTTP(S) proxy URL', h('input', { name: 'proxy_url', value: s.proxy_url, placeholder: 'http://proxy.example:3128' }), 'wide'),
        field('Request timeout (ms)', h('input', { name: 'timeout_ms', type: 'number', min: 1000, max: 120000, value: s.timeout_ms })),
        field('Maximum attempts per post', h('input', { name: 'max_attempts', type: 'number', min: 1, max: 5, value: s.max_attempts }))
      ),
      h('div', { class: 'row' },
        h('button', {}, 'Save'),
        h('button', { type: 'button', class: 'ghost', onclick: act(async () => {
          const r = await api('POST', '/settings/test');
          notify(r.ok ? `Discord reachable in ${r.latency_ms} ms.` : `Discord not reachable: ${r.error}`, !r.ok);
        }) }, 'Test connection (saved settings)')
      )
    ),
  ];
}

// ---------- Shell ----------
const TABS = { communities: renderCommunities, content: renderContent, schedules: renderSchedules, history: renderHistory, settings: renderSettings };

async function render() {
  for (const b of document.querySelectorAll('#tabs button')) b.classList.toggle('active', b.dataset.tab === currentTab);
  try {
    view.replaceChildren(...(await TABS[currentTab]()));
  } catch (err) {
    notify(err.message, true);
  }
}

function signOut() {
  token = '';
  me = null;
  sessionStorage.removeItem('promo_token');
  $('#login').hidden = false;
  for (const id of ['#view', '#tabs', '#session']) $(id).hidden = true;
}

async function start() {
  if (!token) return signOut();
  try {
    me = await api('GET', '/me');
  } catch {
    return;
  }
  $('#login').hidden = true;
  for (const id of ['#view', '#tabs', '#session']) $(id).hidden = false;
  $('#role').textContent = `Signed in as ${me.role}`;
  for (const b of document.querySelectorAll('[data-admin]')) b.hidden = !isAdmin();
  await render();
}

$('#tabs').addEventListener('click', (e) => {
  if (e.target.dataset.tab) {
    currentTab = e.target.dataset.tab;
    render();
  }
});
$('#logout').addEventListener('click', signOut);
$('#login').addEventListener('submit', (e) => {
  e.preventDefault();
  token = e.target.elements.token.value.trim();
  sessionStorage.setItem('promo_token', token);
  e.target.reset();
  start().then(() => { if (!me) notify('That token was not accepted.', true); });
});

start();
