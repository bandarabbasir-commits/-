import React, { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Award, Check, ChevronDown, ChevronUp, Edit3, Plus, Star, Trash2, X } from 'lucide-react';
import type { AuthUser, DirectoryUser, LeaderboardEntry } from '../types/api';
import { ApiError, apiFetch } from '../utils/api';
import { toPersianDigits } from '../utils/persian';
import { useToast } from '../components/ToastProvider';
import { useOnlineStatus } from '../hooks/useOnlineStatus';

interface RatingsPageProps {
  user: AuthUser;
}

const RatingsPage: React.FC<RatingsPageProps> = ({ user }) => {
  const { pushToast } = useToast();
  const isOnline = useOnlineStatus();
  const qc = useQueryClient();
  const isManager = user.roles.includes('manager');

  const [expandedUserId, setExpandedUserId] = useState<number | null>(null);
  const [targetUserId, setTargetUserId] = useState<number | ''>('');
  const [score, setScore] = useState<number>(5);
  const [reason, setReason] = useState('');
  const [formError, setFormError] = useState('');

  const [editingId, setEditingId] = useState<number | null>(null);
  const [editScore, setEditScore] = useState<number>(5);
  const [editReason, setEditReason] = useState('');

  const boardQuery = useQuery({
    queryKey: ['leaderboard'],
    queryFn: ({ signal }) => apiFetch<{ items: LeaderboardEntry[] }>('/api/v1/ratings/leaderboard', { signal }),
  });

  const dirQuery = useQuery({
    queryKey: ['directory-all'],
    queryFn: ({ signal }) => apiFetch<{ items: DirectoryUser[] }>('/api/v1/users/directory', { signal }),
    enabled: isManager,
  });

  const createMut = useMutation({
    mutationFn: () => {
      if (!targetUserId) throw new ApiError(422, 'انتخاب همکار الزامی است.');
      if (reason.trim().length < 2) throw new ApiError(422, 'توضیح یا علت امتیاز الزامی است.');
      return apiFetch('/api/v1/ratings', {
        method: 'POST',
        body: { user_id: Number(targetUserId), score, reason: reason.trim() },
      });
    },
    onSuccess: () => {
      setReason('');
      setFormError('');
      qc.invalidateQueries({ queryKey: ['leaderboard'] });
      pushToast('success', 'امتیاز تشویقی ثبت شد.');
    },
    onError: (e: ApiError) => {
      setFormError(e.message);
      pushToast('error', e.message);
    },
  });

  const updateMut = useMutation({
    mutationFn: ({ id, nextScore, nextReason }: { id: number; nextScore: number; nextReason: string }) => {
      if (nextReason.trim().length < 2) throw new ApiError(422, 'توضیح یا علت امتیاز باید حداقل ۲ کاراکتر باشد.');
      return apiFetch(`/api/v1/ratings/${id}`, {
        method: 'PATCH',
        body: { score: nextScore, reason: nextReason.trim() },
      });
    },
    onSuccess: () => {
      setEditingId(null);
      qc.invalidateQueries({ queryKey: ['leaderboard'] });
      pushToast('success', 'امتیاز دستی ویرایش شد.');
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const deleteMut = useMutation({
    mutationFn: (ratingId: number) => apiFetch(`/api/v1/ratings/${ratingId}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['leaderboard'] });
      pushToast('success', 'امتیاز دستی حذف شد.');
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const items = boardQuery.data?.items ?? [];

  return (
    <div className="space-y-5">
      {isManager && (
        <section className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] p-4 sm:p-5 space-y-3">
          <h2 className="text-sm font-bold text-[var(--hb-text)] flex items-center gap-1.5">
            <Plus className="w-4 h-4 text-[var(--hb-brand)]" />
            <span>ثبت امتیاز دستی مدیر</span>
          </h2>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setFormError('');
              createMut.mutate();
            }}
            className="grid grid-cols-1 sm:grid-cols-12 gap-3 items-end"
          >
            <div className="sm:col-span-4">
              <label htmlFor="rt-user" className="block text-xs font-medium text-[var(--hb-muted)] mb-1">
                همکار
              </label>
              <select
                id="rt-user"
                value={targetUserId}
                onChange={(e) => setTargetUserId(e.target.value ? Number(e.target.value) : '')}
                className="w-full h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-2.5 text-xs"
              >
                <option value="">انتخاب کنید...</option>
                {(dirQuery.data?.items ?? []).map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.display_name} ({u.department})
                  </option>
                ))}
              </select>
            </div>
            <div className="sm:col-span-2">
              <label htmlFor="rt-score" className="block text-xs font-medium text-[var(--hb-muted)] mb-1">
                امتیاز (۱ تا ۵)
              </label>
              <select
                id="rt-score"
                value={score}
                onChange={(e) => setScore(Number(e.target.value))}
                className="w-full h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-2.5 text-xs tabular-nums"
              >
                {[5, 4, 3, 2, 1].map((s) => (
                  <option key={s} value={s}>
                    {toPersianDigits(s)} ستاره
                  </option>
                ))}
              </select>
            </div>
            <div className="sm:col-span-4">
              <label htmlFor="rt-reason" className="block text-xs font-medium text-[var(--hb-muted)] mb-1">
                بابت
              </label>
              <input
                id="rt-reason"
                type="text"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
                placeholder="مثال: پاسخگویی دقیق و سریع"
                className="w-full h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-3 text-xs"
              />
            </div>
            <div className="sm:col-span-2">
              <button
                type="submit"
                disabled={!isOnline || createMut.isPending}
                className="w-full h-10 rounded-lg bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)] text-xs font-bold disabled:opacity-50"
              >
                ثبت امتیاز
              </button>
            </div>
          </form>
          {formError && <p className="text-xs text-rose-600 dark:text-rose-400">{formError}</p>}
        </section>
      )}

      <section className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--hb-border)] flex items-center justify-between">
          <h2 className="text-sm font-bold flex items-center gap-2">
            <Award className="w-4 h-4 text-[var(--hb-brand)]" />
            <span>رتبه‌بندی و تابلوی افتخارات پرسنل</span>
          </h2>
          <span className="text-xs text-[var(--hb-muted)]">ترکیب امتیازات خودکار و ارزیابی مدیر</span>
        </div>

        {boardQuery.isLoading ? (
          <div className="p-4 space-y-2">
            <div className="h-14 rounded-lg bg-slate-100 dark:bg-slate-800 animate-pulse" />
          </div>
        ) : items.length === 0 ? (
          <div className="p-10 text-center text-xs text-[var(--hb-muted)]">هنوز امتیازی ثبت نشده است.</div>
        ) : (
          <div className="divide-y divide-[var(--hb-border)]">
            {items.map((entry) => {
              const isExpanded = expandedUserId === entry.user_id;
              const medalLabel =
                entry.medal === 'gold'
                  ? 'رتبهٔ اول (طلا)'
                  : entry.medal === 'silver'
                  ? 'رتبهٔ دوم (نقره)'
                  : entry.medal === 'bronze'
                  ? 'رتبهٔ سوم (برنز)'
                  : `رتبهٔ ${toPersianDigits(entry.rank)}`;
              return (
                <div key={entry.user_id} className="p-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="w-8 h-8 rounded-full bg-[var(--hb-bg)] border border-[var(--hb-border)] flex items-center justify-center text-xs font-bold tabular-nums shrink-0">
                        {toPersianDigits(entry.rank)}
                      </span>
                      <span
                        className="w-9 h-9 rounded-full flex items-center justify-center text-xs font-bold text-white shrink-0"
                        style={{ backgroundColor: entry.avatar_color || '#0F766E' }}
                      >
                        {entry.display_name.trim().charAt(0)}
                      </span>
                      <div className="min-w-0">
                        <div className="text-sm font-bold text-[var(--hb-text)] truncate">
                          {entry.display_name}
                        </div>
                        <div className="text-xs text-[var(--hb-muted)] truncate">
                          {medalLabel} · {entry.job_title || entry.department}
                        </div>
                      </div>
                    </div>

                    <div className="flex items-center gap-4">
                      <div className="text-left tabular-nums">
                        <div className="flex items-center gap-1 text-sm font-bold text-amber-600 dark:text-amber-300">
                          <Star className="w-4 h-4 fill-current" />
                          <span>{toPersianDigits(entry.avg_score.toFixed(2))}</span>
                        </div>
                        <div className="text-[11px] text-[var(--hb-muted)]">
                          از {toPersianDigits(entry.rating_count)} امتیاز
                        </div>
                      </div>

                      <button
                        type="button"
                        onClick={() => setExpandedUserId(isExpanded ? null : entry.user_id)}
                        aria-expanded={isExpanded}
                        className="inline-flex items-center gap-1 rounded-lg border border-[var(--hb-border)] px-2.5 py-1.5 text-xs font-medium"
                      >
                        <span>جزئیات</span>
                        {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                      </button>
                    </div>
                  </div>

                  {isExpanded && (
                    <div className="mt-3 pt-3 border-t border-[var(--hb-border)] space-y-1.5">
                      {entry.details.map((det) => (
                        <div
                          key={det.id}
                          className="rounded-lg bg-[var(--hb-bg)] px-3 py-2 text-xs space-y-2"
                        >
                          {editingId === det.id ? (
                            <div className="flex flex-wrap items-center gap-2">
                              <select
                                aria-label="امتیاز جدید"
                                value={editScore}
                                onChange={(e) => setEditScore(Number(e.target.value))}
                                className="h-8 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-2 text-xs tabular-nums"
                              >
                                {[5, 4, 3, 2, 1].map((s) => (
                                  <option key={s} value={s}>
                                    {toPersianDigits(s)} ستاره
                                  </option>
                                ))}
                              </select>
                              <input
                                type="text"
                                aria-label="توضیح جدید"
                                value={editReason}
                                onChange={(e) => setEditReason(e.target.value)}
                                className="flex-1 min-w-[160px] h-8 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-2.5 text-xs"
                              />
                              <button
                                type="button"
                                disabled={updateMut.isPending}
                                onClick={() =>
                                  updateMut.mutate({
                                    id: det.id,
                                    nextScore: editScore,
                                    nextReason: editReason,
                                  })
                                }
                                aria-label="ذخیره ویرایش امتیاز"
                                className="inline-flex h-8 items-center gap-1 rounded-lg bg-[var(--hb-primary-bg)] px-2.5 text-xs font-medium text-[var(--hb-primary-text)]"
                              >
                                <Check className="w-3.5 h-3.5" />
                                <span>ذخیره</span>
                              </button>
                              <button
                                type="button"
                                onClick={() => setEditingId(null)}
                                aria-label="انصراف از ویرایش"
                                className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[var(--hb-border)]"
                              >
                                <X className="w-3.5 h-3.5" />
                              </button>
                            </div>
                          ) : (
                            <div className="flex items-center justify-between gap-2">
                              <div>
                                <span className="font-semibold text-[var(--hb-text)]">{det.source_label}</span>
                                <span className="mx-1.5 text-[var(--hb-muted)]">·</span>
                                <span className="text-[var(--hb-muted)]">{det.reason}</span>
                              </div>
                              <div className="flex items-center gap-3 shrink-0 tabular-nums">
                                <span className="font-bold text-amber-700 dark:text-amber-300">
                                  {toPersianDigits(det.score)} ستاره
                                </span>
                                <span className="text-[11px] text-[var(--hb-muted)]">{det.created_at_label}</span>
                                {det.editable && isOnline && (
                                  <div className="flex items-center gap-1.5">
                                    <button
                                      type="button"
                                      onClick={() => {
                                        setEditingId(det.id);
                                        setEditScore(det.score);
                                        setEditReason(det.reason);
                                      }}
                                      aria-label="ویرایش امتیاز دستی"
                                      className="text-[var(--hb-active-text)] hover:opacity-80"
                                    >
                                      <Edit3 className="w-3.5 h-3.5" />
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() => deleteMut.mutate(det.id)}
                                      aria-label="حذف امتیاز دستی"
                                      className="text-rose-600 hover:text-rose-800"
                                    >
                                      <Trash2 className="w-3.5 h-3.5" />
                                    </button>
                                  </div>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
};

export default RatingsPage;
