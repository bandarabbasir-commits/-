import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, CheckCircle2, DatabaseBackup, FileDown, Upload } from 'lucide-react';
import { ApiError, apiFetch, downloadAuthenticatedFile } from '../utils/api';
import { toPersianDigits } from '../utils/persian';
import { useToast } from '../components/ToastProvider';
import { Modal } from '../components/Modal';
import { useOnlineStatus } from '../hooks/useOnlineStatus';

interface DryRunResult {
  valid: boolean;
  schema_version: string;
  exported_at_label: string;
  counts: {
    incoming_users: number;
    incoming_tasks: number;
    new_tasks_to_insert: number;
    existing_tasks_skipped: number;
    incoming_visits: number;
    new_visits_to_insert: number;
  };
  fk_errors: string[];
}

const BackupsPage: React.FC = () => {
  const { pushToast } = useToast();
  const isOnline = useOnlineStatus();
  const qc = useQueryClient();

  const [parsedPayload, setParsedPayload] = useState<Record<string, unknown> | null>(null);
  const [fileName, setFileName] = useState('');
  const [dryRunResult, setDryRunResult] = useState<DryRunResult | null>(null);
  const [restoreModalOpen, setRestoreModalOpen] = useState(false);
  const [confirmPhrase, setConfirmPhrase] = useState('');
  const [adminPassword, setAdminPassword] = useState('');

  const handleExport = async () => {
    try {
      await downloadAuthenticatedFile('/api/v1/backups/export', 'hormozgan-backup-v2.json');
      pushToast('success', 'فایل پشتیبان JSON با موفقیت دانلود شد.');
    } catch (err) {
      pushToast('error', err instanceof ApiError ? err.message : 'خطا در تهیه نسخهٔ پشتیبان.');
    }
  };

  const dryRunMut = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      apiFetch<DryRunResult>('/api/v1/backups/dry-run', {
        method: 'POST',
        body: payload,
      }),
    onSuccess: (res) => {
      setDryRunResult(res);
      pushToast(
        res.valid ? 'success' : 'error',
        res.valid ? 'بررسی آزمایشی (Dry-Run) با موفقیت انجام شد.' : 'در فایل پشتیبان خطاهای ارجاع یافت شد.'
      );
    },
    onError: (err) => {
      setDryRunResult(null);
      pushToast('error', err instanceof ApiError ? err.message : 'ساختار فایل پشتیبان معتبر نیست.');
    },
  });

  const restoreMut = useMutation({
    mutationFn: () =>
      apiFetch<{ ok: boolean; inserted_tasks: number; inserted_visits: number }>('/api/v1/backups/restore', {
        method: 'POST',
        body: {
          backup_payload: parsedPayload,
          confirm_phrase: confirmPhrase.trim(),
          password: adminPassword,
        },
      }),
    onSuccess: (res) => {
      pushToast(
        'success',
        `بازیابی انجام شد: ${toPersianDigits(res.inserted_tasks)} پرونده پیام و ${toPersianDigits(
          res.inserted_visits
        )} مراجعه جدید درج گردید.`
      );
      setRestoreModalOpen(false);
      setConfirmPhrase('');
      setAdminPassword('');
      qc.invalidateQueries();
    },
    onError: (err) => pushToast('error', err instanceof ApiError ? err.message : 'بازیابی پشتیبان ناموفق بود.'),
  });

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setFileName(file.name);
    setDryRunResult(null);
    try {
      const text = await file.text();
      const obj = JSON.parse(text) as Record<string, unknown>;
      setParsedPayload(obj);
      dryRunMut.mutate(obj);
    } catch {
      setParsedPayload(null);
      pushToast('error', 'فایل انتخاب‌شده قالب JSON معتبر ندارد.');
    }
  };

  return (
    <div className="space-y-5">
      <div className="rounded-xl border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950/50 p-4 flex items-start gap-3 text-xs text-amber-900 dark:text-amber-100 leading-relaxed">
        <AlertTriangle className="w-5 h-5 shrink-0 mt-0.5" aria-hidden="true" />
        <div>
          <div className="font-bold mb-1">تذکر محرمانگی و نگهداری امن نسخه‌های پشتیبان</div>
          <p>
            فایل پشتیبان JSON حاوی متن پیام‌ها و مراجعات مردمی است (بدون هش رمز عبور، توکن یا نشست‌های فعال). لطفاً
            فایل‌های دانلودشده را تنها در حافظهٔ رمزنگاری‌شدهٔ سازمانی نگهداری کنید.
          </p>
        </div>
      </div>

      <section className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="space-y-1">
          <div className="flex items-center gap-2 text-sm font-bold text-[var(--hb-text)]">
            <DatabaseBackup className="w-4 h-4 text-[var(--hb-brand)]" aria-hidden="true" />
            <span>دریافت نسخهٔ پشتیبان استاندارد (JSON v2)</span>
          </div>
          <p className="text-xs text-[var(--hb-muted)]">
            شامل کاربران، پرونده‌های پیام، پیش‌نویس‌ها، مراجعات مردمی و امتیازات بدون اطلاعات محرمانهٔ امنیتی.
          </p>
        </div>
        <button
          type="button"
          onClick={handleExport}
          className="inline-flex items-center gap-2 rounded-lg bg-[var(--hb-primary-bg)] hover:bg-[var(--hb-primary-hover)] text-[var(--hb-primary-text)] px-4 py-2.5 text-xs font-bold shrink-0"
        >
          <FileDown className="w-4 h-4" aria-hidden="true" />
          <span>دانلود بکاپ کامل</span>
        </button>
      </section>

      <section className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] p-5 space-y-4">
        <div className="space-y-1">
          <h2 className="text-sm font-bold text-[var(--hb-text)]">بررسی آزمایشی (Dry-Run) و بازیابی افزایشی</h2>
          <p className="text-xs text-[var(--hb-muted)]">
            ابتدا فایل JSON بکاپ را بارگذاری کنید تا بدون اعمال هیچ تغییری در پایگاه داده، گزارش تطبیق و موارد جدید
            نمایش داده شود.
          </p>
        </div>

        <label className="flex items-center justify-center gap-2 rounded-xl border-2 border-dashed border-[var(--hb-border)] p-6 text-xs font-medium text-[var(--hb-text)] cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/30">
          <Upload className="w-4 h-4 text-[var(--hb-brand)]" aria-hidden="true" />
          <span>{fileName ? `فایل انتخاب‌شده: ${fileName}` : 'انتخاب فایل بکاپ JSON برای آزمایش Dry-Run'}</span>
          <input type="file" accept=".json,application/json" onChange={handleFileSelect} className="sr-only" />
        </label>

        {dryRunMut.isPending && (
          <div className="text-xs text-[var(--hb-muted)]">در حال اعتبارسنجی ساختار و ارجاعات فایل...</div>
        )}

        {dryRunResult && (
          <div className="rounded-xl border border-[var(--hb-border)] p-4 space-y-3 bg-slate-50/60 dark:bg-slate-900/30">
            <div className="flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center gap-2 text-xs font-bold">
                {dryRunResult.valid ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-600" />
                ) : (
                  <AlertTriangle className="w-4 h-4 text-rose-600" />
                )}
                <span>
                  {dryRunResult.valid ? 'ساختار و ارجاعات بکاپ معتبر است' : 'خطا در اعتبارسنجی فایل بکاپ'}
                </span>
              </div>
              <span className="text-[11px] text-[var(--hb-muted)] tabular-nums">
                نسخه {dryRunResult.schema_version} · تاریخ بکاپ: {dryRunResult.exported_at_label}
              </span>
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5 text-xs">
              <div className="rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] p-2.5">
                <div className="text-[var(--hb-muted)]">پیام‌های فایل</div>
                <div className="font-bold tabular-nums mt-0.5">
                  {toPersianDigits(dryRunResult.counts.incoming_tasks)}
                </div>
              </div>
              <div className="rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] p-2.5">
                <div className="text-[var(--hb-muted)]">پیام‌های جدید قابل درج</div>
                <div className="font-bold text-emerald-700 dark:text-emerald-300 tabular-nums mt-0.5">
                  {toPersianDigits(dryRunResult.counts.new_tasks_to_insert)}
                </div>
              </div>
              <div className="rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] p-2.5">
                <div className="text-[var(--hb-muted)]">تکراری (رد می‌شوند)</div>
                <div className="font-bold tabular-nums mt-0.5">
                  {toPersianDigits(dryRunResult.counts.existing_tasks_skipped)}
                </div>
              </div>
              <div className="rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] p-2.5">
                <div className="text-[var(--hb-muted)]">مراجعات فایل</div>
                <div className="font-bold tabular-nums mt-0.5">
                  {toPersianDigits(dryRunResult.counts.incoming_visits)}
                </div>
              </div>
              <div className="rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] p-2.5">
                <div className="text-[var(--hb-muted)]">مراجعات جدید قابل درج</div>
                <div className="font-bold text-emerald-700 dark:text-emerald-300 tabular-nums mt-0.5">
                  {toPersianDigits(dryRunResult.counts.new_visits_to_insert)}
                </div>
              </div>
            </div>

            {dryRunResult.fk_errors.length > 0 && (
              <ul className="list-disc list-inside text-xs text-rose-700 dark:text-rose-300 space-y-1">
                {dryRunResult.fk_errors.map((err, i) => (
                  <li key={i}>{err}</li>
                ))}
              </ul>
            )}

            {dryRunResult.valid && parsedPayload && (
              <div className="flex justify-end pt-1">
                <button
                  type="button"
                  disabled={!isOnline}
                  onClick={() => {
                    setConfirmPhrase('');
                    setAdminPassword('');
                    setRestoreModalOpen(true);
                  }}
                  className="rounded-lg bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)] px-4 py-2 text-xs font-bold disabled:opacity-50"
                >
                  تأیید و اجرای بازیابی
                </button>
              </div>
            )}
          </div>
        )}
      </section>

      <Modal
        open={restoreModalOpen}
        title="تأیید نهایی بازیابی پشتیبان"
        onClose={() => setRestoreModalOpen(false)}
        blockBackdropClose
        maxWidthClass="max-w-md"
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            restoreMut.mutate();
          }}
          className="space-y-4 text-xs"
        >
          <p className="text-[var(--hb-muted)] leading-relaxed">
            رکوردهای جدید در یک تراکنش اتمیک به پایگاه داده اضافه می‌شوند و شناسه‌های موجود تغییر نمی‌کنند.
          </p>
          <div>
            <label className="block font-medium text-[var(--hb-muted)] mb-1">
              عبارت «تأیید بازیابی» را دقیقاً وارد کنید:
            </label>
            <input
              type="text"
              value={confirmPhrase}
              onChange={(e) => setConfirmPhrase(e.target.value)}
              placeholder="تأیید بازیابی"
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
              onClick={() => setRestoreModalOpen(false)}
              className="rounded-lg border border-[var(--hb-border)] px-4 py-2 font-medium"
            >
              انصراف
            </button>
            <button
              type="submit"
              disabled={!isOnline || restoreMut.isPending || confirmPhrase.trim() !== 'تأیید بازیابی' || !adminPassword}
              className="rounded-lg bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)] px-4 py-2 font-bold disabled:opacity-50"
            >
              {restoreMut.isPending ? 'در حال بازیابی...' : 'اجرای بازیابی'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
};

export default BackupsPage;
