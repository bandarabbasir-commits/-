import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  Archive,
  Bell,
  BellPlus,
  CheckCircle2,
  Clock,
  Edit3,
  Eye,
  FileDown,
  Filter,
  Folder,
  FolderPlus,
  Forward,
  Lock,
  MessageSquarePlus,
  RefreshCw,
  RotateCcw,
  Search,
  Send,
  Trash2,
  X,
} from 'lucide-react';
import type {
  ActionFlagType,
  AuthUser,
  DirectoryUser,
  FolderItem,
  PriorityType,
  TaskDetail,
  TaskListItem,
  TaskReminderItem,
  TaskStatusType,
} from '../types/api';
import { ApiError, apiFetch, downloadAuthenticatedFile } from '../utils/api';
import { getTehranPlusHoursDefaults } from '../utils/jalali';
import { toPersianDigits } from '../utils/persian';
import { useToast } from '../components/ToastProvider';
import { JalaliDatePicker } from '../components/JalaliDatePicker';
import { StaffSelector } from '../components/StaffSelector';
import { Modal } from '../components/Modal';
import { useOnlineStatus } from '../hooks/useOnlineStatus';

interface InboxPageProps {
  user: AuthUser;
  selectedTaskIdFromNotif: number | null;
  onClearNotifTask: () => void;
}

interface TasksResponse {
  items: TaskListItem[];
  next_cursor: string | null;
  has_more: boolean;
  counters: { pending: number; in_progress: number; urgent: number; total: number };
  sender_tabs: Array<{ sender_id: number; display_name: string; count: number }>;
}

const PRIORITY_STYLE: Record<PriorityType, string> = {
  urgent: 'text-rose-700 dark:text-rose-300 font-bold',
  medium: 'text-amber-700 dark:text-amber-300 font-semibold',
  normal: 'text-[var(--hb-muted)] font-medium',
};

const STATUS_STYLE: Record<TaskStatusType, string> = {
  pending: 'text-amber-700 dark:text-amber-300',
  in_progress: 'text-teal-700 dark:text-teal-300',
  success: 'text-emerald-700 dark:text-emerald-300',
  failed: 'text-rose-700 dark:text-rose-300',
};

const InboxPage: React.FC<InboxPageProps> = ({
  user,
  selectedTaskIdFromNotif,
  onClearNotifTask,
}) => {
  const { pushToast } = useToast();
  const isOnline = useOnlineStatus();
  const qc = useQueryClient();
  const isManager = user.roles.includes('manager');

  const [viewMode, setViewMode] = useState<'my' | 'supervision'>('my');
  const [tab, setTab] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [priorityFilter, setPriorityFilter] = useState<string>('all');
  const [quickTime, setQuickTime] = useState<string>('');
  const [createdFrom, setCreatedFrom] = useState<string>('');
  const [createdTo, setCreatedTo] = useState<string>('');
  const [actionFrom, setActionFrom] = useState<string>('');
  const [actionTo, setActionTo] = useState<string>('');
  const [selectedFolderId, setSelectedFolderId] = useState<number | null>(null);
  const [searchInput, setSearchInput] = useState<string>('');
  const [debouncedQ, setDebouncedQ] = useState<string>('');
  const [showFilters, setShowFilters] = useState<boolean>(false);

  const [cursorStack, setCursorStack] = useState<string[]>([]);
  const [currentCursor, setCurrentCursor] = useState<string | null>(null);

  const [newFolderName, setNewFolderName] = useState('');
  const [showFolderForm, setShowFolderForm] = useState(false);

  // Task detail modal state
  const [openTaskId, setOpenTaskId] = useState<number | null>(null);
  const viewedIdsRef = useRef<Set<string>>(new Set());

  // Action form state inside modal
  const [actionStatus, setActionStatus] = useState<'in_progress' | 'success' | 'failed'>('in_progress');
  const [actionReport, setActionReport] = useState('');
  const [actionPrivate, setActionPrivate] = useState(false);
  const [forwardOpen, setForwardOpen] = useState(false);
  const [forwardIds, setForwardIds] = useState<number[]>([]);
  const [forwardReason, setForwardReason] = useState('');
  const [actionError, setActionError] = useState('');

  // Note & Reminder state
  const [noteBody, setNoteBody] = useState('');
  const [noteVis, setNoteVis] = useState<'private' | 'shared_active_manager'>('private');
  const [noteError, setNoteError] = useState('');
  const [remDate, setRemDate] = useState(() => getTehranPlusHoursDefaults(24).jalaliDate);
  const [remTime, setRemTime] = useState(() => getTehranPlusHoursDefaults(24).tehranTime);
  const [remNote, setRemNote] = useState('');
  const [remError, setRemError] = useState('');

  // Manager edit / reassign state inside detail modal
  const [mgrEditOpen, setMgrEditOpen] = useState(false);
  const [mgrPriority, setMgrPriority] = useState<PriorityType>('normal');
  const [mgrActionFlag, setMgrActionFlag] = useState<ActionFlagType>('action');
  const [mgrNote, setMgrNote] = useState('');
  const [mgrReceivers, setMgrReceivers] = useState<number[]>([]);
  const [mgrEditError, setMgrEditError] = useState('');

  // Reopen modal state
  const [reopenModalOpen, setReopenModalOpen] = useState(false);
  const [reopenReason, setReopenReason] = useState('');
  const [reopenReceivers, setReopenReceivers] = useState<number[]>([]);
  const [reopenError, setReopenError] = useState('');

  useEffect(() => {
    const t = window.setTimeout(() => {
      setDebouncedQ(searchInput.trim());
      setCurrentCursor(null);
      setCursorStack([]);
    }, 250);
    return () => window.clearTimeout(t);
  }, [searchInput]);

  useEffect(() => {
    if (selectedTaskIdFromNotif !== null) {
      setOpenTaskId(selectedTaskIdFromNotif);
      onClearNotifTask();
    }
  }, [selectedTaskIdFromNotif, onClearNotifTask]);

  const queryParamsString = useMemo(() => {
    const p = new URLSearchParams();
    p.set('view_mode', viewMode);
    p.set('tab', tab);
    p.set('status', statusFilter);
    p.set('priority', priorityFilter);
    p.set('limit', '25');
    if (debouncedQ) p.set('q', debouncedQ);
    if (quickTime) p.set('quick_time', quickTime);
    if (createdFrom) p.set('created_from', createdFrom);
    if (createdTo) p.set('created_to', createdTo);
    if (actionFrom) p.set('action_from', actionFrom);
    if (actionTo) p.set('action_to', actionTo);
    if (selectedFolderId !== null) p.set('folder_id', String(selectedFolderId));
    if (currentCursor) p.set('cursor', currentCursor);
    return p.toString();
  }, [
    viewMode,
    tab,
    statusFilter,
    priorityFilter,
    debouncedQ,
    quickTime,
    createdFrom,
    createdTo,
    actionFrom,
    actionTo,
    selectedFolderId,
    currentCursor,
  ]);

  const tasksQuery = useQuery({
    queryKey: ['tasks', queryParamsString],
    queryFn: ({ signal }) => apiFetch<TasksResponse>(`/api/v1/tasks?${queryParamsString}`, { signal }),
  });

  const foldersQuery = useQuery({
    queryKey: ['personal-folders'],
    queryFn: ({ signal }) => apiFetch<{ items: FolderItem[] }>('/api/v1/folders', { signal }),
  });

  const directoryQuery = useQuery({
    queryKey: ['directory-assignable'],
    queryFn: ({ signal }) =>
      apiFetch<{ items: DirectoryUser[] }>('/api/v1/users/directory?assignable_only=true', { signal }),
    enabled: openTaskId !== null || reopenModalOpen,
  });

  const detailQuery = useQuery({
    queryKey: ['task-detail', openTaskId],
    queryFn: ({ signal }) => apiFetch<TaskDetail>(`/api/v1/tasks/${openTaskId}`, { signal }),
    enabled: openTaskId !== null,
  });

  const remindersQuery = useQuery({
    queryKey: ['task-reminders', openTaskId],
    queryFn: ({ signal }) => apiFetch<{ items: TaskReminderItem[] }>(`/api/v1/tasks/${openTaskId}/reminders`, { signal }),
    enabled: openTaskId !== null,
  });

  // Record explicit POST /view once per modal open with idempotency key
  useEffect(() => {
    if (openTaskId === null || !detailQuery.data) return;
    const key = `${openTaskId}:${detailQuery.data.version}`;
    if (viewedIdsRef.current.has(key)) return;
    viewedIdsRef.current.add(key);

    apiFetch(`/api/v1/tasks/${openTaskId}/view`, {
      method: 'POST',
      headers: { 'Idempotency-Key': `ui-open-${openTaskId}-${Date.now()}` },
    })
      .then(() => {
        qc.invalidateQueries({ queryKey: ['tasks'] });
      })
      .catch(() => {
        // Ignore non-fatal view telemetry error
      });
  }, [openTaskId, detailQuery.data, qc]);

  const resetDetailForm = () => {
    const plus24 = getTehranPlusHoursDefaults(24);
    setActionStatus('in_progress');
    setActionReport('');
    setActionPrivate(false);
    setForwardOpen(false);
    setForwardIds([]);
    setForwardReason('');
    setActionError('');
    setNoteBody('');
    setNoteError('');
    setRemDate(plus24.jalaliDate);
    setRemTime(plus24.tehranTime);
    setRemNote('');
    setRemError('');
    setMgrEditOpen(false);
    setMgrEditError('');
    setReopenError('');
  };

  const openManagerEdit = (d: TaskDetail) => {
    setMgrPriority(d.priority);
    setMgrActionFlag(d.action_flag);
    setMgrNote(d.manager_note || '');
    setMgrReceivers(d.receivers.map((r) => r.id));
    setMgrEditError('');
    setMgrEditOpen(true);
  };

  const handleOpenTask = (tid: number) => {
    resetDetailForm();
    setOpenTaskId(tid);
  };

  const createFolderMut = useMutation({
    mutationFn: (name: string) => apiFetch<FolderItem>('/api/v1/folders', { method: 'POST', body: { name } }),
    onSuccess: () => {
      setNewFolderName('');
      setShowFolderForm(false);
      qc.invalidateQueries({ queryKey: ['personal-folders'] });
      pushToast('success', 'فولدر شخصی ایجاد شد.');
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const deleteFolderMut = useMutation({
    mutationFn: (fid: number) => apiFetch(`/api/v1/folders/${fid}`, { method: 'DELETE' }),
    onSuccess: (_, fid) => {
      if (selectedFolderId === fid) setSelectedFolderId(null);
      qc.invalidateQueries({ queryKey: ['personal-folders'] });
      qc.invalidateQueries({ queryKey: ['tasks'] });
      pushToast('success', 'فولدر حذف شد (پرونده‌ها دست‌نخورده ماندند).');
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const assignFolderMut = useMutation({
    mutationFn: ({ taskId, folderId }: { taskId: number; folderId: number | null }) =>
      apiFetch(`/api/v1/tasks/${taskId}/folder`, { method: 'PUT', body: { folder_id: folderId } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['personal-folders'] });
      qc.invalidateQueries({ queryKey: ['tasks'] });
      qc.invalidateQueries({ queryKey: ['task-detail', openTaskId] });
      pushToast('success', 'فولدر پرونده به‌روزرسانی شد.');
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const submitActionMut = useMutation({
    mutationFn: async (detail: TaskDetail) => {
      if (!actionReport.trim() || actionReport.trim().length < 3) {
        throw new ApiError(422, 'متن گزارش اقدام باید حداقل ۳ کاراکتر باشد.');
      }
      if (actionStatus === 'in_progress' && forwardOpen && forwardIds.length === 0) {
        throw new ApiError(422, 'برای ارجاع ثانویه حداقل یک همکار را انتخاب کنید یا انصراف دهید.');
      }
      return apiFetch<{ sender_removed?: boolean; task_id: number }>(`/api/v1/tasks/${detail.id}/action`, {
        method: 'POST',
        body: {
          status: actionStatus,
          report_text: actionReport.trim(),
          is_private: actionPrivate,
          forward_to_ids: actionStatus === 'in_progress' && forwardOpen ? forwardIds : [],
          forward_reason: actionStatus === 'in_progress' && forwardOpen ? forwardReason.trim() : '',
          version: detail.version,
          idempotency_key: `act-${detail.id}-${detail.version}-${Date.now()}`,
        },
      });
    },
    onSuccess: (res) => {
      resetDetailForm();
      qc.invalidateQueries({ queryKey: ['tasks'] });
      qc.invalidateQueries({ queryKey: ['personal-folders'] });
      if (res.sender_removed && !isManager) {
        setOpenTaskId(null);
        pushToast('success', 'اقدام و ارجاع ثانویه ثبت شد و پرونده به گیرندهٔ جدید منتقل گردید.');
      } else {
        qc.invalidateQueries({ queryKey: ['task-detail', openTaskId] });
        pushToast('success', 'اقدام با موفقیت ثبت شد.');
      }
    },
    onError: (e: ApiError) => {
      setActionError(e.message);
      pushToast('error', e.message);
    },
  });

  const addNoteMut = useMutation({
    mutationFn: (taskId: number) => {
      if (!noteBody.trim()) {
        throw new ApiError(422, 'متن یادداشت نمی‌تواند خالی باشد.');
      }
      return apiFetch(`/api/v1/tasks/${taskId}/notes`, {
        method: 'POST',
        body: { body: noteBody.trim(), visibility: noteVis },
      });
    },
    onSuccess: () => {
      setNoteBody('');
      setNoteError('');
      qc.invalidateQueries({ queryKey: ['task-detail', openTaskId] });
      pushToast('success', 'یادداشت ثبت شد.');
    },
    onError: (e: ApiError) => {
      setNoteError(e.message);
      pushToast('error', e.message);
    },
  });

  const addReminderMut = useMutation({
    mutationFn: (taskId: number) => {
      if (!remDate.trim()) {
        throw new ApiError(422, 'انتخاب تاریخ شمسی یادآور الزامی است.');
      }
      if (!/^\d{1,2}:\d{2}$/.test(remTime.trim())) {
        throw new ApiError(422, 'فرمت ساعت باید به‌صورت HH:MM (مثال 09:30) باشد.');
      }
      return apiFetch(`/api/v1/tasks/${taskId}/reminders`, {
        method: 'POST',
        body: { jalali_date: remDate.trim(), tehran_time: remTime.trim(), note: remNote.trim() },
      });
    },
    onSuccess: () => {
      const plus24 = getTehranPlusHoursDefaults(24);
      setRemDate(plus24.jalaliDate);
      setRemTime(plus24.tehranTime);
      setRemNote('');
      setRemError('');
      qc.invalidateQueries({ queryKey: ['task-reminders', openTaskId] });
      qc.invalidateQueries({ queryKey: ['task-detail', openTaskId] });
      qc.invalidateQueries({ queryKey: ['tasks'] });
      pushToast('success', 'یادآور پیگیری تنظیم شد.');
    },
    onError: (e: ApiError) => {
      setRemError(e.message);
      pushToast('error', e.message);
    },
  });

  const deleteReminderMut = useMutation({
    mutationFn: ({ taskId, remId }: { taskId: number; remId: number }) =>
      apiFetch(`/api/v1/tasks/${taskId}/reminders/${remId}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['task-reminders', openTaskId] });
      qc.invalidateQueries({ queryKey: ['task-detail', openTaskId] });
      qc.invalidateQueries({ queryKey: ['tasks'] });
      pushToast('success', 'یادآور حذف شد.');
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const managerUpdateMut = useMutation({
    mutationFn: async (detail: TaskDetail) => {
      const isOpen = detail.status === 'pending' || detail.status === 'in_progress';
      if (isOpen && (mgrReceivers.length < 1 || mgrReceivers.length > 2)) {
        throw new ApiError(422, 'انتخاب ۱ یا ۲ گیرنده برای پروندهٔ باز الزامی است.');
      }
      return apiFetch(`/api/v1/tasks/${detail.id}`, {
        method: 'PATCH',
        body: {
          priority: mgrPriority,
          action_flag: mgrActionFlag,
          manager_note: mgrNote.trim(),
          receiver_ids: isOpen ? mgrReceivers : null,
          version: detail.version,
        },
      });
    },
    onSuccess: () => {
      setMgrEditOpen(false);
      setMgrEditError('');
      qc.invalidateQueries({ queryKey: ['task-detail', openTaskId] });
      qc.invalidateQueries({ queryKey: ['tasks'] });
      pushToast('success', 'اطلاعات و ارجاع پرونده با موفقیت ویرایش شد.');
    },
    onError: (e: ApiError) => {
      setMgrEditError(e.message);
      pushToast('error', e.message);
    },
  });

  const archiveTaskMut = useMutation({
    mutationFn: (taskId: number) =>
      apiFetch(`/api/v1/tasks/${taskId}/archive`, { method: 'POST', body: { reason: '' } }),
    onSuccess: () => {
      setOpenTaskId(null);
      qc.invalidateQueries({ queryKey: ['tasks'] });
      qc.invalidateQueries({ queryKey: ['archive'] });
      pushToast('success', 'پرونده به بایگانی کار منتقل شد.');
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const trashTaskMut = useMutation({
    mutationFn: (taskId: number) => apiFetch(`/api/v1/tasks/${taskId}/trash`, { method: 'POST' }),
    onSuccess: () => {
      setOpenTaskId(null);
      qc.invalidateQueries({ queryKey: ['tasks'] });
      pushToast('success', 'پرونده به سطل زباله منتقل شد.');
    },
    onError: (e: ApiError) => pushToast('error', e.message),
  });

  const reopenTaskMut = useMutation({
    mutationFn: (detail: TaskDetail) => {
      if (reopenReason.trim().length < 3) {
        throw new ApiError(422, 'دلیل بازگشایی باید حداقل ۳ کاراکتر باشد.');
      }
      return apiFetch(`/api/v1/tasks/${detail.id}/reopen`, {
        method: 'POST',
        body: { reason: reopenReason.trim(), receiver_ids: reopenReceivers, version: detail.version },
      });
    },
    onSuccess: () => {
      setReopenModalOpen(false);
      setReopenReason('');
      setReopenReceivers([]);
      setReopenError('');
      qc.invalidateQueries({ queryKey: ['task-detail', openTaskId] });
      qc.invalidateQueries({ queryKey: ['tasks'] });
      pushToast('success', 'پرونده بازگشایی شد.');
    },
    onError: (e: ApiError) => {
      setReopenError(e.message);
      pushToast('error', e.message);
    },
  });

  const handleExport = async (fmt: 'word' | 'excel' | 'csv') => {
    try {
      const p = new URLSearchParams(queryParamsString);
      p.delete('cursor');
      p.delete('limit');
      const ext = fmt === 'word' ? 'docx' : fmt === 'excel' ? 'xlsx' : 'csv';
      await downloadAuthenticatedFile(`/api/v1/exports/${fmt}?${p.toString()}`, `hormozgan-tasks.${ext}`);
      pushToast('success', 'فایل خروجی با موفقیت آماده و دریافت شد.');
    } catch (e) {
      pushToast('error', e instanceof ApiError ? e.message : 'خطا در دانلود خروجی');
    }
  };

  const activeFilters = useMemo(() => {
    const chips: Array<{ key: string; label: string; clear: () => void }> = [];
    if (debouncedQ) chips.push({ key: 'q', label: `جستجو: ${debouncedQ}`, clear: () => setSearchInput('') });
    if (statusFilter !== 'all')
      chips.push({ key: 'st', label: `وضعیت: ${statusFilter}`, clear: () => setStatusFilter('all') });
    if (priorityFilter !== 'all')
      chips.push({ key: 'pr', label: `اولویت: ${priorityFilter}`, clear: () => setPriorityFilter('all') });
    if (quickTime)
      chips.push({
        key: 'qt',
        label: quickTime === 'today' ? 'بازه: امروز' : quickTime === 'week' ? 'بازه: این هفته' : 'بازه: این ماه',
        clear: () => setQuickTime(''),
      });
    if (createdFrom || createdTo)
      chips.push({
        key: 'cd',
        label: `ثبت: ${toPersianDigits(createdFrom || '…')} تا ${toPersianDigits(createdTo || '…')}`,
        clear: () => {
          setCreatedFrom('');
          setCreatedTo('');
        },
      });
    if (actionFrom || actionTo)
      chips.push({
        key: 'ad',
        label: `اقدام: ${toPersianDigits(actionFrom || '…')} تا ${toPersianDigits(actionTo || '…')}`,
        clear: () => {
          setActionFrom('');
          setActionTo('');
        },
      });
    if (selectedFolderId !== null) {
      const fname = foldersQuery.data?.items.find((f) => f.id === selectedFolderId)?.name || 'فولدر';
      chips.push({ key: 'fl', label: `فولدر: ${fname}`, clear: () => setSelectedFolderId(null) });
    }
    return chips;
  }, [debouncedQ, statusFilter, priorityFilter, quickTime, createdFrom, createdTo, actionFrom, actionTo, selectedFolderId, foldersQuery.data]);

  const clearAllFilters = () => {
    setSearchInput('');
    setStatusFilter('all');
    setPriorityFilter('all');
    setQuickTime('');
    setCreatedFrom('');
    setCreatedTo('');
    setActionFrom('');
    setActionTo('');
    setSelectedFolderId(null);
    setTab('all');
    setCurrentCursor(null);
    setCursorStack([]);
  };

  const counters = tasksQuery.data?.counters ?? { pending: 0, in_progress: 0, urgent: 0, total: 0 };
  const items = tasksQuery.data?.items ?? [];
  const senderTabs = tasksQuery.data?.sender_tabs ?? [];
  const folders = foldersQuery.data?.items ?? [];

  const detail = detailQuery.data;
  const isAssigneeOnOpenTask = detail ? detail.receivers.some((r) => r.id === user.id) : false;
  const otherReceiversCount = detail
    ? detail.receivers.filter((r) => r.id !== user.id).length
    : 0;
  const maxForwardAllowed = Math.max(0, 2 - otherReceiversCount);

  return (
    <div className="space-y-4">
      {/* Top 3 clean summary counters + Manager Scope Toggle */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
        <div className="grid grid-cols-3 gap-2.5 sm:gap-3 flex-1">
          <div className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] px-3.5 py-2.5">
            <div className="text-[11px] text-[var(--hb-muted)]">در انتظار اقدام</div>
            <div className="mt-0.5 text-lg font-bold text-amber-700 dark:text-amber-300 tabular-nums">
              {toPersianDigits(counters.pending)}
            </div>
          </div>
          <div className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] px-3.5 py-2.5">
            <div className="text-[11px] text-[var(--hb-muted)]">در حال پیگیری</div>
            <div className="mt-0.5 text-lg font-bold text-teal-700 dark:text-teal-300 tabular-nums">
              {toPersianDigits(counters.in_progress)}
            </div>
          </div>
          <div className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] px-3.5 py-2.5">
            <div className="text-[11px] text-[var(--hb-muted)]">پرونده‌های فوری</div>
            <div className="mt-0.5 text-lg font-bold text-rose-700 dark:text-rose-300 tabular-nums">
              {toPersianDigits(counters.urgent)}
            </div>
          </div>
        </div>

        {isManager && (
          <div className="inline-flex rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] p-1 shrink-0 self-start md:self-auto">
            <button
              type="button"
              onClick={() => {
                setViewMode('my');
                setTab('all');
                setCurrentCursor(null);
              }}
              className={`px-3.5 py-2 rounded-lg text-xs font-semibold transition-colors whitespace-nowrap ${
                viewMode === 'my'
                  ? 'bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)]'
                  : 'text-[var(--hb-muted)] hover:text-[var(--hb-text)]'
              }`}
            >
              کارتابل ارجاعی من
            </button>
            <button
              type="button"
              onClick={() => {
                setViewMode('supervision');
                setTab('all');
                setCurrentCursor(null);
              }}
              className={`px-3.5 py-2 rounded-lg text-xs font-semibold transition-colors whitespace-nowrap ${
                viewMode === 'supervision'
                  ? 'bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)]'
                  : 'text-[var(--hb-muted)] hover:text-[var(--hb-text)]'
              }`}
            >
              نظارت کل دفتر
            </button>
          </div>
        )}
      </div>

      {/* Main layout: Personal folders column + Inbox workspace */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-4 items-start">
        {/* Personal Folders Sidebar */}
        <section
          aria-label="فولدرهای شخصی"
          className="xl:col-span-3 rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] p-3"
        >
          <div className="flex items-center justify-between gap-2 mb-2.5">
            <h2 className="text-xs font-bold text-[var(--hb-text)] flex items-center gap-1.5">
              <Folder className="w-4 h-4 text-[var(--hb-brand)]" aria-hidden="true" />
              <span>فولدرهای شخصی من</span>
            </h2>
            <button
              type="button"
              disabled={!isOnline}
              onClick={() => setShowFolderForm((v) => !v)}
              aria-label="ایجاد فولدر جدید"
              className="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-[var(--hb-border)] text-[var(--hb-active-text)] hover:bg-[var(--hb-active-tint)] disabled:opacity-50"
            >
              <FolderPlus className="w-3.5 h-3.5" />
            </button>
          </div>

          {showFolderForm && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (newFolderName.trim()) createFolderMut.mutate(newFolderName.trim());
              }}
              className="mb-2.5 flex items-center gap-1.5"
            >
              <input
                type="text"
                value={newFolderName}
                onChange={(e) => setNewFolderName(e.target.value)}
                placeholder="نام فولدر..."
                className="flex-1 h-8 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-2.5 text-xs focus:border-[var(--hb-brand)] focus:outline-none"
              />
              <button
                type="submit"
                disabled={createFolderMut.isPending}
                className="h-8 px-2.5 rounded-lg bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)] text-xs font-medium"
              >
                ثبت
              </button>
            </form>
          )}

          <div className="flex xl:flex-col gap-1 overflow-x-auto pb-1 xl:pb-0">
            <button
              type="button"
              onClick={() => setSelectedFolderId(null)}
              className={`flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-xs whitespace-nowrap transition-colors ${
                selectedFolderId === null
                  ? 'bg-[var(--hb-active-tint)] text-[var(--hb-active-text)] font-semibold'
                  : 'text-[var(--hb-muted)] hover:bg-slate-100 dark:hover:bg-slate-800/60'
              }`}
            >
              <span>همهٔ پرونده‌های کارتابل</span>
              <span className="tabular-nums">{toPersianDigits(counters.total)}</span>
            </button>

            {folders.map((f) => (
              <div key={f.id} className="flex items-center gap-1 shrink-0">
                <button
                  type="button"
                  onClick={() => setSelectedFolderId(f.id)}
                  className={`flex-1 flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-xs whitespace-nowrap transition-colors ${
                    selectedFolderId === f.id
                      ? 'bg-[var(--hb-active-tint)] text-[var(--hb-active-text)] font-semibold'
                      : 'text-[var(--hb-text)] hover:bg-slate-100 dark:hover:bg-slate-800/60'
                  }`}
                >
                  <span className="truncate">{f.name}</span>
                  <span className="tabular-nums text-[var(--hb-muted)]">{toPersianDigits(f.count)}</span>
                </button>
                <button
                  type="button"
                  disabled={!isOnline}
                  onClick={() => deleteFolderMut.mutate(f.id)}
                  aria-label={`حذف فولدر ${f.name}`}
                  className="inline-flex h-7 w-7 items-center justify-center rounded-md text-[var(--hb-muted)] hover:text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/40 shrink-0"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </section>

        {/* Main Inbox Column */}
        <section className="xl:col-span-9 space-y-3 min-w-0">
          {/* Sub-tabs */}
          <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
            {[
              { id: 'all', label: 'همه' },
              { id: 'sms', label: 'پیامک‌ها' },
              ...senderTabs.map((st) => ({
                id: `sender:${st.sender_id}`,
                label: `از ${st.display_name} (${toPersianDigits(st.count)})`,
              })),
              { id: 'done', label: 'پایان‌یافته' },
            ].map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => {
                  setTab(t.id);
                  setCurrentCursor(null);
                  setCursorStack([]);
                }}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap border transition-colors ${
                  tab === t.id
                    ? 'border-[var(--hb-brand)] bg-[var(--hb-active-tint)] text-[var(--hb-active-text)] font-bold'
                    : 'border-[var(--hb-border)] bg-[var(--hb-surface)] text-[var(--hb-muted)] hover:text-[var(--hb-text)]'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Search & Actions Toolbar */}
          <div className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] p-3 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative flex-1 min-w-[200px]">
                <Search className="w-4 h-4 text-[var(--hb-muted)] absolute start-3 top-1/2 -translate-y-1/2" aria-hidden="true" />
                <input
                  type="text"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  placeholder="جستجو در متن درخواست یا گزارش اقدامات (با پشتیبانی ی/ک و ارقام)..."
                  aria-label="جستجو در پرونده‌ها"
                  className="w-full h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] ps-9 pe-3 text-xs sm:text-sm focus:border-[var(--hb-brand)] focus:outline-none"
                />
              </div>

              <button
                type="button"
                onClick={() => setShowFilters((s) => !s)}
                aria-expanded={showFilters}
                className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-[var(--hb-border)] px-3 text-xs font-medium hover:bg-slate-50 dark:hover:bg-slate-800 whitespace-nowrap"
              >
                <Filter className="w-4 h-4" />
                <span>فیلترها</span>
              </button>

              <button
                type="button"
                onClick={() => tasksQuery.refetch()}
                aria-label="تازه‌سازی فهرست"
                className="inline-flex h-10 w-10 items-center justify-center rounded-lg border border-[var(--hb-border)] hover:bg-slate-50 dark:hover:bg-slate-800 shrink-0"
              >
                <RefreshCw className={`w-4 h-4 ${tasksQuery.isFetching ? 'animate-spin' : ''}`} />
              </button>

              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => handleExport('excel')}
                  className="inline-flex h-10 items-center gap-1 rounded-lg border border-[var(--hb-border)] px-2.5 text-xs font-medium hover:bg-slate-50 dark:hover:bg-slate-800 whitespace-nowrap"
                >
                  <FileDown className="w-3.5 h-3.5" />
                  <span>Excel</span>
                </button>
                <button
                  type="button"
                  onClick={() => handleExport('word')}
                  className="inline-flex h-10 items-center gap-1 rounded-lg border border-[var(--hb-border)] px-2.5 text-xs font-medium hover:bg-slate-50 dark:hover:bg-slate-800 whitespace-nowrap"
                >
                  <FileDown className="w-3.5 h-3.5" />
                  <span>Word</span>
                </button>
                <button
                  type="button"
                  onClick={() => handleExport('csv')}
                  className="inline-flex h-10 items-center gap-1 rounded-lg border border-[var(--hb-border)] px-2.5 text-xs font-medium hover:bg-slate-50 dark:hover:bg-slate-800 whitespace-nowrap"
                >
                  <FileDown className="w-3.5 h-3.5" />
                  <span>CSV</span>
                </button>
              </div>
            </div>

            {showFilters && (
              <div className="pt-3 border-t border-[var(--hb-border)] grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                <div>
                  <label htmlFor="flt-status" className="block text-xs font-medium text-[var(--hb-muted)] mb-1">
                    وضعیت
                  </label>
                  <select
                    id="flt-status"
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    className="w-full h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-2.5 text-xs"
                  >
                    <option value="all">همه وضعیت‌ها</option>
                    <option value="pending">در انتظار اقدام</option>
                    <option value="in_progress">در حال پیگیری</option>
                    <option value="success">موفق / پایان‌یافته</option>
                    <option value="failed">ناموفق / کنسل‌شده</option>
                  </select>
                </div>

                <div>
                  <label htmlFor="flt-priority" className="block text-xs font-medium text-[var(--hb-muted)] mb-1">
                    اولویت
                  </label>
                  <select
                    id="flt-priority"
                    value={priorityFilter}
                    onChange={(e) => setPriorityFilter(e.target.value)}
                    className="w-full h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-2.5 text-xs"
                  >
                    <option value="all">همه اولویت‌ها</option>
                    <option value="urgent">فوری</option>
                    <option value="medium">متوسط</option>
                    <option value="normal">عادی</option>
                  </select>
                </div>

                <div>
                  <label htmlFor="flt-quicktime" className="block text-xs font-medium text-[var(--hb-muted)] mb-1">
                    بازهٔ سریع ثبت
                  </label>
                  <select
                    id="flt-quicktime"
                    value={quickTime}
                    onChange={(e) => setQuickTime(e.target.value)}
                    className="w-full h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-2.5 text-xs"
                  >
                    <option value="">همه زمان‌ها</option>
                    <option value="today">امروز (تهران)</option>
                    <option value="week">این هفته (از شنبه)</option>
                    <option value="month">این ماه شمسی</option>
                  </select>
                </div>

                <div className="flex items-end">
                  <button
                    type="button"
                    onClick={clearAllFilters}
                    className="w-full h-10 rounded-lg border border-[var(--hb-border)] text-xs font-medium text-[var(--hb-muted)] hover:text-[var(--hb-text)] hover:bg-slate-50 dark:hover:bg-slate-800"
                  >
                    پاک‌کردن همهٔ فیلترها
                  </button>
                </div>

                <JalaliDatePicker
                  id="flt-created-from"
                  label="تاریخ ثبت از (شمسی)"
                  value={createdFrom}
                  onChange={(v) => {
                    setQuickTime('');
                    setCreatedFrom(v);
                  }}
                />
                <JalaliDatePicker
                  id="flt-created-to"
                  label="تاریخ ثبت تا (شمسی)"
                  value={createdTo}
                  onChange={(v) => {
                    setQuickTime('');
                    setCreatedTo(v);
                  }}
                />
                <JalaliDatePicker
                  id="flt-action-from"
                  label="اولین اقدام از (شمسی)"
                  value={actionFrom}
                  onChange={setActionFrom}
                />
                <JalaliDatePicker
                  id="flt-action-to"
                  label="اولین اقدام تا (شمسی)"
                  value={actionTo}
                  onChange={setActionTo}
                />
              </div>
            )}

            {activeFilters.length > 0 && (
              <div className="flex flex-wrap items-center gap-1.5 pt-1 text-xs">
                <span className="text-[var(--hb-muted)]">فیلترهای فعال:</span>
                {activeFilters.map((chip) => (
                  <button
                    key={chip.key}
                    type="button"
                    onClick={chip.clear}
                    className="inline-flex items-center gap-1 rounded-md border border-[var(--hb-border)] bg-[var(--hb-bg)] px-2 py-0.5 text-[11px] hover:border-rose-400"
                  >
                    <span>{chip.label}</span>
                    <X className="w-3 h-3" aria-hidden="true" />
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Data Display: Desktop Table + Mobile Card Stack */}
          <div className="rounded-xl border border-[var(--hb-border)] bg-[var(--hb-surface)] overflow-hidden">
            {tasksQuery.isLoading ? (
              <div className="p-4 space-y-2.5">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div key={i} className="h-12 rounded-lg bg-slate-100 dark:bg-slate-800 animate-pulse" />
                ))}
              </div>
            ) : tasksQuery.isError ? (
              <div className="p-8 text-center text-sm text-rose-600 dark:text-rose-400">
                خطا در دریافت پرونده‌ها: {(tasksQuery.error as Error)?.message}
              </div>
            ) : items.length === 0 ? (
              <div className="p-10 text-center space-y-2">
                <p className="text-sm font-semibold text-[var(--hb-text)]">پرونده‌ای با این شرایط یافت نشد.</p>
                <p className="text-xs text-[var(--hb-muted)]">
                  فیلترهای جستجو یا بازهٔ زمانی را تغییر دهید یا فیلترها را پاک کنید.
                </p>
                {activeFilters.length > 0 && (
                  <button
                    type="button"
                    onClick={clearAllFilters}
                    className="mt-2 inline-flex items-center gap-1.5 rounded-lg bg-[var(--hb-primary-bg)] px-3.5 py-2 text-xs font-medium text-[var(--hb-primary-text)]"
                  >
                    نمایش همهٔ پرونده‌ها
                  </button>
                )}
              </div>
            ) : (
              <>
                {/* Desktop table */}
                <div className="hidden md:block overflow-x-auto">
                  <table className="w-full text-right text-xs">
                    <thead className="border-b border-[var(--hb-border)] bg-[var(--hb-bg)] text-[var(--hb-muted)]">
                      <tr>
                        <th className="py-2.5 px-2 font-semibold w-14">#</th>
                        <th className="py-2.5 px-2 font-semibold">خلاصهٔ درخواست و گزارش</th>
                        <th className="py-2.5 px-2 font-semibold w-20">اولویت</th>
                        <th className="py-2.5 px-2 font-semibold whitespace-nowrap">ثبت و اقدام</th>
                        <th className="py-2.5 px-2 font-semibold w-28">گیرندگان</th>
                        <th className="py-2.5 px-2 font-semibold w-24">وضعیت</th>
                        <th className="py-2.5 px-2 font-semibold w-16 text-left">عملیات</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--hb-border)]">
                      {items.map((item) => (
                        <tr
                          key={item.id}
                          className={`hover:bg-slate-50/80 dark:hover:bg-slate-800/40 transition-colors ${
                            item.priority === 'urgent'
                              ? 'border-s-4 border-s-rose-500 bg-rose-50/35 dark:bg-rose-950/15'
                              : ''
                          }`}
                        >
                          <td className="py-3 px-2 font-bold tabular-nums text-[var(--hb-text)] align-top whitespace-nowrap">
                            #{toPersianDigits(item.id)}
                            <div className="mt-0.5 text-[11px] font-normal text-[var(--hb-muted)]">
                              {item.source_label}
                            </div>
                          </td>
                          <td className="py-3 px-2 align-top min-w-0">
                            <button
                              type="button"
                              onClick={() => handleOpenTask(item.id)}
                              className="text-right font-semibold text-sm text-[var(--hb-text)] hover:text-[var(--hb-active-text)] line-clamp-2"
                            >
                              {item.body_summary}
                            </button>
                            <div className="mt-1 text-[11px] text-[var(--hb-muted)] flex flex-wrap items-center gap-x-2 gap-y-0.5">
                              {item.requester_name && <span>متقاضی: {item.requester_name}</span>}
                              {item.sender_name && item.sender_name !== '—' && (
                                <>
                                  <span aria-hidden="true">·</span>
                                  <span>ارجاع از: {item.sender_name}</span>
                                </>
                              )}
                              {item.latest_report_summary && (
                                <>
                                  <span aria-hidden="true">·</span>
                                  <span className="truncate max-w-[220px]">
                                    آخرین گزارش: {item.latest_report_summary}
                                  </span>
                                </>
                              )}
                            </div>
                          </td>
                          <td className="py-3 px-2 align-top whitespace-nowrap">
                            <span className={`inline-flex items-center gap-1 ${PRIORITY_STYLE[item.priority]}`}>
                              {item.priority === 'urgent' && <AlertTriangle className="w-3.5 h-3.5 shrink-0" />}
                              <span>{item.priority_label}</span>
                            </span>
                            <div className="mt-0.5 text-[11px] text-[var(--hb-muted)]">
                              {item.action_flag_label}
                            </div>
                          </td>
                          <td className="py-3 px-2 align-top tabular-nums whitespace-nowrap">
                            <div className="text-[var(--hb-text)]">{item.created_at_label}</div>
                            {item.assigned_at_label && item.assigned_at_label !== '—' && (
                              <div className="mt-0.5 text-[11px] text-[var(--hb-muted)]">
                                ارجاع: {item.assigned_at_label}
                              </div>
                            )}
                            <div className="mt-0.5 text-[11px] text-[var(--hb-muted)]">
                              اقدام: {item.first_action_at_label}
                            </div>
                          </td>
                          <td className="py-3 px-2 align-top">
                            {item.receivers.length === 0 ? (
                              <span className="text-rose-600 dark:text-rose-400 font-medium">
                                نیازمند واگذاری
                              </span>
                            ) : (
                              <div className="space-y-0.5">
                                {item.receivers.map((r) => (
                                  <div key={r.id} className="truncate max-w-[110px] text-[var(--hb-text)]">
                                    {r.display_name}
                                  </div>
                                ))}
                              </div>
                            )}
                          </td>
                          <td className="py-3 px-2 align-top whitespace-nowrap">
                            <span className={`font-semibold ${STATUS_STYLE[item.status]}`}>
                              {item.status_label}
                            </span>
                            <div className="mt-0.5 flex flex-wrap items-center gap-2 text-[11px] text-[var(--hb-muted)] tabular-nums">
                              <span className="inline-flex items-center gap-1">
                                <Eye className="w-3 h-3" aria-hidden="true" />
                                {toPersianDigits(item.view_count)}
                              </span>
                              {(item.reminder_count ?? 0) > 0 && (
                                <span
                                  title="تعداد یادآور فعال"
                                  className="inline-flex items-center gap-1 text-amber-700 dark:text-amber-300 font-medium"
                                >
                                  <Bell className="w-3 h-3" aria-hidden="true" />
                                  {toPersianDigits(item.reminder_count || 0)}
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="py-3 px-2 align-top text-left">
                            <button
                              type="button"
                              onClick={() => handleOpenTask(item.id)}
                              className="inline-flex items-center gap-1 rounded-lg border border-[var(--hb-border)] px-2.5 py-1.5 text-xs font-medium text-[var(--hb-active-text)] hover:bg-[var(--hb-active-tint)] whitespace-nowrap"
                            >
                              بازکردن
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* Mobile card list (zero horizontal overflow) */}
                <div className="md:hidden divide-y divide-[var(--hb-border)]">
                  {items.map((item) => (
                    <div
                      key={item.id}
                      className={`p-3.5 space-y-2 ${
                        item.priority === 'urgent'
                          ? 'border-s-4 border-s-rose-500 bg-rose-50/35 dark:bg-rose-950/15'
                          : ''
                      }`}
                    >
                      <div className="flex items-center justify-between gap-2 text-xs">
                        <span className="font-bold tabular-nums text-[var(--hb-text)]">
                          #{toPersianDigits(item.id)} · {item.source_label}
                        </span>
                        <span className={`inline-flex items-center gap-1 ${PRIORITY_STYLE[item.priority]}`}>
                          {item.priority === 'urgent' && <AlertTriangle className="w-3.5 h-3.5" />}
                          <span>{item.priority_label}</span>
                        </span>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleOpenTask(item.id)}
                        className="block w-full text-right text-sm font-semibold text-[var(--hb-text)] leading-relaxed"
                      >
                        {item.body_summary}
                      </button>
                      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--hb-muted)]">
                        <span className={`font-semibold ${STATUS_STYLE[item.status]}`}>
                          {item.status_label}
                        </span>
                        <span className="tabular-nums">{item.created_at_label}</span>
                      </div>
                      {(item.sender_name || (item.reminder_count ?? 0) > 0) && (
                        <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-[var(--hb-muted)]">
                          <span>
                            {item.sender_name && item.sender_name !== '—' ? `ارجاع از: ${item.sender_name}` : ''}
                          </span>
                          {(item.reminder_count ?? 0) > 0 && (
                            <span className="inline-flex items-center gap-1 text-amber-700 dark:text-amber-300 font-medium tabular-nums">
                              <Bell className="w-3 h-3" />
                              {toPersianDigits(item.reminder_count || 0)} یادآور فعال
                            </span>
                          )}
                        </div>
                      )}
                      <div className="flex items-center justify-between gap-2 pt-1">
                        <span className="text-[11px] text-[var(--hb-muted)] truncate">
                          {item.receivers.map((r) => r.display_name).join('، ') || 'نیازمند واگذاری'}
                        </span>
                        <button
                          type="button"
                          onClick={() => handleOpenTask(item.id)}
                          className="rounded-lg bg-[var(--hb-primary-bg)] px-3 py-1.5 text-xs font-medium text-[var(--hb-primary-text)] shrink-0"
                        >
                          بررسی و اقدام
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}

            {/* Cursor pagination footer */}
            {(cursorStack.length > 0 || tasksQuery.data?.has_more) && (
              <div className="px-4 py-3 border-t border-[var(--hb-border)] flex items-center justify-between gap-2 text-xs">
                <button
                  type="button"
                  disabled={cursorStack.length === 0}
                  onClick={() => {
                    const prev = [...cursorStack];
                    const last = prev.pop() ?? null;
                    setCursorStack(prev);
                    setCurrentCursor(last);
                  }}
                  className="rounded-lg border border-[var(--hb-border)] px-3 py-1.5 font-medium disabled:opacity-40"
                >
                  صفحهٔ قبل
                </button>
                <button
                  type="button"
                  disabled={!tasksQuery.data?.has_more || !tasksQuery.data?.next_cursor}
                  onClick={() => {
                    if (tasksQuery.data?.next_cursor) {
                      setCursorStack((s) => [...s, currentCursor || '']);
                      setCurrentCursor(tasksQuery.data.next_cursor);
                    }
                  }}
                  className="rounded-lg border border-[var(--hb-border)] px-3 py-1.5 font-medium disabled:opacity-40"
                >
                  صفحهٔ بعد
                </button>
              </div>
            )}
          </div>
        </section>
      </div>

      {/* Task Detail Modal */}
      <Modal
        open={openTaskId !== null}
        title={detail ? `پرونده #${toPersianDigits(detail.id)} — ${detail.source_label}` : 'در حال بارگذاری پرونده...'}
        onClose={() => setOpenTaskId(null)}
        blockBackdropClose={actionReport.trim().length > 0}
        maxWidthClass="max-w-3xl"
      >
        {detailQuery.isLoading ? (
          <div className="space-y-3 py-4">
            <div className="h-20 rounded-lg bg-slate-100 dark:bg-slate-800 animate-pulse" />
            <div className="h-32 rounded-lg bg-slate-100 dark:bg-slate-800 animate-pulse" />
          </div>
        ) : detailQuery.isError ? (
          <div className="p-4 text-sm text-rose-600 dark:text-rose-400">
            {(detailQuery.error as Error)?.message || 'خطا در دریافت جزئیات پرونده'}
          </div>
        ) : detail ? (
          <div className="space-y-5">
            {/* Metadata & Request Body */}
            <div
              className={`rounded-xl border p-4 space-y-2.5 ${
                detail.priority === 'urgent'
                  ? 'border-rose-300 dark:border-rose-800 bg-rose-50/40 dark:bg-rose-950/20'
                  : 'border-[var(--hb-border)] bg-[var(--hb-bg)]'
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--hb-muted)]">
                <div className="flex flex-wrap items-center gap-2">
                  <span className={`inline-flex items-center gap-1 ${PRIORITY_STYLE[detail.priority]}`}>
                    {detail.priority === 'urgent' && <AlertTriangle className="w-3.5 h-3.5" />}
                    <span>{detail.priority_label}</span>
                  </span>
                  <span>·</span>
                  <span className={`font-semibold ${STATUS_STYLE[detail.status]}`}>{detail.status_label}</span>
                  <span>·</span>
                  <span>{detail.action_flag_label}</span>
                </div>
                <span className="tabular-nums">
                  ثبت: {detail.created_at_label}
                  {detail.assigned_at_label && detail.assigned_at_label !== '—'
                    ? ` · ارجاع: ${detail.assigned_at_label}`
                    : ''}
                </span>
              </div>

              <p className="text-sm text-[var(--hb-text)] leading-7 whitespace-pre-wrap">{detail.body}</p>

              <div className="pt-2 border-t border-[var(--hb-border)] flex flex-wrap items-center justify-between gap-2 text-xs text-[var(--hb-muted)]">
                <div>
                  متقاضی: <strong className="text-[var(--hb-text)]">{detail.requester_name || '—'}</strong> · تماس:{' '}
                  <span dir="ltr" className="tabular-nums text-[var(--hb-text)]">
                    {toPersianDigits(detail.requester_phone || '—')}
                  </span>
                  {detail.sender_name && detail.sender_name !== '—' && (
                    <>
                      {' · '}ارجاع‌دهنده: <strong className="text-[var(--hb-text)]">{detail.sender_name}</strong>
                    </>
                  )}
                </div>
                <div>
                  گیرندگان فعال:{' '}
                  <strong className="text-[var(--hb-text)]">
                    {detail.receivers.map((r) => r.display_name).join('، ') || 'نیازمند واگذاری'}
                  </strong>
                </div>
              </div>

              {detail.receivers.some((r) => r.forward_reason) && (
                <div className="rounded-lg border border-teal-300/70 dark:border-teal-800 bg-teal-50/60 dark:bg-teal-950/30 px-3 py-2 text-xs text-teal-900 dark:text-teal-200">
                  <strong>دلیل ارجاع ثانویه:</strong>{' '}
                  {detail.receivers
                    .filter((r) => r.forward_reason)
                    .map((r) => `${r.display_name}: ${r.forward_reason}`)
                    .join(' | ')}
                </div>
              )}

              {isManager && detail.manager_note && (
                <div className="rounded-lg border border-amber-300 dark:border-amber-700/60 bg-amber-50 dark:bg-amber-950/40 px-3 py-2 text-xs text-amber-900 dark:text-amber-200">
                  <strong>توضیح مدیریتی (فقط مدیر):</strong> {detail.manager_note}
                </div>
              )}

              {isManager && detail.needs_reassignment && (
                <div className="rounded-lg border border-rose-300 dark:border-rose-700/60 bg-rose-50 dark:bg-rose-950/40 px-3 py-2 flex items-center justify-between gap-2 text-xs text-rose-800 dark:text-rose-200">
                  <span>این پرونده در انتظار واگذاری مجدد به همکار فعال است.</span>
                  <button
                    type="button"
                    onClick={() => openManagerEdit(detail)}
                    className="rounded-md bg-rose-700 text-white px-2.5 py-1 font-medium shrink-0"
                  >
                    واگذاری فوری
                  </button>
                </div>
              )}
            </div>

            {/* Personal Folder Assign + Manager Controls */}
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2 text-xs">
                <label htmlFor="detail-folder-sel" className="text-[var(--hb-muted)]">
                  فولدر شخصی:
                </label>
                <select
                  id="detail-folder-sel"
                  disabled={!isOnline || assignFolderMut.isPending}
                  value={detail.personal_folder_id ?? ''}
                  onChange={(e) =>
                    assignFolderMut.mutate({
                      taskId: detail.id,
                      folderId: e.target.value ? Number(e.target.value) : null,
                    })
                  }
                  className="h-9 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-2.5 text-xs"
                >
                  <option value="">بدون فولدر</option>
                  {folders.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name}
                    </option>
                  ))}
                </select>
              </div>

              {isManager && (
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    disabled={!isOnline}
                    onClick={() => (mgrEditOpen ? setMgrEditOpen(false) : openManagerEdit(detail))}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--hb-border)] px-3 py-1.5 text-xs font-medium hover:bg-slate-50 dark:hover:bg-slate-800"
                  >
                    <Edit3 className="w-3.5 h-3.5" />
                    <span>{mgrEditOpen ? 'بستن ویرایش مدیر' : 'ویرایش و بازتخصیص'}</span>
                  </button>
                  {(detail.status === 'success' || detail.status === 'failed') && (
                    <>
                      <button
                        type="button"
                        disabled={!isOnline || archiveTaskMut.isPending}
                        onClick={() => archiveTaskMut.mutate(detail.id)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-300 dark:border-emerald-700/60 px-3 py-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-300 hover:bg-emerald-50 dark:hover:bg-emerald-950/40"
                      >
                        <Archive className="w-3.5 h-3.5" />
                        <span>بایگانی پرونده</span>
                      </button>
                      <button
                        type="button"
                        disabled={!isOnline}
                        onClick={() => setReopenModalOpen(true)}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-[var(--hb-border)] px-3 py-1.5 text-xs font-medium hover:bg-slate-50 dark:hover:bg-slate-800"
                      >
                        <RotateCcw className="w-3.5 h-3.5" />
                        <span>بازگشایی پرونده</span>
                      </button>
                    </>
                  )}
                  <button
                    type="button"
                    disabled={!isOnline || trashTaskMut.isPending}
                    onClick={() => trashTaskMut.mutate(detail.id)}
                    className="inline-flex items-center gap-1.5 rounded-lg border border-rose-300 dark:border-rose-700/60 px-3 py-1.5 text-xs font-medium text-rose-700 dark:text-rose-300 hover:bg-rose-50 dark:hover:bg-rose-950/40"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                    <span>انتقال به زباله</span>
                  </button>
                </div>
              )}
            </div>

            {/* Manager Edit & Reassign Inline Panel */}
            {isManager && mgrEditOpen && (
              <div className="rounded-xl border border-[var(--hb-brand)]/60 bg-[var(--hb-bg)] p-4 space-y-3">
                <h3 className="text-xs font-bold text-[var(--hb-text)]">مدیریت اولویت، توضیح و گیرندگان پرونده</h3>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label htmlFor="mgr-priority" className="block text-xs font-medium mb-1">
                      اولویت
                    </label>
                    <select
                      id="mgr-priority"
                      value={mgrPriority}
                      onChange={(e) => setMgrPriority(e.target.value as PriorityType)}
                      className="w-full h-9 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-2.5 text-xs"
                    >
                      <option value="normal">عادی</option>
                      <option value="medium">متوسط</option>
                      <option value="urgent">فوری</option>
                    </select>
                  </div>
                  <div>
                    <label htmlFor="mgr-flag" className="block text-xs font-medium mb-1">
                      نوع دستور
                    </label>
                    <select
                      id="mgr-flag"
                      value={mgrActionFlag}
                      onChange={(e) => setMgrActionFlag(e.target.value as ActionFlagType)}
                      className="w-full h-9 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-2.5 text-xs"
                    >
                      <option value="action">اقدام شود</option>
                      <option value="followup">پیگیری شود</option>
                    </select>
                  </div>
                </div>
                <div>
                  <label htmlFor="mgr-note-edit" className="block text-xs font-medium mb-1">
                    توضیح مدیریتی (فقط مدیر)
                  </label>
                  <input
                    id="mgr-note-edit"
                    type="text"
                    value={mgrNote}
                    onChange={(e) => setMgrNote(e.target.value)}
                    placeholder="یادداشت داخلی برای پیگیری..."
                    className="w-full h-9 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-3 text-xs"
                  />
                </div>
                {(detail.status === 'pending' || detail.status === 'in_progress') && (
                  <div>
                    <p className="text-xs font-medium mb-1.5">تعیین یا تغییر گیرندگان فعال (۱ تا ۲ نفر):</p>
                    <StaffSelector
                      users={directoryQuery.data?.items ?? []}
                      selectedIds={mgrReceivers}
                      onChange={(ids) => {
                        setMgrReceivers(ids);
                        if (mgrEditError) setMgrEditError('');
                      }}
                      maxSelect={2}
                    />
                  </div>
                )}
                {mgrEditError && <p className="text-xs text-rose-600 dark:text-rose-400">{mgrEditError}</p>}
                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setMgrEditOpen(false)}
                    className="px-3 py-1.5 rounded-lg border border-[var(--hb-border)] text-xs font-medium"
                  >
                    انصراف
                  </button>
                  <button
                    type="button"
                    disabled={!isOnline || managerUpdateMut.isPending}
                    onClick={() => managerUpdateMut.mutate(detail)}
                    className="px-4 py-1.5 rounded-lg bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)] text-xs font-bold disabled:opacity-50"
                  >
                    {managerUpdateMut.isPending ? 'در حال ذخیره...' : 'ذخیرهٔ تغییرات مدیر'}
                  </button>
                </div>
              </div>
            )}

            {/* Record Action & Secondary Forward */}
            {detail.status !== 'success' && detail.status !== 'failed' && (isAssigneeOnOpenTask || isManager) && (
              <div className="rounded-xl border border-[var(--hb-border)] p-4 space-y-3">
                <h3 className="text-xs font-bold text-[var(--hb-text)]">ثبت اقدام و تغییر وضعیت</h3>
                <div className="flex flex-wrap gap-2">
                  {[
                    { id: 'in_progress' as const, label: 'در حال پیگیری' },
                    { id: 'success' as const, label: 'موفق / خاتمه' },
                    { id: 'failed' as const, label: 'ناموفق / کنسل' },
                  ].map((opt) => (
                    <button
                      key={opt.id}
                      type="button"
                      onClick={() => {
                        setActionStatus(opt.id);
                        if (opt.id !== 'in_progress') {
                          setForwardOpen(false);
                          setForwardIds([]);
                          setForwardReason('');
                        }
                      }}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                        actionStatus === opt.id
                          ? 'border-[var(--hb-brand)] bg-[var(--hb-active-tint)] text-[var(--hb-active-text)] font-bold'
                          : 'border-[var(--hb-border)] text-[var(--hb-muted)]'
                      }`}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>

                <textarea
                  rows={3}
                  value={actionReport}
                  onChange={(e) => {
                    setActionReport(e.target.value);
                    if (actionError) setActionError('');
                  }}
                  placeholder="شرح دقیق اقدام انجام‌شده یا نتیجهٔ پیگیری را وارد کنید..."
                  className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] p-3 text-sm focus:border-[var(--hb-brand)] focus:outline-none"
                />

                <div className="flex flex-wrap items-center justify-between gap-3">
                  <label className="inline-flex items-center gap-2 text-xs text-[var(--hb-muted)] cursor-pointer">
                    <input
                      type="checkbox"
                      checked={actionPrivate}
                      onChange={(e) => setActionPrivate(e.target.checked)}
                      className="rounded border-[var(--hb-border)] accent-[var(--hb-brand)]"
                    />
                    <Lock className="w-3.5 h-3.5" aria-hidden="true" />
                    <span>گزارش محرمانه (پنهان از سایر همکاران، قابل مشاهده برای مدیر)</span>
                  </label>

                  {actionStatus === 'in_progress' && (
                    <button
                      type="button"
                      onClick={() => setForwardOpen((f) => !f)}
                      className="inline-flex items-center gap-1.5 text-xs font-semibold text-[var(--hb-active-text)] hover:underline"
                    >
                      <Forward className="w-3.5 h-3.5" />
                      <span>{forwardOpen ? 'انصراف از ارجاع ثانویه' : 'ارجاع ثانویه به همکار'}</span>
                    </button>
                  )}
                </div>

                {forwardOpen && actionStatus === 'in_progress' && (
                  <div className="space-y-2 pt-1">
                    {maxForwardAllowed === 0 ? (
                      <div className="rounded-lg border border-amber-300 bg-amber-50 dark:bg-amber-950/40 px-3 py-2 text-xs text-amber-800 dark:text-amber-200 flex items-center gap-2">
                        <AlertTriangle className="w-4 h-4 shrink-0" />
                        <span>سقف ۲ گیرندهٔ فعال پر است؛ امکان ارجاع به همکار جدید وجود ندارد.</span>
                      </div>
                    ) : (
                      <>
                        <p className="text-[11px] text-[var(--hb-muted)]">
                          با ثبت ارجاع ثانویه، پرونده از کارتابل شما خارج شده و به گیرندهٔ جدید منتقل می‌شود (سقف مجموع گیرندگان فعال ۲ نفر است).
                        </p>
                        <StaffSelector
                          users={directoryQuery.data?.items ?? []}
                          selectedIds={forwardIds}
                          onChange={(ids) => {
                            setForwardIds(ids);
                            if (actionError) setActionError('');
                          }}
                          maxSelect={maxForwardAllowed}
                          excludeIds={[user.id]}
                          disabledIds={detail.receivers.map((r) => r.id)}
                        />
                        <input
                          type="text"
                          value={forwardReason}
                          onChange={(e) => setForwardReason(e.target.value)}
                          placeholder="دلیل یا توضیح ارجاع ثانویه (اختیاری)..."
                          className="w-full h-9 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-3 text-xs focus:border-[var(--hb-brand)] focus:outline-none"
                        />
                      </>
                    )}
                  </div>
                )}

                {actionError && <p className="text-xs text-rose-600 dark:text-rose-400">{actionError}</p>}

                <div className="flex justify-end">
                  <button
                    type="button"
                    disabled={!isOnline || submitActionMut.isPending}
                    onClick={() => submitActionMut.mutate(detail)}
                    className="inline-flex items-center gap-2 rounded-lg bg-[var(--hb-primary-bg)] hover:bg-[var(--hb-primary-hover)] px-4 py-2 text-xs font-bold text-[var(--hb-primary-text)] disabled:opacity-50"
                  >
                    <Send className="w-3.5 h-3.5" />
                    <span>{submitActionMut.isPending ? 'در حال ثبت...' : 'ثبت اقدام'}</span>
                  </button>
                </div>
              </div>
            )}

            {/* Personal / Shared Notes & Follow-up Reminders */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="rounded-xl border border-[var(--hb-border)] p-3.5 space-y-2.5">
                <h3 className="text-xs font-bold text-[var(--hb-text)] flex items-center gap-1.5">
                  <MessageSquarePlus className="w-4 h-4 text-[var(--hb-brand)]" />
                  <span>یادداشت‌های پرونده</span>
                </h3>
                <div className="space-y-2">
                  <textarea
                    rows={2}
                    value={noteBody}
                    onChange={(e) => {
                      setNoteBody(e.target.value);
                      if (noteError) setNoteError('');
                    }}
                    placeholder="یادداشت پیگیری..."
                    className="w-full rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] p-2 text-xs focus:border-[var(--hb-brand)] focus:outline-none"
                  />
                  {noteError && <p className="text-[11px] text-rose-600 dark:text-rose-400">{noteError}</p>}
                  <div className="flex items-center justify-between gap-2">
                    <select
                      aria-label="سطح دسترسی یادداشت"
                      value={noteVis}
                      onChange={(e) => setNoteVis(e.target.value as 'private' | 'shared_active_manager')}
                      className="h-8 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-2 text-[11px]"
                    >
                      <option value="private">شخصی (فقط خودم)</option>
                      <option value="shared_active_manager">مشترک با گیرندگان فعال و مدیر</option>
                    </select>
                    <button
                      type="button"
                      disabled={!isOnline || addNoteMut.isPending}
                      onClick={() => addNoteMut.mutate(detail.id)}
                      className="h-8 px-3 rounded-lg bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)] text-xs font-medium disabled:opacity-50"
                    >
                      ثبت یادداشت
                    </button>
                  </div>
                </div>
                <div className="space-y-1.5 max-h-40 overflow-y-auto pt-1">
                  {detail.notes.length === 0 ? (
                    <p className="text-[11px] text-[var(--hb-muted)]">یادداشتی ثبت نشده است.</p>
                  ) : (
                    detail.notes.map((n) => (
                      <div key={n.id} className="rounded-lg bg-[var(--hb-bg)] p-2 text-xs">
                        <div className="flex items-center justify-between text-[11px] text-[var(--hb-muted)]">
                          <span>{n.owner_name}</span>
                          <span className="tabular-nums">{n.created_at_label}</span>
                        </div>
                        <p className="mt-1 text-[var(--hb-text)]">{n.body}</p>
                      </div>
                    ))
                  )}
                </div>
              </div>

              <div className="rounded-xl border border-[var(--hb-border)] p-3.5 space-y-2.5">
                <h3 className="text-xs font-bold text-[var(--hb-text)] flex items-center gap-1.5">
                  <BellPlus className="w-4 h-4 text-[var(--hb-brand)]" />
                  <span>یادآور پیگیری (به وقت تهران)</span>
                </h3>
                {isAssigneeOnOpenTask && detail.status !== 'success' && detail.status !== 'failed' && (
                  <div className="space-y-2">
                    <div className="grid grid-cols-3 gap-2">
                      <div className="col-span-2">
                        <JalaliDatePicker
                          value={remDate}
                          onChange={(v) => {
                            setRemDate(v);
                            if (remError) setRemError('');
                          }}
                          placeholder="۱۴۰۵/۰۹/۰۵"
                        />
                      </div>
                      <input
                        type="text"
                        dir="ltr"
                        aria-label="ساعت یادآور"
                        value={remTime}
                        onChange={(e) => {
                          setRemTime(e.target.value);
                          if (remError) setRemError('');
                        }}
                        placeholder="09:00"
                        className="h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-surface)] px-2 text-xs text-center tabular-nums"
                      />
                    </div>
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        value={remNote}
                        onChange={(e) => setRemNote(e.target.value)}
                        placeholder="متن یادآور (اختیاری)..."
                        className="flex-1 h-8 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-2.5 text-xs"
                      />
                      <button
                        type="button"
                        disabled={!isOnline || addReminderMut.isPending}
                        onClick={() => addReminderMut.mutate(detail.id)}
                        className="h-8 px-3 rounded-lg bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)] text-xs font-medium disabled:opacity-50"
                      >
                        تنظیم
                      </button>
                    </div>
                    {remError && <p className="text-[11px] text-rose-600 dark:text-rose-400">{remError}</p>}
                  </div>
                )}

                <div className="space-y-1.5 max-h-40 overflow-y-auto pt-1">
                  {(remindersQuery.data?.items ?? []).length === 0 ? (
                    <p className="text-[11px] text-[var(--hb-muted)]">یادآور فعالی تنظیم نشده است.</p>
                  ) : (
                    (remindersQuery.data?.items ?? []).map((rem) => (
                      <div
                        key={rem.id}
                        className="flex items-center justify-between gap-2 rounded-lg bg-[var(--hb-bg)] px-2.5 py-1.5 text-xs"
                      >
                        <div className="min-w-0">
                          <div className="font-medium tabular-nums text-[var(--hb-text)] flex items-center gap-1">
                            {rem.fired ? (
                              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
                            ) : (
                              <Clock className="w-3.5 h-3.5 text-amber-600 shrink-0" />
                            )}
                            <span>{rem.due_at_label}</span>
                          </div>
                          {rem.note && <div className="text-[11px] text-[var(--hb-muted)] truncate">{rem.note}</div>}
                        </div>
                        {!rem.fired && (
                          <button
                            type="button"
                            onClick={() => deleteReminderMut.mutate({ taskId: detail.id, remId: rem.id })}
                            aria-label="حذف یادآور"
                            className="p-1 text-[var(--hb-muted)] hover:text-rose-600"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        )}
                      </div>
                    ))
                  )}
                </div>
              </div>
            </div>

            {/* Actions History & Immutable Timeline */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <h3 className="text-xs font-bold text-[var(--hb-text)]">اقدامات و گزارش‌های ثبت‌شده</h3>
                {detail.actions.length === 0 ? (
                  <p className="text-xs text-[var(--hb-muted)]">هنوز اقدامی ثبت نشده است.</p>
                ) : (
                  <div className="space-y-2 max-h-56 overflow-y-auto">
                    {detail.actions.map((act) => (
                      <div key={act.id} className="rounded-lg border border-[var(--hb-border)] p-2.5 text-xs space-y-1">
                        <div className="flex items-center justify-between text-[11px] text-[var(--hb-muted)]">
                          <span className="font-semibold text-[var(--hb-text)]">
                            {act.actor_name} {act.is_private ? '· محرمانه' : ''}
                          </span>
                          <span className="tabular-nums">{act.created_at_label}</span>
                        </div>
                        <div className={`text-[11px] font-medium ${STATUS_STYLE[act.status_after]}`}>
                          وضعیت: {act.status_label}
                        </div>
                        <p className="text-[var(--hb-text)] leading-relaxed">{act.report_text}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="space-y-2">
                <h3 className="text-xs font-bold text-[var(--hb-text)]">خط زمانی پرونده</h3>
                <div className="space-y-2 max-h-56 overflow-y-auto">
                  {detail.timeline.map((ev) => (
                    <div key={ev.id} className="rounded-lg bg-[var(--hb-bg)] px-3 py-2 text-xs space-y-0.5">
                      <div className="flex items-center justify-between text-[11px]">
                        <span className="font-semibold text-[var(--hb-text)]">
                          {ev.actor_display_name} · {ev.actor_role_label}
                        </span>
                        <span className="tabular-nums text-[var(--hb-muted)]">{ev.created_at_label}</span>
                      </div>
                      <div className="text-[11px] text-[var(--hb-muted)]">
                        {ev.event_type === 'direct_created'
                          ? `ثبت و ارجاع مستقیم به ${String(ev.details.receivers || '')}`
                          : ev.event_type === 'draft_distributed'
                          ? String(ev.details.trail || 'توزیع از پیش‌نویس')
                          : ev.event_type === 'first_view_in_progress'
                          ? 'مشاهده و آغاز پیگیری پرونده'
                          : ev.event_type === 'action_recorded'
                          ? `ثبت گزارش اقدام (${String(ev.details.status_after || '')})`
                          : ev.event_type === 'forwarded'
                          ? `ارجاع ثانویه به ${String(ev.details.receivers || '')}${
                              ev.details.reason ? ` — دلیل: ${String(ev.details.reason)}` : ''
                            }`
                          : ev.event_type === 'manager_updated'
                          ? `ویرایش مدیریتی (${String(ev.details.priority || '')} · ${String(ev.details.action_flag || '')})${
                              ev.details.receivers ? ` · گیرندگان: ${String(ev.details.receivers)}` : ''
                            }`
                          : ev.event_type === 'archived'
                          ? `بایگانی پرونده${ev.details.reason ? `: ${String(ev.details.reason)}` : ''}`
                          : ev.event_type === 'reopened'
                          ? `بازگشایی پرونده: ${String(ev.details.reason || '')}`
                          : ev.event_type}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        ) : null}
      </Modal>

      {/* Manager Reopen Modal */}
      <Modal
        open={reopenModalOpen && detail !== undefined}
        title="بازگشایی پروندهٔ خاتمه‌یافته"
        onClose={() => setReopenModalOpen(false)}
        blockBackdropClose
      >
        {detail && (
          <div className="space-y-4">
            <div>
              <label htmlFor="reopen-reason" className="block text-xs font-semibold mb-1">
                دلیل بازگشایی (الزامی)
              </label>
              <input
                id="reopen-reason"
                type="text"
                value={reopenReason}
                onChange={(e) => {
                  setReopenReason(e.target.value);
                  if (reopenError) setReopenError('');
                }}
                placeholder="مثال: پیگیری مجدد با متقاضی..."
                className="w-full h-10 rounded-lg border border-[var(--hb-border)] bg-[var(--hb-bg)] px-3 text-sm"
              />
            </div>
            <div>
              <p className="text-xs font-semibold mb-1.5">انتخاب گیرندگان (حداکثر ۲ نفر):</p>
              <StaffSelector
                users={directoryQuery.data?.items ?? []}
                selectedIds={reopenReceivers}
                onChange={setReopenReceivers}
                maxSelect={2}
              />
            </div>
            {reopenError && <p className="text-xs text-rose-600 dark:text-rose-400">{reopenError}</p>}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setReopenModalOpen(false)}
                className="px-4 py-2 rounded-lg border border-[var(--hb-border)] text-xs font-medium"
              >
                انصراف
              </button>
              <button
                type="button"
                disabled={!isOnline || reopenTaskMut.isPending}
                onClick={() => reopenTaskMut.mutate(detail)}
                className="px-4 py-2 rounded-lg bg-[var(--hb-primary-bg)] text-[var(--hb-primary-text)] text-xs font-bold disabled:opacity-50"
              >
                تأیید بازگشایی
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};

export default InboxPage;
