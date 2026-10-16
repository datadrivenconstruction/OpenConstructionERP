// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// A project governed by a phase model (the owner's project control pack runs a
// development and an execution phase) showed the generic five-step lifecycle on
// its hub, a model the project is not run by. The ribbon now follows the model.

import { describe, expect, it } from 'vitest';
import { governancePhaseSteps } from '../ProjectDetailPage';

describe('the phase ribbon of a governed project', () => {
  it('lists the model phases in their order and marks the current one', () => {
    const phases = [
      { code: 'execution', order: 2 },
      { code: 'development', order: 1 },
    ];
    expect(governancePhaseSteps(phases, 'execution')).toEqual({ codes: ['development', 'execution'], activeIdx: 1 });
    expect(governancePhaseSteps(phases, 'development').activeIdx).toBe(0);
  });

  it('marks no step when the model names no current phase', () => {
    expect(governancePhaseSteps([{ code: 'development', order: 1 }], null).activeIdx).toBe(-1);
    expect(governancePhaseSteps([{ code: 'development', order: 1 }], 'unknown').activeIdx).toBe(-1);
  });
});
