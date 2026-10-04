// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The buying chain's destinations, and the lookup that finds the contract or
// purchase order an award drafted. The lookup mirrors the server's own
// (award_contract.find_award_contract and procurement _find_existing_po): a
// match on any non-empty key, retired rows passed over, first row wins.

import { describe, it, expect } from 'vitest';
import {
  bidPackageDeepLink,
  boqDeepLink,
  boqPositionDeepLink,
  changeOrderWriteback,
  contractSource,
  findAwardRecord,
  RETIRED_AWARD_CONTRACT_STATUSES,
  RETIRED_AWARD_ORDER_STATUSES,
  tenderPackageDeepLink,
} from './awardChainLinks';

describe('each link lands on the record the page reads', () => {
  it('carries the id in the parameter each register consumes', () => {
    expect(tenderPackageDeepLink('tp-1')).toBe('/tendering?package=tp-1');
    expect(bidPackageDeepLink('bp-1')).toBe('/bid-management?highlight=bp-1');
    expect(boqDeepLink('boq-1')).toBe('/boq/boq-1');
    expect(boqDeepLink('boq-1', 'pos-2')).toBe('/boq/boq-1?highlight=pos-2');
    expect(boqDeepLink('boq-1', null)).toBe('/boq/boq-1');
    expect(boqPositionDeepLink('pos-2')).toBe('/boq?positionId=pos-2');
  });

  it('escapes an id that would otherwise rewrite the query string', () => {
    expect(tenderPackageDeepLink('a&tab=x')).toBe('/tendering?package=a%26tab%3Dx');
    expect(boqDeepLink('a/b', 'c d')).toBe('/boq/a%2Fb?highlight=c%20d');
  });
});

type Row = { id: string; status: string; metadata?: Record<string, unknown> | null };

describe('findAwardRecord', () => {
  const rows: Row[] = [
    { id: 'hand-made', status: 'draft', metadata: {} },
    { id: 'from-bid', status: 'draft', metadata: { bid_package_id: 'bp-1' } },
    { id: 'from-tender', status: 'active', metadata: { tender_package_id: 'tp-1' } },
  ];

  it('finds the record by the tender key', () => {
    expect(findAwardRecord(rows, { tender_package_id: 'tp-1' }, RETIRED_AWARD_CONTRACT_STATUSES)?.id).toBe(
      'from-tender',
    );
  });

  it('finds the record by any of several bid-package keys', () => {
    expect(
      findAwardRecord(rows, { bid_package_ids: ['bp-0', 'bp-1'] }, RETIRED_AWARD_CONTRACT_STATUSES)?.id,
    ).toBe('from-bid');
  });

  it('returns null for an award no row carries', () => {
    expect(findAwardRecord(rows, { tender_package_id: 'tp-9' }, RETIRED_AWARD_CONTRACT_STATUSES)).toBeNull();
  });

  it('returns null with no keys at all rather than the first row', () => {
    // An empty key set must not match a hand-made row whose metadata lacks
    // the key (undefined === undefined would).
    expect(findAwardRecord(rows, {}, RETIRED_AWARD_CONTRACT_STATUSES)).toBeNull();
    expect(
      findAwardRecord(rows, { tender_package_id: '', bid_package_ids: [null, undefined] }, RETIRED_AWARD_CONTRACT_STATUSES),
    ).toBeNull();
  });

  it('passes over a terminated contract and a cancelled order', () => {
    const retired: Row[] = [
      { id: 'old', status: 'terminated', metadata: { tender_package_id: 'tp-1' } },
      { id: 'new', status: 'draft', metadata: { tender_package_id: 'tp-1' } },
    ];
    expect(findAwardRecord(retired, { tender_package_id: 'tp-1' }, RETIRED_AWARD_CONTRACT_STATUSES)?.id).toBe('new');

    const orders: Row[] = [{ id: 'po-old', status: 'cancelled', metadata: { tender_package_id: 'tp-1' } }];
    expect(findAwardRecord(orders, { tender_package_id: 'tp-1' }, RETIRED_AWARD_ORDER_STATUSES)).toBeNull();
    // A cancelled status is not retirement for a contract.
    expect(
      findAwardRecord(
        [{ id: 'c', status: 'cancelled', metadata: { tender_package_id: 'tp-1' } }],
        { tender_package_id: 'tp-1' },
        RETIRED_AWARD_CONTRACT_STATUSES,
      )?.id,
    ).toBe('c');
  });

  it('takes the first matching row, which is the newest in a newest-first list', () => {
    const twice: Row[] = [
      { id: 'newer', status: 'draft', metadata: { tender_package_id: 'tp-1' } },
      { id: 'older', status: 'draft', metadata: { tender_package_id: 'tp-1' } },
    ];
    expect(findAwardRecord(twice, { tender_package_id: 'tp-1' }, RETIRED_AWARD_CONTRACT_STATUSES)?.id).toBe('newer');
  });

  it('survives rows with no metadata and ids that are not strings', () => {
    const odd: Row[] = [
      { id: 'a', status: 'draft', metadata: null },
      { id: 'b', status: 'draft' },
      { id: 'c', status: 'draft', metadata: { tender_package_id: 42 } },
    ];
    expect(findAwardRecord(odd, { tender_package_id: '42' }, RETIRED_AWARD_CONTRACT_STATUSES)).toBeNull();
  });
});

describe('contractSource', () => {
  it('reads the origin an award stamped', () => {
    expect(
      contractSource({ source: 'tendering.package.awarded', tender_package_id: 'tp-1', boq_id: 'boq-1' }),
    ).toEqual({ tenderPackageId: 'tp-1', bidPackageId: null, boqId: 'boq-1' });
  });

  it('answers null for every field on a hand-made contract', () => {
    expect(contractSource({})).toEqual({ tenderPackageId: null, bidPackageId: null, boqId: null });
    expect(contractSource(null)).toEqual({ tenderPackageId: null, bidPackageId: null, boqId: null });
    // The tender path writes boq_id: null for a package with no bill.
    expect(contractSource({ boq_id: null, bid_package_id: '' }).boqId).toBeNull();
  });
});

describe('changeOrderWriteback', () => {
  it('reads the stamp the approval wrote', () => {
    expect(
      changeOrderWriteback({ writeback: { boq_id: 'b', boq_section_id: 's', budget_row_id: 'r' } }),
    ).toEqual({ boqId: 'b', boqSectionId: 's', budgetRowId: 'r' });
  });

  it('answers null for an order approved before the stamp, or a malformed one', () => {
    const none = { boqId: null, boqSectionId: null, budgetRowId: null };
    expect(changeOrderWriteback({})).toEqual(none);
    expect(changeOrderWriteback(undefined)).toEqual(none);
    expect(changeOrderWriteback({ writeback: 'boq-1' })).toEqual(none);
    expect(changeOrderWriteback({ writeback: ['boq-1'] })).toEqual(none);
  });
});
