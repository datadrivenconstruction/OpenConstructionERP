/**
 * Shared model types re-exported from feature modules.
 *
 * Import from here when you need these types outside their owning feature,
 * e.g. in shared components, stores, or cross-feature code.
 *
 * NOTE: The canonical definitions live in each feature's api.ts file.
 * This file re-exports them so consumers have a single import path.
 */

export type { Project, CreateProjectData } from '@/features/projects/api';
export type {
  BOQ,
  Position,
  BOQWithPositions,
  Markup,
  MarkupsResponse,
  CreateMarkupData,
  UpdateMarkupData,
  CreateBOQData,
  CreatePositionData,
  UpdatePositionData,
  SectionGroup,
} from '@/features/boq/api';
