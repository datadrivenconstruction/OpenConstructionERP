// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The areas x phases matrix, laid out from GET .../matrix.
//
// The server sends areas x gates with the check of each gate's current
// attempt; this turns it into phases as columns, because a reader thinks in
// phases. A column is a phase and the gate that leaves it, a cell is the
// readiness of the area at that gate plus the frame documents it owes there.

import type {
  CheckStatus,
  DocumentStatus,
  GovernanceGate,
  GovernanceLabel,
  GovernancePhase,
  MatrixArea,
  MatrixResponse,
  Outcome,
} from './api';

export interface MatrixColumn {
  phase: GovernancePhase;
  gate: GovernanceGate | null;
  isCurrent: boolean;
}

export type CellReadiness =
  | { kind: 'decided'; outcome: Outcome | '' }
  | { kind: 'check'; status: CheckStatus; stale: boolean }
  | { kind: 'pending' }
  | { kind: 'none' };

export interface MatrixCell {
  documents: Array<{ id: string; docType: string; status: DocumentStatus; name?: GovernanceLabel }>;
  readiness: CellReadiness;
}

export interface MatrixRow {
  area: MatrixArea;
  cells: MatrixCell[];
}

export interface GovernanceMatrixData {
  columns: MatrixColumn[];
  rows: MatrixRow[];
}

export function buildMatrix(input: {
  phases: GovernancePhase[];
  currentPhase: string | null;
  matrix: MatrixResponse;
}): GovernanceMatrixData {
  const phases = [...input.phases].sort((a, b) => a.order - b.order);
  const live = input.matrix.gates.filter((g) => !g.historic);
  const columns: MatrixColumn[] = phases.map((phase) => ({
    phase,
    gate: live.find((g) => g.from_phase === phase.code) ?? null,
    isCurrent: phase.code === input.currentPhase,
  }));

  const rows = input.matrix.areas.map<MatrixRow>((area) => ({
    area,
    cells: columns.map<MatrixCell>(({ gate }) => {
      const cell = gate ? area.cells[gate.code] : undefined;
      return {
        documents: (cell?.documents ?? []).map((d) => ({
          id: d.document_id,
          docType: d.doc_type,
          status: d.status,
          name: d.name,
        })),
        readiness: readinessOf(area, gate, cell?.check_status ?? null, !!cell?.stale),
      };
    }),
  }));
  return { columns, rows };
}

function readinessOf(
  area: MatrixArea,
  gate: GovernanceGate | null,
  checkStatus: CheckStatus | null,
  stale: boolean,
): CellReadiness {
  if (!gate) return { kind: 'none' };
  if (gate.status === 'decided') return { kind: 'decided', outcome: gate.last_outcome };
  if (!area.applicable) return { kind: 'check', status: 'not_applicable', stale: false };
  if (checkStatus) return { kind: 'check', status: checkStatus, stale };
  // An open gate nobody has assessed yet: say so on the gate in progress, stay quiet ahead of it.
  return gate.status === 'not_started' ? { kind: 'pending' } : { kind: 'check', status: 'not_assessed', stale: false };
}
