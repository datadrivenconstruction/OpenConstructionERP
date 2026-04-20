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
                <tr>
                  <td className="py-2.5 pr-4">Add translations</td>
                  <td className="py-2.5"><Inline>frontend/src/app/i18n-fallbacks.ts</Inline></td>
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
