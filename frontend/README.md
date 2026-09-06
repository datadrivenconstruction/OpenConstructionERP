# OpenConstructionERP Frontend

This is the web client for OpenConstructionERP, the open construction estimating and construction management platform by DataDrivenConstruction. It is a single-page application that talks to the FastAPI backend over its REST API under `/api/v1`.

## Tech stack

- React 18 with TypeScript in strict mode.
- Vite as the dev server and build tool.
- Tailwind CSS for styling.
- Zustand for global client state (stores live in `src/stores`).
- React Query (`@tanstack/react-query`) for server state, caching, and data fetching.
- AG Grid for the Bill of Quantities (BOQ) editing grid.
- Three.js for the 3D model viewer.
- PDF.js (`pdfjs-dist`) for the PDF takeoff viewer.
- i18next with react-i18next for internationalization.

## Prerequisites

- Node.js 22 or newer. Node 24 LTS is what CI and the Docker image build with.
- npm (bundled with Node.js).
- A running backend if you want live data. See the backend README for how to start it. By default it is expected on `http://127.0.0.1:8000`.

## Getting started

Install dependencies:

```bash
npm install
```

Start the dev server:

```bash
npm run dev
```

This runs Vite and serves the app on http://localhost:5173. The port is fixed (`strictPort` is on), so if 5173 is already taken the command fails instead of picking another port. Free the port or stop the other process, then run it again.

### Talking to the backend

The dev server proxies every request under `/api` to the backend, so the app can call the API on the same origin without CORS setup. The default target is `http://127.0.0.1:8000`.

If your backend runs somewhere else, override the target with the `VITE_API_TARGET` environment variable:

```bash
VITE_API_TARGET=http://127.0.0.1:9090 npm run dev
```

On Windows PowerShell:

```powershell
$env:VITE_API_TARGET = "http://127.0.0.1:9090"; npm run dev
```

## Building for production

```bash
npm run build
```

This runs `tsc -b` first and then `vite build`. The output goes to `dist/`.

Treat `npm run build` as the real gate, not just an editor typecheck. The `tsc -b` step compiles against the project `tsconfig.json`, which turns on `noUnusedLocals`, `noUnusedParameters`, and `noUncheckedIndexedAccess`. That means the build fails on unused locals, unused parameters, and unchecked index access that a looser editor check can let through. If the build is green, the types are green.

Preview the production build locally:

```bash
npm run preview
```

## Available scripts

All scripts are defined in `package.json` and run with `npm run <name>`.

| Script | Command | What it does |
| --- | --- | --- |
| `dev` | `vite` | Start the dev server on port 5173 with hot module reload. |
| `build` | `tsc -b && vite build` | Type-check the project, then build the production bundle into `dist/`. |
| `preview` | `vite preview` | Serve the built `dist/` locally to check the production build. |
| `test` | `vitest` | Run the unit and component tests. |
| `test:e2e` | `playwright test` | Run the end-to-end browser tests. |
| `test:e2e:ui` | `playwright test --ui` | Run the end-to-end tests in the interactive runner. |
| `test:e2e:headed` | `playwright test --headed` | Run the end-to-end tests with a visible browser. |
| `test:e2e:smoke` | `playwright test smoke/` | Run only the smoke end-to-end tests. |
| `test:e2e:report` | `playwright show-report qa-report` | Open the last end-to-end HTML report. |
| `test:e2e:install` | `playwright install chromium firefox webkit --with-deps` | Install the browsers Playwright needs. |
| `lint` | `eslint .` | Lint the source with ESLint. |
| `lint:unicode` | inline Node check | Fail if any source file contains stray zero-width Unicode characters. |
| `typecheck` | `tsc --noEmit` | Type-check without emitting output. |
| `api:generate` | `openapi-typescript ...` | Regenerate `src/shared/lib/api-types.ts` from the backend OpenAPI schema. |

## Source layout

Everything lives under `src/`. The import alias `@` points at `src`, so `@/shared/lib/api` resolves to `src/shared/lib/api`.

- `app/` - the application shell, routing, providers, and i18n setup (`App.tsx`, `i18n.ts`, and the locale files).
- `features/` - one folder per product area, mirroring the backend modules. For example `projects`, `boq`, `costs`, `bim`, and takeoff. Each feature holds its own pages, components, and API calls.
- `shared/ui/` - the design system components, re-exported from `shared/ui/index.ts`.
- `shared/hooks/` - reusable React hooks.
- `shared/lib/` - framework-agnostic utilities, the API client, formatters, and the generated `api-types.ts`.
- `stores/` - Zustand stores, one file per store (for example `useAuthStore.ts`, `useThemeStore.ts`).
- `test/` - shared test setup (`setup.ts`) and asset stubs used by Vitest.

## Internationalization

Internationalization is built in, not bolted on. Each language is a TypeScript module under `src/app/locales`, one file per locale, and there are more than two dozen of them today (English, German, Russian, and many more). Locales are loaded on demand, so a session only downloads the language it needs.

Every user-facing string goes through i18n. Hardcoded UI text is not allowed. When you add a string, add its key to `en.ts` and to every other locale so no language falls back to raw keys or to English. When you add a whole new language, add one locale module under `src/app/locales` and wire it into the i18n setup in `src/app`.

## Testing

Unit and component tests run on Vitest with a jsdom environment and Testing Library. Tests are co-located with the code they cover, either next to the file (for example `BOQGrid.test.tsx` beside `BOQGrid.tsx`) or in a nearby `__tests__` folder. The shared setup lives in `src/test/setup.ts`, and Vitest picks up any file matching `src/**/*.test.{ts,tsx}`.

Run them with:

```bash
npm run test
```

End-to-end browser tests run on Playwright. Install the browsers once with `npm run test:e2e:install`, then run `npm run test:e2e`.

## Code style

- TypeScript strict mode is on. Keep it green with `npm run build`.
- There is no automatic formatter. Match the style of the file you are editing.
- Lint with ESLint: `npm run lint`.
- Components are functional and use named exports. Global client state goes in a Zustand store under `src/stores`; server state goes through React Query.
