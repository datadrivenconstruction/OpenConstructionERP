// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One icon per domain an action touches, the same icon the sidebar uses for
 * that module (app/layout/navCatalog.ts), so "Add BOQ position" in the chat
 * wears the icon a person already knows from the BOQ menu entry.
 */
import {
  CalendarDays,
  ClipboardList,
  HelpCircle,
  ListChecks,
  ShieldAlert,
  Sparkles,
  Table2,
  type LucideIcon,
} from 'lucide-react';
import { actionDomain } from './types';

const ICONS: Record<string, LucideIcon> = {
  boq: Table2,
  task: ClipboardList,
  tasks: ClipboardList,
  rfi: HelpCircle,
  risk: ShieldAlert,
  risks: ShieldAlert,
  punch: ListChecks,
  punchlist: ListChecks,
  schedule: CalendarDays,
};

/** Icon for an `action_type` such as `boq.add_position`; unknown types get a sparkle. */
export function actionIcon(actionType: string): LucideIcon {
  return ICONS[actionDomain(actionType)] ?? Sparkles;
}
