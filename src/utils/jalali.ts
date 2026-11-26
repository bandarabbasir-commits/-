import { toAsciiDigits, toPersianDigits } from './persian';

export const JALALI_MONTHS = [
  '',
  'فروردین',
  'اردیبهشت',
  'خرداد',
  'تیر',
  'مرداد',
  'شهریور',
  'مهر',
  'آبان',
  'آذر',
  'دی',
  'بهمن',
  'اسفند',
];

export const JALALI_WEEKDAYS_SHORT = ['ش', 'ی', 'د', 'س', 'چ', 'پ', 'ج'];

// Pure algorithmic Jalali <-> Gregorian conversion (Kazimierz M. Borkowski)
export function div(a: number, b: number): number {
  return ~~(a / b);
}

export function mod(a: number, b: number): number {
  return a - ~~(a / b) * b;
}

export function jalCal(jy: number): { leap: number; gy: number; march: number } {
  const breaks = [
    -61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210, 1635, 2060, 2097, 2192,
    2262, 2324, 2394, 2456, 3178,
  ];
  const bl = breaks.length;
  const gy = jy + 621;
  let leapJ = -14;
  let jp = breaks[0];
  let jm = 0;
  let jump = 0;

  if (jy < jp || jy >= breaks[bl - 1]) {
    throw new Error('سال جلالی خارج از محدوده است');
  }

  for (let i = 1; i < bl; i += 1) {
    jm = breaks[i];
    jump = jm - jp;
    if (jy < jm) break;
    leapJ = leapJ + div(jump, 33) * 8 + div(mod(jump, 33), 4);
    jp = jm;
  }
  let n = jy - jp;
  leapJ = leapJ + div(n, 33) * 8 + div(mod(n, 33) + 3, 4);
  if (mod(jump, 33) === 4 && jump - n === 4) {
    leapJ += 1;
  }

  const leapG = div(gy, 4) - div((div(gy, 100) + 1) * 3, 4) - 150;
  const march = 20 + leapJ - leapG;

  if (jump - n < 6) {
    n = n - jump + div(jump + 4, 33) * 33;
  }
  let leap = mod(mod(n + 1, 33) - 1, 4);
  if (leap === -1) {
    leap = 4;
  }
  return { leap, gy, march };
}

export function isJalaliLeapYear(jy: number): boolean {
  return jalCal(jy).leap === 0;
}

export function daysInJalaliMonth(jy: number, jm: number): number {
  if (jm <= 6) return 31;
  if (jm <= 11) return 30;
  return isJalaliLeapYear(jy) ? 30 : 29;
}

export function j2d(jy: number, jm: number, jd: number): number {
  const r = jalCal(jy);
  return g2d(r.gy, 3, r.march) + (jm - 1) * 31 - div(jm, 7) * (jm - 7) + jd - 1;
}

export function d2j(jdn: number): { jy: number; jm: number; jd: number } {
  const gy = d2g(jdn).gy;
  let jy = gy - 621;
  const r = jalCal(jy);
  const jdn1f = g2d(gy, 3, r.march);
  let k = jdn - jdn1f;
  if (k >= 0) {
    if (k <= 185) {
      const jm = 1 + div(k, 31);
      const jd = mod(k, 31) + 1;
      return { jy, jm, jd };
    }
    k -= 186;
  } else {
    jy -= 1;
    k += 179;
    if (r.leap === 1) k += 1;
  }
  const jm = 7 + div(k, 30);
  const jd = mod(k, 30) + 1;
  return { jy, jm, jd };
}

export function g2d(gy: number, gm: number, gd: number): number {
  let d =
    div((gy + div(gm - 8, 6) + 100100) * 1461, 4) +
    div(153 * mod(gm + 9, 12) + 2, 5) +
    gd -
    34840408;
  d = d - div(div(gy + 100100 + div(gm - 8, 6), 100) * 3, 4) + 752;
  return d;
}

export function d2g(jdn: number): { gy: number; gm: number; gd: number } {
  let j = 4 * jdn + 139361631;
  j = j + div(div(4 * jdn + 183187720, 146097) * 3, 4) * 4 - 3908;
  const i = div(mod(j, 1461), 4) * 5 + 308;
  const gd = div(mod(i, 153), 5) + 1;
  const gm = mod(div(i, 153), 12) + 1;
  const gy = div(j, 1461) - 100100 + div(8 - gm, 6);
  return { gy, gm, gd };
}

export function toJalali(gy: number, gm: number, gd: number): { jy: number; jm: number; jd: number } {
  return d2j(g2d(gy, gm, gd));
}

export function toGregorian(jy: number, jm: number, jd: number): { gy: number; gm: number; gd: number } {
  return d2g(j2d(jy, jm, jd));
}

/** Return Saturday-first weekday index (0 = Saturday .. 6 = Friday) */
export function jalaliWeekdaySatFirst(jy: number, jm: number, jd: number): number {
  const { gy, gm, gd } = toGregorian(jy, jm, jd);
  const jsDay = new Date(Date.UTC(gy, gm - 1, gd)).getUTCDay(); // 0=Sun..6=Sat
  return (jsDay + 1) % 7;
}

export function parseJalaliInput(raw: string): { jy: number; jm: number; jd: number } | null {
  const ascii = toAsciiDigits(raw.trim()).replace(/-/g, '/');
  const m = /^(\d{4})\/(\d{1,2})\/(\d{1,2})$/.exec(ascii);
  if (!m) return null;
  const jy = Number(m[1]);
  const jm = Number(m[2]);
  const jd = Number(m[3]);
  if (jy < 1300 || jy > 1500 || jm < 1 || jm > 12) return null;
  const maxDays = daysInJalaliMonth(jy, jm);
  if (jd < 1 || jd > maxDays) return null;
  return { jy, jm, jd };
}

export function formatJalaliIso(jy: number, jm: number, jd: number): string {
  return `${jy}/${String(jm).padStart(2, '0')}/${String(jd).padStart(2, '0')}`;
}

export function formatJalaliDisplay(jy: number, jm: number, jd: number): string {
  return toPersianDigits(formatJalaliIso(jy, jm, jd));
}

export function getTehranNowParts(date: Date = new Date()): {
  jy: number;
  jm: number;
  jd: number;
  hh: string;
  mm: string;
  ss: string;
  weekdayName: string;
  formattedFull: string;
} {
  // Use Intl Asia/Tehran to extract exact Tehran civil date & time without any network request
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Tehran',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).formatToParts(date);

  const get = (type: string) => parts.find((p) => p.type === type)?.value || '00';
  const gy = Number(get('year'));
  const gm = Number(get('month'));
  const gd = Number(get('day'));
  const hh = get('hour') === '24' ? '00' : get('hour');
  const mm = get('minute');
  const ss = get('second');

  const { jy, jm, jd } = toJalali(gy, gm, gd);
  const weekdayIdx = jalaliWeekdaySatFirst(jy, jm, jd);
  const weekdayNames = ['شنبه', 'یکشنبه', 'دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه'];
  const formattedFull = `${toPersianDigits(jd)} ${JALALI_MONTHS[jm]} ${toPersianDigits(jy)} — ${toPersianDigits(hh)}:${toPersianDigits(mm)}`;

  return { jy, jm, jd, hh, mm, ss, weekdayName: weekdayNames[weekdayIdx], formattedFull };
}

export function getTehranPlusHoursDefaults(
  hours: number = 24,
  baseDate: Date = new Date()
): { jalaliDate: string; tehranTime: string } {
  const target = new Date(baseDate.getTime() + hours * 3600 * 1000);
  const parts = getTehranNowParts(target);
  return {
    jalaliDate: formatJalaliIso(parts.jy, parts.jm, parts.jd),
    tehranTime: `${parts.hh}:${parts.mm}`,
  };
}

