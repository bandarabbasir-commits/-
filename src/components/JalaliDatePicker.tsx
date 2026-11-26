import React, { useEffect, useRef, useState } from 'react';
import { Calendar, ChevronLeft, ChevronRight, X } from 'lucide-react';
import {
  JALALI_MONTHS,
  JALALI_WEEKDAYS_SHORT,
  daysInJalaliMonth,
  formatJalaliDisplay,
  formatJalaliIso,
  getTehranNowParts,
  jalaliWeekdaySatFirst,
  parseJalaliInput,
} from '../utils/jalali';
import { toPersianDigits } from '../utils/persian';

interface JalaliDatePickerProps {
  label?: string;
  value: string; // YYYY/MM/DD ASCII
  onChange: (nextAscii: string) => void;
  placeholder?: string;
  id?: string;
}

export const JalaliDatePicker: React.FC<JalaliDatePickerProps> = ({
  label,
  value,
  onChange,
  placeholder = '۱۴۰۵/۰۸/۳۰',
  id,
}) => {
  const [open, setOpen] = useState(false);
  const [textInput, setTextInput] = useState(() => (value ? toPersianDigits(value) : ''));
  const [errorMsg, setErrorMsg] = useState('');
  const containerRef = useRef<HTMLDivElement>(null);

  const nowParts = getTehranNowParts();
  const parsedVal = value ? parseJalaliInput(value) : null;
  const [viewYear, setViewYear] = useState(parsedVal?.jy ?? nowParts.jy);
  const [viewMonth, setViewMonth] = useState(parsedVal?.jm ?? nowParts.jm);

  useEffect(() => {
    setTextInput(value ? toPersianDigits(value) : '');
    setErrorMsg('');
    const p = value ? parseJalaliInput(value) : null;
    if (p) {
      setViewYear(p.jy);
      setViewMonth(p.jm);
    }
  }, [value]);

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', onDocClick);
    return () => document.removeEventListener('mousedown', onDocClick);
  }, [open]);

  const handleManualBlur = () => {
    const trimmed = textInput.trim();
    if (!trimmed) {
      onChange('');
      setErrorMsg('');
      return;
    }
    const parsed = parseJalaliInput(trimmed);
    if (!parsed) {
      setErrorMsg('تاریخ شمسی معتبر نیست (مثال: ۱۴۰۵/۰۸/۳۰)');
      return;
    }
    setErrorMsg('');
    const iso = formatJalaliIso(parsed.jy, parsed.jm, parsed.jd);
    onChange(iso);
    setTextInput(formatJalaliDisplay(parsed.jy, parsed.jm, parsed.jd));
    setViewYear(parsed.jy);
    setViewMonth(parsed.jm);
  };

  const prevMonth = () => {
    if (viewMonth === 1) {
      setViewYear((y) => y - 1);
      setViewMonth(12);
    } else {
      setViewMonth((m) => m - 1);
    }
  };

  const nextMonth = () => {
    if (viewMonth === 12) {
      setViewYear((y) => y + 1);
      setViewMonth(1);
    } else {
      setViewMonth((m) => m + 1);
    }
  };

  const monthDays = daysInJalaliMonth(viewYear, viewMonth);
  const firstWeekday = jalaliWeekdaySatFirst(viewYear, viewMonth, 1);

  return (
    <div ref={containerRef} className="relative">
      {label && (
        <label htmlFor={id} className="block text-xs font-medium text-[var(--hb-muted)] mb-1">
          {label}
        </label>
      )}
      <div className="relative flex items-center">
        <input
          id={id}
          type="text"
          dir="ltr"
          value={textInput}
          placeholder={placeholder}
          onChange={(e) => {
            setTextInput(e.target.value);
            if (errorMsg) setErrorMsg('');
          }}
          onBlur={handleManualBlur}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              handleManualBlur();
              setOpen(false);
            }
          }}
          className="w-full h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] pe-9 ps-8 text-sm text-[var(--hb-text)] tabular-nums text-right focus:border-[var(--hb-brand)] focus:outline-none"
        />
        <button
          type="button"
          aria-label="بازکردن تقویم شمسی"
          onClick={() => setOpen((o) => !o)}
          className="absolute end-1.5 inline-flex h-7 w-7 items-center justify-center rounded-md text-[var(--hb-muted)] hover:bg-slate-100 dark:hover:bg-slate-800"
        >
          <Calendar className="w-4 h-4" />
        </button>
        {value && (
          <button
            type="button"
            aria-label="پاک‌کردن تاریخ"
            onClick={() => {
              onChange('');
              setTextInput('');
              setErrorMsg('');
            }}
            className="absolute start-1.5 inline-flex h-6 w-6 items-center justify-center rounded text-[var(--hb-muted)] hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        )}
      </div>
      {errorMsg && <p className="mt-1 text-xs text-rose-600 dark:text-rose-400">{errorMsg}</p>}

      {open && (
        <div
          role="dialog"
          aria-label="انتخاب تاریخ شمسی"
          className="absolute z-40 mt-1.5 w-72 rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] p-3 shadow-xl start-0"
        >
          <div className="flex items-center justify-between gap-2 mb-2.5">
            <button
              type="button"
              onClick={prevMonth}
              aria-label="ماه قبل"
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--hb-border)] hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
            <div className="flex items-center gap-1.5">
              <select
                aria-label="انتخاب ماه"
                value={viewMonth}
                onChange={(e) => setViewMonth(Number(e.target.value))}
                className="h-8 rounded-md border border-[var(--hb-border)] bg-[var(--hb-surface)] px-1.5 text-xs font-medium"
              >
                {JALALI_MONTHS.slice(1).map((mName, idx) => (
                  <option key={idx + 1} value={idx + 1}>
                    {mName}
                  </option>
                ))}
              </select>
              <select
                aria-label="انتخاب سال"
                value={viewYear}
                onChange={(e) => setViewYear(Number(e.target.value))}
                className="h-8 rounded-md border border-[var(--hb-border)] bg-[var(--hb-surface)] px-1.5 text-xs font-medium tabular-nums"
              >
                {[1402, 1403, 1404, 1405, 1406, 1407].map((yr) => (
                  <option key={yr} value={yr}>
                    {toPersianDigits(yr)}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="button"
              onClick={nextMonth}
              aria-label="ماه بعد"
              className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--hb-border)] hover:bg-slate-100 dark:hover:bg-slate-800"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
          </div>

          <div className="grid grid-cols-7 gap-1 text-center text-[11px] font-medium text-[var(--hb-muted)] mb-1">
            {JALALI_WEEKDAYS_SHORT.map((wd) => (
              <div key={wd} className="py-1">
                {wd}
              </div>
            ))}
          </div>

          <div className="grid grid-cols-7 gap-1 text-center">
            {Array.from({ length: firstWeekday }).map((_, i) => (
              <div key={`empty-${i}`} />
            ))}
            {Array.from({ length: monthDays }).map((_, i) => {
              const day = i + 1;
              const isSelected =
                parsedVal?.jy === viewYear && parsedVal?.jm === viewMonth && parsedVal?.jd === day;
              const isToday =
                nowParts.jy === viewYear && nowParts.jm === viewMonth && nowParts.jd === day;
              return (
                <button
                  key={day}
                  type="button"
                  onClick={() => {
                    const iso = formatJalaliIso(viewYear, viewMonth, day);
                    onChange(iso);
                    setTextInput(formatJalaliDisplay(viewYear, viewMonth, day));
                    setErrorMsg('');
                    setOpen(false);
                  }}
                  className={`h-8 rounded-lg text-xs tabular-nums transition-colors ${
                    isSelected
                      ? 'bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)] font-bold'
                      : isToday
                      ? 'border border-[var(--hb-brand)] text-[var(--hb-active-text)] font-bold'
                      : 'hover:bg-slate-100 dark:hover:bg-slate-800 text-[var(--hb-text)]'
                  }`}
                >
                  {toPersianDigits(day)}
                </button>
              );
            })}
          </div>

          <div className="mt-2.5 pt-2 border-t border-[var(--hb-border)] flex items-center justify-between text-xs">
            <button
              type="button"
              onClick={() => {
                const iso = formatJalaliIso(nowParts.jy, nowParts.jm, nowParts.jd);
                onChange(iso);
                setTextInput(formatJalaliDisplay(nowParts.jy, nowParts.jm, nowParts.jd));
                setViewYear(nowParts.jy);
                setViewMonth(nowParts.jm);
                setErrorMsg('');
                setOpen(false);
              }}
              className="text-[var(--hb-active-text)] font-medium hover:underline"
            >
              امروز ({toPersianDigits(`${nowParts.jy}/${String(nowParts.jm).padStart(2, '0')}/${String(nowParts.jd).padStart(2, '0')}`)})
            </button>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-[var(--hb-muted)] hover:text-[var(--hb-text)]"
            >
              بستن
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
