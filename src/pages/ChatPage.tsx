import React, { useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { CheckCheck, Megaphone, Send, Users } from 'lucide-react';
import type { AuthUser, ChatMessageItem } from '../types/api';
import { ApiError, apiFetch } from '../utils/api';
import { toPersianDigits } from '../utils/persian';
import { useToast } from '../components/ToastProvider';
import { useOnlineStatus } from '../hooks/useOnlineStatus';

interface ChatPageProps {
  user: AuthUser;
}

interface ChatResponse {
  items: ChatMessageItem[];
  has_more: boolean;
  next_before_id: number | null;
  unread_public: number;
  unread_announcements: number;
}

const ChatPage: React.FC<ChatPageProps> = ({ user }) => {
  const { pushToast } = useToast();
  const isOnline = useOnlineStatus();
  const qc = useQueryClient();
  const isManager = user.roles.includes('manager');

  const [channel, setChannel] = useState<'public' | 'announcements'>('public');
  const [msgText, setMsgText] = useState('');
  const markedRef = useRef<Set<number>>(new Set());

  const chatQuery = useQuery({
    queryKey: ['chat', channel],
    queryFn: ({ signal }) => apiFetch<ChatResponse>(`/api/v1/chat?channel=${channel}&limit=50`, { signal }),
  });

  const presenceQuery = useQuery({
    queryKey: ['chat-presence'],
    queryFn: ({ signal }) =>
      apiFetch<{ online_users: Array<{ id: number; display_name: string; job_title: string; avatar_color: string }> }>(
        '/api/v1/chat/presence',
        { signal }
      ),
    refetchInterval: 25000,
  });

  // Mark unread messages from colleagues as read automatically when viewed
  useEffect(() => {
    const items = chatQuery.data?.items ?? [];
    const toMark = items
      .filter((m) => m.sender_id !== user.id && !m.read_by_me && !markedRef.current.has(m.id))
      .map((m) => m.id);
    if (toMark.length === 0) return;
    toMark.forEach((id) => markedRef.current.add(id));
    apiFetch('/api/v1/chat/reads', { method: 'POST', body: { message_ids: toMark } })
      .then(() => {
        qc.invalidateQueries({ queryKey: ['auth-me'] });
        qc.invalidateQueries({ queryKey: ['chat', channel] });
      })
      .catch(() => {});
  }, [chatQuery.data, user.id, channel, qc]);

  const sendMut = useMutation({
    mutationFn: () => {
      const endpoint = channel === 'announcements' ? '/api/v1/chat/announce' : '/api/v1/chat';
      return apiFetch<ChatMessageItem>(endpoint, {
        method: 'POST',
        body: {
          body: msgText.trim(),
          client_msg_id: `chat-${user.id}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
        },
      });
    },
    onSuccess: () => {
      setMsgText('');
      qc.invalidateQueries({ queryKey: ['chat', channel] });
      qc.invalidateQueries({ queryKey: ['auth-me'] });
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const messages = chatQuery.data?.items ?? [];
  const onlineUsers = presenceQuery.data?.online_users ?? [];
  const canCompose = channel === 'public' || isManager;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-start">
      {/* Main Chat Panel */}
      <section className="lg:col-span-9 rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] flex flex-col h-[calc(100vh-11rem)] min-h-[440px]">
        <div className="px-4 py-3 border-b border-[var(--hb-border)] flex items-center justify-between gap-2 shrink-0">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setChannel('public')}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold ${
                channel === 'public'
                  ? 'bg-[var(--hb-active-tint)] text-[var(--hb-active-text)]'
                  : 'text-[var(--hb-muted)]'
              }`}
            >
              گفتگوی عمومی همکاران{' '}
              {(chatQuery.data?.unread_public ?? 0) > 0 &&
                `(${toPersianDigits(chatQuery.data?.unread_public)})`}
            </button>
            <button
              type="button"
              onClick={() => setChannel('announcements')}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold ${
                channel === 'announcements'
                  ? 'bg-[var(--hb-active-tint)] text-[var(--hb-active-text)]'
                  : 'text-[var(--hb-muted)]'
              }`}
            >
              <Megaphone className="w-3.5 h-3.5" />
              <span>اطلاعیه‌های مدیر</span>
              {(chatQuery.data?.unread_announcements ?? 0) > 0 &&
                `(${toPersianDigits(chatQuery.data?.unread_announcements)})`}
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {chatQuery.isLoading ? (
            <div className="space-y-2">
              <div className="h-14 rounded-lg bg-slate-100 dark:bg-slate-800 animate-pulse" />
              <div className="h-14 rounded-lg bg-slate-100 dark:bg-slate-800 animate-pulse" />
            </div>
          ) : messages.length === 0 ? (
            <div className="py-12 text-center text-xs text-[var(--hb-muted)]">
              هنوز پیامی در این بخش ارسال نشده است.
            </div>
          ) : (
            messages.map((m) => {
              const isMine = m.sender_id === user.id;
              return (
                <div
                  key={m.id}
                  className={`flex flex-col max-w-xl ${isMine ? 'ms-auto items-end' : 'me-auto items-start'}`}
                >
                  <div className="flex items-center gap-2 text-[11px] text-[var(--hb-muted)] mb-1">
                    <span className="font-semibold text-[var(--hb-text)]">{m.sender_name}</span>
                    <span>·</span>
                    <span className="tabular-nums">{m.created_at_label}</span>
                  </div>
                  <div
                    className={`rounded-xl px-3.5 py-2.5 text-sm leading-relaxed border ${
                      isMine
                        ? 'bg-[var(--hb-active-tint)] border-[var(--hb-brand)]/40 text-[var(--hb-text)]'
                        : 'bg-[var(--hb-bg)] border-[var(--hb-border)] text-[var(--hb-text)]'
                    }`}
                  >
                    {m.body}
                  </div>
                  <div className="mt-1 flex items-center gap-1 text-[11px] text-[var(--hb-muted)] tabular-nums">
                    <CheckCheck className="w-3.5 h-3.5 text-[var(--hb-brand)]" />
                    <span>خوانده‌شده توسط {toPersianDigits(m.read_count)} نفر</span>
                  </div>
                </div>
              );
            })
          )}
        </div>

        <div className="p-3 border-t border-[var(--hb-border)] shrink-0">
          {canCompose ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (msgText.trim()) sendMut.mutate();
              }}
              className="flex items-center gap-2"
            >
              <input
                type="text"
                value={msgText}
                onChange={(e) => setMsgText(e.target.value)}
                placeholder={
                  channel === 'announcements' ? 'متن اطلاعیهٔ تیمی مدیر...' : 'پیام خود را بنویسید...'
                }
                className="flex-1 h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-3 text-sm"
              />
              <button
                type="submit"
                disabled={!isOnline || !msgText.trim() || sendMut.isPending}
                className="inline-flex h-10 items-center gap-1.5 rounded-lg bg-[var(--hb-primary-bg)] hover:bg-[var(--hb-primary-hover)] px-4 text-xs font-bold text-[var(--hb-primary-text)] disabled:opacity-50"
              >
                <Send className="w-4 h-4" />
                <span>ارسال</span>
              </button>
            </form>
          ) : (
            <div className="text-center text-xs text-[var(--hb-muted)] py-1">
              انتشار اطلاعیهٔ رسمی در این بخش فقط برای مدیر امکان‌پذیر است.
            </div>
          )}
        </div>
      </section>

      {/* Online Presence Panel */}
      <aside className="lg:col-span-3 rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] p-4 space-y-3">
        <h2 className="text-xs font-bold text-[var(--hb-text)] flex items-center gap-1.5">
          <Users className="w-4 h-4 text-[var(--hb-brand)]" />
          <span>همکاران آنلاین ({toPersianDigits(onlineUsers.length)})</span>
        </h2>
        {onlineUsers.length === 0 ? (
          <p className="text-xs text-[var(--hb-muted)]">همکار آنلاینی ثبت نشده است.</p>
        ) : (
          <ul className="space-y-2">
            {onlineUsers.map((ou) => (
              <li key={ou.id} className="flex items-center gap-2.5 text-xs">
                <span
                  className="inline-flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-bold text-white shrink-0"
                  style={{ backgroundColor: ou.avatar_color || '#0F766E' }}
                >
                  {ou.display_name.trim().charAt(0)}
                </span>
                <div className="min-w-0">
                  <div className="font-semibold text-[var(--hb-text)] truncate">{ou.display_name}</div>
                  <div className="text-[11px] text-[var(--hb-muted)] truncate">{ou.job_title || 'همکار'}</div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
};

export default ChatPage;
