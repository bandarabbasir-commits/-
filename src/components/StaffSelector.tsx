import React, { useMemo, useState } from 'react';
import { Check, LayoutGrid, List, Search, Table } from 'lucide-react';
import type { DirectoryUser } from '../types/api';
import { normalizePersianText, toPersianDigits } from '../utils/persian';

interface StaffSelectorProps {
  users: DirectoryUser[];
  selectedIds: number[];
  onChange: (nextIds: number[]) => void;
  maxSelect?: number;
  excludeIds?: number[];
  disabledIds?: number[];
  disabledReason?: string;
}

export const StaffSelector: React.FC<StaffSelectorProps> = ({
  users,
  selectedIds,
  onChange,
  maxSelect = 2,
  excludeIds = [],
  disabledIds = [],
  disabledReason = 'هم‌اکنون گیرندهٔ فعال است',
}) => {
  const [query, setQuery] = useState('');
  const [viewMode, setViewMode] = useState<'grid' | 'list' | 'table'>('list');

  const filtered = useMemo(() => {
    const qNorm = normalizePersianText(query);
    return users
      .filter((u) => !excludeIds.includes(u.id))
      .filter((u) => {
        if (!qNorm) return true;
        const hay = normalizePersianText(`${u.display_name} ${u.job_title} ${u.department}`);
        return hay.includes(qNorm);
      })
      .sort((a, b) => a.display_name.localeCompare(b.display_name, 'fa'));
  }, [users, excludeIds, query]);

  const toggleUser = (uid: number) => {
    if (disabledIds.includes(uid)) return;
    if (selectedIds.includes(uid)) {
      onChange(selectedIds.filter((id) => id !== uid));
      return;
    }
    if (maxSelect === 1) {
      onChange([uid]);
      return;
    }
    if (selectedIds.length >= maxSelect) {
      return;
    }
    onChange([...selectedIds, uid]);
  };

  const renderInitialBadge = (u: DirectoryUser) => (
    <span
      className="inline-flex h-8 w-8 items-center justify-center rounded-full text-xs font-bold text-white shrink-0"
      style={{ backgroundColor: u.avatar_color || '#0F766E' }}
      aria-hidden="true"
    >
      {u.display_name.trim().charAt(0)}
    </span>
  );

  return (
    <div className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] p-3">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
        <div className="relative flex-1 min-w-[180px]">
          <Search className="w-4 h-4 text-[var(--hb-muted)] absolute start-2.5 top-1/2 -translate-y-1/2" aria-hidden="true" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="جستجوی نام، سمت یا واحد..."
            aria-label="جستجوی همکاران"
            className="w-full h-9 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] ps-8 pe-3 text-xs focus:border-[var(--hb-brand)] focus:outline-none"
          />
        </div>
        <div className="flex items-center gap-1 rounded-lg bg-[var(--hb-bg)] p-1 border border-[var(--hb-border)]">
          <button
            type="button"
            onClick={() => setViewMode('list')}
            aria-label="نمای فهرستی"
            className={`p-1.5 rounded-md ${
              viewMode === 'list' ? 'bg-[var(--hb-surface)] text-[var(--hb-active-text)] shadow-sm' : 'text-[var(--hb-muted)]'
            }`}
          >
            <List className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => setViewMode('grid')}
            aria-label="نمای شبکه‌ای"
            className={`p-1.5 rounded-md ${
              viewMode === 'grid' ? 'bg-[var(--hb-surface)] text-[var(--hb-active-text)] shadow-sm' : 'text-[var(--hb-muted)]'
            }`}
          >
            <LayoutGrid className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => setViewMode('table')}
            aria-label="نمای جدولی"
            className={`p-1.5 rounded-md ${
              viewMode === 'table' ? 'bg-[var(--hb-surface)] text-[var(--hb-active-text)] shadow-sm' : 'text-[var(--hb-muted)]'
            }`}
          >
            <Table className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      <div className="text-xs text-[var(--hb-muted)] mb-2 flex items-center justify-between">
        <span>
          انتخاب‌شده: <strong className="text-[var(--hb-text)] tabular-nums">{toPersianDigits(selectedIds.length)}</strong> از{' '}
          <span className="tabular-nums">{toPersianDigits(maxSelect)}</span> نفر
        </span>
        {selectedIds.length >= maxSelect && maxSelect > 1 && (
          <span className="text-amber-700 dark:text-amber-300">حداکثر سقف انتخاب تکمیل شد</span>
        )}
      </div>

      <div className="max-h-56 overflow-y-auto pe-1">
        {filtered.length === 0 ? (
          <p className="py-6 text-center text-xs text-[var(--hb-muted)]">همکاری با این مشخصات یافت نشد.</p>
        ) : viewMode === 'table' ? (
          <table className="w-full text-xs text-right">
            <thead className="border-b border-[var(--hb-border)] text-[var(--hb-muted)]">
              <tr>
                <th className="py-1.5 font-medium">نام و نام‌خانوادگی</th>
                <th className="py-1.5 font-medium">سمت / واحد</th>
                <th className="py-1.5 font-medium text-left">وضعیت</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--hb-border)]">
              {filtered.map((u) => {
                const selected = selectedIds.includes(u.id);
                const disabled = disabledIds.includes(u.id) || (!selected && selectedIds.length >= maxSelect && maxSelect > 1);
                return (
                  <tr key={u.id}>
                    <td className="py-1.5">
                      <button
                        type="button"
                        disabled={disabled}
                        onClick={() => toggleUser(u.id)}
                        className="flex items-center gap-2 text-right font-medium text-[var(--hb-text)] disabled:opacity-50"
                      >
                        <span
                          className={`inline-flex h-4 w-4 items-center justify-center rounded border ${
                            selected
                              ? 'bg-[var(--hb-primary-bg)] border-[var(--hb-primary-bg)] text-[var(--hb-primary-text)]'
                              : 'border-[var(--hb-border)]'
                          }`}
                        >
                          {selected && <Check className="w-3 h-3" />}
                        </span>
                        {u.display_name}
                      </button>
                    </td>
                    <td className="py-1.5 text-[var(--hb-muted)]">
                      {u.job_title || 'کارشناس'} · {u.department}
                    </td>
                    <td className="py-1.5 text-left text-[var(--hb-muted)]">
                      {disabledIds.includes(u.id) ? disabledReason : u.is_online ? 'آنلاین' : 'آفلاین'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <div className={viewMode === 'grid' ? 'grid grid-cols-1 sm:grid-cols-2 gap-2' : 'space-y-1.5'}>
            {filtered.map((u) => {
              const selected = selectedIds.includes(u.id);
              const isAlreadyAssigned = disabledIds.includes(u.id);
              const atCap = !selected && selectedIds.length >= maxSelect && maxSelect > 1;
              const disabled = isAlreadyAssigned || atCap;

              return (
                <button
                  key={u.id}
                  type="button"
                  disabled={disabled}
                  onClick={() => toggleUser(u.id)}
                  className={`w-full flex items-center justify-between gap-2.5 rounded-lg border px-3 py-2 text-right transition-colors ${
                    selected
                      ? 'border-[var(--hb-brand)] bg-[var(--hb-active-tint)]'
                      : 'border-[var(--hb-border)] hover:bg-slate-50 dark:hover:bg-slate-800/50'
                  } disabled:opacity-50 disabled:cursor-not-allowed`}
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    {renderInitialBadge(u)}
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-[var(--hb-text)] truncate">
                        {u.display_name}
                      </div>
                      <div className="text-[11px] text-[var(--hb-muted)] truncate">
                        {u.job_title || 'همکار'} · {u.department}
                        {isAlreadyAssigned ? ` · ${disabledReason}` : u.is_online ? ' · آنلاین' : ''}
                      </div>
                    </div>
                  </div>
                  <span
                    className={`inline-flex h-5 w-5 items-center justify-center rounded border shrink-0 ${
                      selected
                        ? 'bg-[var(--hb-primary-bg)] border-[var(--hb-primary-bg)] text-[var(--hb-primary-text)]'
                        : 'border-[var(--hb-border)]'
                    }`}
                  >
                    {selected && <Check className="w-3.5 h-3.5" />}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
