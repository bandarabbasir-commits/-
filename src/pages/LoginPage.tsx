import React, { useEffect, useState } from 'react';
import { Eye, EyeOff, Lock, Moon, ShieldCheck, Sun, User as UserIcon } from 'lucide-react';
import type { AuthUser } from '../types/api';
import { ApiError, apiFetch, ensurePreAuthCsrf, setCsrfToken } from '../utils/api';
import { SahelLogo } from '../components/SahelLogo';

interface LoginPageProps {
  theme: 'light' | 'dark';
  onToggleTheme: () => void;
  onSuccess: (user: AuthUser) => void;
}

const LoginPage: React.FC<LoginPageProps> = ({ theme, onToggleTheme, onSuccess }) => {
  const [needsSetup, setNeedsSetup] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPass, setShowPass] = useState(false);

  // First-run production bootstrap state (only shown if zero users exist in DB)
  const [setupUsername, setSetupUsername] = useState('admin');
  const [setupDisplayName, setSetupDisplayName] = useState('');
  const [setupPassword, setSetupPassword] = useState('');
  const [setupConfirm, setSetupConfirm] = useState('');

  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  useEffect(() => {
    let active = true;
    apiFetch<{ needs_setup: boolean }>('/api/v1/auth/bootstrap-status', {
      skipUnauthorizedRedirect: true,
    })
      .then((res) => {
        if (active && res.needs_setup) {
          setNeedsSetup(true);
        }
      })
      .catch(() => {
        // Fallback to standard login view
      });
    return () => {
      active = false;
    };
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password) {
      setErrorMsg('وارد کردن نام کاربری و رمز عبور الزامی است.');
      return;
    }
    setSubmitting(true);
    setErrorMsg('');
    try {
      await ensurePreAuthCsrf(undefined, true);
      const res = await apiFetch<{ user: AuthUser; csrf_token: string }>('/api/v1/auth/login', {
        method: 'POST',
        body: { username: username.trim(), password },
        skipUnauthorizedRedirect: true,
      });
      setCsrfToken(res.csrf_token);
      onSuccess(res.user);
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMsg(err.message);
      } else {
        setErrorMsg('خطا در برقراری ارتباط با سرور سامانه.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleBootstrapSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (setupUsername.trim().length < 2) {
      setErrorMsg('نام کاربری باید حداقل ۲ کاراکتر انگلیسی باشد.');
      return;
    }
    if (setupDisplayName.trim().length < 2) {
      setErrorMsg('نام و نام‌خانوادگی مدیر سیستم الزامی است.');
      return;
    }
    if (setupPassword.length < 8) {
      setErrorMsg('رمز عبور باید حداقل ۸ کاراکتر باشد.');
      return;
    }
    if (setupPassword !== setupConfirm) {
      setErrorMsg('تکرار رمز عبور با رمز عبور یکسان نیست.');
      return;
    }

    setSubmitting(true);
    setErrorMsg('');
    try {
      await ensurePreAuthCsrf(undefined, true);
      const res = await apiFetch<{ user: AuthUser; csrf_token: string }>('/api/v1/auth/bootstrap-admin', {
        method: 'POST',
        body: {
          username: setupUsername.trim(),
          display_name: setupDisplayName.trim(),
          password: setupPassword,
        },
        skipUnauthorizedRedirect: true,
      });
      setCsrfToken(res.csrf_token);
      onSuccess(res.user);
    } catch (err) {
      if (err instanceof ApiError) {
        setErrorMsg(err.message);
        if (err.status === 409) {
          setNeedsSetup(false);
        }
      } else {
        setErrorMsg('خطا در ایجاد حساب مدیر نخستین.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col justify-between bg-[var(--hb-bg)] text-[var(--hb-text)] p-4 sm:p-6">
      <div className="flex items-center justify-between max-w-5xl w-full mx-auto">
        <SahelLogo size={36} showWordmark />
        <button
          type="button"
          onClick={onToggleTheme}
          aria-label={theme === 'dark' ? 'تغییر به پوستهٔ روشن' : 'تغییر به پوستهٔ تیره'}
          className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] text-[var(--hb-text)] hover:bg-slate-100 dark:hover:bg-slate-800"
        >
          {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
        </button>
      </div>

      <main className="my-auto w-full max-w-md mx-auto py-8">
        <div className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] p-6 sm:p-8 shadow-sm">
          {needsSetup ? (
            <>
              <div className="mb-6">
                <div className="inline-flex items-center gap-1.5 text-xs font-bold text-[var(--hb-brand)] mb-2">
                  <ShieldCheck className="w-4 h-4" />
                  <span>راه‌اندازی اولیهٔ سامانه</span>
                </div>
                <h1 className="text-xl font-bold text-[var(--hb-text)]">تعریف مدیر نخستین سیستم</h1>
                <p className="mt-1.5 text-sm text-[var(--hb-muted)]">
                  پایگاه‌داده بدون کاربر است. برای آغاز بهره‌برداری، حساب مدیر ارشد را ایجاد کنید.
                </p>
              </div>

              {errorMsg && (
                <div
                  role="alert"
                  className="mb-4 rounded-lg border border-rose-300 dark:border-rose-700/60 bg-rose-50 dark:bg-rose-950/60 px-3.5 py-2.5 text-xs font-medium text-rose-800 dark:text-rose-200"
                >
                  {errorMsg}
                </div>
              )}

              <form onSubmit={handleBootstrapSubmit} className="space-y-4">
                <div>
                  <label htmlFor="setup-username" className="block text-xs font-semibold text-[var(--hb-text)] mb-1.5">
                    نام کاربری (انگلیسی)
                  </label>
                  <input
                    id="setup-username"
                    type="text"
                    dir="ltr"
                    value={setupUsername}
                    onChange={(e) => setSetupUsername(e.target.value)}
                    placeholder="admin"
                    className="w-full h-11 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-3 text-sm text-left focus:border-[var(--hb-brand)] focus:outline-none"
                  />
                </div>
                <div>
                  <label htmlFor="setup-display" className="block text-xs font-semibold text-[var(--hb-text)] mb-1.5">
                    نام و نام‌خانوادگی مدیر
                  </label>
                  <input
                    id="setup-display"
                    type="text"
                    value={setupDisplayName}
                    onChange={(e) => setSetupDisplayName(e.target.value)}
                    placeholder="مثال: مدیر کل دفتر"
                    className="w-full h-11 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-3 text-sm focus:border-[var(--hb-brand)] focus:outline-none"
                  />
                </div>
                <div>
                  <label htmlFor="setup-pass" className="block text-xs font-semibold text-[var(--hb-text)] mb-1.5">
                    رمز عبور (حداقل ۸ کاراکتر)
                  </label>
                  <input
                    id="setup-pass"
                    type={showPass ? 'text' : 'password'}
                    dir="ltr"
                    value={setupPassword}
                    onChange={(e) => setSetupPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full h-11 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-3 text-sm text-left focus:border-[var(--hb-brand)] focus:outline-none"
                  />
                </div>
                <div>
                  <label htmlFor="setup-confirm" className="block text-xs font-semibold text-[var(--hb-text)] mb-1.5">
                    تکرار رمز عبور
                  </label>
                  <input
                    id="setup-confirm"
                    type={showPass ? 'text' : 'password'}
                    dir="ltr"
                    value={setupConfirm}
                    onChange={(e) => setSetupConfirm(e.target.value)}
                    placeholder="••••••••"
                    className="w-full h-11 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-3 text-sm text-left focus:border-[var(--hb-brand)] focus:outline-none"
                  />
                </div>
                <button
                  type="submit"
                  disabled={submitting}
                  className="w-full h-11 rounded-lg bg-[var(--hb-primary-bg)] hover:bg-[var(--hb-primary-hover)] text-[var(--hb-primary-text)] text-sm font-bold transition-colors disabled:opacity-60"
                >
                  {submitting ? 'در حال ایجاد حساب...' : 'ثبت مدیر نخستین و ورود'}
                </button>
              </form>
            </>
          ) : (
            <>
              <div className="mb-6">
                <h1 className="text-xl font-bold text-[var(--hb-text)]">ورود به سامانهٔ داخلی</h1>
                <p className="mt-1.5 text-sm text-[var(--hb-muted)]">
                  مدیریت ارجاع، پیگیری درخواست‌های مردمی و گزارش‌دهی دفتر
                </p>
              </div>

              {errorMsg && (
                <div
                  role="alert"
                  className="mb-4 rounded-lg border border-rose-300 dark:border-rose-700/60 bg-rose-50 dark:bg-rose-950/60 px-3.5 py-2.5 text-xs font-medium text-rose-800 dark:text-rose-200"
                >
                  {errorMsg}
                </div>
              )}

              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label htmlFor="login-username" className="block text-xs font-semibold text-[var(--hb-text)] mb-1.5">
                    نام کاربری
                  </label>
                  <div className="relative">
                    <UserIcon className="w-4 h-4 text-[var(--hb-muted)] absolute start-3 top-1/2 -translate-y-1/2" aria-hidden="true" />
                    <input
                      id="login-username"
                      type="text"
                      dir="ltr"
                      autoComplete="username"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      placeholder="username"
                      className="w-full h-11 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] ps-9 pe-3 text-sm text-left focus:border-[var(--hb-brand)] focus:outline-none"
                    />
                  </div>
                </div>

                <div>
                  <label htmlFor="login-password" className="block text-xs font-semibold text-[var(--hb-text)] mb-1.5">
                    رمز عبور
                  </label>
                  <div className="relative">
                    <Lock className="w-4 h-4 text-[var(--hb-muted)] absolute start-3 top-1/2 -translate-y-1/2" aria-hidden="true" />
                    <input
                      id="login-password"
                      type={showPass ? 'text' : 'password'}
                      dir="ltr"
                      autoComplete="current-password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="••••••••"
                      className="w-full h-11 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] ps-9 pe-10 text-sm text-left focus:border-[var(--hb-brand)] focus:outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPass((s) => !s)}
                      aria-label={showPass ? 'پنهان‌کردن رمز عبور' : 'نمایش رمز عبور'}
                      className="absolute end-1.5 top-1/2 -translate-y-1/2 inline-flex h-8 w-8 items-center justify-center rounded-md text-[var(--hb-muted)] hover:bg-slate-200/60 dark:hover:bg-slate-800"
                    >
                      {showPass ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                <button
                  type="submit"
                  disabled={submitting}
                  className="w-full h-11 rounded-lg bg-[var(--hb-primary-bg)] hover:bg-[var(--hb-primary-hover)] text-[var(--hb-primary-text)] text-sm font-bold transition-colors disabled:opacity-60"
                >
                  {submitting ? 'در حال بررسی اعتبار...' : 'ورود به میز کار'}
                </button>
              </form>
            </>
          )}
        </div>
      </main>

      <footer className="text-center text-xs text-[var(--hb-muted)] py-2">
        هرمزگان بیدار — سامانهٔ داخلی پیگیری پیام‌های مردمی
      </footer>
    </div>
  );
};

export default LoginPage;
