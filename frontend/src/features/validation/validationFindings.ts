// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Shaping a validation report for a reader.
//
// A report is one row per rule per element: a bill of 300 positions checked by
// a few dozen rules comes back as well over a thousand rows, almost all of them
// passes. Printed flat, the handful of problems sit somewhere inside that list
// and the same rule appears thirty times in a row. This module filters the
// rows down to what the reader asked for, groups them by rule (one heading per
// rule, its findings underneath) and orders the groups so the worst come first.
// It is pure so the ordering and the filter can be tested without the page.

import { compareNames } from '@/shared/lib/collator';

export type FindingSeverity = 'error' | 'warning' | 'info';

/** The fields of a report row this module reads. */
export interface FindingLike {
  rule_id: string;
  rule_name: string;
  severity: FindingSeverity;
  passed: boolean;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

/**
 * What the result list shows. `problems` (errors and warnings) is the default:
 * the reader opened the report to see what is wrong, and the passes stay one
 * click away under `passed`.
 */
export type FindingFilter = 'problems' | 'errors' | 'warnings' | 'info' | 'passed' | 'all';

/** A BOQ position as far as a finding needs it: where it is and what it is. */
export interface PositionRef {
  ordinal: string;
  description: string;
}

/** A finding row together with its index in the report, kept as a stable key. */
export interface IndexedFinding<T extends FindingLike = FindingLike> {
  index: number;
  finding: T;
}

/** One rule's findings under a single heading. */
export interface FindingGroup<T extends FindingLike = FindingLike> {
  ruleId: string;
  ruleName: string;
  /** `passed` when every finding in the group is a pass. */
  tone: FindingSeverity | 'passed';
  findings: IndexedFinding<T>[];
  /** The suggestion every finding in the group shares, if they share one. */
  commonSuggestion: string | null;
}

export function matchesFilter(finding: FindingLike, filter: FindingFilter): boolean {
  switch (filter) {
    case 'problems':
      return !finding.passed && (finding.severity === 'error' || finding.severity === 'warning');
    case 'errors':
      return !finding.passed && finding.severity === 'error';
    case 'warnings':
      return !finding.passed && finding.severity === 'warning';
    case 'info':
      return !finding.passed && finding.severity === 'info';
    case 'passed':
      return finding.passed;
    default:
      return true;
  }
}

export function countFindings(findings: readonly FindingLike[]): Record<FindingFilter, number> {
  const counts: Record<FindingFilter, number> = {
    problems: 0,
    errors: 0,
    warnings: 0,
    info: 0,
    passed: 0,
    all: findings.length,
  };
  for (const f of findings) {
    if (f.passed) {
      counts.passed += 1;
    } else if (f.severity === 'error') {
      counts.errors += 1;
      counts.problems += 1;
    } else if (f.severity === 'warning') {
      counts.warnings += 1;
      counts.problems += 1;
    } else {
      counts.info += 1;
    }
  }
  return counts;
}

const TONE_ORDER: Record<FindingGroup['tone'], number> = { error: 0, warning: 1, info: 2, passed: 3 };

function findingTone(finding: FindingLike): FindingGroup['tone'] {
  return finding.passed ? 'passed' : finding.severity;
}

/**
 * Case-insensitive search over what the reader can see on a finding: the
 * position ordinal and description, the message, the suggestion and the rule
 * title. A blank query matches everything.
 */
export function matchesSearch(
  finding: FindingLike,
  query: string,
  position: PositionRef | undefined,
  title: string,
): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  const haystack = [
    position?.ordinal,
    position?.description,
    finding.message,
    finding.suggestion,
    title,
  ]
    .filter(Boolean)
    .join('\n')
    .toLowerCase();
  return haystack.includes(q);
}

/**
 * Group the findings that pass `filter` (and `search`, when given) by rule.
 *
 * Within a rule a finding keeps the report's order. A rule whose findings mix
 * severities takes the worst one present as its tone. Groups are ordered
 * errors, warnings, info, passes, and within a tone the larger group first,
 * since that is where the most work is; ties keep the rule title order so the
 * list does not reshuffle between renders.
 */
export function groupFindings<T extends FindingLike>(
  findings: readonly T[],
  filter: FindingFilter,
  options: {
    title: (finding: T) => string;
    search?: string;
    position?: (finding: T) => PositionRef | undefined;
  },
): FindingGroup<T>[] {
  const groups = new Map<string, FindingGroup<T>>();
  const search = options.search ?? '';
  findings.forEach((finding, index) => {
    if (!matchesFilter(finding, filter)) return;
    const title = options.title(finding);
    if (search && !matchesSearch(finding, search, options.position?.(finding), title)) return;
    let group = groups.get(finding.rule_id);
    if (!group) {
      group = {
        ruleId: finding.rule_id,
        ruleName: title,
        tone: findingTone(finding),
        findings: [],
        commonSuggestion: null,
      };
      groups.set(finding.rule_id, group);
    }
    const tone = findingTone(finding);
    if (TONE_ORDER[tone] < TONE_ORDER[group.tone]) group.tone = tone;
    group.findings.push({ index, finding });
  });

  for (const group of groups.values()) {
    const first = group.findings[0]?.finding.suggestion ?? null;
    group.commonSuggestion =
      first && group.findings.every((f) => f.finding.suggestion === first) ? first : null;
  }

  return [...groups.values()].sort(
    (a, b) =>
      TONE_ORDER[a.tone] - TONE_ORDER[b.tone] ||
      b.findings.length - a.findings.length ||
      compareNames(a.ruleName, b.ruleName),
  );
}

/** How a finding's element reference resolves against the loaded BOQ. */
export type FindingScope =
  | { kind: 'project' }
  | { kind: 'position'; positionId: string; position: PositionRef }
  | { kind: 'boq'; boqId: string; name: string | null }
  | { kind: 'loading' }
  | { kind: 'missing' };

/**
 * Resolve a finding's `element_ref` to what the reader should see in its place.
 *
 * Rules point at different things: most at a BOQ position, project rules at a
 * whole bill, a few at nothing at all (the project). The id itself means
 * nothing to an estimator, so it is resolved to the position's ordinal and
 * description, or to the bill's name, and never printed.
 */
export function resolveScope(
  elementRef: string | null,
  positions: ReadonlyMap<string, PositionRef> | null,
  boqs: ReadonlyMap<string, string>,
): FindingScope {
  if (!elementRef) return { kind: 'project' };
  const position = positions?.get(elementRef);
  if (position) return { kind: 'position', positionId: elementRef, position };
  if (boqs.has(elementRef)) return { kind: 'boq', boqId: elementRef, name: boqs.get(elementRef) ?? null };
  if (positions === null) return { kind: 'loading' };
  return { kind: 'missing' };
}

/** Collapse whitespace and cut a long description to one readable line. */
export function shortDescription(text: string, max = 90): string {
  const flat = text.replace(/\s+/g, ' ').trim();
  if (flat.length <= max) return flat;
  return `${flat.slice(0, max - 1).trimEnd()}…`;
}
