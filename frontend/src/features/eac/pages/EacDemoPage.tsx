/**
 * `/eac/demo` — development-only preview of the EAC-3.1 block primitives.
 *
 * Shows the palette beside a sample triplet block on a canvas placeholder.
 * The real canvas + slot system lands in EAC-3.2 — this page exists so that
 * Playwright can capture screenshots, axe-core can scan the rendered DOM, and
 * design reviewers can verify color/icon/label hierarchy.
 *
 * The page renders without authentication-only data so it works in
 * Playwright's authenticated session without backend round-trips.
 */
import { DndContext, type DragEndEvent } from '@dnd-kit/core';
import { useState } from 'react';

import { AttributeBlock } from '../components/blocks/AttributeBlock';
import { BlockShell } from '../components/blocks/BlockShell';
import { ConstraintBlock } from '../components/blocks/ConstraintBlock';
import { LogicBlock } from '../components/blocks/LogicBlock';
import { SelectorBlock } from '../components/blocks/SelectorBlock';
import { TripletBlock } from '../components/blocks/TripletBlock';
import { VariableBlock } from '../components/blocks/VariableBlock';
import { EacBlockPalette } from '../components/EacBlockPalette';
import type { PaletteItem } from '../components/DraggablePaletteItem';
import type { AttributeRef, Constraint, EntitySelector, LocalVariableDefinition } from '../types';

const DEMO_SELECTOR: EntitySelector = {
  type: 'category',
  category: 'Walls',
};

const DEMO_ATTRIBUTE: AttributeRef = {
  kind: 'alias',
  alias_id: 'eac.alias.thickness',
  canonical_name: 'Thickness',
};

const DEMO_CONSTRAINT: Constraint = {
  operator: 'gte',
  value: 240,
  unit: 'mm',
};

const DEMO_VARIABLE: LocalVariableDefinition = {
  name: 'totalWallVolume',
  aggregate: 'sum',
  expression: '${Volume}',
  unit: 'm³',
};

export function EacDemoPage() {
  const [lastDropped, setLastDropped] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  function handleDragEnd(event: DragEndEvent) {
    const item = event.active?.data?.current?.['item'] as PaletteItem | undefined;
    if (item) {
      setLastDropped(item.label);
    }
  }

  function handleActivate(item: PaletteItem) {
    setLastDropped(item.label);
  }

  return (
    <DndContext onDragEnd={handleDragEnd}>
      <div
        data-testid="eac-demo-page"
        className="flex h-[calc(100vh-var(--oe-header-height,56px))] w-full overflow-hidden bg-surface-primary"
      >
        <EacBlockPalette onActivate={handleActivate} />
        <main className="flex-1 overflow-auto p-6">
          <header className="mb-4">
            <h1 className="text-xl font-semibold text-content-primary">
              EAC v2 — block primitives preview
            </h1>
            <p className="mt-1 text-sm text-content-secondary">
              EAC-3.1 scaffolding. Canvas + slot system arrive in EAC-3.2.
            </p>
            {lastDropped && (
              <p
                data-testid="eac-demo-last-dropped"
                className="mt-2 text-xs text-content-tertiary"
              >
                Last activated: <span className="font-medium">{lastDropped}</span>
              </p>
            )}
          </header>

          <div className="grid max-w-3xl grid-cols-1 gap-3">
            <SelectorBlock
              selector={DEMO_SELECTOR}
              selected={selected === 'selector'}
              onSelect={() => setSelected('selector')}
            />
            <LogicBlock
              kind="and"
              childCount={2}
              selected={selected === 'logic'}
              onSelect={() => setSelected('logic')}
            />
            <TripletBlock
              attribute={DEMO_ATTRIBUTE}
              constraint={DEMO_CONSTRAINT}
              selected={selected === 'triplet'}
              onSelect={() => setSelected('triplet')}
              attributeSelected={selected === 'triplet-attr'}
              onAttributeSelect={() => setSelected('triplet-attr')}
              constraintSelected={selected === 'triplet-constraint'}
              onConstraintSelect={() => setSelected('triplet-constraint')}
            />
            <AttributeBlock
              attribute={DEMO_ATTRIBUTE}
              selected={selected === 'attribute'}
              onSelect={() => setSelected('attribute')}
            />
            <ConstraintBlock
              constraint={DEMO_CONSTRAINT}
              selected={selected === 'constraint'}
              onSelect={() => setSelected('constraint')}
            />
            <VariableBlock
              variable={DEMO_VARIABLE}
              selected={selected === 'variable'}
              onSelect={() => setSelected('variable')}
            />

            <BlockShell color="selector" label="Drag handle preview" draggable sortableId="demo-1">
              Hold the handle and drop on the canvas (canvas in EAC-3.2)
            </BlockShell>
          </div>
        </main>
      </div>
    </DndContext>
  );
}

export default EacDemoPage;
