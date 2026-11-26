import React, { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Archive, RotateCcw, Search } from 'lucide-react';
import { ApiError, apiFetch } from '../utils/api';
import { toPersianDigits } from '../utils/persian';
import { useToast } from '../components/ToastProvider';
import { JalaliDatePicker } from '../components/JalaliDatePicker';
import { Modal } from '../components/Modal';
import { useOnlineStatus } from '../hooks/useOnlineStatus';

interface ArchivedItem {
  id: number;
  target_type: 'task' | 'visit';
  title: string;
  summary: string;
  status: string;
  archived_at_label: string;
  reason: string | null;
}

const ArchivePage: React.FC = () => {
  const { pushToast } = useToast();
  const isOnline = useOnlineStatus();
  const qc = useQueryClient();

  const [targetType, setTargetType] = useState<'task' | 'visit'>('task');
  const [searchInput, setSearchInput] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [selectedIds, setSelectedIds] = useState<number[]>([]);

  // Clear-done Modal
  const [clearModalOpen, setClearModalOpen] = useState(false);
  const [selectedStatuses, setSelectedStatuses] = useState<string[]>(['success', 'failed']);
  const [beforeDate, setBeforeDate] = useState('');
  const [reason, setReason] = useState('');
  const [previewCount, setPreviewCount] = useState<number | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedQ(searchInput.trim()), 250);
    return () => window.clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    setSelectedStatuses(targetType === 'task' ? ['success', 'failed'] : ['approved', 'rejected']);
    setSelectedIds([]);
    setPreviewCount(null);
  }, [targetType]);

  const archiveQuery = useQuery({
    queryKey: ['archive', targetType, debouncedQ],
    queryFn: ({ signal }) => {
      const p = new URLSearchParams({ target_type: targetType, limit: '50' });
      if (debouncedQ) p.set('q', debouncedQ);
      return apiFetch<{ items: ArchivedItem[]; total: number }>(`/api/v1/archive?${p.toString()}`, { signal });
    },
  });

  const previewMut = useMutation({
    mutationFn: () =>
      apiFetch<{ matching_count: number }>('/api/v1/archive/preview', {
        method: 'POST',
        body: {
          target_type: targetType,
          statuses: selectedStatuses,
          before_jalali_date: beforeDate || null,
          reason: reason.trim(),
        },
      }),
    onSuccess: (res) => setPreviewCount(res.matching_count),
    onError: (err) => pushToast('error', err instanceof ApiError ? err.message : 'خطا در پیش‌نمایش آرشیو.'),
  });

  const clearMut = useMutation({
    mutationFn: () =>
      apiFetch<{ archived_count: number }>('/api/v1/archive/clear-done', {
        method: 'POST',
        body: {
          target_type: targetType,
          statuses: selectedStatuses,
          before_jalali_date: beforeDate || null,
          reason: reason.trim(),
        },
      }),
    onSuccess: (res) => {
      pushToast('success', `${toPersianDigits(res.archived_count)} مورد به آرشیو منتقل شد.`);
      setClearModalOpen(false);
      setPreviewCount(null);
      qc.invalidateQueries({ queryKey: ['archive'] });
      qc.invalidateQueries({ queryKey: ['tasks'] });
      qc.invalidateQueries({ queryKey: ['visits'] });
    },
    onError: (err) => pushToast('error', err instanceof ApiError ? err.message : 'خطا در انتقال به آرشیو.'),
  });

  const restoreMut = useMutation({
    mutationFn: (ids: number[]) =>
      apiFetch<{ restored_count: number }>('/api/v1/archive/restore', {
        method: 'POST',
        body: { target_type: targetType, ids },
      }),
    onSuccess: (res) => {
      pushToast('success', `${toPersianDigits(res.restored_count)} مورد از آرشیو خارج و به لیست اصلی بازگشت.`);
      setSelectedIds([]);
      qc.invalidateQueries({ queryKey: ['archive'] });
      qc.invalidateQueries({ queryKey: ['tasks'] });
      qc.invalidateQueries({ queryKey: ['visits'] });
    },
    onError: (err) => pushToast('error', err instanceof ApiError ? err.message : 'بازگردانی از آرشیو ناموفق بود.'),
  });

  const items = archiveQuery.data?.items || [];

  const statusOptions =
    targetType === 'task'
      ? [
          { id: 'success', label: 'موفق (بسته‌شده)' },
          { id: 'failed', label: 'ناموفق (بسته‌شده)' },
        ]
      : [
          { id: 'approved', label: 'تأییدشده' },
          { id: 'rejected', label: 'ردشده' },
        ];

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] p-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setTargetType('task')}
            className={`rounded-lg px-3.5 py-2 text-xs font-semibold ${
              targetType === 'task'
                ? 'bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)]'
                : 'border border-[var(--hb-border)] text-[var(--hb-text)]'
            }`}
          >
            بایگانی پرونده‌های پیام
          </button>
          <button
            type="button"
            onClick={() => setTargetType('visit')}
            className={`rounded-lg px-3.5 py-2 text-xs font-semibold ${
              targetType === 'visit'
                ? 'bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)]'
                : 'border border-[var(--hb-border)] text-[var(--hb-text)]'
            }`}
          >
            بایگانی مراجعات مردمی
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-2 flex-1 justify-end min-w-[240px]">
          <div className="relative flex-1 max-w-xs">
            <Search className="w-4 h-4 text-[var(--hb-muted)] absolute start-3 top-1/2 -translate-y-1/2" aria-hidden="true" />
            <input
              type="search"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="جستجو در بایگانی..."
              className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] ps-9 pe-3 py-2 text-xs"
            />
          </div>

          {selectedIds.length > 0 && (
            <button
              type="button"
              disabled={!isOnline || restoreMut.isPending}
              onClick={() => restoreMut.mutate(selectedIds)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--hb-border)] px-3 py-2 text-xs font-semibold text-[var(--hb-active-text)] hover:bg-[var(--hb-active-tint)]"
            >
              <RotateCcw className="w-3.5 h-3.5" aria-hidden="true" />
              <span>بازگردانی انتخاب‌شده ({toPersianDigits(selectedIds.length)})</span>
            </button>
          )}

          <button
            type="button"
            disabled={!isOnline}
            onClick={() => {
              setPreviewCount(null);
              setClearModalOpen(true);
            }}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)] px-3.5 py-2 text-xs font-bold disabled:opacity-50"
          >
            <Archive className="w-3.5 h-3.5" aria-hidden="true" />
            <span>بایگانی کارهای مختومه</span>
          </button>
        </div>
      </div>

      {archiveQuery.isLoading ? (
        <div className="h-44 rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] animate-pulse" />
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] py-12 text-center text-sm text-[var(--hb-muted)]">
          موردی در بایگانی این بخش یافت نشد.
        </div>
      ) : (
        <div className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] divide-y divide-[var(--hb-border)]">
          {items.map((item) => {
            const checked = selectedIds.includes(item.id);
            return (
              <div
                key={`${item.target_type}-${item.id}`}
                className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3"
              >
                <div className="flex items-start gap-3 min-w-0">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() =>
                      setSelectedIds((prev) =>
                        prev.includes(item.id) ? prev.filter((x) => x !== item.id) : [...prev, item.id]
                      )
                    }
                    className="mt-1 accent-teal-600"
                  />
                  <div className="min-w-0 space-y-1">
                    <div className="text-sm font-bold text-[var(--hb-text)]">{item.title}</div>
                    <p className="text-xs text-[var(--hb-muted)] line-clamp-2">{item.summary}</p>
                    <div className="text-[11px] text-[var(--hb-muted)] tabular-nums flex flex-wrap gap-3">
                      <span>تاریخ بایگانی: {item.archived_at_label}</span>
                      {item.reason && <span>علت: {item.reason}</span>}
                    </div>
                  </div>
                </div>

                <button
                  type="button"
                  disabled={!isOnline || restoreMut.isPending}
                  onClick={() => restoreMut.mutate([item.id])}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--hb-border)] px-3 py-1.5 text-xs font-medium hover:bg-slate-100 dark:hover:bg-slate-800 shrink-0"
                >
                  <RotateCcw className="w-3.5 h-3.5" aria-hidden="true" />
                  <span>خروج از بایگانی</span>
                </button>
              </div>
            );
          })}
        </div>
      )}

      <Modal
        open={clearModalOpen}
        title={targetType === 'task' ? 'بایگانی پرونده‌های مختومه پیام' : 'بایگانی مراجعات بررسی‌شده'}
        onClose={() => setClearModalOpen(false)}
        blockBackdropClose
        maxWidthClass="max-w-md"
      >
        <div className="space-y-4 text-xs">
          <div>
            <div className="font-semibold text-[var(--hb-text)] mb-2">وضعیت‌های مشمول بایگانی:</div>
            <div className="flex flex-wrap gap-2">
              {statusOptions.map((opt) => {
                const checked = selectedStatuses.includes(opt.id);
                return (
                  <label
                    key={opt.id}
                    className="flex items-center gap-2 rounded-lg border border-[var(--hb-border)] px-3 py-2 cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => {
                        setPreviewCount(null);
                        setSelectedStatuses((prev) =>
                          prev.includes(opt.id) ? prev.filter((x) => x !== opt.id) : [...prev, opt.id]
                        );
                      }}
                      className="accent-teal-600"
                    />
                    <span>{opt.label}</span>
                  </label>
                );
              })}
            </div>
          </div>

          <JalaliDatePicker
            label="موارد ثبت‌شده تا پایان تاریخ شمسی (اختیاری)"
            value={beforeDate}
            onChange={(val) => {
              setBeforeDate(val);
              setPreviewCount(null);
            }}
          />

          <div>
            <label className="block font-medium text-[var(--hb-muted)] mb-1">توضیح یا دوره بایگانی (اختیاری)</label>
            <input
              type="text"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="مثلاً: پاکسازی پایان فصل بهار"
              className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-3 py-2"
            />
          </div>

          {previewCount !== null && (
            <div className="rounded-lg border border-[var(--hb-border)] bg-[var(--hb-active-tint)] p-3 text-[var(--hb-active-text)] font-semibold tabular-nums">
              تعداد رکوردهای واجد شرایط برای انتقال به بایگانی: {toPersianDigits(previewCount)} مورد
            </div>
          )}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => setClearModalOpen(false)}
              className="rounded-lg border border-[var(--hb-border)] px-3.5 py-2 font-medium"
            >
              انصراف
            </button>
            <button
              type="button"
              disabled={!isOnline || previewMut.isPending || selectedStatuses.length === 0}
              onClick={() => previewMut.mutate()}
              className="rounded-lg border border-[var(--hb-border)] px-3.5 py-2 font-semibold hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50"
            >
              {previewMut.isPending ? 'در حال محاسبه...' : 'پیش‌نمایش تعداد'}
            </button>
            <button
              type="button"
              disabled={!isOnline || clearMut.isPending || previewCount === null || previewCount === 0}
              onClick={() => clearMut.mutate()}
              className="rounded-lg bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)] px-3.5 py-2 font-bold disabled:opacity-50"
            >
              {clearMut.isPending ? 'در حال انتقال...' : 'تأیید و بایگانی'}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
};

export default ArchivePage;
