'use strict';
// SQLite storage (uses Node's built-in node:sqlite, no native build step).

const { DatabaseSync } = require('node:sqlite');

const SCHEMA = `
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS communities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  guild_id TEXT NOT NULL UNIQUE,
  timezone TEXT NOT NULL DEFAULT 'UTC',
  rules TEXT NOT NULL DEFAULT '',
  -- Minimum gap between two posts in the same channel, per this server's rules.
  min_interval_minutes INTEGER NOT NULL DEFAULT 1440,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS channels (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  community_id INTEGER NOT NULL REFERENCES communities(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('webhook', 'bot')),
  discord_channel_id TEXT,
  webhook_id TEXT,
  webhook_token TEXT,
  -- Set when Discord confirmed the destination belongs to the community's guild.
  verified_at INTEGER,
  verify_note TEXT,
  -- Set by an admin who confirms the partner server allowed posting here.
  authorized INTEGER NOT NULL DEFAULT 0,
  authorized_note TEXT,
  authorized_at INTEGER,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS contents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  body TEXT NOT NULL DEFAULT '',
  image_url TEXT,
  image_file TEXT,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS schedules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
  content_id INTEGER NOT NULL REFERENCES contents(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('once', 'interval', 'weekly')),
  run_at INTEGER,
  interval_minutes INTEGER,
  weekdays TEXT,
  time_of_day TEXT,
  next_run_at INTEGER,
  last_run_at INTEGER,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at INTEGER NOT NULL
);

-- History keeps name snapshots so it survives deletion of the related rows.
CREATE TABLE IF NOT EXISTS deliveries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  schedule_id INTEGER,
  channel_id INTEGER,
  community_name TEXT,
  channel_name TEXT,
  content_title TEXT,
  trigger TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('sent', 'failed', 'skipped')),
  attempts INTEGER NOT NULL DEFAULT 0,
  http_status INTEGER,
  error TEXT,
  message_id TEXT,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS deliveries_created ON deliveries(created_at);
CREATE INDEX IF NOT EXISTS deliveries_channel ON deliveries(channel_id, status, created_at);

CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
`;

const DEFAULT_SETTINGS = { proxy_url: '', timeout_ms: 15000, max_attempts: 3 };

function openDb(file) {
  const db = new DatabaseSync(file);
  db.exec(SCHEMA);

  db.getSettings = () => {
    const out = { ...DEFAULT_SETTINGS };
    for (const row of db.prepare('SELECT key, value FROM settings').all()) {
      if (row.key in out) out[row.key] = JSON.parse(row.value);
    }
    return out;
  };
  db.setSettings = (patch) => {
    const stmt = db.prepare(
      'INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value'
    );
    for (const [k, v] of Object.entries(patch)) {
      if (k in DEFAULT_SETTINGS) stmt.run(k, JSON.stringify(v));
    }
  };
  return db;
}

module.exports = { openDb, DEFAULT_SETTINGS };
