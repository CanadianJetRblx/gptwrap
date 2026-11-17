'use strict';
// Runs due schedules and records every outcome in the delivery history.

const { computeNextRun } = require('./schedule');

// A one-off post that is this late (e.g. the server was down) is skipped
// instead of being published at an unexpected time.
const ONCE_GRACE_MS = 60 * 60000;

function createScheduler({ db, discord, now = () => Date.now(), tickMs = 15000 }) {
  let timer = null;
  let ticking = false;

  const getSchedule = db.prepare('SELECT * FROM schedules WHERE id = ?');
  const getChannel = db.prepare('SELECT * FROM channels WHERE id = ?');
  const getCommunity = db.prepare('SELECT * FROM communities WHERE id = ?');
  const getContent = db.prepare('SELECT * FROM contents WHERE id = ?');
  const lastSent = db.prepare(
    "SELECT created_at FROM deliveries WHERE channel_id = ? AND status = 'sent' ORDER BY created_at DESC LIMIT 1"
  );
  const insertDelivery = db.prepare(
    `INSERT INTO deliveries (schedule_id, channel_id, community_name, channel_name, content_title,
       trigger, status, attempts, http_status, error, message_id, created_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`
  );

  // Returns a reason string when posting is not allowed, otherwise null.
  // Every send, scheduled or manual, goes through this check.
  function blockReason(channel, community, at) {
    if (!community.enabled) return 'community is disabled';
    if (!channel.verified_at) return 'channel has not been verified against its server';
    if (!channel.authorized) return 'channel is not authorized for posting';
    const prev = lastSent.get(channel.id);
    if (prev) {
      const waitMs = prev.created_at + community.min_interval_minutes * 60000 - at;
      if (waitMs > 0) {
        return `minimum interval for this community not reached (${Math.ceil(waitMs / 60000)} min left)`;
      }
    }
    return null;
  }

  async function deliver({ scheduleId = null, channelId, contentId, trigger, lateReason = null }) {
    const at = now();
    const channel = getChannel.get(channelId);
    const content = getContent.get(contentId);
    const community = channel && getCommunity.get(channel.community_id);
    const record = (status, r = {}) => {
      const info = insertDelivery.run(
        scheduleId, channelId, community?.name ?? null, channel?.name ?? null, content?.title ?? null,
        trigger, status, r.attempts ?? 0, r.status ?? null, r.error ?? null, r.message_id ?? null, now()
      );
      return { id: Number(info.lastInsertRowid), status, error: r.error ?? null, http_status: r.status ?? null };
    };

    if (!channel || !content || !community) return record('skipped', { error: 'channel or content no longer exists' });
    if (lateReason) return record('skipped', { error: lateReason });
    const blocked = blockReason(channel, community, at);
    if (blocked) return record('skipped', { error: blocked });

    const result = await discord.send(channel, content);
    return record(result.ok ? 'sent' : 'failed', result);
  }

  async function runSchedule(schedule, trigger) {
    const at = now();
    const channel = getChannel.get(schedule.channel_id);
    const community = channel && getCommunity.get(channel.community_id);
    let lateReason = null;

    if (trigger === 'schedule') {
      // Advance the schedule before sending so a slow send cannot run twice.
      const next = community ? computeNextRun(schedule, at, community.timezone) : null;
      db.prepare('UPDATE schedules SET next_run_at = ?, last_run_at = ?, enabled = ? WHERE id = ?').run(
        next, at, next === null ? 0 : schedule.enabled, schedule.id
      );
      if (schedule.kind === 'once' && at - schedule.next_run_at > ONCE_GRACE_MS) {
        lateReason = 'missed its scheduled time by more than 60 minutes';
      }
    }
    return deliver({
      scheduleId: schedule.id,
      channelId: schedule.channel_id,
      contentId: schedule.content_id,
      trigger,
      lateReason,
    });
  }

  async function tick() {
    if (ticking) return;
    ticking = true;
    try {
      const due = db
        .prepare('SELECT * FROM schedules WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ? ORDER BY next_run_at')
        .all(now());
      for (const schedule of due) {
        try {
          await runSchedule(schedule, 'schedule');
        } catch (err) {
          console.error(`schedule ${schedule.id} failed:`, err.message);
        }
      }
    } finally {
      ticking = false;
    }
  }

  return {
    tick,
    blockReason,
    runNow: async (scheduleId) => {
      const schedule = getSchedule.get(scheduleId);
      return schedule ? runSchedule(schedule, 'manual') : null;
    },
    start() {
      if (!timer) {
        timer = setInterval(() => tick().catch((e) => console.error('tick error:', e.message)), tickMs);
        timer.unref?.();
      }
    },
    stop() {
      clearInterval(timer);
      timer = null;
    },
  };
}

module.exports = { createScheduler };
