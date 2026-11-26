import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, FileDown, Info } from 'lucide-react';
import type { AdminUserItem } from '../types/api';
import { ApiError, apiFetch, downloadAuthenticatedFile } from '../utils/api';
import { toPersianDigits } from '../utils/persian';
import { useToast } from '../components/ToastProvider';
import { Modal } from '../components/Modal';

interface LoginLogItem {
  id: number;
  user_id: number;
  username: string;
  display_name: string;
  action: 'login' | 'logout';
  action_label: string;
  ip_address: string;
  user_agent: string;
  created_at: string;
  created_at_label: string;
}

const LoginLogsPage: React.FC = () => {
  const { pushToast } = useToast();
  const [userId, setUserId] = useState<string>('');
  const [action, setAction] = useState<string>('');
  const [offset, setOffset] = useState(0);
  const [selectedLog, setSelectedLog] = useState<LoginLogItem | null>(null);
  const limit = 30;

  const usersQuery = useQuery({
    queryKey: ['admin-users-filter'],
    queryFn: ({ signal }) => apiFetch<{ items: AdminUserItem[] }>('/api/v1/users', { signal }),
  });

  const qsParams = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (userId) qsParams.set('user_id', userId);
  if (action) qsParams.set('action', action);

  const logsQuery = useQuery({
    queryKey: ['login-logs', userId, action, offset],
    queryFn: ({ signal }) =>
      apiFetch<{ items: LoginLogItem[]; total: number }>(`/api/v1/login-logs?${qsParams.toString()}`, { signal }),
  });

  const handleExport = async () => {
    try {
      const p = new URLSearchParams();
      if (userId) p.set('user_id', userId);
      if (action) p.set('action', action);
      await downloadAuthenticatedFile(
        `/api/v1/login-logs/export/excel${p.toString() ? `?${p.toString()}` : ''}`,
        'hormozgan-login-logs.xlsx'
      );
      pushToast('success', 'فایل اکسل گزارش ورود و خروج دریافت شد (بدون ستون IP/مرورگر).');
    } catch (err) {
      pushToast('error', err instanceof ApiError ? err.message : 'خطا در خروجی اکسل.');
    }
  };

  const items = logsQuery.data?.items || [];
  const total = logsQuery.data?.total || 0;

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] p-4 flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="block text-xs font-medium text-[var(--hb-muted)] mb-1">کاربر</label>
            <select
              value={userId}
              onChange={(e) => {
                setUserId(e.target.value);
                setOffset(0);
              }}
              className="rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-3 py-2 text-xs min-w-[180px]"
            >
              <option value="">همه کاربران</option>
              {(usersQuery.data?.items || []).map((u) => (
                <option key={u.id} value={String(u.id)}>
                  {u.display_name} (@{u.username})
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-[var(--hb-muted)] mb-1">نوع رویداد</label>
            <select
              value={action}
              onChange={(e) => {
                setAction(e.target.value);
                setOffset(0);
              }}
              className="rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-3 py-2 text-xs"
            >
              <option value="">ورود و خروج</option>
              <option value="login">فقط ورود</option>
              <option value="logout">فقط خروج</option>
            </select>
          </div>
        </div>

        <button
          type="button"
          onClick={handleExport}
          className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--hb-border)] px-3.5 py-2 text-xs font-semibold hover:bg-slate-100 dark:hover:bg-slate-800"
        >
          <FileDown className="w-4 h-4" aria-hidden="true" />
          <span>خروجی اکسل</span>
        </button>
      </div>

      {logsQuery.isLoading ? (
        <div className="h-48 rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] animate-pulse" />
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] py-12 text-center text-sm text-[var(--hb-muted)]">
          گزارشی ثبت نشده است.
        </div>
      ) : (
        <div className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-right text-xs">
              <thead className="bg-slate-50/70 dark:bg-slate-900/30 border-b border-[var(--hb-border)] text-[var(--hb-muted)]">
                <tr>
                  <th className="py-3 px-4 font-semibold">کاربر</th>
                  <th className="py-3 px-4 font-semibold">عملیات</th>
                  <th className="py-3 px-4 font-semibold">زمان شمسی</th>
                  <th className="py-3 px-4 font-semibold text-end">جزئیات فنی</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--hb-border)]">
                {items.map((log) => (
                  <tr key={log.id} className="hover:bg-slate-50/60 dark:hover:bg-slate-800/30">
                    <td className="py-2.5 px-4">
                      <div className="font-semibold text-[var(--hb-text)]">{log.display_name}</div>
                      <div dir="ltr" className="text-[11px] text-[var(--hb-muted)] font-mono inline-block">
                        @{log.username}
                      </div>
                    </td>
                    <td className="py-2.5 px-4">
                      <span
                        className={
                          log.action === 'login'
                            ? 'text-emerald-700 dark:text-emerald-300 font-semibold'
                            : 'text-[var(--hb-muted)] font-medium'
                        }
                      >
                        {log.action_label}
                      </span>
                    </td>
                    <td className="py-2.5 px-4 tabular-nums">{log.created_at_label}</td>
                    <td className="py-2.5 px-4 text-end">
                      <button
                        type="button"
                        onClick={() => setSelectedLog(log)}
                        className="inline-flex items-center gap-1 rounded-lg border border-[var(--hb-border)] px-2.5 py-1 text-[11px] font-medium hover:bg-slate-100 dark:hover:bg-slate-800"
                      >
                        <Info className="w-3.5 h-3.5" aria-hidden="true" />
                        <span>IP و مرورگر</span>
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="px-4 py-3 border-t border-[var(--hb-border)] flex items-center justify-between text-xs text-[var(--hb-muted)]">
            <span className="tabular-nums">
              نمایش {toPersianDigits(offset + 1)} تا {toPersianDigits(Math.min(offset + limit, total))} از{' '}
              {toPersianDigits(total)}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={offset === 0}
                onClick={() => setOffset((o) => Math.max(0, o - limit))}
                className="inline-flex items-center gap-1 rounded-lg border border-[var(--hb-border)] px-2.5 py-1 disabled:opacity-40"
              >
                <ChevronRight className="w-3.5 h-3.5" />
                <span>قبلی</span>
              </button>
              <button
                type="button"
                disabled={offset + limit >= total}
                onClick={() => setOffset((o) => o + limit)}
                className="inline-flex items-center gap-1 rounded-lg border border-[var(--hb-border)] px-2.5 py-1 disabled:opacity-40"
              >
                <span>بعدی</span>
                <ChevronLeft className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>
        </div>
      )}

      <Modal
        open={!!selectedLog}
        title="جزئیات نشست ورود و خروج"
        onClose={() => setSelectedLog(null)}
        maxWidthClass="max-w-md"
      >
        {selectedLog && (
          <dl className="space-y-2.5 text-xs">
            <div className="flex justify-between gap-2 border-b border-[var(--hb-border)] pb-2">
              <dt className="text-[var(--hb-muted)]">کاربر:</dt>
              <dd className="font-bold">
                {selectedLog.display_name} (@{selectedLog.username})
              </dd>
            </div>
            <div className="flex justify-between gap-2 border-b border-[var(--hb-border)] pb-2">
              <dt className="text-[var(--hb-muted)]">رویداد و زمان:</dt>
              <dd className="tabular-nums">
                {selectedLog.action_label} — {selectedLog.created_at_label}
              </dd>
            </div>
            <div className="flex justify-between gap-2 border-b border-[var(--hb-border)] pb-2">
              <dt className="text-[var(--hb-muted)]">نشانی IP:</dt>
              <dd dir="ltr" className="font-mono">
                {selectedLog.ip_address || 'ثبت‌نشده'}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--hb-muted)] mb-1">شناسه مرورگر (User-Agent):</dt>
              <dd dir="ltr" className="rounded-lg bg-slate-100 dark:bg-slate-900 p-2 font-mono text-[11px] break-all">
                {selectedLog.user_agent || 'ثبت‌نشده'}
              </dd>
            </div>
          </dl>
        )}
      </Modal>
    </div>
  );
};

export default LoginLogsPage;
