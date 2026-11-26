import React, { useEffect, useRef, useState } from 'react';
import {
  Archive,
  Award,
  BarChart3,
  Bell,
  CheckCheck,
  DatabaseBackup,
  Download,
  FileEdit,
  History,
  Inbox,
  LogOut,
  Menu,
  MessageSquare,
  Moon,
  PlusCircle,
  Sun,
  Trash2,
  UserCheck,
  Users,
  WifiOff,
  X,
} from 'lucide-react';
import type { AuthUser, NotificationItem } from '../types/api';
import { getTehranNowParts } from '../utils/jalali';
import { toPersianDigits } from '../utils/persian';
import type { WsConnectionStatus } from '../utils/ws';
import { usePWAInstall } from '../hooks/usePWAInstall';
import { useOnlineStatus } from '../hooks/useOnlineStatus';
import { SahelLogo } from './SahelLogo';
import { Modal } from './Modal';

export type NavSectionId =
  | 'inbox'
  | 'direct_create'
  | 'drafts'
  | 'visits'
  | 'chat'
  | 'ratings'
  | 'reports'
  | 'archive'
  | 'users'
  | 'trash'
  | 'login_logs'
  | 'backups';

interface AppShellProps {
  user: AuthUser;
  activeTab: NavSectionId;
  onSelectTab: (tab: NavSectionId) => void;
  theme: 'light' | 'dark';
  onToggleTheme: () => void;
  wsStatus: WsConnectionStatus;
  unreadNotifications: number;
  unreadChatCount: number;
  notifications: NotificationItem[];
  onRefreshNotifications: () => void;
  onMarkAllNotificationsRead: () => void;
  onOpenTaskFromNotification: (taskId: number) => void;
  onLogout: () => void;
  children: React.ReactNode;
}

interface NavItemDef {
  id: NavSectionId;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: number;
  visible: boolean;
  group: 'main' | 'team' | 'admin';
}

export const AppShell: React.FC<AppShellProps> = ({
  user,
  activeTab,
  onSelectTab,
  theme,
  onToggleTheme,
  wsStatus,
  unreadNotifications,
  unreadChatCount,
  notifications,
  onRefreshNotifications,
  onMarkAllNotificationsRead,
  onOpenTaskFromNotification,
  onLogout,
  children,
}) => {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const [iosInstallOpen, setIosInstallOpen] = useState(false);
  const [clockText, setClockText] = useState(() => getTehranNowParts().formattedFull);
  const notifRef = useRef<HTMLDivElement>(null);

  const isOnline = useOnlineStatus();
  const { isInstallable, isInstalled, isIOS, install } = usePWAInstall();

  useEffect(() => {
    const timer = window.setInterval(() => {
      setClockText(getTehranNowParts().formattedFull);
    }, 15000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!notifOpen) return;
    onRefreshNotifications();
    const handleClick = (e: MouseEvent) => {
      if (notifRef.current && !notifRef.current.contains(e.target as Node)) {
        setNotifOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [notifOpen, onRefreshNotifications]);

  const roles = new Set(user.roles);
  const isManager = roles.has('manager');
  const isAdmin = roles.has('admin');
  const isAuthor = roles.has('author');
  const hasInboxRole = roles.has('employee') || roles.has('expert') || isManager;

  const navItems: NavItemDef[] = [
    { id: 'inbox', label: 'صندوق پیگیری', icon: Inbox, visible: hasInboxRole, group: 'main' },
    { id: 'direct_create', label: 'ثبت مستقیم پیام', icon: PlusCircle, visible: isManager, group: 'main' },
    { id: 'drafts', label: 'پیش‌نویس‌ها', icon: FileEdit, visible: isAuthor || isManager, group: 'main' },
    { id: 'visits', label: 'مراجعات مردمی', icon: UserCheck, visible: hasInboxRole, group: 'main' },
    {
      id: 'chat',
      label: 'چت و اطلاع‌رسانی',
      icon: MessageSquare,
      badge: unreadChatCount > 0 ? unreadChatCount : undefined,
      visible: true,
      group: 'team',
    },
    { id: 'ratings', label: 'تابلوی افتخارات', icon: Award, visible: true, group: 'team' },
    { id: 'reports', label: 'گزارش‌ها و آمار', icon: BarChart3, visible: hasInboxRole, group: 'team' },
    { id: 'archive', label: 'بایگانی کارها', icon: Archive, visible: isManager || isAdmin, group: 'admin' },
    { id: 'users', label: 'مدیریت کاربران', icon: Users, visible: isAdmin, group: 'admin' },
    { id: 'trash', label: 'سطل زباله', icon: Trash2, visible: isAdmin, group: 'admin' },
    { id: 'login_logs', label: 'ورود و خروج', icon: History, visible: isAdmin, group: 'admin' },
    { id: 'backups', label: 'پشتیبان‌گیری', icon: DatabaseBackup, visible: isAdmin, group: 'admin' },
  ];

  const visibleItems = navItems.filter((item) => item.visible);
  const activeDef = visibleItems.find((item) => item.id === activeTab);

  const wsLabel =
    wsStatus === 'connected' ? 'همگام‌سازی زنده فعال' : wsStatus === 'connecting' ? 'در حال اتصال' : 'اتصال زنده قطع';

  const renderSidebarContent = () => (
    <div className="flex flex-col h-full">
      <div className="h-16 px-4 flex items-center justify-between border-b border-[var(--hb-border)] shrink-0">
        <SahelLogo size={32} showWordmark />
        <button
          type="button"
          onClick={() => setDrawerOpen(false)}
          aria-label="بستن منو"
          className="lg:hidden inline-flex h-9 w-9 items-center justify-center rounded-lg text-[var(--hb-muted)] hover:bg-slate-100 dark:hover:bg-slate-800"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <nav aria-label="منوی اصلی" className="flex-1 overflow-y-auto p-3 space-y-5">
        {(['main', 'team', 'admin'] as const).map((grp) => {
          const grpItems = visibleItems.filter((i) => i.group === grp);
          if (grpItems.length === 0) return null;
          const grpTitle = grp === 'main' ? 'عملیات روزانه' : grp === 'team' ? 'همکاری و عملکرد' : 'مدیریت و نگهداری';
          return (
            <div key={grp}>
              <div className="px-2.5 pb-1.5 text-[11px] font-semibold text-[var(--hb-muted)]">{grpTitle}</div>
              <ul className="space-y-1">
                {grpItems.map((item) => {
                  const Icon = item.icon;
                  const active = activeTab === item.id;
                  return (
                    <li key={item.id}>
                      <button
                        type="button"
                        onClick={() => {
                          onSelectTab(item.id);
                          setDrawerOpen(false);
                        }}
                        aria-current={active ? 'page' : undefined}
                        className={`w-full flex items-center justify-between gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors whitespace-nowrap ${
                          active
                            ? 'bg-[var(--hb-active-tint)] text-[var(--hb-active-text)] font-semibold'
                            : 'text-[var(--hb-text)] hover:bg-slate-100 dark:hover:bg-slate-800/70'
                        }`}
                      >
                        <span className="flex items-center gap-2.5 min-w-0">
                          <Icon className="w-4 h-4 shrink-0" aria-hidden="true" />
                          <span className="truncate">{item.label}</span>
                        </span>
                        {item.badge !== undefined && (
                          <span className="text-xs font-bold tabular-nums text-[var(--hb-active-text)]">
                            {toPersianDigits(item.badge)}
                          </span>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </nav>

      <div className="p-3 border-t border-[var(--hb-border)] shrink-0 space-y-2">
        <div className="flex items-center gap-2.5 px-2 py-1.5">
          <span
            className="inline-flex h-9 w-9 items-center justify-center rounded-full text-xs font-bold text-white shrink-0"
            style={{ backgroundColor: user.avatar_color || '#0F766E' }}
            aria-hidden="true"
          >
            {user.display_name.trim().charAt(0)}
          </span>
          <div className="min-w-0 flex-1">
            <div className="text-xs font-bold text-[var(--hb-text)] truncate">{user.display_name}</div>
            <div className="text-[11px] text-[var(--hb-muted)] truncate">
              {user.job_title || user.department}
            </div>
          </div>
        </div>
        <button
          type="button"
          onClick={onLogout}
          className="w-full flex items-center justify-center gap-2 rounded-lg border border-[var(--hb-border)] px-3 py-2 text-xs font-medium text-rose-700 dark:text-rose-300 hover:bg-rose-50 dark:hover:bg-rose-950/40 transition-colors"
        >
          <LogOut className="w-3.5 h-3.5" aria-hidden="true" />
          <span>خروج از سامانه</span>
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen flex bg-[var(--hb-bg)] text-[var(--hb-text)]">
      {/* Desktop right sidebar */}
      <aside className="hidden lg:flex lg:w-64 lg:flex-col border-e border-[var(--hb-border)] bg-[var(--hb-surface)] shrink-0 sticky top-0 h-screen">
        {renderSidebarContent()}
      </aside>

      {/* Mobile slide-over drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-50 lg:hidden flex">
          <div
            className="fixed inset-0 bg-slate-950/50"
            onClick={() => setDrawerOpen(false)}
            aria-hidden="true"
          />
          <aside className="relative z-10 w-72 max-w-[85vw] bg-[var(--hb-surface)] border-e border-[var(--hb-border)] h-full shadow-2xl">
            {renderSidebarContent()}
          </aside>
        </div>
      )}

      {/* Main viewport */}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="h-16 border-b border-[var(--hb-border)] bg-[var(--hb-surface)] px-3 sm:px-6 flex items-center justify-between gap-4 sticky top-0 z-30 shrink-0">
          <div className="flex items-center gap-2.5 min-w-0">
            <button
              type="button"
              onClick={() => setDrawerOpen(true)}
              aria-label="بازکردن منوی ناوبری"
              className="lg:hidden inline-flex h-10 w-10 items-center justify-center rounded-lg border border-[var(--hb-border)] text-[var(--hb-text)] hover:bg-slate-100 dark:hover:bg-slate-800 shrink-0"
            >
              <Menu className="w-5 h-5" />
            </button>
            <h1 className="text-sm sm:text-base font-bold text-[var(--hb-text)] truncate">
              {activeDef?.label || 'میز کار هرمزگان بیدار'}
            </h1>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <span className="hidden md:inline-block text-xs text-[var(--hb-muted)] tabular-nums whitespace-nowrap px-2">
              {clockText}
            </span>

            {/* Real WebSocket connection state indicator */}
            <div
              title={wsLabel}
              aria-label={wsLabel}
              className="hidden sm:flex items-center gap-1.5 text-xs text-[var(--hb-muted)] px-2 py-1"
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  wsStatus === 'connected'
                    ? 'bg-emerald-600'
                    : wsStatus === 'connecting'
                    ? 'bg-amber-500'
                    : 'bg-rose-600'
                }`}
                aria-hidden="true"
              />
              <span className="hidden xl:inline whitespace-nowrap">
                {wsStatus === 'connected' ? 'آنلاین' : wsStatus === 'connecting' ? 'اتصال...' : 'قطع'}
              </span>
            </div>

            {!isInstalled && isInstallable && (
              <button
                type="button"
                onClick={install}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--hb-border)] px-2.5 py-1.5 text-xs font-medium text-[var(--hb-active-text)] hover:bg-[var(--hb-active-tint)] whitespace-nowrap"
              >
                <Download className="w-3.5 h-3.5" aria-hidden="true" />
                <span className="hidden sm:inline">نصب برنامه</span>
              </button>
            )}
            {!isInstalled && !isInstallable && isIOS && (
              <button
                type="button"
                onClick={() => setIosInstallOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--hb-border)] px-2.5 py-1.5 text-xs font-medium text-[var(--hb-text)] hover:bg-slate-100 dark:hover:bg-slate-800 whitespace-nowrap"
              >
                <Download className="w-3.5 h-3.5" aria-hidden="true" />
                <span>راهنمای نصب</span>
              </button>
            )}

            <button
              type="button"
              onClick={onToggleTheme}
              aria-label={theme === 'dark' ? 'تغییر به پوستهٔ روشن' : 'تغییر به پوستهٔ تیره'}
              className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-[var(--hb-border)] text-[var(--hb-text)] hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
            </button>

            <div ref={notifRef} className="relative">
              <button
                type="button"
                onClick={() => setNotifOpen((o) => !o)}
                aria-label={`اعلان‌ها (${toPersianDigits(unreadNotifications)} خوانده‌نشده)`}
                className="relative inline-flex h-10 w-10 items-center justify-center rounded-lg border border-[var(--hb-border)] text-[var(--hb-text)] hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                <Bell className="w-4 h-4" />
                {unreadNotifications > 0 && (
                  <span className="absolute -top-1 -start-1 min-w-[18px] h-[18px] px-1 rounded-full bg-rose-600 text-white text-[10px] font-bold flex items-center justify-center tabular-nums">
                    {toPersianDigits(unreadNotifications > 99 ? '99+' : unreadNotifications)}
                  </span>
                )}
              </button>

              {notifOpen && (
                <div
                  role="dialog"
                  aria-label="فهرست اعلان‌ها"
                  className="absolute end-0 mt-2 w-80 sm:w-96 rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] shadow-xl z-40 overflow-hidden"
                >
                  <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--hb-border)]">
                    <span className="text-xs font-bold">اعلان‌های سامانه</span>
                    {unreadNotifications > 0 && (
                      <button
                        type="button"
                        onClick={onMarkAllNotificationsRead}
                        className="inline-flex items-center gap-1 text-[11px] font-medium text-[var(--hb-active-text)] hover:underline"
                      >
                        <CheckCheck className="w-3.5 h-3.5" />
                        <span>خواندن همه</span>
                      </button>
                    )}
                  </div>
                  <div className="max-h-80 overflow-y-auto divide-y divide-[var(--hb-border)]">
                    {notifications.length === 0 ? (
                      <div className="py-8 text-center text-xs text-[var(--hb-muted)]">
                        اعلان تازه‌ای ثبت نشده است.
                      </div>
                    ) : (
                      notifications.map((n) => (
                        <div
                          key={n.id}
                          className={`px-4 py-2.5 text-xs ${
                            n.is_read ? '' : 'bg-[var(--hb-active-tint)]'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2 font-semibold text-[var(--hb-text)]">
                            <span>{n.title}</span>
                            <span className="text-[11px] font-normal text-[var(--hb-muted)] tabular-nums shrink-0">
                              {n.created_at_label}
                            </span>
                          </div>
                          <p className="mt-1 text-[var(--hb-muted)] leading-relaxed">{n.body}</p>
                          {n.task_id !== null && hasInboxRole && (
                            <button
                              type="button"
                              onClick={() => {
                                setNotifOpen(false);
                                onOpenTaskFromNotification(n.task_id!);
                              }}
                              className="mt-1.5 text-[11px] font-semibold text-[var(--hb-active-text)] hover:underline"
                            >
                              مشاهدهٔ پرونده #{toPersianDigits(n.task_id)}
                            </button>
                          )}
                        </div>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </header>

        {!isOnline && (
          <div
            role="alert"
            className="bg-amber-50 dark:bg-amber-950/80 border-b border-amber-300 dark:border-amber-700 px-4 py-2 text-xs font-medium text-amber-900 dark:text-amber-100 flex items-center gap-2"
          >
            <WifiOff className="w-4 h-4 shrink-0" aria-hidden="true" />
            <span>
              اتصال شبکه قطع است. عملیات ثبت و تغییر داده تا زمان بازگشت اینترنت مسدود شده است.
            </span>
          </div>
        )}

        <main className="flex-1 p-3 sm:p-6 max-w-[1440px] w-full mx-auto">{children}</main>
      </div>

      <Modal open={iosInstallOpen} title="نصب برنامه در آیفون و آیپد" onClose={() => setIosInstallOpen(false)} maxWidthClass="max-w-sm">
        <ol className="space-y-2 text-sm text-[var(--hb-text)] list-decimal list-inside leading-relaxed">
          <li>در نوار مرورگر Safari دکمهٔ اشتراک‌گذاری (Share) را لمس کنید.</li>
          <li>گزینهٔ <strong>Add to Home Screen</strong> را انتخاب و تأیید نمایید.</li>
        </ol>
      </Modal>
    </div>
  );
};
