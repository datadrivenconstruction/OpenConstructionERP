# CLAUDE.md — Frontend (React + TypeScript)

Parent: [../CLAUDE.md](../CLAUDE.md)

## Stack

- React 18 + TypeScript (strict mode)
- Vite (build)
- Tailwind CSS + CSS variables
- Zustand (global state) + React Query (server state)
- AG Grid Community (BOQ tables)
- PDF.js (takeoff viewer)
- Three.js (3D CAD viewer)
- i18next (internationalization — 20 languages)
- Yjs (real-time collaboration)

## i18n Rules

**ALL user-visible strings go through i18next. No exceptions.**

```tsx
// ✅ Correct
import { useTranslation } from 'react-i18next';
const { t } = useTranslation();
<button>{t('common.save')}</button>

// ❌ Wrong — hardcoded string
<button>Save</button>
```

Translations loaded from backend `/api/v1/i18n/{locale}` or bundled JSON.

## Commands

```bash
npm run dev          # Vite dev server on :5173
npm run build        # Production build
npm run test         # Vitest
npm run lint         # ESLint
npm run format       # Prettier
npm run typecheck    # tsc --noEmit
```

## File Conventions

- Components: `PascalCase.tsx`, one component per file
- Hooks: `use{Name}.ts`
- Stores: `use{Name}Store.ts`
- API: React Query hooks in `features/{module}/api.ts`
- Types: co-located, or `types.ts` per feature
