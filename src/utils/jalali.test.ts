import test from 'node:test';
import assert from 'node:assert/strict';
import {
  daysInJalaliMonth,
  formatJalaliIso,
  getTehranPlusHoursDefaults,
  isJalaliLeapYear,
  parseJalaliInput,
  toGregorian,
  toJalali,
} from './jalali';

test('Jalali leap year detection for 1403 and 1404', () => {
  assert.equal(isJalaliLeapYear(1403), true);
  assert.equal(daysInJalaliMonth(1403, 12), 30);
  assert.equal(isJalaliLeapYear(1404), false);
  assert.equal(daysInJalaliMonth(1404, 12), 29);
});

test('Gregorian <-> Jalali roundtrip preserves exact calendar date', () => {
  const j = toJalali(2025, 3, 20);
  assert.deepEqual(j, { jy: 1403, jm: 12, jd: 30 });
  const g = toGregorian(1403, 12, 30);
  assert.deepEqual(g, { gy: 2025, gm: 3, gd: 20 });

  const jNowruz = toJalali(2025, 3, 21);
  assert.deepEqual(jNowruz, { jy: 1404, jm: 1, jd: 1 });
});

test('parseJalaliInput normalizes Persian digits and rejects invalid dates', () => {
  assert.deepEqual(parseJalaliInput('۱۴۰۳/۱۲/۳۰'), { jy: 1403, jm: 12, jd: 30 });
  assert.equal(parseJalaliInput('۱۴۰۴/۱۲/۳۰'), null);
  assert.equal(parseJalaliInput('1405-09-05')?.jm, 9);
});

test('getTehranPlusHoursDefaults computes +24h across Tehran midnight and month boundary', () => {
  // 2025-03-20T18:00:00Z = 2025-03-20 21:30 Tehran (+03:30) = 1403/12/30 21:30
  // +24h => 1404/01/01 21:30
  const leapBoundary = new Date('2025-03-20T18:00:00Z');
  const res = getTehranPlusHoursDefaults(24, leapBoundary);
  assert.equal(res.jalaliDate, formatJalaliIso(1404, 1, 1));
  assert.equal(res.tehranTime, '21:30');
});
