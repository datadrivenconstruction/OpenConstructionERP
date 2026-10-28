// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Building a module from a description of it, and rendering the result.
 *
 * The wizard and the two pages are imported lazily by the router and by the
 * header button, so nothing here re-exports them: doing so would pull the whole
 * feature into whichever bundle touched this file first.
 */
export { ModuleBuilderButton } from './ModuleBuilderButton';
export type {
  InstalledModule,
  ModuleFieldSpec,
  ModuleRuleSpec,
  ModuleSpec,
  ModuleUiSpec,
} from './api';
