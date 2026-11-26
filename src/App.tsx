import React, { Suspense, lazy, useCallback, useEffect, useRef, useState } from 'react';
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query';
import type { AuthUser, MeResponse, NotificationItem } from './types/api';
import { ApiError, apiFetch, registerUnauthorizedHandler, setCsrfToken } from './utils/api';
import { realtimeClient, type WsConnectionStatus } from './utils/ws';
import { ToastProvider, useToast } from './components/ToastProvider';
import { AppShell, type NavSectionId } from './components/AppShell';

const LoginPage = lazy(() => import('./pages/LoginPage'));
const InboxPage = lazy(() => import('./pages/InboxPage'));
const DirectCreatePage = lazy(() => import('./pages/DirectCreatePage'));
const DraftsPage = lazy(() => import('./pages/DraftsPage'));
const VisitsPage = lazy(() => import('./pages/VisitsPage'));
const ChatPage = lazy(() => import('./pages/ChatPage'));
const RatingsPage = lazy(() => import('./pages/RatingsPage'));
const ReportsPage = lazy(() => import('./pages/ReportsPage'));
const ArchivePage = lazy(() => import('./pages/ArchivePage'));
const UsersPage = lazy(() => import('./pages/UsersPage'));
const TrashPage = lazy(() => import('./pages/TrashPage'));
const LoginLogsPage = lazy(() => import('./pages/LoginLogsPage'));
const BackupsPage = lazy(() => import('./pages/BackupsPage'));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

const PageSkeleton: React.FC = () => (
  <div className="space-y-4">
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
      <div className="h-20 rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] animate-pulse" />
      <div className="h-20 rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] animate-pulse" />
      <div className="h-20 rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] animate-pulse" />
    </div>
    <div className="h-72 rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] animate-pulse" />
  </div>
);

function getDefaultTabForUser(u: AuthUser): NavSectionId {
  const roles = new Set(u.roles);
  if (roles.has('employee') || roles.has('expert') || roles.has('manager')) {
    return 'inbox';
  }
  if (roles.has('author')) {
    return 'drafts';
  }
  if (roles.has('admin')) {
    return 'users';
  }
  return 'chat';
}

function resolveInitialTheme(): 'light' | 'dark' {
  if (typeof window === 'undefined') return 'light';
  try {
    const saved = localStorage.getItem('hb_theme');
    if (saved === 'dark' || saved === 'light') return saved;
    if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
      return 'dark';
    }
  } catch {
    // Ignore storage access restrictions
  }
  return 'light';
}

function applyThemeToDom(mode: 'light' | 'dark') {
  if (typeof document === 'undefined') return;
  document.documentElement.classList.toggle('dark', mode === 'dark');
  const metaTheme = document.querySelector('meta[name="theme-color"]');
  if (metaTheme) {
    metaTheme.setAttribute('content', mode === 'dark' ? '#0F172A' : '#0D9488');
  }
}

const AppInner: React.FC = () => {
  const { pushToast } = useToast();
  const qc = useQueryClient();

  const [theme, setTheme] = useState<'light' | 'dark'>(() => resolveInitialTheme());
  const [bootstrapping, setBootstrapping] = useState(true);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [activeTab, setActiveTab] = useState<NavSectionId>('inbox');
  const [wsStatus, setWsStatus] = useState<WsConnectionStatus>('disconnected');
  const [unreadNotifications, setUnreadNotifications] = useState(0);
  const [unreadChatCount, setUnreadChatCount] = useState(0);
  const [selectedTaskIdFromNotif, setSelectedTaskIdFromNotif] = useState<number | null>(null);

  const isManualLogoutRef = useRef(false);

  useEffect(() => {
    applyThemeToDom(theme);
  }, [theme]);

  const forceClientLogout = useCallback(
    (toastMsg?: string) => {
      realtimeClient.stop();
      setCsrfToken('');
      setUser(null);
      setUnreadNotifications(0);
      setUnreadChatCount(0);
      qc.clear();
      if (toastMsg) pushToast('info', toastMsg);
    },
    [pushToast, qc]
  );

  useEffect(() => {
    registerUnauthorizedHandler(() => {
      if (isManualLogoutRef.current) return;
      forceClientLogout('نشست کاربری منقضی شد. لطفاً مجدداً وارد شوید.');
    });
    return () => registerUnauthorizedHandler(null);
  }, [forceClientLogout]);

  const applyMeResponse = useCallback((me: MeResponse, resetTabIfNeeded: boolean) => {
    setCsrfToken(me.csrf_token);
    setUser(me.user);
    setUnreadNotifications(me.unread_notifications);
    setUnreadChatCount((me.unread_chat_public || 0) + (me.unread_chat_announcements || 0));
    if (resetTabIfNeeded) {
      setActiveTab(getDefaultTabForUser(me.user));
    }
    try {
      const saved = localStorage.getItem('hb_theme');
      if (!saved && (me.user.theme_preference === 'dark' || me.user.theme_preference === 'light')) {
        setTheme(me.user.theme_preference);
      }
    } catch {
      // Ignore
    }
  }, []);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const me = await apiFetch<MeResponse>('/api/v1/auth/me', { skipUnauthorizedRedirect: true });
        if (!active) return;
        applyMeResponse(me, true);
      } catch {
        // Not logged in yet
      } finally {
        if (active) setBootstrapping(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [applyMeResponse]);

  const notificationsQuery = useQuery({
    queryKey: ['notifications'],
    queryFn: ({ signal }) =>
      apiFetch<{ items: NotificationItem[]; unread_count: number }>('/api/v1/notifications?limit=30', { signal }),
    enabled: !!user,
  });

  useEffect(() => {
    if (notificationsQuery.data) {
      setUnreadNotifications(notificationsQuery.data.unread_count);
    }
  }, [notificationsQuery.data]);

  const refreshMeCounters = useCallback(async () => {
    if (!user) return;
    try {
      const me = await apiFetch<MeResponse>('/api/v1/auth/me');
      setUser(me.user);
      setUnreadNotifications(me.unread_notifications);
      setUnreadChatCount((me.unread_chat_public || 0) + (me.unread_chat_announcements || 0));
    } catch {
      // Handled by global 401 handler if expired
    }
  }, [user]);

  useEffect(() => {
    if (!user) {
      realtimeClient.stop();
      return;
    }

    const unsubStatus = realtimeClient.onStatusChange(setWsStatus);
    const unsubEvents = realtimeClient.onEvent((ev) => {
      const t = ev.type || '';
      if (t === 'session.revoked') {
        if (isManualLogoutRef.current) return;
        forceClientLogout('نشست کاربری شما بسته شد. لطفاً مجدداً وارد شوید.');
        return;
      }
      if (t.startsWith('task.') || t === 'reminder.fired') {
        qc.invalidateQueries({ queryKey: ['tasks'] });
        qc.invalidateQueries({ queryKey: ['task-detail'] });
        qc.invalidateQueries({ queryKey: ['notifications'] });
        qc.invalidateQueries({ queryKey: ['reports-summary'] });
        qc.invalidateQueries({ queryKey: ['reports-staff'] });
        refreshMeCounters();
      } else if (t.startsWith('draft.')) {
        qc.invalidateQueries({ queryKey: ['drafts'] });
      } else if (t.startsWith('visit.')) {
        qc.invalidateQueries({ queryKey: ['visits'] });
        qc.invalidateQueries({ queryKey: ['reports-summary'] });
      } else if (t.startsWith('chat.')) {
        qc.invalidateQueries({ queryKey: ['chat'] });
        qc.invalidateQueries({ queryKey: ['chat-presence'] });
        refreshMeCounters();
      } else if (t.startsWith('rating.')) {
        qc.invalidateQueries({ queryKey: ['leaderboard'] });
      } else if (t === 'sync.required') {
        qc.invalidateQueries();
        refreshMeCounters();
      }
    });

    realtimeClient.start();
    return () => {
      unsubStatus();
      unsubEvents();
    };
  }, [user, qc, forceClientLogout, refreshMeCounters]);

  const handleToggleTheme = async () => {
    const next: 'light' | 'dark' = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    try {
      localStorage.setItem('hb_theme', next);
    } catch {
      // Ignore
    }
    if (user) {
      try {
        await apiFetch('/api/v1/auth/theme', {
          method: 'PATCH',
          body: { theme_preference: next },
        });
      } catch {
        // Non-blocking preference sync
      }
    }
  };

  const handleLoginSuccess = async (loggedUser: AuthUser) => {
    isManualLogoutRef.current = false;
    setUser(loggedUser);
    setActiveTab(getDefaultTabForUser(loggedUser));
    try {
      const me = await apiFetch<MeResponse>('/api/v1/auth/me');
      applyMeResponse(me, true);
    } catch {
      // Fallback already populated
    }
  };

  const handleLogout = async () => {
    isManualLogoutRef.current = true;
    realtimeClient.stop();
    await qc.cancelQueries();
    try {
      await apiFetch('/api/v1/auth/logout', { method: 'POST', skipUnauthorizedRedirect: true });
    } catch {
      // Proceed to clear client session regardless
    }
    forceClientLogout('با موفقیت از سامانه خارج شدید.');
  };

  const handleMarkAllNotificationsRead = async () => {
    try {
      await apiFetch('/api/v1/notifications/read', { method: 'POST' });
      setUnreadNotifications(0);
      qc.invalidateQueries({ queryKey: ['notifications'] });
    } catch (err) {
      pushToast('error', err instanceof ApiError ? err.message : 'خطا در به‌روزرسانی اعلان‌ها.');
    }
  };

  const handleRefreshNotifications = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['notifications'] });
  }, [qc]);

  if (bootstrapping) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--hb-bg)] text-[var(--hb-muted)] text-sm">
        در حال بارگذاری سامانهٔ هرمزگان بیدار...
      </div>
    );
  }

  if (!user) {
    return (
      <Suspense fallback={<div className="min-h-screen bg-[var(--hb-bg)]" />}>
        <LoginPage theme={theme} onToggleTheme={handleToggleTheme} onSuccess={handleLoginSuccess} />
      </Suspense>
    );
  }

  const roles = new Set(user.roles);
  const isManager = roles.has('manager');
  const isAdmin = roles.has('admin');
  const isAuthor = roles.has('author');
  const hasInboxRole = roles.has('employee') || roles.has('expert') || isManager;

  const renderActiveSection = () => {
    switch (activeTab) {
      case 'inbox':
        return hasInboxRole ? (
          <InboxPage
            user={user}
            selectedTaskIdFromNotif={selectedTaskIdFromNotif}
            onClearNotifTask={() => setSelectedTaskIdFromNotif(null)}
          />
        ) : (
          <ChatPage user={user} />
        );
      case 'direct_create':
        return isManager ? <DirectCreatePage onCreated={() => setActiveTab('inbox')} /> : null;
      case 'drafts':
        return isAuthor || isManager ? <DraftsPage user={user} /> : null;
      case 'visits':
        return hasInboxRole ? <VisitsPage user={user} /> : null;
      case 'chat':
        return <ChatPage user={user} />;
      case 'ratings':
        return <RatingsPage user={user} />;
      case 'reports':
        return hasInboxRole ? <ReportsPage /> : null;
      case 'archive':
        return isManager || isAdmin ? <ArchivePage /> : null;
      case 'users':
        return isAdmin ? <UsersPage /> : null;
      case 'trash':
        return isAdmin ? <TrashPage /> : null;
      case 'login_logs':
        return isAdmin ? <LoginLogsPage /> : null;
      case 'backups':
        return isAdmin ? <BackupsPage /> : null;
      default:
        return null;
    }
  };

  return (
    <AppShell
      user={user}
      activeTab={activeTab}
      onSelectTab={setActiveTab}
      theme={theme}
      onToggleTheme={handleToggleTheme}
      wsStatus={wsStatus}
      unreadNotifications={unreadNotifications}
      unreadChatCount={unreadChatCount}
      notifications={notificationsQuery.data?.items || []}
      onRefreshNotifications={handleRefreshNotifications}
      onMarkAllNotificationsRead={handleMarkAllNotificationsRead}
      onOpenTaskFromNotification={(taskId) => {
        if (hasInboxRole) {
          setSelectedTaskIdFromNotif(taskId);
          setActiveTab('inbox');
        }
      }}
      onLogout={handleLogout}
    >
      <Suspense fallback={<PageSkeleton />}>{renderActiveSection()}</Suspense>
    </AppShell>
  );
};

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AppInner />
      </ToastProvider>
    </QueryClientProvider>
  );
}
