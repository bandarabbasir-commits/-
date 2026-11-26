import React, { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ChevronDown,
  ChevronLeft,
  ChevronsDownUp,
  ChevronsUpDown,
  Edit3,
  KeyRound,
  Plus,
  Search,
  Trash2,
  UserCheck,
  UserX,
} from 'lucide-react';
import type { AdminUserItem, RoleName } from '../types/api';
import { ApiError, apiFetch } from '../utils/api';
import { toPersianDigits } from '../utils/persian';
import { useToast } from '../components/ToastProvider';
import { Modal } from '../components/Modal';
import { useOnlineStatus } from '../hooks/useOnlineStatus';

const ALL_ROLES: Array<{ id: RoleName; label: string }> = [
  { id: 'employee', label: 'کارمند / پیگیری' },
  { id: 'expert', label: 'کارشناس تخصصی' },
  { id: 'author', label: 'نگارنده (ثبت پیش‌نویس)' },
  { id: 'manager', label: 'مدیر دفتر / ارجاع' },
  { id: 'admin', label: 'مدیر سامانه (ادمین)' },
];

const ACCESS_LABELS: Record<'employee' | 'supervisor' | 'expert', string> = {
  employee: 'کارمند',
  supervisor: 'ناظر / سرپرست',
  expert: 'کارشناس',
};

const ORG_ROLE_LABELS: Record<'followup' | 'referral' | 'office' | 'technical', string> = {
  followup: 'پیگیری',
  referral: 'ارجاع',
  office: 'امور اداری / دفتری',
  technical: 'فنی / تخصصی',
};

const UsersPage: React.FC = () => {
  const { pushToast } = useToast();
  const isOnline = useOnlineStatus();
  const qc = useQueryClient();

  const [searchInput, setSearchInput] = useState('');
  const [debouncedQ, setDebouncedQ] = useState('');
  const [collapsedDepts, setCollapsedDepts] = useState<Record<string, boolean>>({});

  // Create / Edit User Modal
  const [formOpen, setFormOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<AdminUserItem | null>(null);
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [password, setPassword] = useState('');
  const [jobTitle, setJobTitle] = useState('');
  const [department, setDepartment] = useState('عمومی');
  const [accessLevel, setAccessLevel] = useState<'employee' | 'supervisor' | 'expert'>('employee');
  const [orgRoleType, setOrgRoleType] = useState<'followup' | 'referral' | 'office' | 'technical'>('followup');
  const [roles, setRoles] = useState<RoleName[]>(['employee']);

  // Password Reset Modal
  const [pwdUser, setPwdUser] = useState<AdminUserItem | null>(null);
  const [newPassword, setNewPassword] = useState('');

  // Delete Confirm Modal
  const [deleteUser, setDeleteUser] = useState<AdminUserItem | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setDebouncedQ(searchInput.trim()), 250);
    return () => window.clearTimeout(t);
  }, [searchInput]);

  const usersQuery = useQuery({
    queryKey: ['admin-users', debouncedQ],
    queryFn: ({ signal }) =>
      apiFetch<{ items: AdminUserItem[] }>(
        `/api/v1/users${debouncedQ ? `?q=${encodeURIComponent(debouncedQ)}` : ''}`,
        { signal }
      ),
  });

  const groupedByDept = useMemo(() => {
    const groups = new Map<string, AdminUserItem[]>();
    for (const u of usersQuery.data?.items || []) {
      const dept = u.department || 'عمومی';
      const arr = groups.get(dept) || [];
      arr.push(u);
      groups.set(dept, arr);
    }
    return Array.from(groups.entries()).sort((a, b) => a[0].localeCompare(b[0], 'fa'));
  }, [usersQuery.data]);

  const openCreateModal = () => {
    setEditingUser(null);
    setUsername('');
    setDisplayName('');
    setPassword('');
    setJobTitle('');
    setDepartment('عمومی');
    setAccessLevel('employee');
    setOrgRoleType('followup');
    setRoles(['employee']);
    setFormOpen(true);
  };

  const openEditModal = (u: AdminUserItem) => {
    setEditingUser(u);
    setUsername(u.username);
    setDisplayName(u.display_name);
    setPassword('');
    setJobTitle(u.job_title);
    setDepartment(u.department);
    setAccessLevel(u.display_access_level);
    setOrgRoleType(u.org_role_type);
    setRoles(u.roles.length > 0 ? u.roles : ['employee']);
    setFormOpen(true);
  };

  const toggleRole = (role: RoleName) => {
    setRoles((prev) => (prev.includes(role) ? prev.filter((r) => r !== role) : [...prev, role]));
  };

  const saveMut = useMutation({
    mutationFn: async () => {
      if (displayName.trim().length < 2) throw new ApiError(422, 'نام و نام خانوادگی حداقل ۲ کاراکتر باشد.');
      if (roles.length === 0) throw new ApiError(422, 'انتخاب حداقل یک نقش الزامی است.');
      if (editingUser) {
        return apiFetch(`/api/v1/users/${editingUser.id}`, {
          method: 'PATCH',
          body: {
            display_name: displayName.trim(),
            job_title: jobTitle.trim(),
            department: department.trim() || 'عمومی',
            display_access_level: accessLevel,
            org_role_type: orgRoleType,
            roles,
            version: editingUser.version,
          },
        });
      }
      if (!/^[A-Za-z0-9_.\-]{2,64}$/.test(username.trim())) {
        throw new ApiError(422, 'نام کاربری باید ۲ تا ۶۴ کاراکتر انگلیسی، عدد یا _ . - باشد.');
      }
      if (password.length < 8) {
        throw new ApiError(422, 'رمز عبور باید حداقل ۸ کاراکتر باشد.');
      }
      return apiFetch('/api/v1/users', {
        method: 'POST',
        body: {
          username: username.trim(),
          display_name: displayName.trim(),
          password,
          job_title: jobTitle.trim(),
          department: department.trim() || 'عمومی',
          display_access_level: accessLevel,
          org_role_type: orgRoleType,
          roles,
        },
      });
    },
    onSuccess: () => {
      pushToast('success', editingUser ? 'مشخصات و نقش‌های کاربر به‌روزرسانی شد.' : 'کاربر جدید با موفقیت ایجاد شد.');
      setFormOpen(false);
      setEditingUser(null);
      qc.invalidateQueries({ queryKey: ['admin-users'] });
    },
    onError: (err) => pushToast('error', err instanceof ApiError ? err.message : 'خطا در ذخیره اطلاعات کاربر.'),
  });

  const statusMut = useMutation({
    mutationFn: (u: AdminUserItem) =>
      apiFetch<{
        id: number;
        is_active: boolean;
        open_assignment_count: number;
        reassignment_warning: string | null;
      }>(`/api/v1/users/${u.id}/status`, {
        method: 'POST',
        body: { is_active: !u.is_active, version: u.version },
      }),
    onSuccess: (res) => {
      if (res.reassignment_warning) {
        pushToast('warning', res.reassignment_warning);
      } else {
        pushToast('success', res.is_active ? 'حساب کاربر فعال شد.' : 'حساب کاربر غیرفعال و نشست‌های آن بسته شد.');
      }
      qc.invalidateQueries({ queryKey: ['admin-users'] });
    },
    onError: (err) => pushToast('error', err instanceof ApiError ? err.message : 'تغییر وضعیت ناموفق بود.'),
  });

  const pwdMut = useMutation({
    mutationFn: () => {
      if (!pwdUser) throw new ApiError(400, 'کاربر انتخاب نشده است.');
      if (newPassword.length < 8) throw new ApiError(422, 'رمز عبور جدید باید حداقل ۸ کاراکتر باشد.');
      return apiFetch(`/api/v1/users/${pwdUser.id}/password`, {
        method: 'POST',
        body: { new_password: newPassword },
      });
    },
    onSuccess: () => {
      pushToast('success', 'رمز عبور بازنشانی شد و تمام نشست‌های فعال کاربر لغو گردید.');
      setPwdUser(null);
      setNewPassword('');
      qc.invalidateQueries({ queryKey: ['admin-users'] });
    },
    onError: (err) => pushToast('error', err instanceof ApiError ? err.message : 'خطا در بازنشانی رمز عبور.'),
  });

  const deleteMut = useMutation({
    mutationFn: (u: AdminUserItem) =>
      apiFetch(`/api/v1/users/${u.id}`, {
        method: 'DELETE',
      }),
    onSuccess: () => {
      pushToast('success', 'کاربر به صورت نرم حذف شد و دسترسی آن قطع گردید.');
      setDeleteUser(null);
      qc.invalidateQueries({ queryKey: ['admin-users'] });
    },
    onError: (err) => pushToast('error', err instanceof ApiError ? err.message : 'امکان حذف این کاربر وجود ندارد.'),
  });

  const setAllCollapsed = (collapsed: boolean) => {
    const next: Record<string, boolean> = {};
    for (const [dept] of groupedByDept) next[dept] = collapsed;
    setCollapsedDepts(next);
  };

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] p-4 flex flex-wrap items-center justify-between gap-3">
        <div className="relative flex-1 min-w-[220px] max-w-md">
          <Search className="w-4 h-4 text-[var(--hb-muted)] absolute start-3 top-1/2 -translate-y-1/2" aria-hidden="true" />
          <input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="جستجو در نام، نام کاربری، سمت یا بخش..."
            className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] ps-9 pe-3 py-2 text-xs text-[var(--hb-text)]"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setAllCollapsed(false)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--hb-border)] px-3 py-2 text-xs font-medium text-[var(--hb-text)] hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <ChevronsUpDown className="w-3.5 h-3.5" aria-hidden="true" />
            <span>بازکردن همه بخش‌ها</span>
          </button>
          <button
            type="button"
            onClick={() => setAllCollapsed(true)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--hb-border)] px-3 py-2 text-xs font-medium text-[var(--hb-text)] hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <ChevronsDownUp className="w-3.5 h-3.5" aria-hidden="true" />
            <span>بستن همه بخش‌ها</span>
          </button>
          <button
            type="button"
            disabled={!isOnline}
            onClick={openCreateModal}
            className="inline-flex items-center gap-1.5 rounded-lg bg-[var(--hb-primary-bg)] hover:bg-[var(--hb-primary-hover)] text-[var(--hb-primary-text)] px-3.5 py-2 text-xs font-bold disabled:opacity-50"
          >
            <Plus className="w-4 h-4" aria-hidden="true" />
            <span>افزودن کاربر جدید</span>
          </button>
        </div>
      </div>

      {usersQuery.isLoading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((n) => (
            <div key={n} className="h-24 rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] animate-pulse" />
          ))}
        </div>
      ) : groupedByDept.length === 0 ? (
        <div className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] py-12 text-center text-sm text-[var(--hb-muted)]">
          کاربری با این مشخصات یافت نشد.
        </div>
      ) : (
        <div className="space-y-3">
          {groupedByDept.map(([dept, items]) => {
            const isCollapsed = !!collapsedDepts[dept];
            return (
              <section
                key={dept}
                className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] overflow-hidden"
              >
                <button
                  type="button"
                  onClick={() => setCollapsedDepts((prev) => ({ ...prev, [dept]: !prev[dept] }))}
                  className="w-full px-4 py-3 flex items-center justify-between bg-slate-50/70 dark:bg-slate-900/30 border-b border-[var(--hb-border)] text-start"
                >
                  <div className="flex items-center gap-2">
                    {isCollapsed ? (
                      <ChevronLeft className="w-4 h-4 text-[var(--hb-muted)]" />
                    ) : (
                      <ChevronDown className="w-4 h-4 text-[var(--hb-muted)]" />
                    )}
                    <h2 className="text-sm font-bold text-[var(--hb-text)]">{dept}</h2>
                  </div>
                  <span className="text-xs text-[var(--hb-muted)] tabular-nums">
                    {toPersianDigits(items.length)} کاربر
                  </span>
                </button>

                {!isCollapsed && (
                  <div className="divide-y divide-[var(--hb-border)]">
                    {items.map((u) => (
                      <div
                        key={u.id}
                        className="px-4 py-3 flex flex-col md:flex-row md:items-center justify-between gap-3"
                      >
                        <div className="flex items-start gap-3 min-w-0">
                          <span
                            className="inline-flex h-10 w-10 items-center justify-center rounded-full text-xs font-bold text-white shrink-0"
                            style={{ backgroundColor: u.avatar_color || '#0F766E' }}
                            aria-hidden="true"
                          >
                            {u.display_name.trim().charAt(0)}
                          </span>
                          <div className="min-w-0 space-y-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-sm font-bold text-[var(--hb-text)]">{u.display_name}</span>
                              <span dir="ltr" className="text-xs text-[var(--hb-muted)] font-mono">
                                @{u.username}
                              </span>
                              {!u.is_active && (
                                <span className="text-[11px] font-bold text-rose-700 dark:text-rose-300">
                                  (غیرفعال)
                                </span>
                              )}
                            </div>
                            <div className="text-xs text-[var(--hb-muted)] flex flex-wrap items-center gap-x-3 gap-y-1">
                              <span>{u.job_title || 'بدون عنوان شغلی'}</span>
                              <span>·</span>
                              <span>سطح نمایشی: {ACCESS_LABELS[u.display_access_level]}</span>
                              <span>·</span>
                              <span>نقش سازمانی: {ORG_ROLE_LABELS[u.org_role_type]}</span>
                              {u.open_assignment_count > 0 && (
                                <>
                                  <span>·</span>
                                  <span className="text-amber-700 dark:text-amber-300 tabular-nums font-semibold">
                                    {toPersianDigits(u.open_assignment_count)} پرونده باز
                                  </span>
                                </>
                              )}
                            </div>
                            <div className="flex flex-wrap gap-1.5 pt-0.5">
                              {u.roles.map((r) => (
                                <span
                                  key={r}
                                  className="inline-flex items-center rounded-md border border-[var(--hb-border)] bg-[var(--hb-active-tint)] px-2 py-0.5 text-[11px] font-medium text-[var(--hb-active-text)]"
                                >
                                  {ALL_ROLES.find((ar) => ar.id === r)?.label || r}
                                </span>
                              ))}
                            </div>
                          </div>
                        </div>

                        <div className="flex flex-wrap items-center gap-1.5 shrink-0">
                          <button
                            type="button"
                            disabled={!isOnline}
                            onClick={() => openEditModal(u)}
                            className="inline-flex items-center gap-1 rounded-lg border border-[var(--hb-border)] px-2.5 py-1.5 text-xs font-medium hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50"
                          >
                            <Edit3 className="w-3.5 h-3.5" aria-hidden="true" />
                            <span>ویرایش</span>
                          </button>
                          <button
                            type="button"
                            disabled={!isOnline}
                            onClick={() => {
                              setPwdUser(u);
                              setNewPassword('');
                            }}
                            className="inline-flex items-center gap-1 rounded-lg border border-[var(--hb-border)] px-2.5 py-1.5 text-xs font-medium hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50"
                          >
                            <KeyRound className="w-3.5 h-3.5" aria-hidden="true" />
                            <span>تغییر رمز</span>
                          </button>
                          <button
                            type="button"
                            disabled={!isOnline || statusMut.isPending}
                            onClick={() => statusMut.mutate(u)}
                            className={`inline-flex items-center gap-1 rounded-lg border border-[var(--hb-border)] px-2.5 py-1.5 text-xs font-medium disabled:opacity-50 ${
                              u.is_active
                                ? 'text-amber-700 dark:text-amber-300 hover:bg-amber-50 dark:hover:bg-amber-950/30'
                                : 'text-emerald-700 dark:text-emerald-300 hover:bg-emerald-50 dark:hover:bg-emerald-950/30'
                            }`}
                          >
                            {u.is_active ? (
                              <>
                                <UserX className="w-3.5 h-3.5" aria-hidden="true" />
                                <span>غیرفعال</span>
                              </>
                            ) : (
                              <>
                                <UserCheck className="w-3.5 h-3.5" aria-hidden="true" />
                                <span>فعال‌سازی</span>
                              </>
                            )}
                          </button>
                          <button
                            type="button"
                            disabled={!isOnline}
                            onClick={() => setDeleteUser(u)}
                            className="inline-flex items-center gap-1 rounded-lg border border-[var(--hb-border)] px-2.5 py-1.5 text-xs font-medium text-rose-700 dark:text-rose-300 hover:bg-rose-50 dark:hover:bg-rose-950/40 disabled:opacity-50"
                          >
                            <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
                            <span>حذف</span>
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </section>
            );
          })}
        </div>
      )}

      {/* Create / Edit Modal */}
      <Modal
        open={formOpen}
        title={editingUser ? `ویرایش کاربر: ${editingUser.display_name}` : 'ایجاد حساب کاربری جدید'}
        onClose={() => setFormOpen(false)}
        blockBackdropClose
        maxWidthClass="max-w-xl"
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            saveMut.mutate();
          }}
          className="space-y-4"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-[var(--hb-muted)] mb-1">نام کاربری (لاتین)</label>
              <input
                type="text"
                dir="ltr"
                value={username}
                disabled={!!editingUser}
                onChange={(e) => setUsername(e.target.value)}
                required
                placeholder="ali.rezaei"
                className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-3 py-2 text-xs disabled:opacity-60"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[var(--hb-muted)] mb-1">نام و نام خانوادگی</label>
              <input
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                required
                className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-3 py-2 text-xs"
              />
            </div>
            {!editingUser && (
              <div className="sm:col-span-2">
                <label className="block text-xs font-medium text-[var(--hb-muted)] mb-1">
                  رمز عبور اولیه (حداقل ۸ کاراکتر)
                </label>
                <input
                  type="password"
                  dir="ltr"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={8}
                  className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-3 py-2 text-xs"
                />
              </div>
            )}
            <div>
              <label className="block text-xs font-medium text-[var(--hb-muted)] mb-1">سمت سازمانی</label>
              <input
                type="text"
                value={jobTitle}
                onChange={(e) => setJobTitle(e.target.value)}
                className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-3 py-2 text-xs"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[var(--hb-muted)] mb-1">واحد / بخش</label>
              <input
                type="text"
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                required
                className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-3 py-2 text-xs"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-[var(--hb-muted)] mb-1">سطح نمایشی</label>
              <select
                value={accessLevel}
                onChange={(e) => setAccessLevel(e.target.value as 'employee' | 'supervisor' | 'expert')}
                className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-3 py-2 text-xs"
              >
                <option value="employee">کارمند</option>
                <option value="supervisor">ناظر / سرپرست</option>
                <option value="expert">کارشناس</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-[var(--hb-muted)] mb-1">حوزه وظیفه</label>
              <select
                value={orgRoleType}
                onChange={(e) =>
                  setOrgRoleType(e.target.value as 'followup' | 'referral' | 'office' | 'technical')
                }
                className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-3 py-2 text-xs"
              >
                <option value="followup">پیگیری</option>
                <option value="referral">ارجاع</option>
                <option value="office">امور اداری / دفتری</option>
                <option value="technical">فنی / تخصصی</option>
              </select>
            </div>
          </div>

          <div>
            <div className="text-xs font-semibold text-[var(--hb-text)] mb-2">
              نقش‌های امنیتی (امکان ترکیب هم‌زمان نقش‌ها)
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {ALL_ROLES.map((r) => {
                const checked = roles.includes(r.id);
                return (
                  <label
                    key={r.id}
                    className={`flex items-center gap-2 rounded-lg border px-3 py-2 text-xs cursor-pointer ${
                      checked
                        ? 'border-[var(--hb-brand)] bg-[var(--hb-active-tint)] font-semibold'
                        : 'border-[var(--hb-border)]'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggleRole(r.id)}
                      className="accent-teal-600"
                    />
                    <span>{r.label}</span>
                  </label>
                );
              })}
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={() => setFormOpen(false)}
              className="rounded-lg border border-[var(--hb-border)] px-4 py-2 text-xs font-medium"
            >
              انصراف
            </button>
            <button
              type="submit"
              disabled={!isOnline || saveMut.isPending}
              className="rounded-lg bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)] px-4 py-2 text-xs font-bold disabled:opacity-50"
            >
              {saveMut.isPending ? 'در حال ذخیره...' : editingUser ? 'ذخیره تغییرات' : 'ایجاد کاربر'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Password Reset Modal */}
      <Modal
        open={!!pwdUser}
        title={`بازنشانی رمز عبور: ${pwdUser?.display_name || ''}`}
        onClose={() => setPwdUser(null)}
        blockBackdropClose
        maxWidthClass="max-w-sm"
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            pwdMut.mutate();
          }}
          className="space-y-4"
        >
          <p className="text-xs text-[var(--hb-muted)] leading-relaxed">
            پس از تغییر رمز عبور، تمام نشست‌های فعال این کاربر فوراً قطع می‌شود و ملزم به ورود مجدد خواهد بود.
          </p>
          <div>
            <label className="block text-xs font-medium text-[var(--hb-muted)] mb-1">
              رمز عبور جدید (حداقل ۸ کاراکتر)
            </label>
            <input
              type="password"
              dir="ltr"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              minLength={8}
              required
              className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-3 py-2 text-xs"
            />
          </div>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setPwdUser(null)}
              className="rounded-lg border border-[var(--hb-border)] px-4 py-2 text-xs font-medium"
            >
              انصراف
            </button>
            <button
              type="submit"
              disabled={!isOnline || pwdMut.isPending}
              className="rounded-lg bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)] px-4 py-2 text-xs font-bold disabled:opacity-50"
            >
              {pwdMut.isPending ? 'در حال ثبت...' : 'تغییر رمز و قطع نشست‌ها'}
            </button>
          </div>
        </form>
      </Modal>

      {/* Soft Delete Confirmation Modal */}
      <Modal
        open={!!deleteUser}
        title="تأیید حذف نرم کاربر"
        onClose={() => setDeleteUser(null)}
        blockBackdropClose
        maxWidthClass="max-w-sm"
      >
        <div className="space-y-4 text-xs">
          <p className="text-[var(--hb-text)] leading-relaxed">
            آیا از حذف کاربر <strong>{deleteUser?.display_name}</strong> (@{deleteUser?.username}) اطمینان دارید؟
            سوابق ارجاعات و گزارش‌های قبلی حفظ می‌شوند اما امکان ورود کاربر برای همیشه مسدود خواهد شد.
          </p>
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={() => setDeleteUser(null)}
              className="rounded-lg border border-[var(--hb-border)] px-4 py-2 font-medium"
            >
              انصراف
            </button>
            <button
              type="button"
              disabled={!isOnline || deleteMut.isPending}
              onClick={() => deleteUser && deleteMut.mutate(deleteUser)}
              className="rounded-lg bg-rose-600 text-white px-4 py-2 font-bold disabled:opacity-50"
            >
              {deleteMut.isPending ? 'در حال حذف...' : 'تأیید حذف'}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
};

export default UsersPage;
