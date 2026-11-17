'use strict';
// Pure time helpers: computing the next run of a schedule in a community's timezone.

function isValidTimezone(tz) {
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}

// Wall-clock fields of an instant in the given IANA timezone.
function tzParts(ts, tz) {
  const fmt = new Intl.DateTimeFormat('en-US', {
    timeZone: tz,
    hourCycle: 'h23',
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: 'numeric',
    minute: 'numeric',
    second: 'numeric',
  });
  const out = {};
  for (const part of fmt.formatToParts(new Date(ts))) {
    if (part.type !== 'literal') out[part.type] = Number(part.value);
  }
  return out;
}

function tzOffsetMs(ts, tz) {
  const p = tzParts(ts, tz);
  const asUtc = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second);
  return asUtc - Math.floor(ts / 1000) * 1000;
}

// Convert a wall-clock time in `tz` to a UTC timestamp (two passes handle DST edges).
function zonedToUtc(year, month, day, hour, minute, tz) {
  const guess = Date.UTC(year, month - 1, day, hour, minute);
  const first = guess - tzOffsetMs(guess, tz);
  return guess - tzOffsetMs(first, tz);
}

// Next occurrence strictly after `after` of HH:MM on one of `weekdays` (0 = Sunday).
function nextWeekly(after, tz, weekdays, timeOfDay) {
  const [hh, mm] = timeOfDay.split(':').map(Number);
  const p = tzParts(after, tz);
  for (let i = 0; i <= 8; i++) {
    const day = new Date(Date.UTC(p.year, p.month - 1, p.day + i));
    if (!weekdays.includes(day.getUTCDay())) continue;
    const ts = zonedToUtc(day.getUTCFullYear(), day.getUTCMonth() + 1, day.getUTCDate(), hh, mm, tz);
    if (ts > after) return ts;
  }
  return null;
}

function parseWeekdays(csv) {
  return String(csv || '')
    .split(',')
    .filter((x) => x !== '')
    .map(Number);
}

// First run for a new schedule, or the run after `after` for a recurring one.
// Returns null when a one-off schedule has nothing left to run.
function computeNextRun(schedule, after, tz, { initial = false } = {}) {
  if (schedule.kind === 'once') return initial ? schedule.run_at : null;
  if (schedule.kind === 'interval') {
    if (initial && schedule.run_at) return schedule.run_at;
    return after + schedule.interval_minutes * 60000;
  }
  return nextWeekly(after, tz, parseWeekdays(schedule.weekdays), schedule.time_of_day);
}

module.exports = { isValidTimezone, tzParts, zonedToUtc, nextWeekly, parseWeekdays, computeNextRun };
