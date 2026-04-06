/**
 * Changelog — Displays version history as a timeline with version badges.
 */

import { useTranslation } from 'react-i18next';
import { Badge } from '@/shared/ui';

interface ChangelogEntry {
  version: string;
  date: string;
  changes: string[];
}

const CHANGELOG: ChangelogEntry[] = [
  {
    version: '0.4.0',
    date: '2026-04-06',
    changes: [
      'New: Modal dialogs for creating BOQ, Projects, and Assemblies — no more separate pages',
      'New: BOQ list auto-filters by active project from header context',
      'New: Data Explorer landing redesign — dashed dropzone, compact session list',
      'New: Table of contents navigation in GitHub README',
      'New: Privacy Policy and Terms of Service pages',
      'Fix: New BOQ not appearing in list after creation (cache invalidation)',
      'Fix: CostBreakdownPanel styling — consistent rounded borders and shadows',
      'Fix: Data Explorer landing — professional compact layout for recent models',
      'Cleanup: Removed 76 test/smoke projects from seed database',
    ],
  },
  {
    version: '0.2.1',
    date: '2026-04-04',
    changes: [
      'Security: Path traversal protection on document downloads, CORS hardening, login enumeration fix',
      'Fix: BOQ duplication crash (MissingGreenlet) — now works correctly',
      'Fix: CWICR cost database import 500 error on Windows (ProcessPoolExecutor → asyncio.to_thread)',
      'Fix: pip install -e ./backend broken (pyproject.toml structure)',
      'Fix: Docker quickstart — Dockerfile, migration, asyncpg, APP_ENV',
      'New: Competitor comparison table in README (vs iTWO, CostX, Sage, Bluebeam)',
      'New: Free DDC book section on About page',
      'New: Setup Wizard link in welcome modal for re-onboarding',
      'New: Version number displayed in sidebar (v0.2.1)',
      'New: Nginx CSP, HSTS, Permissions-Policy security headers',
      'Updated: 9 vulnerable dependencies (aiohttp, cryptography, pillow, etc.)',
      'Removed: streamlit and dev screenshot artifacts from repository',
    ],
  },
  {
    version: '0.1.1',
    date: '2026-04-01',
    changes: [
      'Fix: Settings page freeze resolved + missing "Regional Standards" EN translation',
      'Fix: DELETE project 500 error + XSS sanitization in project names',
      'Fix: Removed duplicate "#1" on login page',
      'Build: Added requirements.txt for easier pip install',
      'Build: Cleaned repository for GitHub release (removed 159 dev artifacts)',
    ],
  },
  {
    version: '0.1.0',
    date: '2026-03-27',
    changes: [
      'Initial release',
      '18 validation rules (DIN 276, GAEB, BOQ Quality)',
      'AI-powered estimation (Text, Photo, PDF, Excel, CAD/BIM)',
      '55,000+ cost items across 11 regional databases',
      '20 languages supported',
      'BOQ Editor with AG Grid, markups, and exports',
      '4D Schedule with Gantt and CPM',
      '5D Cost Model with EVM',
      'Tendering with bid comparison',
    ],
  },
];

export function Changelog() {
  const { t } = useTranslation();

  return (
    <div>
      <h2 className="text-lg font-semibold text-content-primary mb-4">
        {t('about.changelog_title', { defaultValue: 'Changelog' })}
      </h2>

      <div className="relative">
        {/* Timeline line */}
        <div className="absolute left-[18px] top-3 bottom-3 w-px bg-border-light" />

        <div className="space-y-6">
          {CHANGELOG.map((entry) => (
            <div key={entry.version} className="relative flex gap-4">
              {/* Timeline dot */}
              <div className="relative z-10 flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-oe-blue/10 border-2 border-oe-blue">
                <div className="h-2.5 w-2.5 rounded-full bg-oe-blue" />
              </div>

              {/* Content */}
              <div className="flex-1 pt-0.5">
                <div className="flex items-center gap-3 mb-2">
                  <Badge variant="blue" size="sm">v{entry.version}</Badge>
                  <span className="text-xs text-content-tertiary">{entry.date}</span>
                </div>

                <ul className="space-y-1.5">
                  {entry.changes.map((change, idx) => (
                    <li key={idx} className="flex items-start gap-2 text-sm text-content-secondary">
                      <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-content-tertiary/50" />
                      <span>{change}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
