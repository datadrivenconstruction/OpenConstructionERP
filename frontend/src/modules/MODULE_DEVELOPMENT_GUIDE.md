# Module Development Guide

How to create, register, and publish a plugin module for OpenConstructionERP.

---

## Quick Start (5 minutes)

```
frontend/src/modules/
├── _types.ts          ← TypeScript interfaces (DO NOT EDIT)
├── _registry.ts       ← Central registry (add your import here)
├── your-module/       ← Your module folder
│   ├── manifest.ts    ← Required: metadata, routes, nav, translations
│   ├── YourModule.tsx ← Main page component (React.lazy loaded)
│   ├── index.ts       ← Barrel export
│   └── ...            ← Data helpers, sub-components, tests
```

### Step 1: Create the folder

```
frontend/src/modules/my-feature/
```

### Step 2: Create `manifest.ts`

```ts
import { lazy } from 'react';
import { Sparkles } from 'lucide-react';         // pick any lucide icon
import type { ModuleManifest } from '../_types';

const MyFeatureModule = lazy(() => import('./MyFeatureModule'));

export const manifest: ModuleManifest = {
  id: 'my-feature',                               // unique, kebab-case
  name: 'My Feature',                             // display name
  description: 'Short description of what it does',
  version: '1.0.0',                               // semver
  icon: Sparkles,
  category: 'tools',                              // estimation | planning | procurement | tools
  defaultEnabled: false,                           // false = user must enable in Modules page
  depends: ['boq'],                                // optional: module IDs this depends on

  routes: [
    {
      path: '/my-feature',                         // URL path
      title: 'My Feature',                         // shown in header
      component: MyFeatureModule,
    },
  ],

  navItems: [
    {
      labelKey: 'nav.my_feature',                  // i18n key (MUST be registered — see Step 5)
      to: '/my-feature',
      icon: Sparkles,
      group: 'tools',                              // sidebar group
      advancedOnly: true,                          // only visible in Advanced mode
    },
  ],

  searchEntries: [
    {
      label: 'My Feature',
      path: '/my-feature',
      keywords: ['feature', 'custom', 'plugin'],   // fuzzy search terms
    },
  ],

  // Optional: module-bundled translations (merged into i18next on load)
  translations: {
    en: {
      'myfeature.title': 'My Feature',
      'myfeature.subtitle': 'Description here',
    },
    de: {
      'myfeature.title': 'Meine Funktion',
      'myfeature.subtitle': 'Beschreibung hier',
    },
  },
};
```

### Step 3: Create the page component

```tsx
// frontend/src/modules/my-feature/MyFeatureModule.tsx
import { useTranslation } from 'react-i18next';

export default function MyFeatureModule() {
  const { t } = useTranslation();

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <h1 className="text-2xl font-bold">
          {t('myfeature.title', { defaultValue: 'My Feature' })}
        </h1>
      </div>
      <p className="text-gray-500">
        {t('myfeature.subtitle', { defaultValue: 'Description here' })}
      </p>

      {/* Your module UI here */}
    </div>
  );
}
```

### Step 4: Create `index.ts`

```ts
export { manifest } from './manifest';
```

### Step 5: Register the module

Edit `frontend/src/modules/_registry.ts`:

```ts
// Add import
import { manifest as myFeature } from './my-feature/manifest';

// Add to array
export const MODULE_REGISTRY: ModuleManifest[] = [
  sustainability,
  costBenchmark,
  // ... existing modules ...
  myFeature,        // ← add here
];
```

Edit `frontend/src/app/i18n.ts` — find each language block (search for `// === English`, `// === German`, etc.) and add the nav key:

```ts
// In the English block:
'nav.my_feature': 'My Feature',

// In the German block:
'nav.my_feature': 'Meine Funktion',

// In the French block:
'nav.my_feature': 'Ma fonctionnalité',

// In the Russian block:
'nav.my_feature': 'Моя функция',
```

> **Why both places?** The `translations` field in the manifest is loaded asynchronously via dynamic `import()`. The sidebar renders synchronously at startup. If the nav key isn't in `i18n.ts`, users see the raw key for a split second. Always add `nav.*` keys to `i18n.ts` directly.

### Step 6: Done!

- `npm run dev` — your module appears in Modules page
- Toggle it on → appears in sidebar
- Click → navigates to your page (lazy-loaded)
- Search (`/`) → your module appears in results

---

## Architecture Deep Dive

### How modules get loaded

```
App startup
    │
    ├── _registry.ts imports all manifest.ts files (tiny, no page code)
    │
    ├── useModuleStore reads enabled/disabled state from localStorage
    │
    ├── App.tsx calls getAllModuleRoutes() → registers <Route> for each
    │   └── Components are React.lazy() → code-split by Vite automatically
    │
    ├── Sidebar.tsx calls getModuleNavItems(groupId) → shows nav links
    │   └── Filtered by isModuleEnabled() from useModuleStore
    │
    ├── CommandPalette calls getModuleSearchEntries() → search results
    │
    └── ModulesPage reads MODULE_REGISTRY → renders toggle cards
```

### Module lifecycle

| Event | What happens |
|-------|-------------|
| User enables module | `useModuleStore.setModuleEnabled(id, true)` → saved to localStorage |
| User navigates to route | React.lazy triggers dynamic import → Vite loads chunk |
| User disables module | Nav item hidden, route still works (direct URL) |
| App starts | Module manifests loaded, routes registered, nav filtered |

### Dependencies

If your module `depends: ['boq']`, then:
- User cannot enable your module unless `boq` is enabled
- If user disables `boq`, your module gets disabled too
- Modules page shows "Requires: Bill of Quantities" badge

### Sidebar groups

| Group ID | Section | Typical modules |
|----------|---------|----------------|
| `estimation` | Estimation | Projects, BOQ, Costs, Assemblies |
| `planning` | Planning | Schedule, 5D Cost Model |
| `procurement` | Procurement | Tendering, Reports |
| `tools` | Tools | Validation, Sustainability, Benchmarks, **your module** |

---

## Common Patterns

### Fetching data from the API

```tsx
import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/shared/lib/api';

// Fetch projects
const { data: projects = [] } = useQuery({
  queryKey: ['projects'],
  queryFn: () => apiGet<Project[]>('/v1/projects/'),
});

// Fetch BOQs for a project
const { data: boqs = [] } = useQuery({
  queryKey: ['boqs', projectId],
  queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${projectId}`),
  enabled: !!projectId,
});

// Fetch BOQ with positions (CORRECT way — positions are embedded)
const { data: positions = [] } = useQuery({
  queryKey: ['boq-positions', boqId],
  queryFn: async () => {
    const boq = await apiGet<{ positions?: Position[] }>(`/v1/boq/boqs/${boqId}`);
    return boq.positions ?? [];
  },
  enabled: !!boqId,
});
```

> **Important:** There is no `GET /v1/boq/boqs/{id}/positions/` endpoint. Positions are returned as part of the BOQ detail response at `GET /v1/boq/boqs/{id}`.

### Using toasts

```tsx
import { useToastStore } from '@/stores/useToastStore';

const { addToast } = useToastStore();
addToast({
  type: 'success',           // 'success' | 'error' | 'info' | 'warning'
  title: 'Done!',
  message: 'Operation completed',
});
```

### Using shared UI components

```tsx
import { Button, Badge } from '@/shared/ui';

<Button variant="primary" onClick={handleClick}>
  Run Analysis
</Button>

<Badge variant="green">Active</Badge>
```

### Pure data logic (testable without React)

Put computation in a separate `data/` folder:

```
my-feature/
├── data/
│   ├── calculator.ts          ← pure functions, no React
│   └── calculator.test.ts     ← unit tests (vitest)
├── MyFeatureModule.tsx         ← React page
├── manifest.ts
└── index.ts
```

```ts
// data/calculator.ts
export function computeResult(input: number[]): number {
  return input.reduce((sum, v) => sum + v, 0);
}
```

```ts
// data/calculator.test.ts
import { describe, it, expect } from 'vitest';
import { computeResult } from './calculator';

describe('computeResult', () => {
  it('sums all values', () => {
    expect(computeResult([1, 2, 3])).toBe(6);
  });
});
```

### Multi-tab page layout

```tsx
const [activeTab, setActiveTab] = useState<'import' | 'export'>('import');

<div className="flex gap-1 border-b border-gray-200">
  <button
    onClick={() => setActiveTab('import')}
    className={activeTab === 'import' ? 'border-b-2 border-blue-500 font-medium' : 'text-gray-500'}
  >
    Import
  </button>
  <button
    onClick={() => setActiveTab('export')}
    className={activeTab === 'export' ? 'border-b-2 border-blue-500 font-medium' : 'text-gray-500'}
  >
    Export
  </button>
</div>

{activeTab === 'import' && <ImportPanel />}
{activeTab === 'export' && <ExportPanel />}
```

---

## Translation Guidelines

### Where to put translations

| Key prefix | Where to define | Why |
|-----------|----------------|-----|
| `nav.*` | `i18n.ts` (main) | Sidebar renders synchronously at startup |
| `modules.*` | `i18n.ts` (main) OR manifest `translations` | Module listing page |
| `yourmodule.*` | manifest `translations` | Module-specific strings |

### Minimum languages

Always provide at least **English** and **German** (DACH market is primary). French and Russian are recommended.

```ts
translations: {
  en: { 'mymod.title': 'My Module' },
  de: { 'mymod.title': 'Mein Modul' },
  fr: { 'mymod.title': 'Mon Module' },
  ru: { 'mymod.title': 'Мой модуль' },
},
```

### Using translations in components

```tsx
const { t } = useTranslation();

// Always provide a defaultValue fallback
{t('mymod.title', { defaultValue: 'My Module' })}
```

---

## Testing

### Test file location

```
my-feature/
├── data/
│   └── helper.test.ts          ← unit tests for pure logic
├── MyFeatureModule.test.tsx     ← component tests (optional)
```

### Running tests

```bash
# All tests
npx vitest run

# Only your module
npx vitest run src/modules/my-feature

# Watch mode
npx vitest src/modules/my-feature
```

### Example test

```ts
import { describe, it, expect } from 'vitest';
import { myFunction } from './data/helper';

describe('myFunction', () => {
  it('handles basic case', () => {
    expect(myFunction(10)).toBe(20);
  });

  it('handles edge case', () => {
    expect(myFunction(0)).toBe(0);
  });
});
```

---

## Checklist

Before submitting your module:

- [ ] `manifest.ts` has unique `id` (kebab-case)
- [ ] Page component uses `export default` (required for React.lazy)
- [ ] `index.ts` exports manifest
- [ ] Module registered in `_registry.ts`
- [ ] `nav.*` key added to all 4 language blocks in `i18n.ts`
- [ ] `defaultEnabled: false` (users opt-in)
- [ ] `depends` lists any required modules
- [ ] Tests pass: `npx vitest run src/modules/your-module`
- [ ] Build passes: `npx vite build`
- [ ] Manual test: toggle on/off in Modules page, navigate to route, check sidebar

---

## Real Examples

| Module | Files | What it demonstrates |
|--------|-------|---------------------|
| `sustainability/` | Simple page, i18n keys as name | Minimal module |
| `cost-benchmark/` | API data fetching, charts | Data visualization module |
| `pdf-takeoff/` | Canvas rendering, tools | Complex interactive module |
| `risk-analysis/` | Pure logic in `data/`, Monte Carlo | Heavy computation + data separation |
| `gaeb-exchange/` | Tabs, file upload, XML generation | Import/export module with file handling |
| `collaboration/` | Hooks, real-time features | Advanced hooks module |

---

## ModuleManifest Interface Reference

```ts
interface ModuleManifest {
  id: string;                    // Unique kebab-case identifier
  name: string;                  // Display name (plain text or i18n key starting with 'modules.')
  description: string;           // Short description (plain text or i18n key)
  version: string;               // SemVer: '1.0.0'
  icon: LucideIcon;              // Any icon from 'lucide-react'
  category: 'estimation' | 'planning' | 'procurement' | 'tools';
  defaultEnabled: boolean;       // false = opt-in
  depends?: string[];            // Module IDs this requires
  routes: ModuleRoute[];         // Pages to register
  navItems: ModuleNavItem[];     // Sidebar links
  searchEntries?: ModuleSearchEntry[];  // Command palette entries
  translations?: Record<string, Record<string, string>>;  // Bundled i18n
}
```
