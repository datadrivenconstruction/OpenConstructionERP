// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Translated labels for condition data. Scale level titles are data (a pack or
 * a project can bring its own scale); only the shipped neutral scale has
 * interface translations, the others are shown as written.
 */
import type { TFunction } from 'i18next';
import type { ActionStatus, ActionType, ScaleLevel } from './api';

export function levelLabel(t: TFunction, scaleKey: string, level: ScaleLevel): string {
  if (scaleKey !== 'default_6') return level.label;
  switch (level.level) {
    case 1:
      return t('condition.level_default_6_1', { defaultValue: 'Excellent' });
    case 2:
      return t('condition.level_default_6_2', { defaultValue: 'Good' });
    case 3:
      return t('condition.level_default_6_3', { defaultValue: 'Satisfactory' });
    case 4:
      return t('condition.level_default_6_4', { defaultValue: 'Deficient' });
    case 5:
      return t('condition.level_default_6_5', { defaultValue: 'Poor' });
    case 6:
      return t('condition.level_default_6_6', { defaultValue: 'Very poor' });
    default:
      return level.label;
  }
}

export function actionTypeLabel(t: TFunction, type: ActionType): string {
  switch (type) {
    case 'inspect':
      return t('condition.action_inspect', { defaultValue: 'Inspect' });
    case 'maintain':
      return t('condition.action_maintain', { defaultValue: 'Maintain' });
    case 'repair':
      return t('condition.action_repair', { defaultValue: 'Repair' });
    default:
      return t('condition.action_replace', { defaultValue: 'Replace' });
  }
}

export function actionStatusLabel(t: TFunction, status: ActionStatus): string {
  switch (status) {
    case 'proposed':
      return t('condition.status_proposed', { defaultValue: 'Proposed' });
    case 'approved':
      return t('condition.status_approved', { defaultValue: 'Approved' });
    case 'done':
      return t('condition.status_done', { defaultValue: 'Done' });
    default:
      return t('condition.status_rejected', { defaultValue: 'Rejected' });
  }
}

/** Severity and intensity share the 1..4 scale; the words differ. */
export function severityLabel(t: TFunction, value: number): string {
  switch (value) {
    case 1:
      return t('condition.severity_1', { defaultValue: '1 - minor' });
    case 2:
      return t('condition.severity_2', { defaultValue: '2 - moderate' });
    case 3:
      return t('condition.severity_3', { defaultValue: '3 - serious' });
    default:
      return t('condition.severity_4', { defaultValue: '4 - critical' });
  }
}

export function intensityLabel(t: TFunction, value: number): string {
  switch (value) {
    case 1:
      return t('condition.intensity_1', { defaultValue: '1 - stable' });
    case 2:
      return t('condition.intensity_2', { defaultValue: '2 - slow' });
    case 3:
      return t('condition.intensity_3', { defaultValue: '3 - progressing' });
    default:
      return t('condition.intensity_4', { defaultValue: '4 - urgent' });
  }
}

export function levelOf(levels: ScaleLevel[], rating: number): ScaleLevel | undefined {
  return levels.find((l) => l.level === rating);
}
