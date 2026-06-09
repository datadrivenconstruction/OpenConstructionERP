# Porting Guide: App Shell, White-Label Branding, Module System, Updates

Hand this file to the agent that will rebuild these features in the new platform.
It is self-contained: every feature lists the source files (path:line), the state
stores, the API endpoints, the CSS tokens, and concrete reimplementation steps.

Source stack of the original app (for reference, adapt to your target stack):
React 18 + TypeScript + Vite + Tailwind CSS + Zustand (client state) + React Query
(server state) + react-router. Backend is FastAPI. Desktop build is Tauri.

All file paths below are relative to the repo root of the source app
(`frontend/...`, `backend/...`, `desktop/...`).

What you are porting, in one sentence each:
1. A persistent app shell where the sidebar and header mount once and only the page area swaps.
2. A left sidebar with a swappable company logo (white-label), an icon-rail collapse, bottom utility buttons, and a per-user menu editor that hides/shows modules.
3. A top header bar (sticky, glass) with breadcrumb/title, search, notifications, language, theme, and account.
4. A CSS-variable design-token theming system with light/dark and a co-brand layer.
5. A plugin-style module system (manifest + loader on the backend, enable/disable + scaffold), and how the sidebar is gated by it.
6. An update system: a sidebar "update available" card, a full-screen update modal, a one-click upgrade, plus the version-check and upgrade backend endpoints.

---

## 0. Architecture: the persistent App Shell

The shell mounts the sidebar and header exactly once; route changes only swap the
page area (`<Outlet/>`). This keeps sidebar scroll position, collapse state, and
header state stable across navigation, and avoids re-mounting heavy chrome.

- `frontend/src/app/App.tsx:523-565` - `AppShell()` renders `<AppLayout>` with the
  page `<Outlet/>` inside a `<Suspense>` and an `<ErrorBoundary key={location.pathname}>`
  so a page crash does not take down the shell.
- `frontend/src/app/App.tsx:836` - the shell is mounted once: `<Route element={<AppShell/>}>`.
- `frontend/src/app/layout/AppLayout.tsx:33-185` - `AppLayout` composes `Sidebar` + `Header`
  + the content column. The sidebar is a fixed overlay drawer on mobile and a static
  column on desktop (`lg:pl-sidebar` offsets the content by the sidebar width).
- Page title flows up via a context: `PageTitleContext.Provider` in `App.tsx`; each
  page calls `setTitle(...)`, and `AppLayout` passes `title` to `Header`.

Reimplementation: create one layout route that renders `Sidebar` + `Header` + an
`<Outlet/>`. Do not put the sidebar/header inside each page. Pass the page title up
through a context or a small Zustand store.

---

## 1. Left Sidebar

Main files:
- `frontend/src/app/layout/Sidebar.tsx:924-2421` - the whole sidebar (nav groups,
  items, admin grid, footer, edit mode, keyboard shortcuts).
- `frontend/src/app/layout/AppLayout.tsx` - mounts it, handles mobile drawer.
- `frontend/src/app/layout/CustomBranding.tsx:73-224` - the top logo/brand block.
- `frontend/src/app/layout/routeIcons.ts:92-248` - route to lucide-icon map (shared with header).

### 1.1 Nav data model (data-driven)

Nav items and groups are plain data arrays, not hardcoded JSX:

```ts
// Sidebar.tsx:113-176
interface NavItem {
  labelKey: string;            // i18n key
  to: string;                  // route path (may carry ?query)
  icon: LucideIcon;
  badge?: string;              // e.g. 'BETA'
  moduleKey?: string;          // gating key: hidden unless module enabled
  advancedOnly?: boolean;      // hidden in "simple" view mode
  roleGate?: ('admin'|'manager'|'editor'|'viewer')[];
  adminOnly?: boolean;
}
interface NavGroup {
  id: string;                  // 'grp_overview', 'grp_estimating', ...
  labelKey: string;
  items: NavItem[];
  defaultOpen: boolean;
  hideInSimple?: boolean;      // collapsed away in simple mode
  separator?: boolean;
}
```

- The group array is defined at `Sidebar.tsx:179-508` (about 19 groups: overview,
  estimating, cost data, takeoff, coordination, scheduling, cost control, commercial,
  procurement, field, resources, quality, safety, communication, documents, real
  estate, finance, controls/BI, automation/AI).
- Dynamic items from the module registry are injected per group via
  `getModuleNavItems(group.id)` (`Sidebar.tsx:1448`).
- Active route resolution is query-aware then longest-prefix: `pickActiveRoute()`
  at `Sidebar.tsx:873-922` (so `/bim` and `/bim/rules` do not both light up).
- Active item style: `border-l-2 border-oe-blue bg-oe-blue/[0.14] text-oe-blue`
  (`Sidebar.tsx:2091`).

Reimplementation: keep nav as a typed array. Gate each item by `moduleKey` (section 5)
and by role. Resolve the active item with longest-prefix matching.

### 1.2 Collapse to an icon rail (push left)

Two desktop widths: full (248px) and icon-only (64px). There is no fully-hidden
desktop mode; mobile uses an overlay drawer instead.

- Store: `frontend/src/stores/useSidebarCollapseStore.ts:1-47`
  - localStorage key `oe_sidebar_iconified`
  - exports `SIDEBAR_WIDTH_FULL = '248px'`, `SIDEBAR_WIDTH_ICON = '64px'`
  - shape: `{ iconified: boolean; setIconified; toggle }`
- The width is published to CSS as a variable so the content offset follows it:
  `Sidebar.tsx:988-991` sets `--oe-sidebar-width` to the icon or full width in a
  `useEffect`. Content uses `lg:pl-sidebar` where `sidebar` spacing = `var(--oe-sidebar-width)`.
- Toggle control: a half-protruding pill on the inner edge, `Sidebar.tsx:1297-1351`
  (`onClick={toggleIconified}`, chevron rotates, `transition-all duration-200`).
- In icon mode: labels hide, items become icon buttons with native `title` tooltips
  (`Sidebar.tsx:2015-2052`); group headers collapse to thin hairlines.

Reimplementation: store one boolean (iconified) in localStorage; drive the column
width and the content left-padding from a single CSS variable so they animate together.

### 1.3 Top logo + white-label branding (the key white-label feature)

The brand block at the top of the sidebar supports three modes so a company can drop
in their own logo while only a small "by <product>" mark remains.

- Component: `frontend/src/app/layout/CustomBranding.tsx:73-224`
- Store: `frontend/src/stores/useBrandingStore.ts:1-147`
  - localStorage key `oe_custom_branding_v1`, logo cap `MAX_LOGO_BYTES = 2 MB`
  - shape:
    ```ts
    type BrandingMode = 'default' | 'logo' | 'text';
    interface BrandingState {
      mode: BrandingMode;
      logoDataUrl: string | null;   // base64 data URL (PNG/JPG/SVG/WebP)
      companyName: string;
      setLogo(d: string | null): void;
      setCompanyName(n: string): void;
      reset(): void;
    }
    ```
  - cross-tab sync via `window 'storage'` listener (`useBrandingStore.ts:87`).
- Modes (`CustomBranding.tsx`):
  - `default`: the product wordmark.
  - `logo`: the uploaded logo (`<img ... max-h-[40px] object-contain>`), with a small
    `by <product>` line at about 8px beneath it (the only remaining original brand).
  - `text`: the company name in the wordmark font, same small `by <product>` line.
- Editor: `BrandingEditorModal` (in the same file, around `:233-536`) - two tabs
  (logo drag/drop or file picker, and company name). The logo is read client-side to a
  base64 data URL; no backend upload is required. A pencil button next to the brand
  opens it; the same editor is reused on the login page.
- Browser tab title also follows the company name:
  `AppLayout.tsx:54-62` builds `document.title` as `"<page> | <companyName or product>"`.

Reimplementation: store `{mode, logoDataUrl, companyName}` in localStorage. Render the
logo when `mode==='logo'`, the name when `mode==='text'`, the product wordmark
otherwise. Always render a tiny "by <product>" mark so attribution survives. Keep the
logo client-side as a data URL so it works offline and needs no upload endpoint.

### 1.4 Bottom of the sidebar (utility buttons)

Above the footer there is a 2-column "admin grid" and a footer with external links,
version, license, and the update card.

- Admin grid items (`Sidebar.tsx:524-541`): Settings, Users, Modules, Governance
  (role-gated), Audit log (role-gated), About. Rendered by `AdminGrid`
  (`Sidebar.tsx:2253-2339`); role-gated by JWT role.
- Footer (`Sidebar.tsx:1750-1845`):
  - GitHub and Telegram buttons, the version string `v{APP_VERSION}`, and an AGPL link
    to `/api/source`.
  - The update card `<UpdateNotification/>` is rendered here when not iconified
    (`Sidebar.tsx:1744-1748`). See section 6.
- In icon mode these become stacked icon-only buttons.

Reimplementation: a small grid of secondary destinations plus a footer row with
external links, the version, and the update card.

### 1.5 Menu editor: per-user module visibility (show/hide items)

Users can hide nav items they do not use; the choice persists per user.

- Enter edit mode: dashed "Edit menu" button with a pencil icon
  (`Sidebar.tsx:1604-1627`). In edit mode it becomes Save/Cancel (`:1575-1601`).
- Per-item toggle: in edit mode each row shows an Eye/EyeOff button instead of the pin
  (`Sidebar.tsx:2184-2210`); handler `handleHiddenClick` stops navigation and calls
  `onToggleHidden(item.to)` (`:1997-2004`). Hidden rows render at `opacity-50`.
- Working set vs committed: edit mode edits a transient `editingHidden` set; in edit
  mode `effectiveHidden = []` so everything shows (`Sidebar.tsx:1053`); normal render
  filters with `!effectiveHidden.includes(item.to)` (`:1487`) and drops empty groups.
- A "{n} hidden" badge appears next to Edit menu when items are hidden (`:1615-1625`).
- Persistence hook: `frontend/src/shared/hooks/useHiddenModules.ts`
  - localStorage cache key `oe.sidebar_hidden_modules:{userEmail}` (per-user scoped).
  - server endpoint `GET/PUT /v1/users/me/sidebar-preferences/`, payload
    `{ hidden_modules: string[] }`.
  - optimistic: writes local + localStorage immediately, then background-saves via
    React Query; next mount reconciles server vs local by deep-equality.
  - returns `{ hiddenModules, setHiddenModules, isLoading }`.

Reimplementation: store `hidden_modules: string[]` per user (server + localStorage
cache). In edit mode show all rows with eye toggles editing a temporary set; on Save,
commit to the server. In normal mode filter the nav by the committed set.

---

## 2. Top Header

File: `frontend/src/app/layout/Header.tsx:1-368`. Mounts once inside `AppLayout`
(`AppLayout.tsx:135-138`), receives `title` and `onMenuClick`.

### 2.1 Layout

Container (`Header.tsx:204-210`):

```
sticky top-0 z-30 flex h-header items-center justify-between gap-3
px-4 sm:px-6 lg:px-8 bg-surface-primary/80 backdrop-blur-xl
```

- height = `var(--oe-header-height)` (52px), sticky, `z-30` (below modals), glass
  background at 80% opacity with `backdrop-blur-xl`, a soft gradient hairline at the
  bottom (`:213`).

Zones, left to right:
- Left: mobile hamburger (`lg:hidden`), project switcher, chevron, page title `h1`
  with the route icon, and a "module info reopener" icon (section 2.2).
- Center: partner co-brand badge, only when a partner pack is active
  (`Header.tsx:284-288`, `hidden lg:flex`).
- Right: command-palette (Ctrl/Cmd+K) trigger, notifications bell, support/subscribe
  CTAs, bug-report and help popovers, upload-queue indicator, language switcher, theme
  toggle, user menu.

### 2.2 Module info: collapse a page header into the top bar

Pages can show a dismissible "module info" help card. When collapsed, it parks a small
reopener icon in the header.

- Store: `frontend/src/stores/useModuleInfoStore.ts:1-49` -
  `entries: {key, expand}[]`, `register`, `unregister`, `expandAll`.
- Header reopener: `Header.tsx:269` renders `ModuleInfoReopener` (`:375-393`); clicking
  it calls `expandAll()`. The icon disappears when no cards are collapsed.

Reimplementation: a tiny registry store; the page card registers an `expand` callback
on collapse; the header shows a reopener that calls `expandAll()`.

### 2.3 Partner co-brand badge

- Hook: `frontend/src/shared/hooks/usePartnerPack.ts` reads `GET /api/v1/partner-pack/current`.
- Badge: `frontend/src/shared/ui/PartnerLogoBadge.tsx`, variant `nav` (compact chip in
  the header center) and `dashboard` (wider banner). Shows partner logo (from
  `/api/v1/partner-pack/logo/{slug}`, public) or an initials monogram, a "in
  partnership with <name>" label, and a session-dismiss button.
- Colors come from the pack manifest `branding.primary_color` / `accent_color`; falls
  back to the app accent if missing.

---

## 3. Theming: design tokens, dark mode, re-skin

### 3.1 Tokens

All colors, radii, shadows, and layout sizes are CSS variables in
`frontend/src/index.css:8-172` (`:root`) with dark overrides at `:176-258` (`.dark`).
Key tokens:

```css
:root {
  --oe-blue: #0071e3;            /* brand accent */
  --oe-blue-ch: 0 113 227;       /* RGB channel triplet, needed for alpha utilities */
  --oe-bg: #ffffff; --oe-bg-secondary: #f5f5f7; --oe-bg-tertiary: #fbfbfd;
  --oe-border: #d2d2d7; --oe-border-light: #e8e8ed;
  --oe-text-primary: #1d1d1f; --oe-text-secondary: #5b5e66; --oe-text-tertiary: #666b78;
  --oe-success: #1d7a3a; --oe-warning: #b45309; --oe-error: #c41e10; --oe-info: #0369a1;
  --oe-radius-sm: 6px; --oe-radius-md: 8px; --oe-radius-lg: 10px; --oe-radius-xl: 12px;
  --oe-sidebar-width: 248px; --oe-header-height: 52px; --oe-content-max-width: 1440px;
}
.dark { --oe-blue: #3b82f6; --oe-bg: #0f1117; --oe-bg-secondary: #161822; /* ... */ color-scheme: dark; }
```

Important gotcha: any token used with a Tailwind alpha modifier (e.g. `bg-oe-blue/10`)
needs a matching `-ch` channel triplet, and Tailwind must define the color in
function form so `rgb(var(--oe-blue-ch) / 0.1)` resolves. Without the `-ch` variant the
alpha utilities are silently dropped at build time.

- Tailwind config: `frontend/tailwind.config.js` - `darkMode: 'class'`, colors mapped to
  the CSS vars (function form with channel triplets), `spacing.sidebar` =
  `var(--oe-sidebar-width)`, `spacing.header` = `var(--oe-header-height)`,
  radii/shadows mapped to the vars.

### 3.2 Theme switching

- Store: `frontend/src/stores/useThemeStore.ts` - `theme: 'light'|'dark'|'system'`,
  `resolved`, `setTheme`, `init`. localStorage key `oe_theme`. Applies the `.dark`
  class to `<html>`; in `system` mode it follows `matchMedia('(prefers-color-scheme: dark)')`.
  A 350ms `theme-transition` class animates the color swap.
- Toggle button: `ThemeToggle` in the header (cycles light -> dark -> system).

Reimplementation / re-skin for a company: change `--oe-blue` (+ its `-ch` triplet) and
the surface/text tokens; keep the same variable names so component classes need no
edits. Toggle dark by adding/removing `.dark` on `<html>`.

---

## 4. Product-name centralization (what to replace for white-label)

The dynamic brand (sidebar logo/name, partner badge, tab title) is already swappable.
The fixed product name still appears as literals in a few places; centralize these in
the new app behind one constant so a deployment can rename everything:

- `frontend/src/app/layout/CustomBranding.tsx:163-167` - the "by <product>" attribution.
- `frontend/src/app/layout/Header.tsx` - bug-report subject and GitHub repo slug
  (`:524`, `:857`, `:900`, `GITHUB_REPO` at `:990`).
- `index.html` - tab title and SEO/OG/JSON-LD meta.
- Sidebar footer GitHub/Telegram URLs (`Sidebar.tsx:1761`, `:1771`).

Recommended: introduce `PRODUCT_NAME`, `GITHUB_REPO`, `SUPPORT_URL` constants (or build
env vars) and reference them everywhere instead of literals. The only intentionally
persistent mark is the small "by <product>" line in the sidebar brand block.

---

## 5. Module system (creating and toggling modules)

### 5.1 Backend: manifest + loader (plugin discovery)

- Loader: `backend/app/core/module_loader.py`
  - `ModuleManifest` dataclass (`:29-44`): `name, version, display_name, description,
    author, category, depends, optional_depends, display_name_i18n, auto_install, enabled`.
  - Discovery (`:69-106`): scans `app/modules/*/manifest.py`, imports each, keys by name.
  - Dependency order (`:108-136`): topological sort over `depends`, detects cycles.
  - Load (`:138-259`): imports the package and auto-registers by convention -
    `router.py` mounts at `/api/v1/{kebab-name}`, `models.py` for Alembic,
    plus `hooks.py`, `events.py`, `validators.py`, `pipeline_nodes.py`; calls
    optional `on_startup()`.
- Module folder convention: `manifest.py, models.py, schemas.py, router.py, service.py,
  repository.py, hooks.py, events.py, validators.py, migrations/, tests/`.

### 5.2 Backend: enable/disable API

- `backend/app/core/module_router.py` (prefix `/api/v1/modules`):
  - `GET /` list all with status (`:22`).
  - `POST /{module_name}/enable` (admin) (`:40`).
  - `POST /{module_name}/disable` (admin, fails if dependents are enabled) (`:62`).
  - `GET /dependency-tree/{module_name}` (`:84`).
  - list item shape includes `has_router, loaded, enabled, is_core, depends, category`.

### 5.3 Scaffolding a new module

- CLI: `make module-new NAME=oe_my_module` -> `backend/app/scripts/scaffold_module.py`.
  Copies `modules/oe-module-template/` and substitutes `{{module_name}}`,
  `{{module_short}}`, `{{display_name}}`, `{{author}}`. Produces manifest/router/models/
  schemas/service/repository/tests + a migration stub. Post steps: edit manifest, move
  the migration into `backend/alembic/versions/` with a correct `down_revision`, run
  migrate + tests.

### 5.4 Frontend: gating + the /modules page

- Store: `frontend/src/stores/useModuleStore.ts` - `isModuleEnabled(key)` (core always
  true), `setModuleEnabled`, `canDisable` (returns blockers). Server pref endpoint
  `GET /v1/users/me/module-preferences/` -> `{ modules: { [key]: boolean } }`.
- Sidebar gating: `Sidebar.tsx:1477` shows an item only when
  `!item.moduleKey || isModuleEnabled(item.moduleKey)`; backend-disabled routes are also
  filtered (`isRouteBackendDisabled`). `useModulePresence()` dims routes with no data
  for the current project (separate from enable/disable).
- Page: `frontend/src/features/modules/ModulesPage.tsx` - tabs for Company Profiles,
  Partner Packs, Data Packages, and System Modules (enable/disable toggles backed by the
  module API). `ModuleDeveloperGuide.tsx` documents building modules (scaffold via CLI,
  no in-UI upload).

Reimplementation: keep one registry of modules with `enabled` per user; gate nav items
by module key; expose an admin toggle page. Module creation is a developer/CLI flow, not
an end-user upload.

---

## 6. Update / upgrade system

Three surfaces: a small sidebar card, a full-screen modal, and a one-click upgrade.
Frontend file: `frontend/src/shared/ui/UpdateChecker.tsx`.

### 6.1 Sidebar "update available" card

- `UpdateNotification()` (`UpdateChecker.tsx:267-425`): compact gradient card showing
  `v{CURRENT} -> v{LATEST}`, an "available" pill, the publish date, and a change count.
  Clicking it opens the full modal (`setShowFullModal(true)`).
- Show condition (`:334-335`): render only if a newer release exists and it is not
  dismissed. Dismiss stores the version in `sessionStorage` so it stays hidden until a
  newer version appears.
- Placement: `Sidebar.tsx:1744-1748`, only when not iconified. The About page renders
  `<UpdateNotification forceShow hideDismiss/>` (`AboutPage.tsx:96`).

### 6.2 Full-screen update modal

- `UpdateFullModal()` (`UpdateChecker.tsx:486-844`). States:
  - idle: "Install v{version} now" button, plus copyable pip/git commands and a "how to
    update" section.
  - running: spinner, "Running pip install, this can take a minute".
  - done: checkmark, "Installed v{version}", restart hint, expandable pip log.
  - error: error text + pip log + the command to run manually.
- Header shows the version, date, change count, current version. Highlights are parsed
  from the release notes and grouped into New/Fixed/Polished/Other
  (`groupHighlights`, `:98-185`), max 6 per group with a "+N more".
- One-click apply calls `POST /api/system/upgrade` (`:513`).

### 6.3 Version check

- Current version: `frontend/src/shared/lib/version.ts:9` - `APP_VERSION`, injected by
  Vite from `package.json` (`__APP_VERSION__` define).
- Frontend check (`UpdateChecker.tsx:219-257`): first run ~2s after mount, then hourly;
  caches in localStorage (`oe_update_cache_v1`, 1h TTL); compares with `isNewer()`
  (`:88-96`, numeric semver). It reads GitHub releases-latest directly, and the backend
  also exposes a check (below) that additionally consults PyPI.

### 6.4 Backend endpoints

- `GET /api/system/version-check` (`backend/app/main.py:1447-1513`): returns
  `{current_version, latest_version, update_available, release_url, release_notes,
  published_at, upgrade_command}`. Sources PyPI first, GitHub releases as fallback; 4h
  cache; compares via `_semver_tuple()` (`:1425-1444`).
- `POST /api/system/upgrade` (`main.py:1515-1599`): runs
  `python -m pip install --upgrade <package>[==version]` in the same interpreter,
  captures stdout/stderr, reads the new installed version, clears the version cache, and
  returns `{ok, exit_code, command, stdout, stderr, installed_version, running_version,
  restart_required, restart_hint}`. Gated by env `ALLOW_RUNTIME_UPGRADE` (default true;
  set false for managed/SaaS installs -> 403).
- Version detection: `backend/app/config.py:82-109` reads `pyproject.toml` when running
  from source, else `importlib.metadata.version(...)`.
- CLI equivalent: `backend/app/cli.py:900-941` - `<package> upgrade [--version]` runs the
  same pip command in the launcher's venv, then prints a restart instruction.

### 6.5 Desktop note

- `desktop/src-tauri/tauri.conf.json`: `createUpdaterArtifacts: false`, no Tauri updater
  plugin (it was removed in 7.0.x after a crash). The desktop app upgrades through the
  same `POST /api/system/upgrade` endpoint, then the user restarts the launcher. Windows
  webview uses `embedBootstrapper` (WebView2 bundled, not downloaded).

### 6.6 Changelog

- `frontend/src/features/about/Changelog.tsx` - a hand-maintained array
  `{version, date, summary, tag}` sorted newest first, rendered in responsive columns.

Reimplementation: store the current version at build time; poll a "latest version"
source (your releases API or package index) on an interval with a cached compare; show
the small card when newer; open a modal that calls a guarded server "upgrade" endpoint
running your package manager, streams the log, and asks for a restart. Keep a guard env
so hosted/managed installs disable the in-app upgrade.

---

## 7. Quick reference tables

### Zustand stores
| Store | File | Persists (key) | Purpose |
|---|---|---|---|
| useSidebarCollapseStore | stores/useSidebarCollapseStore.ts | localStorage `oe_sidebar_iconified` | icon-rail collapse + widths |
| useBrandingStore | stores/useBrandingStore.ts | localStorage `oe_custom_branding_v1` | white-label logo/name |
| useThemeStore | stores/useThemeStore.ts | localStorage `oe_theme` | light/dark/system |
| useModuleInfoStore | stores/useModuleInfoStore.ts | in-memory | collapse page info into header |
| useModuleStore | stores/useModuleStore.ts | localStorage + server | per-user module enable/disable |
| useHiddenModules (hook) | shared/hooks/useHiddenModules.ts | localStorage `oe.sidebar_hidden_modules:{email}` + server | menu editor hidden items |

### API endpoints
| Endpoint | Purpose |
|---|---|
| GET/PUT /v1/users/me/sidebar-preferences/ | `{hidden_modules: string[]}` menu editor |
| GET /v1/users/me/module-preferences/ | `{modules: {[key]: boolean}}` module toggles |
| GET /api/v1/modules/ , POST /{name}/enable|disable | module management (admin) |
| GET /api/v1/partner-pack/current , /logo/{slug} | co-brand pack + logo |
| GET /api/system/version-check | current/latest version + notes |
| POST /api/system/upgrade | run pip upgrade (guarded by ALLOW_RUNTIME_UPGRADE) |

### Layout constants
| Token | Value | Where |
|---|---|---|
| sidebar full width | 248px | useSidebarCollapseStore + `--oe-sidebar-width` |
| sidebar icon width | 64px | same |
| header height | 52px | `--oe-header-height` |
| modal z-index | 40/110 | header is z-30, below modals |

---

## 8. Suggested build order in the new app

1. Persistent shell route (sidebar + header + Outlet), page-title context.
2. CSS-variable tokens + Tailwind mapping + theme store (light/dark).
3. Sidebar: nav data model, active resolution, icon-rail collapse.
4. Branding block + store + editor modal (the white-label win).
5. Header zones (title/breadcrumb, search, language, theme, account) + module-info reopener.
6. Module registry + gating + admin toggle page; wire `moduleKey` gating into nav.
7. Menu editor (hidden modules) with server-backed persistence.
8. Update card + full-screen modal + version-check/upgrade endpoints (guarded).
9. Partner co-brand badge (optional second branding layer).
