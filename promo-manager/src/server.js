'use strict';
// HTTP API + static admin panel.

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const express = require('express');

const { openDb } = require('./db');
const { createDiscord, parseWebhookUrl, MIME } = require('./discord');
const { createScheduler } = require('./scheduler');
const { isValidTimezone, computeNextRun, parseWeekdays } = require('./schedule');

const SNOWFLAKE = /^\d{17,20}$/;
const MAX_IMAGE_BYTES = 8 * 1024 * 1024;
const MIN_INTERVAL_FLOOR = 5; // minutes; hard floor regardless of community settings

class HttpError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}
const bad = (msg) => new HttpError(400, msg);

function tokenEquals(a, b) {
  const ha = crypto.createHash('sha256').update(String(a)).digest();
  const hb = crypto.createHash('sha256').update(String(b)).digest();
  return crypto.timingSafeEqual(ha, hb);
}

function str(value, field, { max = 200, required = true } = {}) {
  const s = typeof value === 'string' ? value.trim() : '';
  if (!s && required) throw bad(`${field} is required`);
  if (s.length > max) throw bad(`${field} must be at most ${max} characters`);
  return s;
}

function int(value, field, { min, max }) {
  const n = Number(value);
  if (!Number.isInteger(n) || n < min || n > max) throw bad(`${field} must be an integer between ${min} and ${max}`);
  return n;
}

function createApp({ db, discord, scheduler, adminToken, editorToken = '', uploadsDir, now = () => Date.now() }) {
  const app = express();
  app.disable('x-powered-by');
  app.use(express.json({ limit: '12mb' }));
  app.use(express.static(path.join(__dirname, '..', 'public')));

  // ---- Panel access control: admin (everything) or editor (content + schedules) ----
  app.use('/api', (req, res, next) => {
    const header = req.get('authorization') || '';
    const token = header.startsWith('Bearer ') ? header.slice(7) : '';
    if (token && tokenEquals(token, adminToken)) req.role = 'admin';
    else if (token && editorToken && tokenEquals(token, editorToken)) req.role = 'editor';
    else return res.status(401).json({ error: 'invalid or missing access token' });
    next();
  });
  const adminOnly = (req, res, next) =>
    req.role === 'admin' ? next() : res.status(403).json({ error: 'admin access required' });

  const find = (table, id) => {
    const row = db.prepare(`SELECT * FROM ${table} WHERE id = ?`).get(Number(id));
    if (!row) throw new HttpError(404, `${table.slice(0, -1)} not found`);
    return row;
  };

  // Webhook tokens are secrets and never leave the server.
  const presentChannel = (c) => ({
    id: c.id,
    community_id: c.community_id,
    name: c.name,
    kind: c.kind,
    destination: c.kind === 'webhook' ? `webhook …${c.webhook_id.slice(-4)}` : `channel ${c.discord_channel_id}`,
    verified_at: c.verified_at,
    verify_note: c.verify_note,
    authorized: Boolean(c.authorized),
    authorized_note: c.authorized_note,
    authorized_at: c.authorized_at,
  });

  app.get('/api/me', (req, res) => res.json({ role: req.role, bot_configured: discord.hasBotToken() }));

  // ---- Communities ----
  function communityInput(body) {
    const timezone = str(body.timezone ?? 'UTC', 'timezone', { max: 64 });
    if (!isValidTimezone(timezone)) throw bad('timezone must be a valid IANA zone, e.g. Europe/Berlin');
    const guild_id = str(body.guild_id, 'guild_id', { max: 20 });
    if (!SNOWFLAKE.test(guild_id)) throw bad('guild_id must be a Discord server ID (17-20 digits)');
    return {
      name: str(body.name, 'name', { max: 100 }),
      guild_id,
      timezone,
      rules: str(body.rules ?? '', 'rules', { max: 4000, required: false }),
      min_interval_minutes: int(body.min_interval_minutes ?? 1440, 'min_interval_minutes', { min: MIN_INTERVAL_FLOOR, max: 525600 }),
      enabled: body.enabled === false ? 0 : 1,
    };
  }

  app.get('/api/communities', (req, res) => {
    const communities = db.prepare('SELECT * FROM communities ORDER BY name').all();
    const channels = db.prepare('SELECT * FROM channels ORDER BY name').all();
    res.json(
      communities.map((c) => ({
        ...c,
        enabled: Boolean(c.enabled),
        channels: channels.filter((ch) => ch.community_id === c.id).map(presentChannel),
      }))
    );
  });

  app.post('/api/communities', adminOnly, (req, res) => {
    const c = communityInput(req.body || {});
    if (db.prepare('SELECT 1 FROM communities WHERE guild_id = ?').get(c.guild_id)) throw bad('a community with this guild_id already exists');
    const info = db
      .prepare('INSERT INTO communities (name, guild_id, timezone, rules, min_interval_minutes, enabled, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)')
      .run(c.name, c.guild_id, c.timezone, c.rules, c.min_interval_minutes, c.enabled, now());
    res.status(201).json({ id: Number(info.lastInsertRowid) });
  });

  app.put('/api/communities/:id', adminOnly, (req, res) => {
    const existing = find('communities', req.params.id);
    const c = communityInput({ ...existing, enabled: Boolean(existing.enabled), ...req.body });
    if (c.guild_id !== existing.guild_id) {
      // A different server invalidates every earlier verification/authorization.
      db.prepare('UPDATE channels SET verified_at = NULL, authorized = 0, authorized_at = NULL WHERE community_id = ?').run(existing.id);
    }
    db.prepare('UPDATE communities SET name = ?, guild_id = ?, timezone = ?, rules = ?, min_interval_minutes = ?, enabled = ? WHERE id = ?')
      .run(c.name, c.guild_id, c.timezone, c.rules, c.min_interval_minutes, c.enabled, existing.id);
    res.json({ ok: true });
  });

  app.delete('/api/communities/:id', adminOnly, (req, res) => {
    db.prepare('DELETE FROM communities WHERE id = ?').run(find('communities', req.params.id).id);
    res.json({ ok: true });
  });

  // ---- Channels (posting destinations) ----
  app.post('/api/communities/:id/channels', adminOnly, (req, res) => {
    const community = find('communities', req.params.id);
    const body = req.body || {};
    const name = str(body.name, 'name', { max: 100 });
    let row;
    if (body.kind === 'webhook') {
      const parsed = parseWebhookUrl(body.webhook_url);
      if (!parsed) throw bad('webhook_url must be a Discord webhook URL');
      row = { kind: 'webhook', discord_channel_id: null, ...parsed };
    } else if (body.kind === 'bot') {
      const id = str(body.discord_channel_id, 'discord_channel_id', { max: 20 });
      if (!SNOWFLAKE.test(id)) throw bad('discord_channel_id must be a Discord channel ID (17-20 digits)');
      row = { kind: 'bot', discord_channel_id: id, webhook_id: null, webhook_token: null };
    } else {
      throw bad("kind must be 'webhook' or 'bot'");
    }
    const info = db
      .prepare('INSERT INTO channels (community_id, name, kind, discord_channel_id, webhook_id, webhook_token, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)')
      .run(community.id, name, row.kind, row.discord_channel_id, row.webhook_id, row.webhook_token, now());
    res.status(201).json({ id: Number(info.lastInsertRowid) });
  });

  app.delete('/api/channels/:id', adminOnly, (req, res) => {
    db.prepare('DELETE FROM channels WHERE id = ?').run(find('channels', req.params.id).id);
    res.json({ ok: true });
  });

  // Confirms with Discord that the destination lives in the community's server.
  app.post('/api/channels/:id/verify', adminOnly, async (req, res) => {
    const channel = find('channels', req.params.id);
    const community = find('communities', channel.community_id);
    const result = await discord.lookupDestination(channel);
    let verified = false;
    let note;
    if (!result.ok) note = `lookup failed: ${result.error}`;
    else if (result.guild_id !== community.guild_id) note = 'destination belongs to a different server than this community';
    else {
      verified = true;
      note = `verified as #${result.label || result.discord_channel_id}`;
    }
    if (verified) {
      db.prepare('UPDATE channels SET verified_at = ?, verify_note = ?, discord_channel_id = COALESCE(discord_channel_id, ?) WHERE id = ?')
        .run(now(), note, result.discord_channel_id ?? null, channel.id);
    } else {
      db.prepare('UPDATE channels SET verified_at = NULL, verify_note = ?, authorized = 0, authorized_at = NULL WHERE id = ?').run(note, channel.id);
    }
    res.json({ verified, note });
  });

  // Explicit admin sign-off that the partner server permits posting here.
  app.post('/api/channels/:id/authorize', adminOnly, (req, res) => {
    const channel = find('channels', req.params.id);
    const body = req.body || {};
    if (body.authorized === false) {
      db.prepare('UPDATE channels SET authorized = 0, authorized_at = NULL WHERE id = ?').run(channel.id);
      return res.json({ authorized: false });
    }
    if (!channel.verified_at) throw bad('verify the channel before authorizing it');
    if (body.confirm !== true) throw bad('confirm that the partner server approved posting in this channel');
    const note = str(body.note ?? '', 'note', { max: 500, required: false });
    db.prepare('UPDATE channels SET authorized = 1, authorized_note = ?, authorized_at = ? WHERE id = ?').run(note, now(), channel.id);
    res.json({ authorized: true });
  });

  // ---- Content ----
  function contentInput(body) {
    const c = {
      title: str(body.title, 'title', { max: 100 }),
      body: str(body.body ?? '', 'body', { max: 2000, required: false }),
      image_url: str(body.image_url ?? '', 'image_url', { max: 500, required: false }) || null,
      image_file: str(body.image_file ?? '', 'image_file', { max: 100, required: false }) || null,
    };
    if (c.image_url && !/^https:\/\/\S+$/.test(c.image_url)) throw bad('image_url must be an https URL');
    if (c.image_file && !fs.existsSync(path.join(uploadsDir, path.basename(c.image_file)))) throw bad('image_file does not exist');
    if (c.image_file) c.image_file = path.basename(c.image_file);
    if (c.image_url && c.image_file) throw bad('use either image_url or an uploaded image, not both');
    if (!c.body && !c.image_url && !c.image_file) throw bad('content needs a message body or an image');
    return c;
  }

  app.get('/api/contents', (req, res) => res.json(db.prepare('SELECT * FROM contents ORDER BY updated_at DESC').all()));

  app.post('/api/contents', (req, res) => {
    const c = contentInput(req.body || {});
    const info = db
      .prepare('INSERT INTO contents (title, body, image_url, image_file, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)')
      .run(c.title, c.body, c.image_url, c.image_file, now(), now());
    res.status(201).json({ id: Number(info.lastInsertRowid) });
  });

  app.put('/api/contents/:id', (req, res) => {
    const existing = find('contents', req.params.id);
    const c = contentInput({ ...existing, ...req.body });
    db.prepare('UPDATE contents SET title = ?, body = ?, image_url = ?, image_file = ?, updated_at = ? WHERE id = ?')
      .run(c.title, c.body, c.image_url, c.image_file, now(), existing.id);
    res.json({ ok: true });
  });

  app.delete('/api/contents/:id', (req, res) => {
    db.prepare('DELETE FROM contents WHERE id = ?').run(find('contents', req.params.id).id);
    res.json({ ok: true });
  });

  app.post('/api/uploads', (req, res) => {
    const ext = path.extname(String(req.body?.filename || '')).toLowerCase();
    if (!MIME[ext]) throw bad('image must be a .png, .jpg, .gif or .webp file');
    const buf = Buffer.from(String(req.body?.data || ''), 'base64');
    if (!buf.length) throw bad('image data is empty');
    if (buf.length > MAX_IMAGE_BYTES) throw bad('image must be at most 8 MB');
    const name = crypto.randomBytes(12).toString('hex') + ext;
    fs.writeFileSync(path.join(uploadsDir, name), buf);
    res.status(201).json({ image_file: name });
  });

  // ---- Schedules ----
  function scheduleInput(body) {
    const channel = find('channels', body.channel_id);
    const community = find('communities', channel.community_id);
    find('contents', body.content_id);
    const s = { channel_id: channel.id, content_id: Number(body.content_id), kind: body.kind, run_at: null, interval_minutes: null, weekdays: null, time_of_day: null };

    if (s.kind === 'once' || (s.kind === 'interval' && body.run_at)) {
      s.run_at = Number(body.run_at);
      if (!Number.isFinite(s.run_at) || s.run_at <= now()) throw bad('run_at must be a time in the future');
    }
    if (s.kind === 'interval') {
      const floor = Math.max(MIN_INTERVAL_FLOOR, community.min_interval_minutes);
      s.interval_minutes = int(body.interval_minutes, 'interval_minutes', { min: floor, max: 525600 });
    } else if (s.kind === 'weekly') {
      const days = [...new Set(parseWeekdays(Array.isArray(body.weekdays) ? body.weekdays.join(',') : body.weekdays))];
      if (!days.length || days.some((d) => !Number.isInteger(d) || d < 0 || d > 6)) throw bad('weekdays must list days 0 (Sunday) to 6 (Saturday)');
      if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(body.time_of_day || '')) throw bad('time_of_day must be HH:MM');
      s.weekdays = days.sort().join(',');
      s.time_of_day = body.time_of_day;
    } else if (s.kind !== 'once') {
      throw bad("kind must be 'once', 'interval' or 'weekly'");
    }
    s.next_run_at = computeNextRun(s, now(), community.timezone, { initial: true });
    return s;
  }

  app.get('/api/schedules', (req, res) => {
    const rows = db
      .prepare(
        `SELECT s.*, ch.name AS channel_name, ch.authorized AS channel_authorized, co.id AS community_id,
                co.name AS community_name, co.timezone, ct.title AS content_title
         FROM schedules s
         JOIN channels ch ON ch.id = s.channel_id
         JOIN communities co ON co.id = ch.community_id
         JOIN contents ct ON ct.id = s.content_id
         ORDER BY co.name, s.next_run_at IS NULL, s.next_run_at`
      )
      .all();
    res.json(rows.map((r) => ({ ...r, enabled: Boolean(r.enabled), channel_authorized: Boolean(r.channel_authorized) })));
  });

  app.post('/api/schedules', (req, res) => {
    const s = scheduleInput(req.body || {});
    const info = db
      .prepare('INSERT INTO schedules (channel_id, content_id, kind, run_at, interval_minutes, weekdays, time_of_day, next_run_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)')
      .run(s.channel_id, s.content_id, s.kind, s.run_at, s.interval_minutes, s.weekdays, s.time_of_day, s.next_run_at, now());
    res.status(201).json({ id: Number(info.lastInsertRowid), next_run_at: s.next_run_at });
  });

  app.post('/api/schedules/:id/toggle', (req, res) => {
    const s = find('schedules', req.params.id);
    const enable = req.body?.enabled !== false;
    let next = s.next_run_at;
    if (enable) {
      const channel = find('channels', s.channel_id);
      const community = find('communities', channel.community_id);
      if (s.kind === 'once') {
        if (!s.run_at || s.run_at <= now()) throw bad('this one-off schedule is in the past; create a new one');
        next = s.run_at;
      } else if (!next || next <= now()) {
        next = computeNextRun(s, now(), community.timezone);
      }
    }
    db.prepare('UPDATE schedules SET enabled = ?, next_run_at = ? WHERE id = ?').run(enable ? 1 : 0, next, s.id);
    res.json({ enabled: enable, next_run_at: next });
  });

  app.post('/api/schedules/:id/run-now', async (req, res) => {
    const s = find('schedules', req.params.id);
    res.json(await scheduler.runNow(s.id));
  });

  app.delete('/api/schedules/:id', (req, res) => {
    db.prepare('DELETE FROM schedules WHERE id = ?').run(find('schedules', req.params.id).id);
    res.json({ ok: true });
  });

  // ---- History ----
  app.get('/api/deliveries', (req, res) => {
    const limit = Math.min(Math.max(Number(req.query.limit) || 100, 1), 500);
    const status = ['sent', 'failed', 'skipped'].includes(req.query.status) ? req.query.status : null;
    const rows = status
      ? db.prepare('SELECT * FROM deliveries WHERE status = ? ORDER BY id DESC LIMIT ?').all(status, limit)
      : db.prepare('SELECT * FROM deliveries ORDER BY id DESC LIMIT ?').all(limit);
    const totals = db.prepare('SELECT status, COUNT(*) AS n FROM deliveries GROUP BY status').all();
    res.json({ rows, totals: Object.fromEntries(totals.map((t) => [t.status, t.n])) });
  });

  // ---- Network settings ----
  app.get('/api/settings', adminOnly, (req, res) => res.json(db.getSettings()));

  app.put('/api/settings', adminOnly, (req, res) => {
    const body = req.body || {};
    const proxy_url = str(body.proxy_url ?? '', 'proxy_url', { max: 500, required: false });
    if (proxy_url) {
      let parsed;
      try {
        parsed = new URL(proxy_url);
      } catch {
        throw bad('proxy_url is not a valid URL');
      }
      if (!['http:', 'https:'].includes(parsed.protocol)) throw bad('proxy_url must start with http:// or https://');
    }
    db.setSettings({
      proxy_url,
      timeout_ms: int(body.timeout_ms ?? 15000, 'timeout_ms', { min: 1000, max: 120000 }),
      max_attempts: int(body.max_attempts ?? 3, 'max_attempts', { min: 1, max: 5 }),
    });
    res.json(db.getSettings());
  });

  app.post('/api/settings/test', adminOnly, async (req, res) => res.json(await discord.ping()));

  // ---- Errors ----
  app.use('/api', (req, res) => res.status(404).json({ error: 'not found' }));
  app.use((err, req, res, next) => {
    const status = err.status || err.statusCode || 500;
    if (status >= 500) console.error(err);
    res.status(status).json({ error: status >= 500 ? 'internal error' : err.message });
  });

  return app;
}

function main() {
  const envFile = path.join(__dirname, '..', '.env');
  if (fs.existsSync(envFile)) process.loadEnvFile(envFile);

  const dataDir = path.resolve(process.env.DATA_DIR || path.join(__dirname, '..', 'data'));
  const uploadsDir = path.join(dataDir, 'uploads');
  fs.mkdirSync(uploadsDir, { recursive: true });

  let adminToken = process.env.ADMIN_TOKEN || '';
  if (!adminToken) {
    adminToken = crypto.randomBytes(24).toString('hex');
    console.log(`ADMIN_TOKEN is not set. Temporary admin token for this run: ${adminToken}`);
  }

  const db = openDb(path.join(dataDir, 'promo.db'));
  const discord = createDiscord({
    apiBase: process.env.DISCORD_API_BASE || undefined,
    botToken: process.env.DISCORD_BOT_TOKEN || '',
    getSettings: db.getSettings,
    uploadsDir,
  });
  const scheduler = createScheduler({ db, discord });
  const app = createApp({ db, discord, scheduler, adminToken, editorToken: process.env.EDITOR_TOKEN || '', uploadsDir });

  const port = Number(process.env.PORT) || 8787;
  const host = process.env.HOST || '127.0.0.1';
  app.listen(port, host, () => {
    console.log(`Promo manager panel: http://${host}:${port}`);
    scheduler.start();
    scheduler.tick();
  });
}

if (require.main === module) main();

module.exports = { createApp };
