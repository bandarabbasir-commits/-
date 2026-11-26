import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, RotateCcw, Send } from 'lucide-react';
import type { ActionFlagType, DirectoryUser, PriorityType, SourceType } from '../types/api';
import { ApiError, apiFetch } from '../utils/api';
import { toPersianDigits, validateIranPhoneClient } from '../utils/persian';
import { useToast } from '../components/ToastProvider';
import { StaffSelector } from '../components/StaffSelector';
import { useOnlineStatus } from '../hooks/useOnlineStatus';

interface DirectCreatePageProps {
  onCreated: () => void;
}

interface FormErrors {
  requesterName?: string;
  requesterPhone?: string;
  body?: string;
  receivers?: string;
}

const DirectCreatePage: React.FC<DirectCreatePageProps> = ({ onCreated }) => {
  const { pushToast } = useToast();
  const isOnline = useOnlineStatus();
  const qc = useQueryClient();

  const [sourceType, setSourceType] = useState<SourceType>('sms');
  const [requesterName, setRequesterName] = useState('');
  const [requesterPhone, setRequesterPhone] = useState('');
  const [priority, setPriority] = useState<PriorityType>('normal');
  const [actionFlag, setActionFlag] = useState<ActionFlagType>('action');
  const [body, setBody] = useState('');
  const [managerNote, setManagerNote] = useState('');
  const [receiverIds, setReceiverIds] = useState<number[]>([]);
  const [errors, setErrors] = useState<FormErrors>({});
  const [createdTaskId, setCreatedTaskId] = useState<number | null>(null);

  const dirQuery = useQuery({
    queryKey: ['directory-assignable'],
    queryFn: ({ signal }) =>
      apiFetch<{ items: DirectoryUser[] }>('/api/v1/users/directory?assignable_only=true', { signal }),
  });

  const handleClearForm = () => {
    setSourceType('sms');
    setRequesterName('');
    setRequesterPhone('');
    setPriority('normal');
    setActionFlag('action');
    setBody('');
    setManagerNote('');
    setReceiverIds([]);
    setErrors({});
    setCreatedTaskId(null);
  };

  const validateFields = (): { valid: boolean; phoneNorm: string | null } => {
    const nextErrors: FormErrors = {};
    if (requesterName.trim().length < 2) {
      nextErrors.requesterName = 'نام متقاضی باید حداقل ۲ کاراکتر باشد.';
    }
    const phoneNorm = validateIranPhoneClient(requesterPhone);
    if (!phoneNorm) {
      nextErrors.requesterPhone = 'شمارهٔ تماس ایرانی معتبر نیست (مثال: ۰۹۱۷۰۰۰۰۰۰۰).';
    }
    if (body.trim().length < 5) {
      nextErrors.body = 'شرح درخواست باید حداقل ۵ کاراکتر باشد.';
    }
    if (receiverIds.length < 1 || receiverIds.length > 2) {
      nextErrors.receivers = 'انتخاب ۱ یا ۲ گیرنده الزامی است.';
    }
    setErrors(nextErrors);
    return { valid: Object.keys(nextErrors).length === 0, phoneNorm };
  };

  const createMut = useMutation({
    mutationFn: async (phoneNorm: string) => {
      return apiFetch<{ task_id: number }>('/api/v1/tasks/direct', {
        method: 'POST',
        body: {
          source_type: sourceType,
          requester_name: requesterName.trim(),
          requester_phone: phoneNorm,
          body: body.trim(),
          priority,
          action_flag: actionFlag,
          manager_note: managerNote.trim(),
          receiver_ids: receiverIds,
          idempotency_key: `direct-ui-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        },
      });
    },
    onSuccess: (res) => {
      setRequesterName('');
      setRequesterPhone('');
      setBody('');
      setManagerNote('');
      setReceiverIds([]);
      setErrors({});
      setCreatedTaskId(res.task_id);
      qc.invalidateQueries({ queryKey: ['tasks'] });
      pushToast('success', `پرونده #${toPersianDigits(res.task_id)} ثبت و ارجاع شد.`);
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const { valid, phoneNorm } = validateFields();
    if (!valid || !phoneNorm) return;
    createMut.mutate(phoneNorm);
  };

  return (
    <div className="max-w-3xl mx-auto space-y-4">
      {createdTaskId !== null && (
        <div
          role="status"
          className="rounded-xl border border-emerald-300 dark:border-emerald-700/60 bg-emerald-50 dark:bg-emerald-950/50 p-4 flex flex-wrap items-center justify-between gap-3"
        >
          <div className="flex items-center gap-2.5 text-sm font-semibold text-emerald-900 dark:text-emerald-200">
            <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0" />
            <span>پرونده #{toPersianDigits(createdTaskId)} با موفقیت ثبت و به گیرندگان ارجاع شد.</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onCreated}
              className="rounded-lg bg-[var(--hb-primary-bg)] hover:bg-[var(--hb-primary-hover)] px-3.5 py-2 text-xs font-bold text-[var(--hb-primary-text)]"
            >
              مشاهده در کارتابل
            </button>
            <button
              type="button"
              onClick={() => setCreatedTaskId(null)}
              className="rounded-lg border border-emerald-400/60 px-3 py-2 text-xs font-medium text-emerald-900 dark:text-emerald-200"
            >
              ثبت پیام جدید
            </button>
          </div>
        </div>
      )}

      <div className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] p-5 sm:p-6 space-y-5">
        <div>
          <h2 className="text-base font-bold text-[var(--hb-text)]">ثبت و ارجاع مستقیم پیام مردمی</h2>
          <p className="mt-1 text-xs text-[var(--hb-muted)]">
            پروندهٔ جدید بدون گذر از صف پیش‌نویس مستقیماً برای ۱ یا ۲ همکار ارجاع می‌شود.
          </p>
        </div>

        <form onSubmit={handleSubmit} noValidate className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div>
              <label htmlFor="dc-source" className="block text-xs font-semibold mb-1">
                منبع دریافت
              </label>
              <select
                id="dc-source"
                value={sourceType}
                onChange={(e) => setSourceType(e.target.value as SourceType)}
                className="w-full h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-3 text-sm"
              >
                <option value="sms">پیامک</option>
                <option value="phone">تماس تلفنی</option>
                <option value="in_person">مراجعهٔ حضوری</option>
                <option value="social">شبکهٔ اجتماعی</option>
              </select>
            </div>
            <div>
              <label htmlFor="dc-priority" className="block text-xs font-semibold mb-1">
                اولویت
              </label>
              <select
                id="dc-priority"
                value={priority}
                onChange={(e) => setPriority(e.target.value as PriorityType)}
                className="w-full h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-3 text-sm"
              >
                <option value="normal">عادی</option>
                <option value="medium">متوسط</option>
                <option value="urgent">فوری</option>
              </select>
            </div>
            <div>
              <label htmlFor="dc-flag" className="block text-xs font-semibold mb-1">
                نوع دستور
              </label>
              <select
                id="dc-flag"
                value={actionFlag}
                onChange={(e) => setActionFlag(e.target.value as ActionFlagType)}
                className="w-full h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-3 text-sm"
              >
                <option value="action">اقدام شود</option>
                <option value="followup">پیگیری شود</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label htmlFor="dc-name" className="block text-xs font-semibold mb-1">
                نام و نام‌خانوادگی متقاضی
              </label>
              <input
                id="dc-name"
                type="text"
                value={requesterName}
                onChange={(e) => {
                  setRequesterName(e.target.value);
                  if (errors.requesterName) setErrors((prev) => ({ ...prev, requesterName: undefined }));
                }}
                placeholder="مثال: حسین مرادی"
                className={`w-full h-10 rounded-lg border bg-[var(--hb-bg)] px-3 text-sm ${
                  errors.requesterName ? 'border-rose-500' : 'border-[var(--hb-border)]'
                }`}
              />
              {errors.requesterName && (
                <p className="mt-1 text-[11px] text-rose-600 dark:text-rose-400">{errors.requesterName}</p>
              )}
            </div>
            <div>
              <label htmlFor="dc-phone" className="block text-xs font-semibold mb-1">
                شمارهٔ تماس متقاضی
              </label>
              <input
                id="dc-phone"
                type="text"
                dir="ltr"
                value={requesterPhone}
                onChange={(e) => {
                  setRequesterPhone(e.target.value);
                  if (errors.requesterPhone) setErrors((prev) => ({ ...prev, requesterPhone: undefined }));
                }}
                placeholder="09170000000"
                className={`w-full h-10 rounded-lg border bg-[var(--hb-bg)] px-3 text-sm text-left tabular-nums ${
                  errors.requesterPhone ? 'border-rose-500' : 'border-[var(--hb-border)]'
                }`}
              />
              {errors.requesterPhone && (
                <p className="mt-1 text-[11px] text-rose-600 dark:text-rose-400">{errors.requesterPhone}</p>
              )}
            </div>
          </div>

          <div>
            <label htmlFor="dc-body" className="block text-xs font-semibold mb-1">
              متن کامل درخواست
            </label>
            <textarea
              id="dc-body"
              rows={4}
              value={body}
              onChange={(e) => {
                setBody(e.target.value);
                if (errors.body) setErrors((prev) => ({ ...prev, body: undefined }));
              }}
              placeholder="متن پیام یا درخواست مردمی را بنویسید..."
              className={`w-full rounded-lg border bg-[var(--hb-bg)] p-3 text-sm ${
                errors.body ? 'border-rose-500' : 'border-[var(--hb-border)]'
              }`}
            />
            {errors.body && <p className="mt-1 text-[11px] text-rose-600 dark:text-rose-400">{errors.body}</p>}
          </div>

          <div>
            <label htmlFor="dc-mnote" className="block text-xs font-semibold mb-1">
              توضیح مدیریتی (اختیاری — فقط برای مدیران قابل مشاهده)
            </label>
            <input
              id="dc-mnote"
              type="text"
              value={managerNote}
              onChange={(e) => setManagerNote(e.target.value)}
              placeholder="یادداشت داخلی برای پیگیری..."
              className="w-full h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-3 text-sm"
            />
          </div>

          <div>
            <p className="text-xs font-semibold mb-1.5">انتخاب گیرنده یا گیرندگان (۱ تا ۲ نفر):</p>
            <StaffSelector
              users={dirQuery.data?.items ?? []}
              selectedIds={receiverIds}
              onChange={(ids) => {
                setReceiverIds(ids);
                if (errors.receivers) setErrors((prev) => ({ ...prev, receivers: undefined }));
              }}
              maxSelect={2}
            />
            {errors.receivers && (
              <p className="mt-1 text-[11px] text-rose-600 dark:text-rose-400">{errors.receivers}</p>
            )}
          </div>

          <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
            <button
              type="button"
              onClick={handleClearForm}
              className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--hb-border)] px-4 py-2.5 text-xs font-medium text-[var(--hb-muted)] hover:text-[var(--hb-text)] hover:bg-slate-50 dark:hover:bg-slate-800"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>پاک‌کردن فرم</span>
            </button>

            <button
              type="submit"
              disabled={!isOnline || createMut.isPending}
              className="inline-flex items-center gap-2 rounded-lg bg-[var(--hb-primary-bg)] hover:bg-[var(--hb-primary-hover)] px-5 py-2.5 text-sm font-bold text-[var(--hb-primary-text)] disabled:opacity-50"
            >
              <Send className="w-4 h-4" />
              <span>{createMut.isPending ? 'در حال ثبت...' : 'ثبت و ارجاع پرونده'}</span>
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default DirectCreatePage;
