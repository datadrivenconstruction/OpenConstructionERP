// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
import { API_BASE, apiDelete, apiGet, apiPatch, apiPost, apiPut, getAuthToken } from '@/shared/lib/api';

export interface StandupComment {
  id: string;
  entry_id: string;
  user_id: string;
  author_name: string;
  body: string;
  created_at: string;
}

export interface StandupEntry {
  id: string;
  user_id: string;
  author_name: string;
  day: string;
  status: string;
  yesterday: string;
  today: string;
  blockers: string;
  job_ids: string[];
  created_at: string;
  updated_at: string;
  comments: StandupComment[];
}

export interface Job {
  id: string;
  name: string;
  code: string;
}

export interface OpenTask {
  id: string;
  project_id: string;
  title: string;
  status: string;
  priority: string;
  due_date: string | null;
  overdue: boolean;
}

export interface LastEntry {
  day: string;
  status: string;
  today: string;
  blockers: string;
}

export interface TeamMember {
  user_id: string;
  name: string;
  has_posted: boolean;
  open_tasks: OpenTask[];
  open_tasks_total: number;
  last_entry: LastEntry | null;
}

export interface Board {
  day: string;
  me: { user_id: string; name: string };
  entries: StandupEntry[];
  roster: TeamMember[];
  jobs: Job[];
}

export interface BlockerRow {
  id: string;
  user_id: string;
  author_name: string;
  day: string;
  blockers: string;
}

export interface EntryUpsert {
  day: string;
  status: string;
  yesterday: string;
  today: string;
  blockers: string;
  job_ids: string[];
}

const BASE = '/v1/team-standup';

export const fetchBoard = (day: string) =>
  apiGet<Board>(`${BASE}/board?day=${encodeURIComponent(day)}`);

export const saveEntry = (body: EntryUpsert) =>
  apiPut<StandupEntry, EntryUpsert>(`${BASE}/entries`, body);

/** Every list route in this module answers with a page envelope. */
interface StandupPage<T> {
  items?: T[];
  total?: number;
}

export const fetchBlockers = async (fromDay: string, toDay: string) =>
  (
    await apiGet<StandupPage<BlockerRow>>(
      `${BASE}/blockers?from_day=${encodeURIComponent(fromDay)}&to_day=${encodeURIComponent(toDay)}`,
    )
  ).items ?? [];

export const fetchHistory = async (fromDay: string, toDay: string, userId?: string) =>
  (
    await apiGet<StandupPage<StandupEntry>>(
      `${BASE}/entries?from_day=${encodeURIComponent(fromDay)}&to_day=${encodeURIComponent(toDay)}${
        userId ? `&user_id=${encodeURIComponent(userId)}` : ''
      }`,
    )
  ).items ?? [];

export const postComment = (entryId: string, body: string) =>
  apiPost<StandupComment, { body: string }>(`${BASE}/entries/${entryId}/comments`, { body });

export const deleteComment = (commentId: string) =>
  apiDelete<void>(`${BASE}/comments/${commentId}`);

// ── Native tasks bridge (oe_tasks) ────────────────────────────────────────
// The standup page drives the REAL task system, not a parallel one: a
// quick-added task lands in /tasks and the project's task list like any
// other, and ticking one here completes it for everyone.

interface TaskCreateBody {
  project_id: string;
  task_type: string;
  title: string;
  responsible_id: string;
  status: string;
  due_date?: string;
}

export const createTask = (projectId: string, title: string, responsibleId: string, dueDate?: string) =>
  apiPost<{ id: string }, TaskCreateBody>('/v1/tasks/', {
    project_id: projectId,
    task_type: 'task',
    title,
    responsible_id: responsibleId,
    status: 'open',
    ...(dueDate ? { due_date: dueDate } : {}),
  });

export const completeTask = (taskId: string) =>
  apiPost<unknown, { result?: string }>(`/v1/tasks/${taskId}/complete/`, {});

// ══════════════════════════════════════════════════════════════════════
// V3 - the delivery board. One full-board read; granular writes with the
// rails (stage templates, recurrence, the log) enforced server-side.
// ══════════════════════════════════════════════════════════════════════

export interface Stage {
  id: string;
  name: string;
  color: string;
  position: number;
  wip_limit: number | null;
  is_done: boolean;
  spawn: string[];
}

export interface Activity {
  id: string;
  name: string;
  color: string;
  position: number;
  exclusive: boolean;
}

export interface StandupFile {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  uploaded_by: string;
  created_at: string;
}

export interface EntryV3 extends StandupEntry {
  activities: string[];
  blocker_by: string;
  files: StandupFile[];
}

export interface TaskComment {
  id: string;
  task_id: string;
  user_id: string;
  author_name: string;
  body: string;
  created_at: string;
}

export interface BoardTask {
  id: string;
  title: string;
  project_id: string;
  stage_id: string;
  assignee_id: string;
  assignee_name: string;
  due: string;
  priority: string;
  waiting_on: string;
  notes: string;
  repeat_rule: string;
  link_kind: string;
  link_ref: string;
  link_target_id: string;
  is_sub: boolean;
  /** 'public' (the team) or 'private' (creator, assignee, admins). The
   * server never sends a private task the caller is outside of. */
  visibility: 'public' | 'private';
  created_by: string;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  comments: TaskComment[];
  files: StandupFile[];
}

export interface Person {
  id: string;
  name: string;
  initials: string;
  color: string;
}

export interface LogRow {
  id: string;
  author_name: string;
  what: string;
  where_label: string;
  kind: string;
  color: string;
  created_at: string;
}

export interface BoardJob {
  id: string;
  code: string;
  client: string;
  /** The client contact's brand colour as a hex string; '' when unset. */
  client_color: string;
  label: string;
  name: string;
}

export interface FullBoard {
  day: string;
  today: string;
  me: { user_id: string; name: string };
  people: Person[];
  entries: EntryV3[];
  week: { start: string; entries: EntryV3[] };
  stages: Stage[];
  /** Per-job stage runs keyed by project id; a job listed here shows
   * only these columns, every other job shows `stages`. */
  stage_overrides: Record<string, Stage[]>;
  activities: Activity[];
  waits: string[];
  tasks: BoardTask[];
  jobs: BoardJob[];
  log: LogRow[];
}

export interface EntryUpsertV3 extends EntryUpsert {
  activities: string[];
  blocker_by: string;
}

export interface TaskWrite {
  title: string;
  project_id: string;
  stage_id?: string;
  assignee_id?: string;
  due?: string;
  priority?: string;
  waiting_on?: string;
  notes?: string;
  repeat_rule?: string;
  link_kind?: string;
  link_ref?: string;
  link_target_id?: string;
  /** Creator, assignee or admin only on a patch - anyone else gets 403. */
  visibility?: 'public' | 'private';
}

export interface MoveResult {
  task: BoardTask;
  spawned: BoardTask[];
  repeated: BoardTask | null;
}

export const fetchFullBoard = (day: string) =>
  apiGet<FullBoard>(`${BASE}/full-board?day=${encodeURIComponent(day)}`);

export const saveEntryV3 = (body: EntryUpsertV3) =>
  apiPut<EntryV3, EntryUpsertV3>(`${BASE}/entries`, body);

export const createBoardTasks = (tasks: TaskWrite[]) =>
  apiPost<BoardTask[], { tasks: TaskWrite[] }>(`${BASE}/tasks`, { tasks });

export const patchBoardTask = (taskId: string, fields: Partial<TaskWrite>) =>
  apiPatch<BoardTask, Partial<TaskWrite>>(`${BASE}/tasks/${taskId}`, fields);

export const moveBoardTask = (taskId: string, stageId: string) =>
  apiPost<MoveResult, { stage_id: string }>(`${BASE}/tasks/${taskId}/move`, {
    stage_id: stageId,
  });

export interface MoveUndoBody {
  to_stage_id: string;
  spawned_ids: string[];
  repeated_id: string | null;
}

export const undoBoardMove = (taskId: string, body: MoveUndoBody) =>
  apiPost<BoardTask, MoveUndoBody>(`${BASE}/tasks/${taskId}/move-undo`, body);

export const deleteBoardTask = (taskId: string) =>
  apiDelete<void>(`${BASE}/tasks/${taskId}`);

export const restoreBoardTask = (taskId: string) =>
  apiPost<BoardTask, Record<string, never>>(`${BASE}/tasks/${taskId}/restore`, {});

export const addBoardTaskComment = (taskId: string, body: string) =>
  apiPost<TaskComment, { body: string }>(`${BASE}/tasks/${taskId}/comments`, { body });

export const deleteBoardTaskComment = (commentId: string) =>
  apiDelete<void>(`${BASE}/task-comments/${commentId}`);

export interface StageWrite {
  id: string | null;
  name: string;
  color: string;
  wip_limit: number | null;
  is_done: boolean;
  spawn: string[];
}

export const putStages = (stages: StageWrite[]) =>
  apiPut<Stage[], { stages: StageWrite[] }>(`${BASE}/config/stages`, { stages });

export const resetStagesToDefault = () =>
  apiPost<Stage[], Record<string, never>>(`${BASE}/config/stages/reset`, {});

/** Give one job its own stage run (create or replace). */
export const putJobStages = (projectId: string, stages: StageWrite[]) =>
  apiPut<Stage[], { stages: StageWrite[] }>(
    `${BASE}/config/stages/${encodeURIComponent(projectId)}`,
    { stages },
  );

/** Drop a job's own stage run; the standard set comes back. */
export const deleteJobStages = (projectId: string) =>
  apiDelete<Stage[]>(`${BASE}/config/stages/${encodeURIComponent(projectId)}`);

export interface ActivityWrite {
  id: string | null;
  name: string;
  color: string;
  exclusive: boolean;
}

export const putActivities = (activities: ActivityWrite[]) =>
  apiPut<Activity[], { activities: ActivityWrite[] }>(`${BASE}/config/activities`, {
    activities,
  });

export const putWaits = (reasons: string[]) =>
  apiPut<{ reasons: string[] }, { reasons: string[] }>(`${BASE}/config/waits`, {
    reasons,
  });

/** Nudge everyone who has not posted today. The server decides who is
 * missing and what the notification says - no ids, no free text. */
export const sendNudge = () =>
  apiPost<{ nudged: string[] }, Record<string, never>>(`${BASE}/nudge`, {});

export const deleteTaskFile = (fileId: string) =>
  apiDelete<void>(`${BASE}/task-files/${fileId}`);

export const deleteEntryFile = (fileId: string) =>
  apiDelete<void>(`${BASE}/entry-files/${fileId}`);

/** Multipart upload - api.ts JSON-stringifies bodies, so uploads use the
 * documented raw-fetch recipe (browser sets the multipart boundary). */
async function uploadFile(path: string, file: File): Promise<StandupFile> {
  const formData = new FormData();
  formData.append('file', file);
  const token = getAuthToken();
  const res = await fetch(`${API_BASE}/v1/team-standup${path}`, {
    method: 'POST',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      'X-DDC-Client': 'OE/1.0',
    },
    body: formData,
  });
  if (!res.ok) {
    let detail = `Upload failed (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* keep the status message */
    }
    throw new Error(detail);
  }
  return (await res.json()) as StandupFile;
}

export const uploadTaskFile = (taskId: string, file: File) =>
  uploadFile(`/tasks/${taskId}/files`, file);

export const uploadEntryFile = (entryId: string, file: File) =>
  uploadFile(`/entries/${entryId}/files`, file);

/** Fetch an attachment as an object URL (the <img>/<video> tags cannot
 * carry the bearer token themselves). Callers own revocation. */
export async function fileObjectUrl(kind: 'task' | 'entry', fileId: string): Promise<string> {
  const token = getAuthToken();
  const res = await fetch(`${API_BASE}/v1/team-standup/${kind}-files/${fileId}/download`, {
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      'X-DDC-Client': 'OE/1.0',
    },
  });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  return URL.createObjectURL(await res.blob());
}

// ── Linked records: registers + project mail ─────────────────────────────

export interface RegisterItemRow {
  id: string;
  project_id: string;
  kind: string;
  reference: string;
  title: string;
  status: string;
  due_date: string | null;
  current_step?: string | null;
  ball_in_court_name?: string;
  responsible?: string;
  fields?: Record<string, unknown>;
  created_at?: string;
}

export const fetchRegisterItems = (projectId: string, kind?: string) =>
  apiGet<RegisterItemRow[]>(
    `/v1/register-workflow/items?project_id=${encodeURIComponent(projectId)}${
      kind ? `&kind=${encodeURIComponent(kind)}` : ''
    }`,
  );

export const raiseRegisterItem = (projectId: string, kind: string, title: string) =>
  apiPost<RegisterItemRow, { project_id: string; kind: string; title: string }>(
    '/v1/register-workflow/items',
    { project_id: projectId, kind, title },
  );

export interface CorrespondenceRow {
  id: string;
  reference_number: string;
  subject: string;
  direction: string;
  status: string;
  date_sent: string | null;
  date_received: string | null;
  notes: string;
  created_at?: string;
}

export const fetchCorrespondence = (projectId: string) =>
  apiGet<{ items: CorrespondenceRow[] }>(
    `/v1/correspondence/?project_id=${encodeURIComponent(projectId)}&limit=100`,
  );

// ── Linked records: department work requests ─────────────────────────────
// The Work requests module ships separately (`/api/v1/work-requests`).
// Callers treat a 404 as "not mounted here" and list nothing - never an
// error on the board.

export interface WorkRequestPerson {
  id: string;
  name: string;
}

export interface WorkRequestRow {
  id: string;
  /** e.g. WR-WKS-000012 */
  reference: string;
  project_id: string;
  project_code: string;
  department: string;
  request_type: string;
  title: string;
  status: string;
  stage: string;
  due_date: string | null;
  is_overdue: boolean;
  ball_in_court: 'requester' | 'department';
  responsible: WorkRequestPerson | null;
  assignees: WorkRequestPerson[];
  hours_logged: number;
  quoted_hours: number;
  deviation_hours: number;
  created_at: string;
}

export interface WorkRequestDepartment {
  key: string;
  name: string;
  colour: string;
  stages: { key: string; name: string; colour: string; closes: boolean }[];
}

/** A job's open requests (the module defaults to open only). */
export const fetchWorkRequests = (projectId: string) =>
  apiGet<WorkRequestRow[]>(
    `/v1/work-requests/requests?project_id=${encodeURIComponent(projectId)}`,
  );

export const fetchWorkRequestDepartments = () =>
  apiGet<WorkRequestDepartment[]>('/v1/work-requests/departments');

// ── Job facts live in Projects; the board edits them through the
// projects API so its ownership rail stays in charge. ───────────────────

export const patchProject = (
  projectId: string,
  fields: { name?: string; project_code?: string },
) => apiPatch<unknown, typeof fields>(`/v1/projects/${projectId}`, fields);
