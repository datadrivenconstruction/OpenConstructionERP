/**
 * ModuleDeveloperGuide — in-app, readable, search-friendly guide for
 * building your own module. Mirrors the repo's MODULES.md but rendered
 * natively so users don't leave the app to learn the workflow.
 */

import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import {
  Package,
  Server,
  Layers,
  Sparkles,
  CheckCircle2,
  Info,
  ArrowLeft,
  Terminal,
  FileText,
  FolderTree,
  ExternalLink,
  BookOpen,
  Bot,
  Wrench,
  Database,
  Zap,
  Lock,
  TestTube2,
  AlertTriangle,
  Rocket,
  Download,
} from 'lucide-react';
import { Card, Badge, Breadcrumb } from '@/shared/ui';

interface StepProps {
  number: number;
  title: string;
  children: React.ReactNode;
}

function Step({ number, title, children }: StepProps) {
  return (
    <div className="flex gap-4">
      <div className="shrink-0 h-8 w-8 rounded-full bg-oe-blue/10 text-oe-blue font-bold flex items-center justify-center text-sm">
        {number}
      </div>
      <div className="flex-1 min-w-0 pb-1">
        <h4 className="font-semibold text-content-primary mb-2">{title}</h4>
        <div className="text-sm text-content-secondary leading-relaxed space-y-3">{children}</div>
      </div>
    </div>
  );
}

interface CodeProps {
  lang?: string;
  children: string;
}

function Code({ lang, children }: CodeProps) {
  return (
    <pre className="not-prose relative overflow-x-auto rounded-lg bg-gray-900 dark:bg-gray-950 text-gray-100 text-[11.5px] leading-relaxed p-4 font-mono border border-border-light">
      {lang && (
        <span className="absolute top-2 right-2 text-[9px] uppercase tracking-wider text-gray-400">
          {lang}
        </span>
      )}
      <code className="whitespace-pre">{children}</code>
    </pre>
  );
}

function Inline({ children }: { children: React.ReactNode }) {
  return (
    <code className="rounded bg-surface-secondary px-1 py-0.5 text-[12px] font-mono text-oe-blue">
      {children}
    </code>
  );
}

export function ModuleDeveloperGuide() {
  const { t } = useTranslation();

  return (
    <div className="max-w-4xl mx-auto animate-fade-in">
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', 'Dashboard'), to: '/' },
          { label: t('nav.modules', 'Modules'), to: '/modules' },
          { label: t('modules.dev_guide', 'Developer guide') },
        ]}
        className="mb-4"
      />

      {/* Header */}
      <div className="mb-6">
        <div className="flex items-center gap-3 mb-2">
          <div className="h-11 w-11 rounded-xl bg-gradient-to-br from-oe-blue to-blue-700 text-white flex items-center justify-center shadow-sm">
            <Package size={20} />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-content-primary">
              {t('modules.dev_guide_title', { defaultValue: 'Build your own module' })}
            </h1>
            <p className="text-sm text-content-secondary">
              {t('modules.dev_guide_subtitle', {
                defaultValue:
                  'A practical, 10-minute walkthrough for adding business features to OpenConstructionERP.',
              })}
            </p>
          </div>
        </div>
        <Link
          to="/modules"
          className="inline-flex items-center gap-1 text-xs text-content-tertiary hover:text-oe-blue transition-colors"
        >
          <ArrowLeft size={12} />
          {t('modules.back_to_modules', { defaultValue: 'Back to Modules & Marketplace' })}
        </Link>
      </div>

      {/* Prerequisites */}
      <Card className="mb-5">
        <div className="p-6">
          <div className="flex items-center gap-2 mb-3">
            <Wrench size={18} className="text-amber-500" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('modules.dev_prereq_title', { defaultValue: 'Prerequisites' })}
            </h2>
          </div>
          <p className="text-sm text-content-secondary mb-4">
            {t('modules.dev_prereq_intro', {
              defaultValue:
                'Have these ready before starting. If you can run the app locally, you already have everything you need.',
            })}
          </p>
          <div className="grid sm:grid-cols-2 gap-3">
            <ul className="space-y-1.5 text-sm text-content-secondary">
              <li className="flex gap-2">
                <CheckCircle2 size={14} className="text-emerald-500 shrink-0 mt-0.5" />
                <span>
                  <strong>Python 3.12+</strong> — backend runtime
                </span>
              </li>
              <li className="flex gap-2">
                <CheckCircle2 size={14} className="text-emerald-500 shrink-0 mt-0.5" />
                <span>
                  <strong>Node.js 20+</strong> — frontend build
                </span>
              </li>
              <li className="flex gap-2">
                <CheckCircle2 size={14} className="text-emerald-500 shrink-0 mt-0.5" />
                <span>
                  <strong>Git</strong> — clone + commit
                </span>
              </li>
            </ul>
            <ul className="space-y-1.5 text-sm text-content-secondary">
              <li className="flex gap-2">
                <CheckCircle2 size={14} className="text-emerald-500 shrink-0 mt-0.5" />
                <span>
                  <strong>PostgreSQL 16 or SQLite</strong> — SQLite auto-created in dev
                </span>
              </li>
              <li className="flex gap-2">
                <CheckCircle2 size={14} className="text-emerald-500 shrink-0 mt-0.5" />
                <span>
                  <strong>Editor</strong> — VS Code, Cursor, or anything with Python + TS
                </span>
              </li>
              <li className="flex gap-2">
                <CheckCircle2 size={14} className="text-emerald-500 shrink-0 mt-0.5" />
                <span>
                  <strong>Clone the repo</strong> to hack on the module
                </span>
              </li>
            </ul>
          </div>
          <Code lang="bash">
{`git clone https://github.com/datadrivenconstruction/OpenConstructionERP.git
cd OpenConstructionERP
# Backend
cd backend && pip install -e ".[dev]"
uvicorn app.main:create_app --factory --reload --port 8000
# Frontend (new terminal)
cd frontend && npm install && npm run dev`}
          </Code>
          <p className="text-xs text-content-tertiary mt-3">
            {t('modules.dev_prereq_verify', {
              defaultValue:
                'Open http://localhost:5173 and log in. Confirm the Modules page loads before starting.',
            })}
          </p>
        </div>
      </Card>

      {/* Hello World demo */}
      <Card className="mb-5">
        <div className="p-6">
          <div className="flex items-center gap-2 mb-3">
            <Rocket size={18} className="text-rose-500" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('modules.dev_demo_title', {
                defaultValue: 'Hello World — your first module in 3 minutes',
              })}
            </h2>
            <Badge variant="neutral" size="sm">Backend only</Badge>
          </div>
          <p className="text-sm text-content-secondary mb-4">
            {t('modules.dev_demo_intro', {
              defaultValue:
                'Minimal end-to-end module that serves a greeting endpoint. Copy-paste the four blocks below, restart the backend, and curl the route — that is the full loop.',
            })}
          </p>

          <div className="space-y-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
                {t('modules.dev_demo_step1', {
                  defaultValue: '1. Create the folder',
                })}
              </p>
              <Code lang="bash">{`mkdir -p backend/app/modules/hello_world`}</Code>
            </div>

            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
                {t('modules.dev_demo_step2', {
                  defaultValue:
                    '2. backend/app/modules/hello_world/__init__.py (empty file)',
                })}
              </p>
              <Code lang="bash">{`touch backend/app/modules/hello_world/__init__.py`}</Code>
            </div>

            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
                {t('modules.dev_demo_step3', {
                  defaultValue: '3. backend/app/modules/hello_world/manifest.py',
                })}
              </p>
              <Code lang="python">
{`from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_hello_world",
    version="0.1.0",
    display_name="Hello World",
    description="My first module",
    author="Me",
    category="community",
    depends=[],
    auto_install=True,
    enabled=True,
)`}
              </Code>
            </div>

            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
                {t('modules.dev_demo_step4', {
                  defaultValue: '4. backend/app/modules/hello_world/router.py',
                })}
              </p>
              <Code lang="python">
{`from fastapi import APIRouter

router = APIRouter(prefix="/hello_world", tags=["hello_world"])

@router.get("/")
async def greet(name: str = "World"):
    return {"message": f"Hello, {name}!"}`}
              </Code>
            </div>

            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
                {t('modules.dev_demo_step5', {
                  defaultValue: '5. Restart backend and test',
                })}
              </p>
              <Code lang="bash">
{`# Restart: Ctrl+C, then re-run uvicorn
curl "http://localhost:8000/api/v1/hello_world/?name=Artem"
# -> {"message":"Hello, Artem!"}`}
              </Code>
            </div>
          </div>

          <div className="mt-5 rounded-lg bg-rose-50 dark:bg-rose-950/20 border border-rose-200 dark:border-rose-800 p-3 flex items-start gap-2">
            <Info size={14} className="text-rose-600 dark:text-rose-400 shrink-0 mt-0.5" />
            <p className="text-xs text-content-secondary">
              {t('modules.dev_demo_note', {
                defaultValue:
                  'That is it — no main.py edit, no registry import, no migration. The module loader discovers the folder, reads the manifest, and mounts the router. The module also appears under Modules & Marketplace automatically.',
              })}
            </p>
          </div>
        </div>
      </Card>

      {/* What is a module */}
      <Card className="mb-5">
        <div className="p-6">
          <div className="flex items-center gap-2 mb-3">
            <Info size={18} className="text-oe-blue" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('modules.dev_what', { defaultValue: 'What is a module?' })}
            </h2>
          </div>
          <p className="text-sm text-content-secondary leading-relaxed mb-4">
            {t('modules.dev_what_desc', {
              defaultValue:
                'Every business feature in this system — BOQ, BIM Hub, Schedule, CDE, regional BOQ packs, AI tooling — is a self-contained module. A module can add REST routes, database tables, UI pages, validation rules, translations, or any combination. You can enable, disable, install, or replace any module without touching the core.',
            })}
          </p>
          <div className="grid sm:grid-cols-3 gap-3">
            <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3">
              <Server size={16} className="text-emerald-500 mb-1.5" />
              <p className="font-semibold text-sm text-content-primary">
                {t('modules.dev_what_backend', { defaultValue: 'Backend only' })}
              </p>
              <p className="text-xs text-content-tertiary mt-1">
                {t('modules.dev_what_backend_ex', {
                  defaultValue: 'e.g. a new API connector or webhook receiver',
                })}
              </p>
            </div>
            <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3">
              <Layers size={16} className="text-purple-500 mb-1.5" />
              <p className="font-semibold text-sm text-content-primary">
                {t('modules.dev_what_frontend', { defaultValue: 'Frontend only' })}
              </p>
              <p className="text-xs text-content-tertiary mt-1">
                {t('modules.dev_what_frontend_ex', {
                  defaultValue: 'e.g. a regional BOQ-exchange UI or a niche report',
                })}
              </p>
            </div>
            <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-3">
              <Sparkles size={16} className="text-oe-blue mb-1.5" />
              <p className="font-semibold text-sm text-content-primary">
                {t('modules.dev_what_full', { defaultValue: 'Full-stack' })}
              </p>
              <p className="text-xs text-content-tertiary mt-1">
                {t('modules.dev_what_full_ex', {
                  defaultValue: 'most real features — routes, UI, and a DB migration',
                })}
              </p>
            </div>
          </div>
        </div>
      </Card>

      {/* Backend walkthrough */}
      <Card className="mb-5">
        <div className="p-6">
          <div className="flex items-center gap-2 mb-2">
            <Server size={18} className="text-emerald-500" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('modules.dev_backend_title', { defaultValue: 'Backend module — in 5 minutes' })}
            </h2>
            <Badge variant="neutral" size="sm">Python / FastAPI</Badge>
          </div>
          <p className="text-sm text-content-secondary mb-5">
            {t('modules.dev_backend_intro', {
              defaultValue:
                'Everything starts from the template in the repo. The module loader auto-discovers anything you drop into backend/app/modules/ — no manual wiring of routes or migrations.',
            })}
          </p>
          <div className="space-y-5">
            <Step number={1} title={t('modules.dev_step_copy', { defaultValue: 'Copy the template' })}>
              <Code lang="bash">
{`cp -r modules/oe-module-template backend/app/modules/my_module`}
              </Code>
            </Step>

            <Step number={2} title={t('modules.dev_step_manifest', { defaultValue: 'Edit the manifest' })}>
              <p>
                Open <Inline>backend/app/modules/my_module/manifest.py</Inline> and set{' '}
                <Inline>name</Inline>, <Inline>version</Inline>, <Inline>display_name</Inline>, and any
                dependencies on other modules.
              </p>
              <Code lang="python">
{`from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_my_module",        # unique, snake_case, oe_ prefix
    version="0.1.0",
    display_name="My Module",
    description="One-line description",
    author="Your Name",
    category="community",        # core | integration | regional | community
    depends=["oe_projects"],     # modules this needs
    auto_install=False,          # user enables it from /modules
    enabled=True,
)`}
              </Code>
            </Step>

            <Step number={3} title={t('modules.dev_step_router', { defaultValue: 'Add a router' })}>
              <p>
                Routes live in <Inline>router.py</Inline>. The loader mounts the router at{' '}
                <Inline>/api/v1/my_module/*</Inline> automatically — you do not touch{' '}
                <Inline>main.py</Inline>.
              </p>
              <Code lang="python">
{`from fastapi import APIRouter

router = APIRouter(prefix="/my_module", tags=["my_module"])

@router.get("/")
async def list_items():
    return {"items": []}`}
              </Code>
            </Step>

            <Step number={4} title={t('modules.dev_step_models', { defaultValue: 'Add models & schemas (optional)' })}>
              <p>
                Drop SQLAlchemy models into <Inline>models.py</Inline>, Pydantic request/response
                schemas into <Inline>schemas.py</Inline>. If you add tables, generate an Alembic
                migration under <Inline>migrations/</Inline> and run <Inline>make migrate</Inline>.
              </p>
            </Step>

            <Step number={5} title={t('modules.dev_step_validation', { defaultValue: 'Declare validation rules' })}>
              <p>
                Modules that ingest data must ship validation rules. Subclass{' '}
                <Inline>ValidationRule</Inline> in{' '}
                <Inline>backend/app/core/validation/rules/my_module.py</Inline> — the engine
                auto-registers it.
              </p>
            </Step>

            <Step number={6} title={t('modules.dev_step_restart', { defaultValue: 'Restart and enable' })}>
              <p>
                Restart the backend. The module loader picks up your folder, and the module appears
                under{' '}
                <Link to="/modules" className="text-oe-blue hover:underline">
                  Modules &amp; Marketplace → System Modules
                </Link>
                . Toggle it on.
              </p>
            </Step>
          </div>
          <div className="mt-5 rounded-lg bg-emerald-50 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-800 p-3 flex items-start gap-2">
            <CheckCircle2 size={14} className="text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
            <p className="text-xs text-content-secondary">
              {t('modules.dev_backend_ref', {
                defaultValue:
                  'Reference implementations: backend/app/modules/boq/ and backend/app/modules/projects/.',
              })}
            </p>
          </div>
        </div>
      </Card>

      {/* File structure */}
      <Card className="mb-5">
        <div className="p-6">
          <div className="flex items-center gap-2 mb-3">
            <FolderTree size={18} className="text-indigo-500" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('modules.dev_tree_title', { defaultValue: 'File structure — what goes where' })}
            </h2>
          </div>
          <p className="text-sm text-content-secondary mb-4">
            {t('modules.dev_tree_intro', {
              defaultValue:
                'Both backend and frontend modules follow a strict convention. Follow it and the loader + registry will wire everything up; deviate and things break in surprising places.',
            })}
          </p>
          <div className="grid md:grid-cols-2 gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
                {t('modules.dev_tree_backend', { defaultValue: 'Backend module' })}
              </p>
              <Code lang="tree">
{`backend/app/modules/my_module/
├── __init__.py          # empty, marks as package
├── manifest.py          # required: metadata + deps
├── models.py            # SQLAlchemy models (auto-registered)
├── schemas.py           # Pydantic request/response
├── router.py            # FastAPI routes (auto-mounted)
├── service.py           # business logic (stateless)
├── repository.py        # data access layer
├── permissions.py       # permission declarations
├── events.py            # event handlers (optional)
├── hooks.py             # hook handlers (optional)
├── validators.py        # validation rules (optional)
├── migrations/          # Alembic migrations (module-scoped)
│   └── versions/
└── tests/               # pytest — run with: pytest backend/app/modules/my_module`}
              </Code>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
                {t('modules.dev_tree_frontend', { defaultValue: 'Frontend module' })}
              </p>
              <Code lang="tree">
{`frontend/src/modules/my-feature/
├── manifest.ts          # required: id, routes, navItems
├── MyFeatureModule.tsx  # main React component
├── components/          # sub-components (optional)
│   └── MyWidget.tsx
├── api.ts               # API client fns (uses shared/lib/api)
├── hooks/               # custom hooks (optional)
│   └── useMyData.ts
├── types.ts             # TS types (optional)
└── __tests__/           # vitest — run with: npm run test`}
              </Code>
            </div>
          </div>
          <p className="text-xs text-content-tertiary mt-4">
            {t('modules.dev_tree_note', {
              defaultValue:
                'All files except manifest.* are optional — start with the smallest set and add files as the module grows.',
            })}
          </p>
        </div>
      </Card>

      {/* Database migrations */}
      <Card className="mb-5">
        <div className="p-6">
          <div className="flex items-center gap-2 mb-3">
            <Database size={18} className="text-blue-500" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('modules.dev_db_title', { defaultValue: 'Database migrations' })}
            </h2>
            <Badge variant="neutral" size="sm">Alembic</Badge>
          </div>
          <p className="text-sm text-content-secondary mb-4">
            {t('modules.dev_db_intro', {
              defaultValue:
                'If your module adds or changes tables, you must ship a migration. The project uses Alembic — autogenerate is your friend but always review the result.',
            })}
          </p>

          <div className="space-y-4">
            <Step number={1} title={t('modules.dev_db_step1', { defaultValue: 'Define your model' })}>
              <Code lang="python">
{`# backend/app/modules/my_module/models.py
from sqlalchemy import Column, String, Integer, DateTime
from sqlalchemy.sql import func
from app.database import Base

class MyItem(Base):
    __tablename__ = "oe_my_module_item"   # prefix with module name

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    created_at = Column(DateTime, server_default=func.now())`}
              </Code>
            </Step>

            <Step number={2} title={t('modules.dev_db_step2', { defaultValue: 'Register the model on app startup' })}>
              <p>
                Open <Inline>backend/app/main.py</Inline>, find the
                <Inline>_import_models_for_migrations</Inline> block, and add one line:
              </p>
              <Code lang="python">
{`from app.modules.my_module import models as _my_module_models  # noqa: F401`}
              </Code>
            </Step>

            <Step number={3} title={t('modules.dev_db_step3', { defaultValue: 'Generate the migration' })}>
              <Code lang="bash">
{`cd backend
alembic revision --autogenerate -m "my_module: initial schema"
# Review alembic/versions/<hash>_my_module_initial_schema.py
alembic upgrade head`}
              </Code>
            </Step>

            <Step number={4} title={t('modules.dev_db_step4', { defaultValue: 'Ship it' })}>
              <p>
                Commit the migration file in <Inline>backend/alembic/versions/</Inline>. On upgrade,
                existing installs run <Inline>alembic upgrade head</Inline> and pick up your new
                tables automatically.
              </p>
            </Step>
          </div>

          <div className="mt-5 rounded-lg bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800 p-3 flex items-start gap-2">
            <AlertTriangle size={14} className="text-amber-600 dark:text-amber-400 shrink-0 mt-0.5" />
            <p className="text-xs text-content-secondary">
              {t('modules.dev_db_warn', {
                defaultValue:
                  'Always prefix table names with the module slug (oe_my_module_*) to avoid collisions. Never drop columns in a single migration — add the new column, backfill, then drop in a later release.',
              })}
            </p>
          </div>
        </div>
      </Card>

      {/* Frontend walkthrough */}
      <Card className="mb-5">
        <div className="p-6">
          <div className="flex items-center gap-2 mb-2">
            <Layers size={18} className="text-purple-500" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('modules.dev_frontend_title', { defaultValue: 'Frontend module — in 5 minutes' })}
            </h2>
            <Badge variant="neutral" size="sm">React / TypeScript</Badge>
          </div>
          <p className="text-sm text-content-secondary mb-5">
            {t('modules.dev_frontend_intro', {
              defaultValue:
                'Frontend modules live in frontend/src/modules/. Each one exports a manifest that declares routes, nav items, and translations. The registry wires them into the sidebar and router automatically.',
            })}
          </p>
          <div className="space-y-5">
            <Step number={1} title={t('modules.dev_front_step_folder', { defaultValue: 'Create the folder' })}>
              <Code lang="bash">{`mkdir frontend/src/modules/my-feature`}</Code>
            </Step>

            <Step number={2} title={t('modules.dev_front_step_manifest', { defaultValue: 'Create manifest.ts' })}>
              <Code lang="ts">
{`import { lazy } from 'react';
import { Sparkles } from 'lucide-react';
import type { ModuleManifest } from '../_types';

const MyFeatureModule = lazy(() => import('./MyFeatureModule'));

export const manifest: ModuleManifest = {
  id: 'my-feature',
  name: 'My Feature',
  description: 'What this module does in one line',
  version: '1.0.0',
  icon: Sparkles,
  category: 'tools',
  defaultEnabled: false,
  depends: ['boq'],

  routes: [
    { path: '/my-feature', title: 'My Feature', component: MyFeatureModule },
  ],

  navItems: [
    {
      labelKey: 'nav.my_feature',
      to: '/my-feature',
      icon: Sparkles,
      group: 'tools',
      advancedOnly: true,
    },
  ],
};`}
              </Code>
            </Step>

            <Step number={3} title={t('modules.dev_front_step_component', { defaultValue: 'Build the React page' })}>
              <p>
                Create <Inline>MyFeatureModule.tsx</Inline> — a normal React component. Use{' '}
                <Inline>useTranslation()</Inline> for every user-visible string.
              </p>
            </Step>

            <Step number={4} title={t('modules.dev_front_step_register', { defaultValue: 'Register it' })}>
              <p>
                Open <Inline>frontend/src/modules/_registry.ts</Inline> and add your import to the{' '}
                <Inline>MODULE_REGISTRY</Inline> array.
              </p>
              <Code lang="ts">
{`import { manifest as myFeature } from './my-feature/manifest';
export const MODULE_REGISTRY = [..., myFeature];`}
              </Code>
            </Step>

            <Step number={5} title={t('modules.dev_front_step_i18n', { defaultValue: 'Add translations' })}>
              <p>
                Add the English fallback for every new i18n key to{' '}
                <Inline>frontend/src/app/i18n-fallbacks.ts</Inline>. Never leave a raw English string
                in TSX.
              </p>
            </Step>
          </div>
        </div>
      </Card>

      {/* Events & hooks */}
      <Card className="mb-5">
        <div className="p-6">
          <div className="flex items-center gap-2 mb-3">
            <Zap size={18} className="text-yellow-500" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('modules.dev_events_title', {
                defaultValue: 'Events & hooks — how modules talk to each other',
              })}
            </h2>
          </div>
          <p className="text-sm text-content-secondary mb-4">
            {t('modules.dev_events_intro', {
              defaultValue:
                'Never import from another module directly. Emit events and subscribe to them. This keeps modules decoupled and makes installing/disabling safe.',
            })}
          </p>

          <div className="grid md:grid-cols-2 gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
                {t('modules.dev_events_publish', { defaultValue: 'Publish an event' })}
              </p>
              <Code lang="python">
{`from app.core.events import publish_event

await publish_event(
    "my_module.item.created",
    {"item_id": item.id, "name": item.name},
    source_module="oe_my_module",
)`}
              </Code>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
                {t('modules.dev_events_subscribe', { defaultValue: 'Subscribe in events.py' })}
              </p>
              <Code lang="python">
{`# backend/app/modules/my_module/events.py
from app.core.events import subscribe

@subscribe("boq.position.updated")
async def on_boq_change(payload):
    # re-index, notify, whatever
    ...`}
              </Code>
            </div>
          </div>

          <p className="text-xs text-content-tertiary mt-4 mb-2">
            {t('modules.dev_events_known', {
              defaultValue: 'Common events you can listen for:',
            })}
          </p>
          <ul className="text-xs text-content-secondary space-y-1 pl-4 list-disc">
            <li>
              <Inline>projects.project.created</Inline> — after a project is created
            </li>
            <li>
              <Inline>boq.position.created</Inline> / <Inline>.updated</Inline> /{' '}
              <Inline>.deleted</Inline>
            </li>
            <li>
              <Inline>users.user.created</Inline> / <Inline>.role_changed</Inline>
            </li>
            <li>
              <Inline>documents.document.uploaded</Inline>
            </li>
            <li>
              <Inline>bim.model.ingested</Inline> — after CAD/BIM conversion succeeds
            </li>
          </ul>
        </div>
      </Card>

      {/* Permissions & RBAC */}
      <Card className="mb-5">
        <div className="p-6">
          <div className="flex items-center gap-2 mb-3">
            <Lock size={18} className="text-rose-500" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('modules.dev_perms_title', { defaultValue: 'Permissions & RBAC' })}
            </h2>
          </div>
          <p className="text-sm text-content-secondary mb-4">
            {t('modules.dev_perms_intro', {
              defaultValue:
                'Declare the permissions your module uses. Protect every mutating endpoint with RequirePermission — never rely on the user being logged in alone.',
            })}
          </p>

          <Step number={1} title={t('modules.dev_perms_step1', { defaultValue: 'Declare in permissions.py' })}>
            <Code lang="python">
{`# backend/app/modules/my_module/permissions.py
PERMISSIONS = [
    ("my_module.read",   "Read My Module data"),
    ("my_module.create", "Create My Module items"),
    ("my_module.update", "Update My Module items"),
    ("my_module.delete", "Delete My Module items"),
]`}
            </Code>
          </Step>

          <Step number={2} title={t('modules.dev_perms_step2', { defaultValue: 'Guard your routes' })}>
            <Code lang="python">
{`from fastapi import Depends
from app.dependencies import RequirePermission

@router.post("/")
async def create_item(
    data: CreateItemSchema,
    _: None = Depends(RequirePermission("my_module.create")),
):
    return await service.create(data)`}
            </Code>
          </Step>

          <div className="mt-4 rounded-lg bg-rose-50 dark:bg-rose-950/20 border border-rose-200 dark:border-rose-800 p-3 flex items-start gap-2">
            <Info size={14} className="text-rose-600 dark:text-rose-400 shrink-0 mt-0.5" />
            <p className="text-xs text-content-secondary">
              {t('modules.dev_perms_roles', {
                defaultValue:
                  'Roles admin / manager / editor / viewer are assembled from permission sets. Admin always has every permission (bypass). New permissions default to admin+manager only unless you explicitly grant them in backend/app/modules/users/seed_roles.py.',
              })}
            </p>
          </div>
        </div>
      </Card>

      {/* Testing */}
      <Card className="mb-5">
        <div className="p-6">
          <div className="flex items-center gap-2 mb-3">
            <TestTube2 size={18} className="text-emerald-500" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('modules.dev_test_title', { defaultValue: 'Testing your module' })}
            </h2>
          </div>
          <p className="text-sm text-content-secondary mb-4">
            {t('modules.dev_test_intro', {
              defaultValue:
                'Tests gate every PR. The project uses pytest for backend, vitest for frontend, and Playwright for e2e. Running them locally is the same commands used in CI.',
            })}
          </p>

          <div className="grid md:grid-cols-3 gap-3">
            <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
                {t('modules.dev_test_backend', { defaultValue: 'Backend — pytest' })}
              </p>
              <Code lang="bash">
{`# run this module's tests
pytest backend/app/modules/my_module

# integration tests
pytest backend/tests/integration`}
              </Code>
            </div>
            <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
                {t('modules.dev_test_frontend', { defaultValue: 'Frontend — vitest' })}
              </p>
              <Code lang="bash">
{`cd frontend
npm run test       # all tests
npm run typecheck  # TS-level checks`}
              </Code>
            </div>
            <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-4">
              <p className="text-xs font-semibold uppercase tracking-wider text-content-tertiary mb-2">
                {t('modules.dev_test_e2e', { defaultValue: 'E2E — Playwright' })}
              </p>
              <Code lang="bash">
{`cd frontend
npx playwright test       # all specs
npx playwright test my-   # filter by spec name`}
              </Code>
            </div>
          </div>

          <p className="text-xs text-content-tertiary mt-4">
            {t('modules.dev_test_pattern', {
              defaultValue:
                'Backend tests use httpx + ASGITransport — no real HTTP. Frontend tests run in jsdom. Shared integration fixtures live in backend/tests/integration/_auth_helpers.py.',
            })}
          </p>
        </div>
      </Card>

      {/* Install & share */}
      <Card className="mb-5">
        <div className="p-6">
          <div className="flex items-center gap-2 mb-3">
            <Terminal size={18} className="text-amber-500" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('modules.dev_install_title', { defaultValue: 'Installing a third-party module' })}
            </h2>
          </div>
          <div className="grid md:grid-cols-2 gap-3">
            <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-content-tertiary mb-2">
                {t('modules.dev_install_zip', { defaultValue: 'Zip install (recommended)' })}
              </p>
              <Code>{`openestimate module install path/to/my-module-1.0.0.zip`}</Code>
            </div>
            <div className="rounded-lg border border-border-light bg-surface-secondary/40 p-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-content-tertiary mb-2">
                {t('modules.dev_install_manual', { defaultValue: 'Manual copy (development)' })}
              </p>
              <Code>{`cp -r downloaded-module backend/app/modules/
# restart backend`}</Code>
            </div>
          </div>
          <p className="text-xs text-content-tertiary mt-3">
            {t('modules.dev_install_enable', {
              defaultValue:
                'Then enable it under Modules & Marketplace → System Modules.',
            })}
          </p>
        </div>
      </Card>

      {/* Core rules */}
      <Card className="mb-5">
        <div className="p-6">
          <div className="flex items-center gap-2 mb-3">
            <CheckCircle2 size={18} className="text-oe-blue" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('modules.dev_rules_title', { defaultValue: 'Core rules (enforced in PR review)' })}
            </h2>
          </div>
          <ul className="space-y-2.5 text-sm text-content-secondary">
            <li className="flex gap-2">
              <span className="text-oe-blue font-bold shrink-0">1.</span>
              <span>
                <strong>i18n everywhere</strong> — every user-visible string goes through{' '}
                <Inline>t()</Inline>. Fallbacks live in{' '}
                <Inline>frontend/src/app/i18n-fallbacks.ts</Inline>.
              </span>
            </li>
            <li className="flex gap-2">
              <span className="text-oe-blue font-bold shrink-0">2.</span>
              <span>
                <strong>No IfcOpenShell / BCF / native IFC</strong> — CAD/BIM is always converted
                through DDC cad2data into the canonical JSON format.
              </span>
            </li>
            <li className="flex gap-2">
              <span className="text-oe-blue font-bold shrink-0">3.</span>
              <span>
                <strong>Validation is not optional</strong> — any module that ingests data must
                declare validation rules.
              </span>
            </li>
            <li className="flex gap-2">
              <span className="text-oe-blue font-bold shrink-0">4.</span>
              <span>
                <strong>AI-augmented, human-confirmed</strong> — AI suggestions must show a
                confidence score and require user confirmation before mutating data.
              </span>
            </li>
            <li className="flex gap-2">
              <span className="text-oe-blue font-bold shrink-0">5.</span>
              <span>
                <strong>AGPL-3.0 compliance</strong> — contributions are dual-licensed (AGPL +
                Commercial). First-time contributors sign a CLA via bot.
              </span>
            </li>
          </ul>
        </div>
      </Card>

      {/* Quick reference table */}
      <Card className="mb-5">
        <div className="p-6">
          <div className="flex items-center gap-2 mb-3">
            <FolderTree size={18} className="text-indigo-500" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('modules.dev_ref_title', { defaultValue: 'Quick reference' })}
            </h2>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border-light text-left">
                  <th className="pb-2 font-semibold text-content-secondary">
                    {t('modules.dev_ref_need', { defaultValue: 'I need to…' })}
                  </th>
                  <th className="pb-2 font-semibold text-content-secondary">
                    {t('modules.dev_ref_look', { defaultValue: 'Look at…' })}
                  </th>
                </tr>
              </thead>
              <tbody className="text-content-secondary">
                <tr className="border-b border-border-light/50">
                  <td className="py-2.5 pr-4">Scaffold a backend module</td>
                  <td className="py-2.5"><Inline>modules/oe-module-template/</Inline></td>
                </tr>
                <tr className="border-b border-border-light/50">
                  <td className="py-2.5 pr-4">Real-world backend example</td>
                  <td className="py-2.5"><Inline>backend/app/modules/boq/</Inline></td>
                </tr>
                <tr className="border-b border-border-light/50">
                  <td className="py-2.5 pr-4">Real-world frontend example</td>
                  <td className="py-2.5"><Inline>frontend/src/modules/pdf-takeoff/</Inline></td>
                </tr>
                <tr className="border-b border-border-light/50">
                  <td className="py-2.5 pr-4">Add validation rules</td>
                  <td className="py-2.5"><Inline>backend/app/core/validation/rules/</Inline></td>
                </tr>
                <tr className="border-b border-border-light/50">
                  <td className="py-2.5 pr-4">Hook into events</td>
                  <td className="py-2.5"><Inline>backend/app/core/events.py</Inline></td>
                </tr>
                <tr className="border-b border-border-light/50">
                  <td className="py-2.5 pr-4">Add translations</td>
                  <td className="py-2.5"><Inline>frontend/src/app/i18n-fallbacks.ts</Inline></td>
                </tr>
                <tr className="border-b border-border-light/50">
                  <td className="py-2.5 pr-4">Declare a permission</td>
                  <td className="py-2.5"><Inline>backend/app/modules/my_module/permissions.py</Inline></td>
                </tr>
                <tr className="border-b border-border-light/50">
                  <td className="py-2.5 pr-4">Guard an endpoint</td>
                  <td className="py-2.5"><Inline>Depends(RequirePermission("my_module.create"))</Inline></td>
                </tr>
                <tr className="border-b border-border-light/50">
                  <td className="py-2.5 pr-4">Register a model for migrations</td>
                  <td className="py-2.5"><Inline>backend/app/main.py</Inline> → <Inline>_import_models_for_migrations</Inline></td>
                </tr>
                <tr className="border-b border-border-light/50">
                  <td className="py-2.5 pr-4">Generate a migration</td>
                  <td className="py-2.5"><Inline>alembic revision --autogenerate -m "msg"</Inline></td>
                </tr>
                <tr className="border-b border-border-light/50">
                  <td className="py-2.5 pr-4">Publish an event</td>
                  <td className="py-2.5"><Inline>publish_event("my_module.item.created", payload)</Inline></td>
                </tr>
                <tr className="border-b border-border-light/50">
                  <td className="py-2.5 pr-4">Subscribe to an event</td>
                  <td className="py-2.5"><Inline>@subscribe("boq.position.updated")</Inline></td>
                </tr>
                <tr className="border-b border-border-light/50">
                  <td className="py-2.5 pr-4">Enable / disable a module</td>
                  <td className="py-2.5"><Link to="/modules" className="text-oe-blue hover:underline">Modules &amp; Marketplace</Link></td>
                </tr>
                <tr className="border-b border-border-light/50">
                  <td className="py-2.5 pr-4">Run backend tests</td>
                  <td className="py-2.5"><Inline>pytest backend/app/modules/my_module</Inline></td>
                </tr>
                <tr className="border-b border-border-light/50">
                  <td className="py-2.5 pr-4">Run frontend typecheck</td>
                  <td className="py-2.5"><Inline>cd frontend && npm run typecheck</Inline></td>
                </tr>
                <tr>
                  <td className="py-2.5 pr-4">Package module for sharing</td>
                  <td className="py-2.5"><Inline>zip -r my-module-0.1.0.zip my_module/</Inline></td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </Card>

      {/* AI agent note */}
      <Card className="mb-5">
        <div className="p-6">
          <div className="flex items-center gap-2 mb-3">
            <Bot size={18} className="text-rose-500" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('modules.dev_ai_title', { defaultValue: 'For AI agents' })}
            </h2>
          </div>
          <p className="text-sm text-content-secondary mb-3">
            {t('modules.dev_ai_intro', {
              defaultValue:
                'If you are an AI agent scaffolding a module on behalf of a user, follow the same rules as humans plus:',
            })}
          </p>
          <ul className="space-y-2 text-sm text-content-secondary list-disc pl-5">
            <li>
              {t('modules.dev_ai_copy', {
                defaultValue:
                  'Copy the template — do not invent the manifest schema. It changes faster than any document.',
              })}
            </li>
            <li>
              {t('modules.dev_ai_check', {
                defaultValue:
                  'Before reporting the module done, run npm run typecheck and ruff check + pytest. A green build is the contract.',
              })}
            </li>
            <li>
              {t('modules.dev_ai_registry', {
                defaultValue:
                  'Never edit the contract files _types.ts or the shape of _registry.ts — only append to the registry array.',
              })}
            </li>
            <li>
              {t('modules.dev_ai_i18n', {
                defaultValue:
                  'Every new user-visible string gets a translation key and an English fallback in i18n-fallbacks.ts.',
              })}
            </li>
          </ul>
        </div>
      </Card>

      {/* Troubleshooting */}
      <Card className="mb-5">
        <div className="p-6">
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle size={18} className="text-amber-500" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('modules.dev_trouble_title', {
                defaultValue: 'Troubleshooting — common issues',
              })}
            </h2>
          </div>

          <div className="space-y-4">
            <div className="rounded-lg border border-border-light bg-surface-secondary/30 p-4">
              <p className="font-semibold text-sm text-content-primary mb-1">
                {t('modules.dev_trouble_1_q', {
                  defaultValue: 'Module does not appear under Modules & Marketplace',
                })}
              </p>
              <p className="text-xs text-content-secondary">
                {t('modules.dev_trouble_1_a', {
                  defaultValue:
                    'Backend must have been restarted after dropping the folder. Check the startup log for "[modules] loaded oe_your_module". Missing? Verify __init__.py exists and manifest.py defines a `manifest` object at module scope.',
                })}
              </p>
            </div>

            <div className="rounded-lg border border-border-light bg-surface-secondary/30 p-4">
              <p className="font-semibold text-sm text-content-primary mb-1">
                {t('modules.dev_trouble_2_q', {
                  defaultValue: '404 on your routes',
                })}
              </p>
              <p className="text-xs text-content-secondary">
                {t('modules.dev_trouble_2_a', {
                  defaultValue:
                    'The loader prefixes with /api/v1/<module_name>/. So router.py paths like @router.get("/") become /api/v1/my_module/. Keep the trailing slash on the frontend API client — redirect_slashes is disabled on the backend.',
                })}
              </p>
            </div>

            <div className="rounded-lg border border-border-light bg-surface-secondary/30 p-4">
              <p className="font-semibold text-sm text-content-primary mb-1">
                {t('modules.dev_trouble_3_q', {
                  defaultValue: 'Alembic autogenerate produces empty migration',
                })}
              </p>
              <p className="text-xs text-content-secondary">
                {t('modules.dev_trouble_3_a', {
                  defaultValue:
                    'Alembic only sees models that are imported at app startup. Add the "from app.modules.my_module import models as _m  # noqa: F401" line in _import_models_for_migrations (backend/app/main.py).',
                })}
              </p>
            </div>

            <div className="rounded-lg border border-border-light bg-surface-secondary/30 p-4">
              <p className="font-semibold text-sm text-content-primary mb-1">
                {t('modules.dev_trouble_4_q', {
                  defaultValue: 'Frontend shows raw i18n key like "modules.my_feature.title"',
                })}
              </p>
              <p className="text-xs text-content-secondary">
                {t('modules.dev_trouble_4_a', {
                  defaultValue:
                    'You forgot to add the English fallback in frontend/src/app/i18n-fallbacks.ts. Add it there — the backend serves locales via /api/v1/i18n/ by merging that file with each translation JSON.',
                })}
              </p>
            </div>

            <div className="rounded-lg border border-border-light bg-surface-secondary/30 p-4">
              <p className="font-semibold text-sm text-content-primary mb-1">
                {t('modules.dev_trouble_5_q', {
                  defaultValue: '403 Missing permission: my_module.create',
                })}
              </p>
              <p className="text-xs text-content-secondary">
                {t('modules.dev_trouble_5_a', {
                  defaultValue:
                    'You declared a new permission but no role has it. Edit backend/app/modules/users/seed_roles.py and re-run seed. Admin always bypasses; every other role needs explicit grant.',
                })}
              </p>
            </div>

            <div className="rounded-lg border border-border-light bg-surface-secondary/30 p-4">
              <p className="font-semibold text-sm text-content-primary mb-1">
                {t('modules.dev_trouble_6_q', {
                  defaultValue: 'TypeScript error in manifest.ts about routes',
                })}
              </p>
              <p className="text-xs text-content-secondary">
                {t('modules.dev_trouble_6_a', {
                  defaultValue:
                    'The contract lives in frontend/src/modules/_types.ts — import ModuleManifest from there. Never modify _types.ts or the shape of _registry.ts: only append your import to the MODULE_REGISTRY array.',
                })}
              </p>
            </div>

            <div className="rounded-lg border border-border-light bg-surface-secondary/30 p-4">
              <p className="font-semibold text-sm text-content-primary mb-1">
                {t('modules.dev_trouble_7_q', {
                  defaultValue: 'Nav item not appearing in sidebar',
                })}
              </p>
              <p className="text-xs text-content-secondary">
                {t('modules.dev_trouble_7_a', {
                  defaultValue:
                    'Check that defaultEnabled is true in manifest.ts (user can still disable later via Modules page), and that the nav item\'s group matches an existing sidebar group id. advancedOnly: true hides the item until user enables "Advanced mode" from Settings.',
                })}
              </p>
            </div>
          </div>
        </div>
      </Card>

      {/* Publishing */}
      <Card className="mb-5">
        <div className="p-6">
          <div className="flex items-center gap-2 mb-3">
            <Download size={18} className="text-blue-500" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('modules.dev_publish_title', {
                defaultValue: 'Sharing your module with others',
              })}
            </h2>
          </div>
          <p className="text-sm text-content-secondary mb-4">
            {t('modules.dev_publish_intro', {
              defaultValue:
                'Once your module works locally, package it as a zip so others can install it with one command.',
            })}
          </p>
          <Code lang="bash">
{`# 1. Build a zip of the module folder
cd backend/app/modules
zip -r ~/my-module-0.1.0.zip my_module

# 2. Share the zip — recipients install with:
openestimate module install ~/my-module-0.1.0.zip

# 3. Optional — publish on the OpenEstimate marketplace:
#    open a PR against github.com/datadrivenconstruction/OpenConstructionERP-modules
#    adding your zip URL + manifest summary`}
          </Code>
          <p className="text-xs text-content-tertiary mt-3">
            {t('modules.dev_publish_versioning', {
              defaultValue:
                'Always bump manifest.version on every release — the installer uses it to decide when to upgrade an existing install.',
            })}
          </p>
        </div>
      </Card>

      {/* External references */}
      <Card>
        <div className="p-6">
          <div className="flex items-center gap-2 mb-3">
            <BookOpen size={18} className="text-content-secondary" />
            <h2 className="text-lg font-semibold text-content-primary">
              {t('modules.dev_refs_title', { defaultValue: 'Further reading' })}
            </h2>
          </div>
          <div className="grid sm:grid-cols-2 gap-3">
            <a
              href="https://github.com/datadrivenconstruction/OpenConstructionERP/blob/main/MODULES.md"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-secondary/30 p-3 text-sm text-content-secondary hover:bg-surface-secondary hover:text-content-primary transition-colors"
            >
              <FileText size={16} className="text-content-tertiary shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="font-medium truncate">MODULES.md on GitHub</p>
                <p className="text-xs text-content-tertiary truncate">Single source of truth</p>
              </div>
              <ExternalLink size={12} className="text-content-quaternary shrink-0" />
            </a>
            <a
              href="https://github.com/datadrivenconstruction/OpenConstructionERP/blob/main/CONTRIBUTING.md"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 rounded-lg border border-border-light bg-surface-secondary/30 p-3 text-sm text-content-secondary hover:bg-surface-secondary hover:text-content-primary transition-colors"
            >
              <FileText size={16} className="text-content-tertiary shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="font-medium truncate">CONTRIBUTING.md</p>
                <p className="text-xs text-content-tertiary truncate">Style, commits, PR process</p>
              </div>
              <ExternalLink size={12} className="text-content-quaternary shrink-0" />
            </a>
          </div>
        </div>
      </Card>
    </div>
  );
}

export default ModuleDeveloperGuide;
