import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, FileDown, FolderPlus, Plus, Trash2, X } from 'lucide-react';
import type { AuthUser, FolderItem, VisitItem } from '../types/api';
import { ApiError, apiFetch, downloadAuthenticatedFile } from '../utils/api';
import { toPersianDigits, validateIranPhoneClient } from '../utils/persian';
import { useToast } from '../components/ToastProvider';
import { Modal } from '../components/Modal';
import { useOnlineStatus } from '../hooks/useOnlineStatus';

interface VisitsPageProps {
  user: AuthUser;
}

const VisitsPage: React.FC<VisitsPageProps> = ({ user }) => {
  const { pushToast } = useToast();
  const isOnline = useOnlineStatus();
  const qc = useQueryClient();
  const isManager = user.roles.includes('manager');

  const [view, setView] = useState<'my' | 'pending_review' | 'approved' | 'rejected'>('my');
  const [selectedFolder, setSelectedFolder] = useState<number | null>(null);
  const [newFolderName, setNewFolderName] = useState('');
  const [selectedIds, setSelectedIds] = useState<number[]>([]);

  // Form
  const [personOrOrg, setPersonOrOrg] = useState('');
  const [phone, setPhone] = useState('');
  const [requestDesc, setRequestDesc] = useState('');
  const [followupDesc, setFollowupDesc] = useState('');
  const [actionTaken, setActionTaken] = useState('');

  // Reject Modal
  const [rejectTarget, setRejectTarget] = useState<VisitItem | null>(null);
  const [rejectReason, setRejectReason] = useState('');

  const visitsQuery = useQuery({
    queryKey: ['visits', view, selectedFolder],
    queryFn: ({ signal }) => {
      const p = new URLSearchParams({ view });
      if (selectedFolder !== null) p.set('folder_id', String(selectedFolder));
      return apiFetch<{ items: VisitItem[]; total: number }>(`/api/v1/visits?${p.toString()}`, { signal });
    },
  });

  const foldersQuery = useQuery({
    queryKey: ['visit-folders'],
    queryFn: ({ signal }) => apiFetch<{ items: FolderItem[] }>('/api/v1/visits/folders', { signal }),
  });

  const createMut = useMutation({
    mutationFn: async () => {
      if (personOrOrg.trim().length < 2) throw new ApiError(422, 'نام فرد یا سازمان الزامی است.');
      const norm = validateIranPhoneClient(phone);
      if (!norm) throw new ApiError(422, 'شمارهٔ تماس ایرانی معتبر نیست.');
      if (requestDesc.trim().length < 3 || followupDesc.trim().length < 3 || actionTaken.trim().length < 3) {
        throw new ApiError(422, 'شرح درخواست، پیگیری و اقدام انجام‌شده باید حداقل ۳ کاراکتر باشد.');
      }
      return apiFetch('/api/v1/visits', {
        method: 'POST',
        body: {
          person_or_org: personOrOrg.trim(),
          phone: norm,
          request_desc: requestDesc.trim(),
          followup_desc: followupDesc.trim(),
          action_taken: actionTaken.trim(),
        },
      });
    },
    onSuccess: () => {
      setPersonOrOrg('');
      setPhone('');
      setRequestDesc('');
      setFollowupDesc('');
      setActionTaken('');
      qc.invalidateQueries({ queryKey: ['visits'] });
      pushToast('success', 'گزارش برای بررسی ارسال شد');
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const reviewMut = useMutation({
    mutationFn: ({ visit, decision, note }: { visit: VisitItem; decision: 'approved' | 'rejected'; note: string }) =>
      apiFetch(`/api/v1/visits/${visit.id}/review`, {
        method: 'POST',
        body: { decision, review_note: note, version: visit.version },
      }),
    onSuccess: () => {
      setRejectTarget(null);
      setRejectReason('');
      qc.invalidateQueries({ queryKey: ['visits'] });
      pushToast('success', 'وضعیت مراجعه ثبت شد.');
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const createFolderMut = useMutation({
    mutationFn: (name: string) => apiFetch('/api/v1/visits/folders', { method: 'POST', body: { name } }),
    onSuccess: () => {
      setNewFolderName('');
      qc.invalidateQueries({ queryKey: ['visit-folders'] });
      pushToast('success', 'فولدر مراجعات ساخته شد.');
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const assignFolderMut = useMutation({
    mutationFn: ({ visitId, folderId }: { visitId: number; folderId: number | null }) =>
      apiFetch(`/api/v1/visits/${visitId}/folder`, { method: 'PUT', body: { folder_id: folderId } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['visits'] });
      qc.invalidateQueries({ queryKey: ['visit-folders'] });
      pushToast('success', 'فولدر مراجعه به‌روزرسانی شد.');
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const bulkTrashMut = useMutation({
    mutationFn: (visitIds: number[]) =>
      apiFetch('/api/v1/visits/bulk-trash', { method: 'POST', body: { visit_ids: visitIds, reason: 'حذف گروهی مدیر' } }),
    onSuccess: () => {
      setSelectedIds([]);
      qc.invalidateQueries({ queryKey: ['visits'] });
      pushToast('success', 'موارد انتخاب‌شده به سطل زباله منتقل شد.');
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const visits = visitsQuery.data?.items ?? [];
  const folders = foldersQuery.data?.items ?? [];

  return (
    <div className="space-y-5">
      {/* Submit Visit Form */}
      <section className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] p-4 sm:p-5 space-y-3">
        <h2 className="text-sm font-bold text-[var(--hb-text)] flex items-center gap-1.5">
          <Plus className="w-4 h-4 text-[var(--hb-brand)]" />
          <span>ثبت گزارش مراجعه و پیگیری حضوری</span>
        </h2>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            createMut.mutate();
          }}
          className="space-y-3"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="vs-person" className="block text-xs font-medium text-[var(--hb-muted)] mb-1">
                نام فرد یا سازمان
              </label>
              <input
                id="vs-person"
                type="text"
                value={personOrOrg}
                onChange={(e) => setPersonOrOrg(e.target.value)}
                className="w-full h-9 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-3 text-sm"
              />
            </div>
            <div>
              <label htmlFor="vs-phone" className="block text-xs font-medium text-[var(--hb-muted)] mb-1">
                تلفن تماس
              </label>
              <input
                id="vs-phone"
                type="text"
                dir="ltr"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="0917..."
                className="w-full h-9 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-3 text-sm text-left tabular-nums"
              />
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div>
              <label htmlFor="vs-req" className="block text-xs font-medium text-[var(--hb-muted)] mb-1">
                شرح درخواست
              </label>
              <textarea
                id="vs-req"
                rows={2}
                value={requestDesc}
                onChange={(e) => setRequestDesc(e.target.value)}
                className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] p-2.5 text-xs"
              />
            </div>
            <div>
              <label htmlFor="vs-fol" className="block text-xs font-medium text-[var(--hb-muted)] mb-1">
                روند پیگیری
              </label>
              <textarea
                id="vs-fol"
                rows={2}
                value={followupDesc}
                onChange={(e) => setFollowupDesc(e.target.value)}
                className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] p-2.5 text-xs"
              />
            </div>
            <div>
              <label htmlFor="vs-act" className="block text-xs font-medium text-[var(--hb-muted)] mb-1">
                اقدام انجام‌شده
              </label>
              <textarea
                id="vs-act"
                rows={2}
                value={actionTaken}
                onChange={(e) => setActionTaken(e.target.value)}
                className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] p-2.5 text-xs"
              />
            </div>
          </div>

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={!isOnline || createMut.isPending}
              className="rounded-lg bg-[var(--hb-primary-bg)] hover:bg-[var(--hb-primary-hover)] px-4 py-2 text-xs font-bold text-[var(--hb-primary-text)] disabled:opacity-50"
            >
              {createMut.isPending ? 'در حال ارسال...' : 'ارسال برای بررسی مدیر'}
            </button>
          </div>
        </form>
      </section>

      {/* Tabs, Folders & Export */}
      <section className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] overflow-hidden">
        <div className="p-3 border-b border-[var(--hb-border)] flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            {(
              [
                { id: 'my', label: 'مراجعات من' },
                { id: 'pending_review', label: isManager ? 'در انتظار تأیید مدیر' : 'در انتظار بررسی' },
                { id: 'approved', label: 'تأییدشده' },
                { id: 'rejected', label: 'ردشده' },
              ] as const
            ).map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => {
                  setView(t.id);
                  setSelectedIds([]);
                }}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${
                  view === t.id
                    ? 'bg-[var(--hb-active-tint)] text-[var(--hb-active-text)]'
                    : 'text-[var(--hb-muted)] hover:text-[var(--hb-text)]'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <select
              aria-label="فیلتر فولدر مراجعه"
              value={selectedFolder ?? ''}
              onChange={(e) => setSelectedFolder(e.target.value ? Number(e.target.value) : null)}
              className="h-8 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-2 text-xs"
            >
              <option value="">همه فولدرها</option>
              {folders.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name} ({toPersianDigits(f.count)})
                </option>
              ))}
            </select>

            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (newFolderName.trim()) createFolderMut.mutate(newFolderName.trim());
              }}
              className="inline-flex items-center gap-1"
            >
              <input
                type="text"
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                placeholder="فولدر جدید..."
                className="w-28 h-8 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-2 text-xs"
              />
              <button
                type="submit"
                aria-label="ساخت فولدر"
                className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--hb-border)]"
              >
                <FolderPlus className="w-3.5 h-3.5" />
              </button>
            </form>

            {isManager && selectedIds.length > 0 && (
              <button
                type="button"
                onClick={() => bulkTrashMut.mutate(selectedIds)}
                className="inline-flex h-8 items-center gap-1 rounded-lg bg-rose-600 px-3 text-xs font-medium text-white"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>حذف گروهی ({toPersianDigits(selectedIds.length)})</span>
              </button>
            )}

            <button
              type="button"
              onClick={() =>
                downloadAuthenticatedFile(`/api/v1/visits/export/excel?view=${view}`, 'hormozgan-visits.xlsx')
                  .then(() => pushToast('success', 'خروجی اکسل دریافت شد.'))
                  .catch((e) => pushToast('error', e instanceof ApiError ? e.message : 'خطا'))
              }
              className="inline-flex h-8 items-center gap-1 rounded-lg border border-[var(--hb-border)] px-2.5 text-xs font-medium"
            >
              <FileDown className="w-3.5 h-3.5" />
              <span>Excel</span>
            </button>
          </div>
        </div>

        {visitsQuery.isLoading ? (
          <div className="p-4 space-y-2">
            <div className="h-16 rounded-lg bg-slate-100 dark:bg-slate-800 animate-pulse" />
          </div>
        ) : visits.length === 0 ? (
          <div className="p-10 text-center text-xs text-[var(--hb-muted)]">موردی ثبت نشده است.</div>
        ) : (
          <div className="divide-y divide-[var(--hb-border)]">
            {visits.map((v) => (
              <div key={v.id} className="p-4 space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                  <div className="flex items-center gap-2">
                    {isManager && (
                      <input
                        type="checkbox"
                        aria-label={`انتخاب مراجعه ${v.id}`}
                        checked={selectedIds.includes(v.id)}
                        onChange={(e) =>
                          setSelectedIds((prev) =>
                            e.target.checked ? [...prev, v.id] : prev.filter((i) => i !== v.id)
                          )
                        }
                        className="accent-[var(--hb-brand)]"
                      />
                    )}
                    <span className="font-bold text-[var(--hb-text)]">
                      #{toPersianDigits(v.id)} · {v.person_or_org}
                    </span>
                    <span dir="ltr" className="text-[var(--hb-muted)] tabular-nums">
                      {toPersianDigits(v.phone)}
                    </span>
                    <span className="font-semibold text-[var(--hb-active-text)]">{v.status_label}</span>
                  </div>
                  <span className="text-[var(--hb-muted)] tabular-nums">
                    {v.creator_name} · {v.created_at_label}
                  </span>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-2 text-xs text-[var(--hb-text)]">
                  <div>
                    <strong className="text-[var(--hb-muted)]">درخواست:</strong> {v.request_desc}
                  </div>
                  <div>
                    <strong className="text-[var(--hb-muted)]">پیگیری:</strong> {v.followup_desc}
                  </div>
                  <div>
                    <strong className="text-[var(--hb-muted)]">اقدام:</strong> {v.action_taken}
                  </div>
                </div>

                {v.review_note && (
                  <div className="text-xs text-amber-700 dark:text-amber-300">
                    نظر مدیر: {v.review_note}
                  </div>
                )}

                <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
                  <select
                    aria-label="فولدر مراجعه"
                    value={v.folder_id ?? ''}
                    onChange={(e) =>
                      assignFolderMut.mutate({
                        visitId: v.id,
                        folderId: e.target.value ? Number(e.target.value) : null,
                      })
                    }
                    className="h-8 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-2 text-[11px]"
                  >
                    <option value="">بدون فولدر</option>
                    {folders.map((f) => (
                      <option key={f.id} value={f.id}>
                        {f.name}
                      </option>
                    ))}
                  </select>

                  {isManager && v.status === 'pending_review' && (
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        disabled={!isOnline || reviewMut.isPending}
                        onClick={() => reviewMut.mutate({ visit: v, decision: 'approved', note: '' })}
                        className="inline-flex items-center gap-1 rounded-lg bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white"
                      >
                        <Check className="w-3.5 h-3.5" />
                        <span>تأیید</span>
                      </button>
                      <button
                        type="button"
                        disabled={!isOnline}
                        onClick={() => {
                          setRejectTarget(v);
                          setRejectReason('');
                        }}
                        className="inline-flex items-center gap-1 rounded-lg border border-rose-300 px-3 py-1.5 text-xs font-semibold text-rose-700 dark:text-rose-300"
                      >
                        <X className="w-3.5 h-3.5" />
                        <span>رد</span>
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      <Modal
        open={rejectTarget !== null}
        title="دلیل رد گزارش مراجعه"
        onClose={() => setRejectTarget(null)}
        blockBackdropClose
        maxWidthClass="max-w-md"
      >
        {rejectTarget && (
          <div className="space-y-3">
            <label htmlFor="vs-reject-reason" className="block text-xs font-semibold">
              درج دلیل رد الزامی است:
            </label>
            <input
              id="vs-reject-reason"
              type="text"
              value={rejectReason}
              onChange={(e) => setRejectReason(e.target.value)}
              className="w-full h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-3 text-sm"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setRejectTarget(null)}
                className="px-4 py-2 rounded-lg border border-[var(--hb-border)] text-xs"
              >
                انصراف
              </button>
              <button
                type="button"
                disabled={!isOnline || !rejectReason.trim() || reviewMut.isPending}
                onClick={() =>
                  reviewMut.mutate({ visit: rejectTarget, decision: 'rejected', note: rejectReason.trim() })
                }
                className="px-4 py-2 rounded-lg bg-rose-600 text-white text-xs font-bold disabled:opacity-50"
              >
                تأیید رد گزارش
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default VisitsPage;
