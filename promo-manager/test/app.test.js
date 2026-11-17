'use strict';
// End-to-end tests against a local mock of the Discord REST API.

const test = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { openDb } = require('../src/db');
const { createDiscord, parseWebhookUrl } = require('../src/discord');
const { createScheduler } = require('../src/scheduler');
const { createApp } = require('../src/server');
const { nextWeekly, computeNextRun } = require('../src/schedule');

const GUILD = '111111111111111111';
const OTHER_GUILD = '222222222222222222';
const WEBHOOK_ID = '333333333333333333';
const WEBHOOK_TOKEN = 'abcdefghijklmnopqrstuvwxyz_0123456789';
const WEBHOOK_URL = `https://discord.com/api/webhooks/${WEBHOOK_ID}/${WEBHOOK_TOKEN}`;

const listen = (server) => new Promise((resolve) => server.listen(0, '127.0.0.1', () => resolve(server.address().port)));

async function setup() {
  const state = { posts: [], webhookGuild: GUILD, failNext: [] };
  const mock = http.createServer((req, res) => {
    let raw = '';
    req.on('data', (d) => (raw += d));
    req.on('end', () => {
      const json = (status, body) => {
        res.writeHead(status, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(body));
      };
      if (req.method === 'GET' && req.url === `/webhooks/${WEBHOOK_ID}/${WEBHOOK_TOKEN}`) {
        return json(200, { guild_id: state.webhookGuild, channel_id: '444444444444444444', name: 'partners' });
      }
      if (req.method === 'POST' && req.url.startsWith(`/webhooks/${WEBHOOK_ID}/${WEBHOOK_TOKEN}`)) {
        const fail = state.failNext.shift();
        if (fail) return json(fail.status, fail.body);
        state.posts.push({ contentType: req.headers['content-type'], raw });
        return json(200, { id: '555555555555555555' });
      }
      json(404, { message: 'Unknown' });
    });
  });
  const mockPort = await listen(mock);

  const clock = { t: Date.UTC(2026, 0, 5, 12, 0) };
  const now = () => clock.t;
  const uploadsDir = fs.mkdtempSync(path.join(os.tmpdir(), 'promo-test-'));
  const db = openDb(':memory:');
  const discord = createDiscord({ apiBase: `http://127.0.0.1:${mockPort}`, getSettings: db.getSettings, uploadsDir, backoffMs: 1 });
  const scheduler = createScheduler({ db, discord, now });
  const app = createApp({ db, discord, scheduler, adminToken: 'admin-secret', editorToken: 'editor-secret', uploadsDir, now });
  const server = http.createServer(app);
  const port = await listen(server);

  const api = async (method, url, body, token = 'admin-secret') => {
    const res = await fetch(`http://127.0.0.1:${port}/api${url}`, {
      method,
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    });
    return { status: res.status, body: await res.json() };
  };
  const close = () => {
    server.close();
    mock.close();
    fs.rmSync(uploadsDir, { recursive: true, force: true });
  };

  // One community with one webhook channel and one piece of content.
  const community = (await api('POST', '/communities', { name: 'Partner A', guild_id: GUILD, min_interval_minutes: 60 })).body.id;
  const channel = (await api('POST', `/communities/${community}/channels`, { name: 'promo', kind: 'webhook', webhook_url: WEBHOOK_URL })).body.id;
  const content = (await api('POST', '/contents', { title: 'Launch', body: 'Hello @everyone' })).body.id;

  return { api, state, clock, scheduler, db, close, community, channel, content };
}

test('weekly schedule respects timezone and DST', () => {
  // Monday 2026-03-02 09:00 in New York (EST, UTC-5) is 14:00 UTC.
  const after = Date.UTC(2026, 2, 1, 0, 0);
  assert.equal(nextWeekly(after, 'America/New_York', [1], '09:00'), Date.UTC(2026, 2, 2, 14, 0));
  // After the DST switch on 2026-03-08 the same wall time is 13:00 UTC.
  assert.equal(nextWeekly(Date.UTC(2026, 2, 8, 12, 0), 'America/New_York', [1], '09:00'), Date.UTC(2026, 2, 9, 13, 0));
  // Same-day time already passed rolls over to the next week.
  assert.equal(nextWeekly(Date.UTC(2026, 2, 2, 15, 0), 'America/New_York', [1], '09:00'), Date.UTC(2026, 2, 9, 13, 0));
  assert.equal(computeNextRun({ kind: 'once', run_at: 5 }, 10, 'UTC'), null);
  assert.equal(computeNextRun({ kind: 'interval', interval_minutes: 30 }, 0, 'UTC'), 30 * 60000);
});

test('webhook URL parsing only accepts Discord hosts', () => {
  assert.deepEqual(parseWebhookUrl(WEBHOOK_URL), { webhook_id: WEBHOOK_ID, webhook_token: WEBHOOK_TOKEN });
  assert.equal(parseWebhookUrl(`https://evil.example/api/webhooks/${WEBHOOK_ID}/${WEBHOOK_TOKEN}`), null);
  assert.equal(parseWebhookUrl(`https://discord.com.evil.example/api/webhooks/${WEBHOOK_ID}/${WEBHOOK_TOKEN}`), null);
});

test('nothing is posted to a channel that is not verified and authorized', async () => {
  const t = await setup();
  try {
    const run_at = t.clock.t + 60000;
    const s = await t.api('POST', '/schedules', { channel_id: t.channel, content_id: t.content, kind: 'once', run_at });
    assert.equal(s.status, 201);

    // Authorizing before verification is rejected.
    assert.equal((await t.api('POST', `/channels/${t.channel}/authorize`, { confirm: true })).status, 400);

    t.clock.t = run_at + 1000;
    await t.scheduler.tick();
    assert.equal(t.state.posts.length, 0);
    const history = (await t.api('GET', '/deliveries')).body;
    assert.equal(history.rows[0].status, 'skipped');
    assert.match(history.rows[0].error, /not been verified/);
  } finally {
    t.close();
  }
});

test('verification fails when the webhook belongs to another server', async () => {
  const t = await setup();
  try {
    t.state.webhookGuild = OTHER_GUILD;
    const v = await t.api('POST', `/channels/${t.channel}/verify`);
    assert.equal(v.body.verified, false);
    assert.match(v.body.note, /different server/);
    assert.equal((await t.api('POST', `/channels/${t.channel}/authorize`, { confirm: true })).status, 400);
  } finally {
    t.close();
  }
});

test('authorized channel receives the post, with retries, mentions disabled and minimum interval enforced', async () => {
  const t = await setup();
  try {
    assert.equal((await t.api('POST', `/channels/${t.channel}/verify`)).body.verified, true);
    // Explicit confirmation is required.
    assert.equal((await t.api('POST', `/channels/${t.channel}/authorize`, {})).status, 400);
    assert.equal((await t.api('POST', `/channels/${t.channel}/authorize`, { confirm: true, note: 'ok per staff' })).status, 200);

    // Interval shorter than the community minimum (60 min) is rejected.
    assert.equal((await t.api('POST', '/schedules', { channel_id: t.channel, content_id: t.content, kind: 'interval', interval_minutes: 30 })).status, 400);
    const s = await t.api('POST', '/schedules', { channel_id: t.channel, content_id: t.content, kind: 'interval', interval_minutes: 60 });
    assert.equal(s.body.next_run_at, t.clock.t + 3600000);

    // First attempt is rate limited, second succeeds.
    t.state.failNext.push({ status: 429, body: { message: 'rate limited', retry_after: 0.01 } });
    t.clock.t += 3600000;
    await t.scheduler.tick();
    assert.equal(t.state.posts.length, 1);
    const payload = JSON.parse(t.state.posts[0].raw);
    assert.deepEqual(payload.allowed_mentions, { parse: [] });

    let history = (await t.api('GET', '/deliveries')).body;
    assert.equal(history.rows[0].status, 'sent');
    assert.equal(history.rows[0].attempts, 2);
    assert.equal(history.rows[0].message_id, '555555555555555555');

    // A manual run right away violates the community's minimum interval.
    const manual = await t.api('POST', `/schedules/${s.body.id}/run-now`);
    assert.equal(manual.body.status, 'skipped');
    assert.match(manual.body.error, /minimum interval/);
    assert.equal(t.state.posts.length, 1);

    // Client errors are logged as failures and not retried.
    t.state.failNext.push({ status: 403, body: { message: 'Missing Permissions' } });
    t.clock.t += 3600000;
    await t.scheduler.tick();
    history = (await t.api('GET', '/deliveries')).body;
    assert.equal(history.rows[0].status, 'failed');
    assert.equal(history.rows[0].http_status, 403);
    assert.equal(history.rows[0].attempts, 1);
    assert.deepEqual(history.totals, { failed: 1, sent: 1, skipped: 1 });

    // Secrets never appear in API responses.
    const listed = JSON.stringify((await t.api('GET', '/communities')).body);
    assert.ok(!listed.includes(WEBHOOK_TOKEN));
  } finally {
    t.close();
  }
});

test('uploaded images are sent as multipart attachments', async () => {
  const t = await setup();
  try {
    await t.api('POST', `/channels/${t.channel}/verify`);
    await t.api('POST', `/channels/${t.channel}/authorize`, { confirm: true });
    const png = Buffer.from('89504e470d0a1a0a', 'hex').toString('base64');
    const up = await t.api('POST', '/uploads', { filename: 'banner.png', data: png });
    assert.equal(up.status, 201);
    assert.equal((await t.api('POST', '/uploads', { filename: 'x.exe', data: png })).status, 400);
    const content = (await t.api('POST', '/contents', { title: 'Banner', image_file: up.body.image_file })).body.id;
    const s = await t.api('POST', '/schedules', { channel_id: t.channel, content_id: content, kind: 'once', run_at: t.clock.t + 1000 });
    t.clock.t += 2000;
    await t.scheduler.tick();
    assert.equal(t.state.posts.length, 1);
    assert.match(t.state.posts[0].contentType, /^multipart\/form-data/);
    assert.match(t.state.posts[0].raw, /payload_json/);
    // A one-off schedule disables itself after running.
    const listed = (await t.api('GET', '/schedules')).body.find((x) => x.id === s.body.id);
    assert.equal(listed.enabled, false);
  } finally {
    t.close();
  }
});

test('access tokens and roles are enforced', async () => {
  const t = await setup();
  try {
    assert.equal((await t.api('GET', '/communities', null, 'wrong')).status, 401);
    assert.equal((await t.api('GET', '/communities', null, 'editor-secret')).status, 200);
    assert.equal((await t.api('POST', '/contents', { title: 'By editor', body: 'hi' }, 'editor-secret')).status, 201);
    // Editors cannot add destinations, authorize channels or change network settings.
    assert.equal((await t.api('POST', `/channels/${t.channel}/authorize`, { confirm: true }, 'editor-secret')).status, 403);
    assert.equal((await t.api('POST', '/communities', { name: 'X', guild_id: OTHER_GUILD }, 'editor-secret')).status, 403);
    assert.equal((await t.api('PUT', '/settings', { proxy_url: '' }, 'editor-secret')).status, 403);
    // Settings validation.
    assert.equal((await t.api('PUT', '/settings', { proxy_url: 'socks5://x:1' })).status, 400);
    assert.equal((await t.api('PUT', '/settings', { proxy_url: 'http://proxy.internal:3128', timeout_ms: 5000, max_attempts: 2 })).body.max_attempts, 2);
  } finally {
    t.close();
  }
});
