export type RoleName = 'admin' | 'manager' | 'author' | 'employee' | 'expert';
export type ThemePreference = 'system' | 'light' | 'dark';
export type SourceType = 'sms' | 'phone' | 'in_person' | 'social';
export type PriorityType = 'urgent' | 'medium' | 'normal';
export type TaskStatusType = 'pending' | 'in_progress' | 'success' | 'failed';
export type ActionFlagType = 'action' | 'followup';

export interface AuthUser {
  id: number;
  username: string;
  display_name: string;
  job_title: string;
  department: string;
  display_access_level: 'employee' | 'supervisor' | 'expert';
  org_role_type: 'followup' | 'referral' | 'office' | 'technical';
  roles: RoleName[];
  avatar_color: string;
  theme_preference: ThemePreference;
}

export interface MeResponse {
  user: AuthUser;
  csrf_token: string;
  unread_notifications: number;
  unread_chat_public: number;
  unread_chat_announcements: number;
}

export interface DirectoryUser {
  id: number;
  display_name: string;
  job_title: string;
  department: string;
  avatar_color: string;
  is_online: boolean;
}

export interface AdminUserItem {
  id: number;
  username: string;
  display_name: string;
  job_title: string;
  department: string;
  display_access_level: 'employee' | 'supervisor' | 'expert';
  org_role_type: 'followup' | 'referral' | 'office' | 'technical';
  roles: RoleName[];
  is_active: boolean;
  is_deleted: boolean;
  avatar_color: string;
  theme_preference: ThemePreference;
  open_assignment_count: number;
  created_at: string;
  version: number;
}

export interface TaskReceiver {
  id: number;
  display_name: string;
  avatar_color: string;
  job_title: string;
  assigned_at_label?: string;
  forward_reason?: string;
  sender_name?: string;
}

export interface TaskListItem {
  id: number;
  source_type: SourceType;
  source_label: string;
  body_summary: string;
  requester_name: string;
  priority: PriorityType;
  priority_label: string;
  status: TaskStatusType;
  status_label: string;
  action_flag: ActionFlagType;
  action_flag_label: string;
  created_at: string;
  created_at_label: string;
  first_action_at: string | null;
  first_action_at_label: string;
  latest_report_summary: string;
  view_count: number;
  sender_name?: string;
  assigned_at_label?: string;
  reminder_count?: number;
  receivers: TaskReceiver[];
  personal_folder_id: number | null;
  needs_reassignment: boolean;
  version: number;
}

export interface TaskActionItem {
  id: number;
  actor_id: number;
  actor_name: string;
  status_after: TaskStatusType;
  status_label: string;
  report_text: string;
  is_private: boolean;
  created_at: string;
  created_at_label: string;
}

export interface TaskNoteItem {
  id: number;
  owner_id: number;
  owner_name: string;
  body: string;
  visibility: 'private' | 'shared_active_manager';
  created_at: string;
  created_at_label: string;
}

export interface TaskTimelineItem {
  id: number;
  actor_display_name: string;
  actor_role_label: string;
  event_type: string;
  created_at: string;
  created_at_label: string;
  details: Record<string, unknown>;
}

export interface TaskDetail extends TaskListItem {
  body: string;
  requester_phone: string;
  manager_note: string | null;
  closed_at: string | null;
  closed_at_label: string;
  actions: TaskActionItem[];
  notes: TaskNoteItem[];
  timeline: TaskTimelineItem[];
}

export interface TaskReminderItem {
  id: number;
  due_at: string;
  due_at_label: string;
  note: string;
  fired: boolean;
  fired_at_label: string | null;
}

export interface FolderItem {
  id: number;
  name: string;
  count: number;
}

export interface DraftItem {
  id: number;
  author_id: number;
  author_name: string;
  source_type: SourceType;
  source_label: string;
  requester_name: string;
  requester_phone: string;
  body: string;
  priority: PriorityType;
  priority_label: string;
  status: 'new' | 'edited' | 'ready_to_distribute' | 'distributed' | 'closed';
  status_label: string;
  action_flag: ActionFlagType;
  manager_note: string | null;
  edited_at: string | null;
  edited_at_label: string | null;
  distributed_task_id: number | null;
  closed_at_label: string | null;
  created_at: string;
  created_at_label: string;
  version: number;
}

export interface VisitItem {
  id: number;
  creator_id: number;
  creator_name: string;
  person_or_org: string;
  phone: string;
  request_desc: string;
  followup_desc: string;
  action_taken: string;
  status: 'pending_review' | 'approved' | 'rejected';
  status_label: string;
  review_note: string | null;
  reviewed_at_label: string | null;
  created_at: string;
  created_at_label: string;
  folder_id: number | null;
  version: number;
}

export interface ChatMessageItem {
  id: number;
  channel: 'public' | 'announcements';
  sender_id: number;
  sender_name: string;
  sender_job_title: string;
  sender_avatar_color: string;
  body: string;
  created_at: string;
  created_at_label: string;
  read_count: number;
  read_by_me: boolean;
  readers: Array<{ display_name: string; read_at_label: string }> | null;
}

export interface NotificationItem {
  id: number;
  type: string;
  title: string;
  body: string;
  task_id: number | null;
  is_read: boolean;
  created_at: string;
  created_at_label: string;
}

export interface LeaderboardEntry {
  rank: number;
  medal: 'gold' | 'silver' | 'bronze' | null;
  user_id: number;
  display_name: string;
  job_title: string;
  department: string;
  avatar_color: string;
  avg_score: number;
  rating_count: number;
  details: Array<{
    id: number;
    score: number;
    source: string;
    source_label: string;
    reason: string;
    created_at_label: string;
    editable: boolean;
  }>;
}
