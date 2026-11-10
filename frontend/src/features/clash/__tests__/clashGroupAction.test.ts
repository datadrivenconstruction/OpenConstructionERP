// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';

import type { ClashCluster, ClashGroupActionProposal } from '../api';
import {
  canCreateAction,
  clamp01,
  clusterChipLabel,
  confidenceBand,
  confidenceChipClass,
  confidenceLabel,
  groupClustersByPair,
  severityToPriority,
  summarizeProposal,
  targetNoun,
} from '../clashGroupAction';

function cluster(over: Partial<ClashCluster> = {}): ClashCluster {
  return {
    cluster_id: 1,
    label: 'Mechanical x Structural - Level 2',
    size: 5,
    dominant_disciplines: ['Mechanical', 'Structural'],
    storey: 2,
    ...over,
  };
}

function proposal(
  over: Partial<ClashGroupActionProposal> = {},
): ClashGroupActionProposal {
  return {
    cluster_id: 1,
    target: 'punchlist',
    title: 'Coordinate clash group',
    description: 'body',
    priority: 'high',
    suggested_assignee: null,
    member_count: 12,
    dominant_disciplines: ['Mechanical', 'Structural'],
    storey: 2,
    max_severity: 'high',
    confidence: 0.82,
    already_linked: false,
    existing_action_id: null,
    existing_action_target: null,
    ...over,
  };
}

describe('clamp01', () => {
  it('clamps out-of-range and non-finite values', () => {
    expect(clamp01(0.5)).toBe(0.5);
    expect(clamp01(-1)).toBe(0);
    expect(clamp01(2)).toBe(1);
    expect(clamp01(Number.NaN)).toBe(0);
    expect(clamp01(Number.POSITIVE_INFINITY)).toBe(0);
  });
});

describe('confidenceBand / label / chip', () => {
  it('buckets scores into bands at the right thresholds', () => {
    expect(confidenceBand(0.9)).toBe('high');
    expect(confidenceBand(0.75)).toBe('high');
    expect(confidenceBand(0.6)).toBe('medium');
    expect(confidenceBand(0.5)).toBe('medium');
    expect(confidenceBand(0.49)).toBe('low');
    expect(confidenceBand(-5)).toBe('low');
  });

  it('formats a percentage label', () => {
    expect(confidenceLabel(0.82)).toBe('82%');
    expect(confidenceLabel(1)).toBe('100%');
    expect(confidenceLabel(Number.NaN)).toBe('0%');
  });

  it('returns a distinct class per band', () => {
    expect(confidenceChipClass(0.9)).toContain('semantic-success');
    expect(confidenceChipClass(0.6)).toContain('semantic-warning');
    expect(confidenceChipClass(0.1)).toContain('semantic-error');
  });
});

describe('severityToPriority', () => {
  it('maps known severities and degrades unknowns to medium', () => {
    expect(severityToPriority('critical')).toBe('critical');
    expect(severityToPriority('high')).toBe('high');
    expect(severityToPriority('low')).toBe('low');
    expect(severityToPriority('medium')).toBe('medium');
    expect(severityToPriority(null)).toBe('medium');
    expect(severityToPriority(undefined)).toBe('medium');
  });
});

describe('clusterChipLabel', () => {
  it('includes the derived label and size', () => {
    expect(clusterChipLabel(cluster())).toBe(
      'Cluster 1 · Mechanical x Structural - Level 2 (5)',
    );
  });

  it('falls back to a bare cluster id when no label', () => {
    expect(clusterChipLabel(cluster({ label: '', size: 3 }))).toBe(
      'Cluster 1 (3)',
    );
  });

  it('never renders a negative size', () => {
    expect(clusterChipLabel(cluster({ label: '', size: -4 }))).toBe(
      'Cluster 1 (0)',
    );
  });
});

describe('summarizeProposal', () => {
  it('renders a one-line summary', () => {
    expect(summarizeProposal(proposal())).toBe(
      '12 clashes → punch item · high priority · 82% confidence',
    );
  });

  it('uses the singular noun for one clash and the task target', () => {
    expect(
      summarizeProposal(proposal({ member_count: 1, target: 'task' })),
    ).toBe('1 clash → task · high priority · 82% confidence');
  });
});

describe('targetNoun', () => {
  it('returns the human noun', () => {
    expect(targetNoun('task')).toBe('task');
    expect(targetNoun('punchlist')).toBe('punch item');
  });
});

describe('canCreateAction', () => {
  it('disables when linked, empty or absent', () => {
    expect(canCreateAction(proposal())).toBe(true);
    expect(canCreateAction(proposal({ already_linked: true }))).toBe(false);
    expect(canCreateAction(proposal({ member_count: 0 }))).toBe(false);
    expect(canCreateAction(null)).toBe(false);
    expect(canCreateAction(undefined)).toBe(false);
  });
});

describe('groupClustersByPair', () => {
  it('collapses clusters by symmetric discipline pair, biggest first', () => {
    const clusters: ClashCluster[] = [
      cluster({ cluster_id: 1, dominant_disciplines: ['Mechanical', 'Structural'], size: 3 }),
      cluster({ cluster_id: 2, dominant_disciplines: ['Structural', 'Mechanical'], size: 4 }),
      cluster({ cluster_id: 3, dominant_disciplines: ['Architectural', 'Mechanical'], size: 10 }),
    ];
    const groups = groupClustersByPair(clusters);
    expect(groups).toHaveLength(2);
    // Architectural|Mechanical has the larger total (10) → first.
    expect(groups[0]!.label).toBe('Architectural x Mechanical');
    expect(groups[0]!.totalSize).toBe(10);
    // The symmetric (M,S) / (S,M) pair collapses into one bucket of 2 clusters.
    const ms = groups[1]!;
    expect(ms.label).toBe('Mechanical x Structural');
    expect(ms.clusters).toHaveLength(2);
    expect(ms.totalSize).toBe(7);
  });

  it('routes clusters with no resolved disciplines into (mixed)', () => {
    const groups = groupClustersByPair([
      cluster({ cluster_id: 9, dominant_disciplines: [], label: '', size: 2 }),
      cluster({ cluster_id: 10, dominant_disciplines: ['', '  '], label: '', size: 1 }),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0]!.key).toBe('(mixed)');
    expect(groups[0]!.totalSize).toBe(3);
  });

  it('returns an empty array for no clusters', () => {
    expect(groupClustersByPair([])).toEqual([]);
  });
});
