import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FileDown } from 'lucide-react';
import { ApiError, apiFetch, downloadAuthenticatedFile } from '../utils/api';
import { toPersianDigits } from '../utils/persian';
import { JalaliDatePicker } from '../components/JalaliDatePicker';
import { useToast } from '../components/ToastProvider';

interface SummaryResponse {
  scope: 'organization' | 'personal';
  total: number;
  pending: number;
  in_progress: number;
  success: number;
  failed: number;
  success_rate_label: string;
  avg_response_label: string;
}

interface StaffRow {
  user_id: number;
  display_name: string;
  job_title: string;
  department: string;
  assigned_count: number;
  actions_count: number;
  completed_count: number;
  pending_count: number;
}

const ReportsPage: React.FC = () => {
  const { pushToast } = useToast();
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');

  const params = new URLSearchParams();
  if (startDate) params.set('start_date', startDate);
  if (endDate) params.set('end_date', endDate);
  const qs = params.toString();

  const summaryQuery = useQuery({
    queryKey: ['reports-summary', qs],
    queryFn: ({ signal }) => apiFetch<SummaryResponse>(`/api/v1/reports/summary?${qs}`, { signal }),
  });

  const staffQuery = useQuery({
    queryKey: ['reports-staff', qs],
    queryFn: ({ signal }) => apiFetch<{ items: StaffRow[]; total: number }>(`/api/v1/reports/staff?${qs}`, { signal }),
  });

  const s = summaryQuery.data;

  const handleExport = async (fmt: 'word' | 'excel') => {
    try {
      const ext = fmt === 'word' ? 'docx' : 'xlsx';
      await downloadAuthenticatedFile(`/api/v1/reports/export/${fmt}?${qs}`, `hormozgan-report.${ext}`);
      pushToast('success', 'فایل گزارش آماده و دریافت شد.');
    } catch (e) {
      pushToast('error', e instanceof ApiError ? e.message : 'خطا در دریافت گزارش');
    }
  };

  return (
    <div className="space-y-5">
      {/* Date Filter & Export */}
      <section className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] p-4 flex flex-wrap items-end justify-between gap-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 flex-1 min-w-[260px] max-w-lg">
          <JalaliDatePicker label="از تاریخ (شمسی)" value={startDate} onChange={setStartDate} />
          <JalaliDatePicker label="تا تاریخ (شمسی)" value={endDate} onChange={setEndDate} />
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => handleExport('excel')}
            className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-[var(--hb-border)] px-3.5 text-xs font-medium hover:bg-slate-50 dark:hover:bg-slate-800"
          >
            <FileDown className="w-4 h-4" />
            <span>خروجی Excel</span>
          </button>
          <button
            type="button"
            onClick={() => handleExport('word')}
            className="inline-flex h-10 items-center gap-1.5 rounded-lg bg-[var(--hb-primary-bg)] px-3.5 text-xs font-bold text-[var(--hb-primary-text)]"
          >
            <FileDown className="w-4 h-4" />
            <span>گزارش رسمی Word</span>
          </button>
        </div>
      </section>

      {/* KPI Grid */}
      <section className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        {[
          { label: 'کل پرونده‌ها', value: s ? toPersianDigits(s.total) : '—' },
          { label: 'در انتظار', value: s ? toPersianDigits(s.pending) : '—' },
          { label: 'در حال پیگیری', value: s ? toPersianDigits(s.in_progress) : '—' },
          { label: 'موفق', value: s ? toPersianDigits(s.success) : '—' },
          { label: 'نرخ موفقیت', value: s?.success_rate_label ?? '—' },
          { label: 'میانگین زمان پاسخ', value: s?.avg_response_label ?? '—' },
        ].map((kpi) => (
          <div key={kpi.label} className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] p-3.5">
            <div className="text-[11px] text-[var(--hb-muted)]">{kpi.label}</div>
            <div className="mt-1 text-base font-bold text-[var(--hb-text)] tabular-nums">{kpi.value}</div>
          </div>
        ))}
      </section>

      {/* Staff Breakdown Table */}
      <section className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--hb-border)] flex items-center justify-between">
          <h2 className="text-sm font-bold text-[var(--hb-text)]">عملکرد تفکیکی کارشناسان</h2>
          <span className="text-xs text-[var(--hb-muted)]">
            {s?.scope === 'organization' ? 'نمای کل دفتر' : 'نمای کارکرد شخصی'}
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-right text-xs">
            <thead className="bg-[var(--hb-bg)] border-b border-[var(--hb-border)] text-[var(--hb-muted)]">
              <tr>
                <th className="py-2.5 px-3 font-semibold">نام و نام‌خانوادگی</th>
                <th className="py-2.5 px-3 font-semibold">سمت / واحد</th>
                <th className="py-2.5 px-3 font-semibold">کل ارجاع‌ها</th>
                <th className="py-2.5 px-3 font-semibold">اقدامات ثبت‌شده</th>
                <th className="py-2.5 px-3 font-semibold">موفق</th>
                <th className="py-2.5 px-3 font-semibold">در انتظار</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--hb-border)] tabular-nums">
              {(staffQuery.data?.items ?? []).map((r) => (
                <tr key={r.user_id}>
                  <td className="py-2.5 px-3 font-semibold text-[var(--hb-text)]">{r.display_name}</td>
                  <td className="py-2.5 px-3 text-[var(--hb-muted)]">
                    {r.job_title || 'همکار'} · {r.department}
                  </td>
                  <td className="py-2.5 px-3">{toPersianDigits(r.assigned_count)}</td>
                  <td className="py-2.5 px-3">{toPersianDigits(r.actions_count)}</td>
                  <td className="py-2.5 px-3 text-emerald-700 dark:text-emerald-300 font-semibold">
                    {toPersianDigits(r.completed_count)}
                  </td>
                  <td className="py-2.5 px-3 text-amber-700 dark:text-amber-300">
                    {toPersianDigits(r.pending_count)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
};

export default ReportsPage;
