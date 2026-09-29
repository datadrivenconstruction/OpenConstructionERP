#!/usr/bin/env node
/**
 * Fold the per-route findings of tests/e2e/smoke-every-route.spec.ts into one
 * table: qa-routes/report.md (also appended to the GitHub step summary when
 * GITHUB_STEP_SUMMARY is set) and qa-routes/report.json.
 *
 * Usage: node scripts/smoke-routes-report.mjs [qa-routes]
 */
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(process.argv[2] ?? 'qa-routes');
const dir = path.join(root, 'routes');
const rows = fs.existsSync(dir)
  ? fs.readdirSync(dir).filter((f) => f.endsWith('.json')).map((f) => JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')))
  : [];

const order = { fail: 0, soft: 1, unresolved: 2, ok: 3 };
rows.sort((a, b) => order[a.status] - order[b.status] || a.route.localeCompare(b.route));

const count = (s) => rows.filter((r) => r.status === s).length;
const cell = (s) => String(s).replace(/\|/g, '\\|').replace(/\s+/g, ' ').slice(0, 220);

const evidence = (r) => {
  const parts = [
    ...r.crashes.map((c) => c.replace('[ErrorBoundary] Caught render error:', 'boundary:')),
    ...r.pageErrors,
    ...r.apiErrors,
    ...r.consoleErrors.map((c) => `console: ${c}`),
    ...r.tabs.flatMap((t) => [`tab "${t.tab}": ${[...t.symptoms, ...t.details].join('; ')}`]),
  ];
  return parts.slice(0, 4).map(cell).join('<br>');
};

const lines = [
  '# Smoke every route',
  '',
  `${rows.length} routes: ${count('fail')} fail, ${count('soft')} soft (4xx or console only), ${count('unresolved')} unresolved, ${count('ok')} ok.`,
  '',
  '| status | route | opened | symptom | failing call / console message |',
  '|---|---|---|---|---|',
  ...rows
    .filter((r) => r.status !== 'ok')
    .map((r) => `| ${r.status} | \`${cell(r.route)}\` | ${cell(r.url)} | ${cell(r.symptoms.join(', ') || '-')} | ${evidence(r) || '-'} |`),
  '',
];

fs.mkdirSync(root, { recursive: true });
fs.writeFileSync(path.join(root, 'report.md'), lines.join('\n'));
fs.writeFileSync(path.join(root, 'report.json'), JSON.stringify(rows, null, 2));
if (process.env.GITHUB_STEP_SUMMARY) fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, lines.join('\n'));
console.log(lines.slice(0, 3).join('\n'));
