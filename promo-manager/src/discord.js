'use strict';
// Thin Discord REST client: official bot token and webhooks only.

const fs = require('node:fs');
const path = require('node:path');
const { fetch, FormData, ProxyAgent } = require('undici');

const WEBHOOK_RE =
  /^https:\/\/(?:(?:ptb|canary)\.)?discord(?:app)?\.com\/api(?:\/v\d+)?\/webhooks\/(\d{17,20})\/([\w-]{20,})\/?$/;

const MIME = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp' };

function parseWebhookUrl(url) {
  const m = WEBHOOK_RE.exec(String(url || '').trim());
  return m ? { webhook_id: m[1], webhook_token: m[2] } : null;
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function createDiscord({ apiBase = 'https://discord.com/api/v10', botToken = '', getSettings, uploadsDir, backoffMs = 1000 }) {
  let cachedProxy = { url: '', agent: null };

  function dispatcherFor(proxyUrl) {
    if (!proxyUrl) return undefined;
    if (cachedProxy.url !== proxyUrl) {
      cachedProxy.agent?.close().catch(() => {});
      cachedProxy = { url: proxyUrl, agent: new ProxyAgent(proxyUrl) };
    }
    return cachedProxy.agent;
  }

  // Performs a request with timeout and bounded retries. Retries only on
  // rate limits (waiting as long as Discord asks) and transient failures.
  async function request(method, urlPath, { bot = false, makeBody } = {}) {
    const settings = getSettings();
    const maxAttempts = Math.max(1, settings.max_attempts);
    let last = { ok: false, status: null, error: 'not attempted', attempts: 0 };

    for (let attempt = 1; attempt <= maxAttempts; attempt++) {
      let wait = backoffMs * 2 ** (attempt - 1);
      try {
        const headers = {};
        if (bot) headers.Authorization = `Bot ${botToken}`;
        let body;
        if (makeBody) {
          body = makeBody();
          if (typeof body === 'string') headers['Content-Type'] = 'application/json';
        }
        const res = await fetch(apiBase + urlPath, {
          method,
          headers,
          body,
          dispatcher: dispatcherFor(settings.proxy_url),
          signal: AbortSignal.timeout(settings.timeout_ms),
        });
        const text = await res.text();
        let json = null;
        try {
          json = JSON.parse(text);
        } catch {
          /* non-JSON body */
        }
        if (res.ok) return { ok: true, status: res.status, json, attempts: attempt };

        last = { ok: false, status: res.status, error: json?.message || text.slice(0, 300) || res.statusText, attempts: attempt };
        if (res.status === 429) {
          const retryAfter = Number(json?.retry_after ?? res.headers.get('retry-after') ?? 1);
          wait = Math.min(Math.ceil(retryAfter * 1000), 60000);
        } else if (res.status < 500) {
          return last; // client errors are not retried
        }
      } catch (err) {
        // Never include the URL here: webhook URLs contain a secret token.
        const reason = err.name === 'TimeoutError' ? 'request timed out' : err.cause?.code || err.cause?.message || err.message;
        last = { ok: false, status: null, error: `network error: ${reason}`, attempts: attempt };
      }
      if (attempt < maxAttempts) await sleep(wait);
    }
    return last;
  }

  // Asks Discord which guild a destination really belongs to.
  async function lookupDestination(channel) {
    if (channel.kind === 'webhook') {
      const res = await request('GET', `/webhooks/${channel.webhook_id}/${channel.webhook_token}`);
      if (!res.ok) return res;
      return { ok: true, guild_id: res.json.guild_id, discord_channel_id: res.json.channel_id, label: res.json.name };
    }
    if (!botToken) return { ok: false, error: 'DISCORD_BOT_TOKEN is not configured' };
    const res = await request('GET', `/channels/${channel.discord_channel_id}`, { bot: true });
    if (!res.ok) return res;
    return { ok: true, guild_id: res.json.guild_id, discord_channel_id: res.json.id, label: res.json.name };
  }

  async function send(channel, content) {
    const payload = {
      content: content.body || '',
      // Promotions must never ping @everyone, roles or users.
      allowed_mentions: { parse: [] },
    };
    if (content.image_url) payload.embeds = [{ image: { url: content.image_url } }];

    let makeBody = () => JSON.stringify(payload);
    if (content.image_file) {
      const file = path.join(uploadsDir, path.basename(content.image_file));
      let buf;
      try {
        buf = fs.readFileSync(file);
      } catch {
        return { ok: false, status: null, error: 'uploaded image file is missing', attempts: 0 };
      }
      const type = MIME[path.extname(file).toLowerCase()] || 'application/octet-stream';
      makeBody = () => {
        const form = new FormData();
        form.set('payload_json', JSON.stringify(payload));
        form.set('files[0]', new Blob([buf], { type }), path.basename(file));
        return form;
      };
    }

    let res;
    if (channel.kind === 'webhook') {
      res = await request('POST', `/webhooks/${channel.webhook_id}/${channel.webhook_token}?wait=true`, { makeBody });
    } else {
      if (!botToken) return { ok: false, status: null, error: 'DISCORD_BOT_TOKEN is not configured', attempts: 0 };
      res = await request('POST', `/channels/${channel.discord_channel_id}/messages`, { bot: true, makeBody });
    }
    if (res.ok) res.message_id = res.json?.id || null;
    return res;
  }

  // Connectivity check against a public, unauthenticated endpoint.
  async function ping() {
    const started = Date.now();
    const res = await request('GET', '/gateway');
    return { ok: res.ok, status: res.status, error: res.error, attempts: res.attempts, latency_ms: Date.now() - started };
  }

  return { lookupDestination, send, ping, hasBotToken: () => Boolean(botToken) };
}

module.exports = { createDiscord, parseWebhookUrl, MIME };
