import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, RotateCcw, Trash2 } from 'lucide-react';
import { ApiError, apiFetch } from '../utils/api';
import { toPersianDigits } from '../utils/persian';
import { useToast } from '../components/ToastProvider';
import { Modal } from '../components/Modal';
import { useOnlineStatus } from '../hooks/useOnlineStatus';

interface TrashItem {
  id: number;
  target_type: 'task' | 'visit';
  title: string;
  summary: string;
  status: string;
  deleted_at_label: string;
  version: number;
}

const TrashPage: React.FC = () => {
  const { pushToast } = useToast();
  const isOnline = useOnlineStatus();
  const qc = useQueryClient();

  const [targetType, setTargetType] = useState<'task' | 'visit'>('task');
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [purgeStep, setPurgeStep] = useState<0 | 1 | 2>(0);
  const [confirmPhrase, setConfirmPhrase] = useState('');
  const [adminPassword, setAdminPassword] = useState('');

  const trashQuery = useQuery({
    queryKey: ['trash', targetType],
    queryFn: ({ signal }) =>
      apiFetch<{ items: TrashItem[]; total: number }>(`/api/v1/trash?target_type=${targetType}&limit=50`, {
        signal,
      }),
  });

  const items = trashQuery.data?.items || [];

  const restoreMut = useMutation({
    mutationFn: (item: TrashItem) =>
      apiFetch<{ ok: boolean; id: number; needs_reassignment: boolean }>(`/api/v1/trash/${item.id}/restore`, {
        method: 'POST',
        body: { target_type: item.target_type, version: item.version },
      }),
    onSuccess: (res) => {
      if (res.needs_reassignment) {
        pushToast('warning', 'رکورد بازیابی شد؛ اما به‌دلیل غیرفعال‌بودن گیرندهٔ قبلی نیازمند ارجاع مجدد است.');
      } else {
        pushToast('success', 'رکورد با موفقیت بازیابی شد.');
      }
      setSelectedIds((prev) => prev.filter((id) => id !== res.id));
      qc.invalidateQueries({ queryKey: ['trash'] });
      qc.invalidateQueries({ queryKey: ['tasks'] });
      qc.invalidateQueries({ queryKey: ['visits'] });
    },
    onError: (err) => pushToast('error', err instanceof ApiError ? err.message : 'بازیابی ناموفق بود.'),
  });

  const purgeMut = useMutation({
    mutationFn: () =>
      apiFetch<{ purged_count: number }>('/api/v1/trash/purge', {
        method: 'POST',
        body: {
          target_type: targetType,
          ids: selectedIds,
          confirm_phrase: confirmPhrase.trim(),
          password: adminPassword,
          expected_count: selectedIds.length,
        },
      }),
    onSuccess: (res) => {
      pushToast('success', `${toPersianDigits(res.purged_count)} مورد برای همیشه پاکسازی شد.`);
      setPurgeStep(0);
      setSelectedIds([]);
      setConfirmPhrase('');
      setAdminPassword('');
      qc.invalidateQueries({ queryKey: ['trash'] });
    },
    onError: (err) => pushToast('error', err instanceof ApiError ? err.message : 'حذف دائم ناموفق بود.'),
  });

  const toggleId = (id: number) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const toggleAll = () => {
    if (selectedIds.length === items.length) {
      setSelectedIds([]);
    } else {
      setSelectedIds(items.map((i) => i.id));
    }
  };

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] p-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              setTargetType('task');
              setSelectedIds([]);
            }}
            className={`rounded-lg px-3.5 py-2 text-xs font-semibold ${
              targetType === 'task'
                ? 'bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)]'
                : 'border border-[var(--hb-border)] text-[var(--hb-text)]'
            }`}
          >
            پرونده‌های پیام
          </button>
          <button
            type="button"
            onClick={() => {
              setTargetType('visit');
              setSelectedIds([]);
            }}
            className={`rounded-lg px-3.5 py-2 text-xs font-semibold ${
              targetType === 'visit'
                ? 'bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)]'
                : 'border border-[var(--hb-border)] text-[var(--hb-text)]'
            }`}
          >
            مراجعات مردمی
          </button>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-[var(--hb-muted)] tabular-nums">
            کل موارد: {toPersianDigits(trashQuery.data?.total || 0)}
          </span>
          {selectedIds.length > 0 && (
            <button
              type="button"
              disabled={!isOnline}
              onClick={() => {
                setConfirmPhrase('');
                setAdminPassword('');
                setPurgeStep(1);
              }}
              className="inline-flex items-center gap-1.5 rounded-lg bg-rose-600 hover:bg-rose-700 text-white px-3.5 py-2 text-xs font-bold disabled:opacity-50"
            >
              <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
              <span>حذف دائم انتخاب‌شده‌ها ({toPersianDigits(selectedIds.length)})</span>
            </button>
          )}
        </div>
      </div>

      {trashQuery.isLoading ? (
        <div className="h-40 rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] animate-pulse" />
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] py-12 text-center text-sm text-[var(--hb-muted)]">
          سطل زباله در این بخش خالی است.
        </div>
      ) : (
        <div className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] overflow-hidden">
          <div className="px-4 py-2.5 border-b border-[var(--hb-border)] bg-slate-50/70 dark:bg-slate-900/30 flex items-center gap-3 text-xs">
            <label className="flex items-center gap-2 cursor-pointer font-medium">
              <input
                type="checkbox"
                checked={items.length > 0 && selectedIds.length === items.length}
                onChange={toggleAll}
                className="accent-teal-600"
              />
              <span>انتخاب همه موارد نمایش‌داده‌شده</span>
            </label>
          </div>
          <div className="divide-y divide-[var(--hb-border)]">
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
                      onChange={() => toggleId(item.id)}
                      aria-label={`انتخاب ${item.title}`}
                      className="mt-1 accent-teal-600"
                    />
                    <div className="min-w-0 space-y-1">
                      <div className="text-sm font-bold text-[var(--hb-text)]">{item.title}</div>
                      <p className="text-xs text-[var(--hb-muted)] line-clamp-2">{item.summary}</p>
                      <div className="text-[11px] text-[var(--hb-muted)] tabular-nums">
                        زمان انتقال به سطل زباله: {item.deleted_at_label}
                      </div>
                    </div>
                  </div>
                  <button
                    type="button"
                    disabled={!isOnline || restoreMut.isPending}
                    onClick={() => restoreMut.mutate(item)}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--hb-border)] px-3 py-1.5 text-xs font-semibold text-[var(--hb-active-text)] hover:bg-[var(--hb-active-tint)] shrink-0 disabled:opacity-50"
                  >
                    <RotateCcw className="w-3.5 h-3.5" aria-hidden="true" />
                    <span>بازیابی</span>
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 2-Step Purge Modal */}
      <Modal
        open={purgeStep > 0}
        title={purgeStep === 1 ? 'هشدار حذف دائم (گام ۱ از ۲)' : 'تأیید امنیتی حذف دائم (گام ۲ از ۲)'}
        onClose={() => setPurgeStep(0)}
        blockBackdropClose
        maxWidthClass="max-w-md"
      >
        {purgeStep === 1 ? (
          <div className="space-y-4 text-xs">
            <div className="rounded-lg border border-rose-300 dark:border-rose-700 bg-rose-50 dark:bg-rose-950/50 p-3 flex items-start gap-2.5 text-rose-900 dark:text-rose-100">
              <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" aria-hidden="true" />
              <div className="space-y-1 leading-relaxed">
                <div className="font-bold">این عملیات غیرقابل بازگشت است!</div>
                <p>
                  تعداد <strong>{toPersianDigits(selectedIds.length)}</strong> مورد برای همیشه از پایگاه داده پاک خواهند شد.
                </p>
              </div>
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setPurgeStep(0)}
                className="rounded-lg border border-[var(--hb-border)] px-4 py-2 font-medium"
              >
                انصراف
              </button>
              <button
                type="button"
                onClick={() => setPurgeStep(2)}
                className="rounded-lg bg-rose-600 text-white px-4 py-2 font-bold"
              >
                ادامه به تأیید امنیتی
              </button>
            </div>
          </div>
        ) : (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              purgeMut.mutate();
            }}
            className="space-y-4 text-xs"
          >
            <div>
              <label className="block font-medium text-[var(--hb-muted)] mb-1">
                عبارت «حذف دائم» را دقیقاً وارد کنید:
              </label>
              <input
                type="text"
                value={confirmPhrase}
                onChange={(e) => setConfirmPhrase(e.target.value)}
                placeholder="حذف دائم"
                required
                className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-3 py-2"
              />
            </div>
            <div>
              <label className="block font-medium text-[var(--hb-muted)] mb-1">رمز عبور فعلی مدیر سامانه:</label>
              <input
                type="password"
                dir="ltr"
                value={adminPassword}
                onChange={(e) => setAdminPassword(e.target.value)}
                required
                className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-3 py-2"
              />
            </div>
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setPurgeStep(1)}
                className="rounded-lg border border-[var(--hb-border)] px-4 py-2 font-medium"
              >
                بازگشت
              </button>
              <button
                type="submit"
                disabled={!isOnline || purgeMut.isPending || confirmPhrase.trim() !== 'حذف دائم' || !adminPassword}
                className="rounded-lg bg-rose-600 text-white px-4 py-2 font-bold disabled:opacity-50"
              >
                {purgeMut.isPending ? 'در حال پاکسازی...' : 'پاکسازی نهایی'}
              </button>
            </div>
          </form>
        )}
      </Modal>
    </div>
  );
};

export default TrashPage;
