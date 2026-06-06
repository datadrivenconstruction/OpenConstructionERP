/**
 * Deep-link helpers for the AI Chat read renderers (CONN-80).
 *
 * The chat tool handlers (`backend/app/modules/erp_chat/tools.py`) already put
 * the primary key on every row they return - a project `id`, a `boq_id`, a
 * position `id`, a validation report `id`, a risk `id`. Until now those ids
 * died at display: the renderer drew the data but offered no way to open the
 * underlying record. These helpers turn an id that is already on the wire into
 * a route the app router can navigate to, so a user reading an AI answer can
 * jump straight to the real module screen.
 *
 * No backend field is invented here - every target is derived from data the
 * tool already serializes. Routes are validated against `src/app/App.tsx`:
 *   - project    -> /projects/{id}          (ProjectDetailPage)
 *   - boq        -> /boq/{boqId}            (BOQEditorPage; ?highlight=posId
 *                                            scrolls to one position)
 *   - schedule   -> /schedule               (4D Schedule lander)
 *   - validation -> /validation             (Validation dashboard)
 *   - risk       -> /risks                  (Risk Register)
 *
 * Navigation is performed with react-router's `useNavigate` (never
 * window.location) so it works inside both chat surfaces (the /chat full page
 * and the floating panel), both of which mount under the app router.
 */

/** Build the path to a project detail screen. */
export function projectPath(id: string | undefined): string | null {
  return id ? `/projects/${id}` : null;
}

/**
 * Build the path to the BOQ editor for a BOQ, optionally scrolling to a single
 * position. `/boq/{boqId}?highlight={positionId}` is consumed by
 * BOQEditorPage (it scrolls + flashes the matching row).
 */
export function boqPath(boqId: string | undefined, positionId?: string): string | null {
  if (!boqId) return null;
  return positionId ? `/boq/${boqId}?highlight=${encodeURIComponent(positionId)}` : `/boq/${boqId}`;
}

/** The 4D Schedule lander. The tool result carries no project context that the
 * global /schedule route consumes, so this is an un-parameterised open. */
export function schedulePath(): string {
  return '/schedule';
}

/** The Validation dashboard. */
export function validationPath(): string {
  return '/validation';
}

/** The Risk Register. */
export function riskPath(): string {
  return '/risks';
}

/** Read a string field off an unknown envelope without throwing. */
export function readString(data: unknown, key: string): string | undefined {
  if (data && typeof data === 'object' && !Array.isArray(data)) {
    const v = (data as Record<string, unknown>)[key];
    if (typeof v === 'string' && v.length > 0) return v;
  }
  return undefined;
}
