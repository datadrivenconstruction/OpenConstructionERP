// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Public barrel for the portfolio / multi-project (schedule-of-schedules)
// feature. Only the enterprise portfolio surface is re-exported here.
//
// NOTE: the resource capacity-planning / leveling pages that also live in this
// directory (CapacityPlanningPage, ResourceLevelingPage) are deep-imported by
// path in App.tsx and are intentionally NOT re-exported here, and their typed
// client lives in the sibling ./api.ts (left untouched). The portfolio-tree /
// cross-project-CPM client lives in ./portfolioCpmApi.ts; it is re-exported by
// name (not `export *`) so it cannot collide with that ./api.ts.

export { PortfolioPage } from './PortfolioPage';
export {
  portfolioCpmApi,
  type PortfolioTreeNode,
  type PortfolioNode,
  type PortfolioNodeType,
  type NodeCreateBody,
  type NodePatchBody,
  type CrossLink,
  type CrossLinkCreateBody,
  type DepType,
  type PortfolioCpmActivity,
  type PortfolioCpmResult,
} from './portfolioCpmApi';
