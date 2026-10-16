// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// An answered RFI read "Beantwortet Beantwortet" on its detail page: the status
// badge and the ball-in-court pill both said it. The pill now shows only while
// someone still owes the next move, as on the list row.

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { ballInCourtSide } from '../RFIPage';
import type { RFI } from '../api';

describe('the ball-in-court pill on the RFI detail page', () => {
  it('is not the side of an answered or closed RFI', () => {
    for (const status of ['answered', 'closed']) {
      const side = ballInCourtSide({ status, ball_in_court: null } as unknown as RFI, 'u1');
      expect(side === 'you' || side === 'them').toBe(false);
    }
  });

  it('renders only for a side that still owes the next move', () => {
    const src = readFileSync(resolve(__dirname, '../RFIDetailPage.tsx'), 'utf8');
    expect(src).toMatch(/\{\(bicSide === 'you' \|\| bicSide === 'them'\) && \(\s*<span\s+data-testid="rfi-detail-bic-pill"/);
  });
});
