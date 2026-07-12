# ACAP Indonesia launch: declutter sidebar (simple-mode default) + surface ACAP project tabs

Goal: make the product Indonesia/ACAP-focused. Everything REVERSIBLE (hide via
existing `hideInSimple`/`advancedOnly` flags — do NOT delete any group, item,
or route). ponytail stance: smallest working diff, reuse existing machinery,
no new dependencies. Touch ONLY the three files named below. Do NOT commit —
leave the working tree dirty for review.

## File 1: `frontend/src/stores/useViewModeStore.ts`

Change the DEFAULT view mode from `'advanced'` to `'simple'` for a first-time
user with no persisted `localStorage['oe_view_mode']` value. An explicit
`'advanced'` persisted value must still be honored (toggle stays fully
reversible).

Replace:
```ts
function readMode(): ViewMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === 'simple' ? 'simple' : 'advanced';
  } catch {
    return 'advanced';
  }
}
```
with:
```ts
function readMode(): ViewMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    // Default is 'simple' for the Indonesia/ACAP launch (a first-time user
    // with no persisted choice sees the decluttered sidebar). An explicit
    // 'advanced' choice — stored the moment a user flips the toggle — is
    // still honored and persists across sessions, so this only changes the
    // out-of-the-box default, not the toggle's reversibility.
    return v === 'advanced' ? 'advanced' : 'simple';
  } catch {
    return 'simple';
  }
}
```
Do not touch anything else in this file (the zustand store body reads
`readMode()` twice already at init — leave that as-is, no refactor needed).

## File 2: `frontend/src/app/layout/Sidebar.tsx`

The `navGroups: NavGroup[]` array starts at line 207. `NavGroup` supports
`hideInSimple?: boolean` (whole group hidden in simple view); `NavItem`
supports `advancedOnly?: boolean` (item hidden in simple view). Most enterprise
groups ALREADY have `hideInSimple: true` set. You only need to add it to
THREE groups that currently lack it. Do not touch any other group. Do not
remove `hideInSimple` from any group that already has it.

**KEEP visible in simple mode (do NOT add hideInSimple — verify these three
still do NOT have it, but do not edit them otherwise):** `grp_overview`,
`grp_estimating`, `grp_cost_data`.

**Add `hideInSimple: true` to these three groups (currently missing it):**

1. `grp_takeoff` (id `'grp_takeoff'`, comment header `// ── 2. TAKEOFF`) —
   add `hideInSimple: true,` as a new property on the group object (e.g.
   right after the `defaultOpen: true,` line for that group).

2. `grp_reality` (id `'grp_reality'`, comment header
   `// ── 5. REALITY CAPTURE & 3D`) — this group already has
   `dynamicGroupKey: 'reality',` and `defaultOpen: true,` — add
   `hideInSimple: true,` alongside those two properties (do not remove
   `dynamicGroupKey`).

3. `grp_commercial` (id `'grp_commercial'`, comment header
   `// ── 9. COMMERCIAL`) — this group currently has a comment block
   explaining it was deliberately kept visible in Simple mode after a past
   user complaint ("Visible in Simple mode too. A user reported..."). For
   this ACAP/Indonesia launch, supersede that decision: add
   `hideInSimple: true,` to the group object, and REPLACE that old comment
   block with:
   ```
    // Hidden in Simple mode for the Indonesia/ACAP launch (2026-07-12) —
    // supersedes the earlier "visible in Simple mode too" exception for a
    // small residential RAB workflow. Still fully reachable via the
    // Advanced view toggle. CRM and Subcontractors remain advancedOnly
    // within the group for when it is shown.
   ```
   Keep the three items (`nav.crm`, `nav.contracts`, `nav.subcontractors`)
   exactly as they are — only the group-level `hideInSimple` and the comment
   change.

**Add one short comment right above the `const navGroups: NavGroup[] = [`
declaration (line 207)**, e.g.:
```
// NOTE(acap): the hideInSimple flags below (grp_takeoff, grp_reality,
// grp_commercial — plus the enterprise groups that already carried the
// flag) were set/extended for the Indonesia/ACAP simple-mode launch
// (2026-07-12) to declutter the default sidebar around a small residential
// estimation workflow. Nothing is deleted; switching to Advanced view
// (useViewModeStore) restores full visibility.
```

Do not touch imports, `adminGridItems`, `ALL_NAV_ITEMS`, `GROUP_ID_BY_ROUTE`,
or any other group besides the three listed above.

## File 3: `frontend/src/features/projects/ProjectDetailPage.tsx`

Add three new tab buttons to the existing tab bar that NAVIGATE to the
existing standalone ACAP routes for the current project (these are full
page routes already registered in `App.tsx` at
`/projects/:projectId/layout` → FloorPlanEditorPage,
`/projects/:projectId/timeline` → TimelinePage,
`/projects/:projectId/render` → RenderPage — do not touch App.tsx, do not
touch those page components, they already exist and already have their own
per-project authorization/key-gating internally).

Context: the existing tab bar (around line 2007-2034) is driven by local
`activeTab` state (`useState<ProjectTab>`, `ProjectTab` from the
`PROJECT_TABS` string-literal union at lines ~129-138) and an inline array
literal of `{ key, label, icon }` objects mapped to `<button onClick={() =>
setActiveTab(tab.key)}>`. That pattern renders an INLINE content panel below
(`{activeTab === 'photos' && (...)}` etc.) — there is no such inline panel
for layout/timeline/render, they are separate routed pages. So the three new
tab buttons must NOT reuse `setActiveTab` — they must `navigate()` to the
acap route instead, and must NOT be added to the `PROJECT_TABS`/`ProjectTab`
union (adding them there would require a matching `activeTab === '...'`
content block that doesn't exist, and would break the `?tab=` deep-link
validation that checks `PROJECT_TABS.includes(urlTab)`).

Implementation:

1. Near the top of the tab-bar array (lines ~2009-2017), extend each element
   with an optional `to?: string` field so TypeScript keeps a single map()
   loop. Add three new entries whose `key` is a string NOT in `ProjectTab`
   (cast loosely, e.g. `key: 'acap-layout' as any` is NOT desired — instead
   type the array items as `{ key: string; label: string; icon: JSX.Element;
   to?: string }` explicitly rather than reusing the `as ProjectTab` cast
   for these three, since they are route-nav tabs not state tabs). Concretely,
   change the array's per-element typing so the existing 7 entries keep
   `key: 'dashboard' as ProjectTab` etc., and the 3 new entries use a plain
   string key plus a `to` field, e.g.:
   ```tsx
   { key: 'acap-layout', label: 'Denah', icon: <LayoutGrid size={15} />, to: `/projects/${projectId}/layout` },
   // TODO(acap): add RAB tab once the RAB page exists
   { key: 'acap-timeline', label: 'Timeline', icon: <CalendarClock size={15} />, to: `/projects/${projectId}/timeline` },
   { key: 'acap-render', label: 'Render', icon: <ImageIcon size={15} />, to: `/projects/${projectId}/render` },
   ```
   (Reuse `LayoutGrid` if already imported from `lucide-react` at the top of
   the file — check the import block first; if not present, add it to the
   existing `lucide-react` import list. `CalendarClock` and `ImageIcon` are
   already imported and used by the `schedule`/`photos` tabs — reuse them,
   do not re-import.)

2. In the `.map((tab) => (...))` button renderer, branch the `onClick` on
   whether the entry has a `to`:
   ```tsx
   onClick={() => (tab.to ? navigate(tab.to) : setActiveTab(tab.key as ProjectTab))}
   ```
   and the active-state className check should treat a `to`-based tab as
   never "active" via `activeTab` (it's a route navigation away from this
   page, not a same-page state switch) — e.g. guard with
   `!tab.to && activeTab === tab.key` for the active styling condition, or
   simply leave `activeTab === tab.key` (a route tab's key will just never
   match `activeTab` so it naturally never highlights — either is fine, pick
   whichever keeps the diff smaller and compiles).

3. `navigate` is already available in this component (`const navigate =
   useNavigate();` near line 1233) — reuse it, do not add a new import.

4. `projectId` is already in scope in this component (used throughout,
   e.g. `<PhotosTab projectId={projectId ?? null} />`) — reuse the same
   variable for building the `to` template strings. If `projectId` can be
   `undefined` at the point the tab array is built, guard so `to` is only
   built when `projectId` is defined, OR simply build the string with
   `${projectId}` as-is (matching how other parts of this file already
   interpolate `projectId` into paths/keys without extra guards) — follow
   whatever the file's existing convention is once you look at it.

Do not add a "RAB" tab (no page exists yet) — the `// TODO(acap): add RAB
tab once the RAB page exists` comment above must be present in the final
code, placed among the three new tab entries (exact position doesn't
matter, just present and visible near them).

Labels must be Indonesian: "Denah", "Timeline", "Render" (exactly as shown
above — do not translate via i18n `t()`, use plain string literals to match
how ponytail says: smallest diff, these are new UI strings without existing
locale keys).

## GATE (must pass before you're done)

From `frontend/`, run the project's typecheck/build script (check
`frontend/package.json` `scripts` — likely `npx tsc -b` or `npm run build`
or `npm run typecheck`). Iterate until it passes with **zero new TypeScript
errors** (pre-existing unrelated errors, if any, are not your concern — but
there should be none introduced by these three files). Do NOT commit. Leave
the diff for human review.
