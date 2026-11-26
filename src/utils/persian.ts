const PERSIAN_DIGITS = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹'];

export function toPersianDigits(input: string | number | null | undefined): string {
  if (input === null || input === undefined) return '';
  return String(input)
    .replace(/[0-9]/g, (d) => PERSIAN_DIGITS[Number(d)])
    .replace(/[٠-٩]/g, (d) => PERSIAN_DIGITS[d.charCodeAt(0) - 0x0660]);
}

export function toAsciiDigits(input: string): string {
  return input
    .replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06f0))
    .replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660));
}

export function normalizePersianText(input: string): string {
  return toAsciiDigits(input)
    .replace(/[يیى]/g, 'ی')
    .replace(/[كک]/g, 'ک')
    .replace(/\u200c/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

export function validateIranPhoneClient(raw: string): string | null {
  const ascii = toAsciiDigits(raw.trim()).replace(/[\s\-\.\(\)]+/g, '');
  let norm = ascii;
  if (norm.startsWith('+98')) norm = '0' + norm.slice(3);
  else if (norm.startsWith('0098')) norm = '0' + norm.slice(4);
  else if (norm.startsWith('98') && norm.length === 12) norm = '0' + norm.slice(2);
  else if (norm.startsWith('9') && norm.length === 10) norm = '0' + norm;

  if (/^09\d{9}$/.test(norm) || /^0[1-8]\d{9}$/.test(norm)) {
    return norm;
  }
  return null;
}

export function formatPhoneDisplay(phone: string): string {
  return toPersianDigits(phone || '—');
}
