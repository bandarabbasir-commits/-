import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle, Edit3, Plus, Send, Trash2, XCircle } from 'lucide-react';
import type { ActionFlagType, AuthUser, DirectoryUser, DraftItem, PriorityType, SourceType } from '../types/api';
import { ApiError, apiFetch } from '../utils/api';
import { toPersianDigits, validateIranPhoneClient } from '../utils/persian';
import { useToast } from '../components/ToastProvider';
import { Modal } from '../components/Modal';
import { StaffSelector } from '../components/StaffSelector';
import { useOnlineStatus } from '../hooks/useOnlineStatus';

interface DraftsPageProps {
  user: AuthUser;
}

const DraftsPage: React.FC<DraftsPageProps> = ({ user }) => {
  const { pushToast } = useToast();
  const isOnline = useOnlineStatus();
  const qc = useQueryClient();
  const isManager = user.roles.includes('manager');

  const [statusTab, setStatusTab] = useState<'open' | 'history'>('open');

  // Create form
  const [sourceType, setSourceType] = useState<SourceType>('sms');
  const [requesterName, setRequesterName] = useState('');
  const [requesterPhone, setRequesterPhone] = useState('');
  const [priority, setPriority] = useState<PriorityType>('normal');
  const [actionFlag, setActionFlag] = useState<ActionFlagType>('action');
  const [body, setBody] = useState('');

  // Manager Edit Modal
  const [editingDraft, setEditingDraft] = useState<DraftItem | null>(null);
  const [editBody, setEditBody] = useState('');
  const [editPriority, setEditPriority] = useState<PriorityType>('normal');
  const [editFlag, setEditFlag] = useState<ActionFlagType>('action');
  const [editManagerNote, setEditManagerNote] = useState('');
  const [editMarkReady, setEditMarkReady] = useState(true);

  // Manager Distribute Modal
  const [distDraft, setDistDraft] = useState<DraftItem | null>(null);
  const [distReceivers, setDistReceivers] = useState<number[]>([]);

  // Manager Trash Modal
  const [trashDraft, setTrashDraft] = useState<DraftItem | null>(null);
  const [trashReason, setTrashReason] = useState('');

  const draftsQuery = useQuery({
    queryKey: ['drafts', statusTab],
    queryFn: ({ signal }) =>
      apiFetch<{ items: DraftItem[]; total: number }>(`/api/v1/drafts?status=${statusTab}`, { signal }),
  });

  const dirQuery = useQuery({
    queryKey: ['directory-assignable'],
    queryFn: ({ signal }) =>
      apiFetch<{ items: DirectoryUser[] }>('/api/v1/users/directory?assignable_only=true', { signal }),
    enabled: isManager && distDraft !== null,
  });

  const createMut = useMutation({
    mutationFn: async () => {
      if (body.trim().length < 3) throw new ApiError(422, 'متن پیش‌نویس باید حداقل ۳ کاراکتر باشد.');
      let phoneClean = '';
      if (requesterPhone.trim()) {
        const norm = validateIranPhoneClient(requesterPhone);
        if (!norm) throw new ApiError(422, 'شمارهٔ تماس واردشده معتبر نیست.');
        phoneClean = norm;
      }
      return apiFetch<DraftItem>('/api/v1/drafts', {
        method: 'POST',
        body: {
          source_type: sourceType,
          requester_name: requesterName.trim(),
          requester_phone: phoneClean,
          body: body.trim(),
          priority,
          action_flag: actionFlag,
        },
      });
    },
    onSuccess: () => {
      setRequesterName('');
      setRequesterPhone('');
      setBody('');
      qc.invalidateQueries({ queryKey: ['drafts'] });
      pushToast('success', 'پیش‌نویس ثبت شد.');
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const updateMut = useMutation({
    mutationFn: (d: DraftItem) =>
      apiFetch<DraftItem>(`/api/v1/drafts/${d.id}`, {
        method: 'PATCH',
        body: {
          body: editBody.trim(),
          priority: editPriority,
          action_flag: editFlag,
          manager_note: editManagerNote.trim(),
          mark_ready: editMarkReady,
          version: d.version,
        },
      }),
    onSuccess: () => {
      setEditingDraft(null);
      qc.invalidateQueries({ queryKey: ['drafts'] });
      pushToast('success', 'پیش‌نویس ویرایش و ذخیره شد.');
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const distributeMut = useMutation({
    mutationFn: (d: DraftItem) =>
      apiFetch<{ task_id: number; trail: string }>(`/api/v1/drafts/${d.id}/distribute`, {
        method: 'POST',
        body: {
          receiver_ids: distReceivers,
          version: d.version,
          idempotency_key: `dist-${d.id}-${d.version}`,
        },
      }),
    onSuccess: (res) => {
      setDistDraft(null);
      setDistReceivers([]);
      qc.invalidateQueries({ queryKey: ['drafts'] });
      qc.invalidateQueries({ queryKey: ['tasks'] });
      pushToast('success', `پیش‌نویس به پرونده #${toPersianDigits(res.task_id)} تبدیل و ارجاع شد.`);
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const closeMut = useMutation({
    mutationFn: (d: DraftItem) =>
      apiFetch(`/api/v1/drafts/${d.id}/close`, {
        method: 'POST',
        body: { manager_note: '', version: d.version },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['drafts'] });
      pushToast('success', 'پیش‌نویس بدون تبدیل به پرونده بسته شد.');
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const trashMut = useMutation({
    mutationFn: (d: DraftItem) =>
      apiFetch(`/api/v1/drafts/${d.id}/trash`, {
        method: 'POST',
        body: { reason: trashReason.trim(), version: d.version },
      }),
    onSuccess: () => {
      setTrashDraft(null);
      setTrashReason('');
      qc.invalidateQueries({ queryKey: ['drafts'] });
      pushToast('success', 'پیش‌نویس حذف شد.');
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const drafts = draftsQuery.data?.items ?? [];

  return (
    <div className="space-y-5">
      {/* Create Draft Card */}
      <section className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] p-4 sm:p-5 space-y-3">
        <h2 className="text-sm font-bold text-[var(--hb-text)] flex items-center gap-1.5">
          <Plus className="w-4 h-4 text-[var(--hb-brand)]" />
          <span>ثبت پیش‌نویس جدید</span>
        </h2>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            createMut.mutate();
          }}
          className="space-y-3"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <div>
              <label htmlFor="dr-source" className="block text-xs font-medium text-[var(--hb-muted)] mb-1">
                منبع
              </label>
              <select
                id="dr-source"
                value={sourceType}
                onChange={(e) => setSourceType(e.target.value as SourceType)}
                className="w-full h-9 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-2.5 text-xs"
              >
                <option value="sms">پیامک</option>
                <option value="phone">تلفن</option>
                <option value="in_person">حضوری</option>
                <option value="social">شبکه اجتماعی</option>
              </select>
            </div>
            <div>
              <label htmlFor="dr-priority" className="block text-xs font-medium text-[var(--hb-muted)] mb-1">
                اولویت پیشنهادی
              </label>
              <select
                id="dr-priority"
                value={priority}
                onChange={(e) => setPriority(e.target.value as PriorityType)}
                className="w-full h-9 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-2.5 text-xs"
              >
                <option value="normal">عادی</option>
                <option value="medium">متوسط</option>
                <option value="urgent">فوری</option>
              </select>
            </div>
            <div>
              <label htmlFor="dr-name" className="block text-xs font-medium text-[var(--hb-muted)] mb-1">
                نام متقاضی (اختیاری)
              </label>
              <input
                id="dr-name"
                type="text"
                value={requesterName}
                onChange={(e) => setRequesterName(e.target.value)}
                className="w-full h-9 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-2.5 text-xs"
              />
            </div>
            <div>
              <label htmlFor="dr-phone" className="block text-xs font-medium text-[var(--hb-muted)] mb-1">
                تلفن متقاضی (اختیاری)
              </label>
              <input
                id="dr-phone"
                type="text"
                dir="ltr"
                value={requesterPhone}
                onChange={(e) => setRequesterPhone(e.target.value)}
                placeholder="0917..."
                className="w-full h-9 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-2.5 text-xs text-left tabular-nums"
              />
            </div>
          </div>

          <textarea
            rows={3}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="متن پیام یا گزارش اولیه را بنویسید..."
            className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] p-3 text-sm"
          />

          <div className="flex items-center justify-between gap-2">
            <select
              aria-label="نوع اقدام"
              value={actionFlag}
              onChange={(e) => setActionFlag(e.target.value as ActionFlagType)}
              className="h-9 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-2.5 text-xs"
            >
              <option value="action">اقدام شود</option>
              <option value="followup">پیگیری شود</option>
            </select>
            <button
              type="submit"
              disabled={!isOnline || createMut.isPending}
              className="rounded-lg bg-[var(--hb-primary-bg)] hover:bg-[var(--hb-primary-hover)] px-4 py-2 text-xs font-bold text-[var(--hb-primary-text)] disabled:opacity-50"
            >
              {createMut.isPending ? 'در حال ثبت...' : 'ارسال پیش‌نویس برای بررسی'}
            </button>
          </div>
        </form>
      </section>

      {/* Drafts List */}
      <section className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--hb-border)] flex items-center justify-between gap-3">
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => setStatusTab('open')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${
                statusTab === 'open'
                  ? 'bg-[var(--hb-active-tint)] text-[var(--hb-active-text)]'
                  : 'text-[var(--hb-muted)]'
              }`}
            >
              صف بررسی ({statusTab === 'open' ? toPersianDigits(draftsQuery.data?.total ?? 0) : '…'})
            </button>
            <button
              type="button"
              onClick={() => setStatusTab('history')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${
                statusTab === 'history'
                  ? 'bg-[var(--hb-active-tint)] text-[var(--hb-active-text)]'
                  : 'text-[var(--hb-muted)]'
              }`}
            >
              سابقهٔ توزیع و بسته‌شده
            </button>
          </div>
        </div>

        {draftsQuery.isLoading ? (
          <div className="p-4 space-y-2">
            <div className="h-16 rounded-lg bg-slate-100 dark:bg-slate-800 animate-pulse" />
            <div className="h-16 rounded-lg bg-slate-100 dark:bg-slate-800 animate-pulse" />
          </div>
        ) : drafts.length === 0 ? (
          <div className="p-10 text-center text-xs text-[var(--hb-muted)]">
            پیش‌نویسی در این بخش وجود ندارد.
          </div>
        ) : (
          <div className="divide-y divide-[var(--hb-border)]">
            {drafts.map((d) => (
              <div key={d.id} className="p-4 space-y-2">
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--hb-muted)]">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-bold tabular-nums text-[var(--hb-text)]">
                      پیش‌نویس #{toPersianDigits(d.id)}
                    </span>
                    <span>·</span>
                    <span>{d.source_label}</span>
                    <span>·</span>
                    <span>ثبت: {d.author_name}</span>
                    <span>·</span>
                    <span className="font-semibold text-[var(--hb-active-text)]">{d.status_label}</span>
                    <span>·</span>
                    <span>{d.priority_label}</span>
                  </div>
                  <span className="tabular-nums">{d.created_at_label}</span>
                </div>

                <p className="text-sm text-[var(--hb-text)] leading-relaxed">{d.body}</p>

                {isManager && d.manager_note && (
                  <div className="rounded-lg bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800/50 px-3 py-1.5 text-xs text-amber-900 dark:text-amber-200">
                    توضیح مدیر: {d.manager_note}
                  </div>
                )}

                {isManager && d.status !== 'distributed' && d.status !== 'closed' && (
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <button
                      type="button"
                      onClick={() => {
                        setEditingDraft(d);
                        setEditBody(d.body);
                        setEditPriority(d.priority);
                        setEditFlag(d.action_flag);
                        setEditManagerNote(d.manager_note || '');
                        setEditMarkReady(true);
                      }}
                      className="inline-flex items-center gap-1 rounded-lg border border-[var(--hb-border)] px-3 py-1.5 text-xs font-medium hover:bg-slate-50 dark:hover:bg-slate-800"
                    >
                      <Edit3 className="w-3.5 h-3.5" />
                      <span>ویرایش و آماده‌سازی</span>
                    </button>
                    <button
                      type="button"
                      disabled={!isOnline}
                      onClick={() => {
                        setDistDraft(d);
                        setDistReceivers([]);
                      }}
                      className="inline-flex items-center gap-1 rounded-lg bg-[var(--hb-primary-bg)] px-3 py-1.5 text-xs font-bold text-[var(--hb-primary-text)]"
                    >
                      <Send className="w-3.5 h-3.5" />
                      <span>توزیع و ارجاع</span>
                    </button>
                    <button
                      type="button"
                      disabled={!isOnline}
                      onClick={() => closeMut.mutate(d)}
                      className="inline-flex items-center gap-1 rounded-lg border border-[var(--hb-border)] px-3 py-1.5 text-xs font-medium text-[var(--hb-muted)] hover:text-[var(--hb-text)]"
                    >
                      <XCircle className="w-3.5 h-3.5" />
                      <span>بستن بدون ارجاع</span>
                    </button>
                    <button
                      type="button"
                      disabled={!isOnline}
                      onClick={() => {
                        setTrashDraft(d);
                        setTrashReason('');
                      }}
                      className="inline-flex items-center gap-1 rounded-lg border border-rose-300 dark:border-rose-700/60 px-3 py-1.5 text-xs font-medium text-rose-700 dark:text-rose-300"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      <span>حذف</span>
                    </button>
                  </div>
                )}

                {isManager && d.distributed_task_id && (
                  <div className="text-xs text-emerald-700 dark:text-emerald-300 flex items-center gap-1">
                    <CheckCircle className="w-3.5 h-3.5" />
                    <span>تبدیل‌شده به پرونده #{toPersianDigits(d.distributed_task_id)}</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Edit Draft Modal */}
      <Modal
        open={editingDraft !== null}
        title={editingDraft ? `ویرایش پیش‌نویس #${toPersianDigits(editingDraft.id)}` : ''}
        onClose={() => setEditingDraft(null)}
        blockBackdropClose
      >
        {editingDraft && (
          <div className="space-y-3">
            <textarea
              rows={4}
              value={editBody}
              onChange={(e) => setEditBody(e.target.value)}
              className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] p-3 text-sm"
            />
            <div className="grid grid-cols-2 gap-3">
              <select
                aria-label="اولویت"
                value={editPriority}
                onChange={(e) => setEditPriority(e.target.value as PriorityType)}
                className="h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-2.5 text-xs"
              >
                <option value="normal">عادی</option>
                <option value="medium">متوسط</option>
                <option value="urgent">فوری</option>
              </select>
              <select
                aria-label="نوع اقدام"
                value={editFlag}
                onChange={(e) => setEditFlag(e.target.value as ActionFlagType)}
                className="h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-2.5 text-xs"
              >
                <option value="action">اقدام شود</option>
                <option value="followup">پیگیری شود</option>
              </select>
            </div>
            <input
              type="text"
              value={editManagerNote}
              onChange={(e) => setEditManagerNote(e.target.value)}
              placeholder="توضیح مدیریتی (پنهان از نویسنده)..."
              className="w-full h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-3 text-xs"
            />
            <label className="inline-flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                checked={editMarkReady}
                onChange={(e) => setEditMarkReady(e.target.checked)}
                className="accent-[var(--hb-brand)]"
              />
              <span>علامت‌گذاری به‌عنوان «در انتظار توزیع»</span>
            </label>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setEditingDraft(null)}
                className="px-4 py-2 rounded-lg border border-[var(--hb-border)] text-xs"
              >
                انصراف
              </button>
              <button
                type="button"
                disabled={!isOnline || updateMut.isPending}
                onClick={() => updateMut.mutate(editingDraft)}
                className="px-4 py-2 rounded-lg bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)] text-xs font-bold"
              >
                ذخیرهٔ تغییرات
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* Distribute Draft Modal */}
      <Modal
        open={distDraft !== null}
        title={distDraft ? `توزیع پیش‌نویس #${toPersianDigits(distDraft.id)} و تبدیل به پرونده` : ''}
        onClose={() => setDistDraft(null)}
        blockBackdropClose
      >
        {distDraft && (
          <div className="space-y-4">
            <p className="text-xs text-[var(--hb-muted)]">
              گیرندگان پرونده (۱ تا ۲ نفر) را انتخاب کنید. پس از توزیع، پیش‌نویس قفل و به پروندهٔ رسمی تبدیل می‌شود.
            </p>
            <StaffSelector
              users={dirQuery.data?.items ?? []}
              selectedIds={distReceivers}
              onChange={setDistReceivers}
              maxSelect={2}
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setDistDraft(null)}
                className="px-4 py-2 rounded-lg border border-[var(--hb-border)] text-xs"
              >
                انصراف
              </button>
              <button
                type="button"
                disabled={!isOnline || distReceivers.length === 0 || distributeMut.isPending}
                onClick={() => distributeMut.mutate(distDraft)}
                className="px-4 py-2 rounded-lg bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)] text-xs font-bold disabled:opacity-50"
              >
                تأیید و ارجاع
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* Trash Draft Modal */}
      <Modal
        open={trashDraft !== null}
        title="حذف پیش‌نویس (با ثبت دلیل)"
        onClose={() => setTrashDraft(null)}
        blockBackdropClose
        maxWidthClass="max-w-md"
      >
        {trashDraft && (
          <div className="space-y-3">
            <label htmlFor="dr-trash-reason" className="block text-xs font-semibold">
              دلیل حذف (حداقل ۳ کاراکتر):
            </label>
            <input
              id="dr-trash-reason"
              type="text"
              value={trashReason}
              onChange={(e) => setTrashReason(e.target.value)}
              className="w-full h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-3 text-sm"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setTrashDraft(null)}
                className="px-4 py-2 rounded-lg border border-[var(--hb-border)] text-xs"
              >
                انصراف
              </button>
              <button
                type="button"
                disabled={!isOnline || trashReason.trim().length < 3 || trashMut.isPending}
                onClick={() => trashMut.mutate(trashDraft)}
                className="px-4 py-2 rounded-lg bg-rose-600 text-white text-xs font-bold disabled:opacity-50"
              >
                حذف پیش‌نویس
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default DraftsPage;
