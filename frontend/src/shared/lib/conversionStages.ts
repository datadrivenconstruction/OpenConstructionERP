// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One vocabulary for "my CAD file is being turned into a model".
 *
 * The BIM upload dock, the model overlay and the DWG takeoff card all show the
 * same ordered stages and the same plain-words errors, so an estimator sees one
 * process no matter where the file went in.
 */

export type ConversionStageId = 'upload' | 'converter' | 'convert' | 'model3d' | 'table' | 'entities';

/** Stages of a BIM model (RVT, IFC), in the order the server runs them. */
export const BIM_STAGES: readonly ConversionStageId[] = ['upload', 'converter', 'convert', 'model3d', 'table'];

/** Stages of a DWG drawing. */
export const DWG_STAGES: readonly ConversionStageId[] = ['upload', 'converter', 'convert', 'entities'];

/** Backend `conversion_stage` value to UI stage. Unknown values read as the long conversion step. */
export function stageFromServer(value: string | null | undefined): ConversionStageId {
  switch (value) {
    case 'preparing_converter':
      return 'converter';
    case 'building_3d':
      return 'model3d';
    case 'reading_elements':
      return 'table';
    case 'reading_entities':
      return 'entities';
    default:
      return 'convert';
  }
}

export type StageState = 'done' | 'current' | 'pending';

export function stageStates(stages: readonly ConversionStageId[], current: ConversionStageId): StageState[] {
  const at = Math.max(0, stages.indexOf(current));
  return stages.map((_, i) => (i < at ? 'done' : i === at ? 'current' : 'pending'));
}

/** Plain minutes for the time limit; the server default is 30 minutes. */
export function limitMinutes(limitS: number | null | undefined): number {
  return Math.max(1, Math.round((limitS && limitS > 0 ? limitS : 1800) / 60));
}

export type ConversionErrorKind = 'timeout' | 'unreadable' | 'converter_install' | 'stalled' | 'empty' | 'generic';

/** Group the many server error codes into the few things a user can act on. */
export function conversionErrorKind(code: string | null | undefined): ConversionErrorKind {
  switch (code) {
    case 'convert_timeout':
      return 'timeout';
    case 'ddc_failed':
    case 'convert_failed':
    case 'dwg_too_old':
    case 'parse_failed':
    case 'no_entities':
    case 'unclassified_rows':
    case 'unexpected':
      return 'unreadable';
    case 'converter_missing':
    case 'ddc_not_found':
    case 'ddc_smoke_failed':
    case 'converter_outdated':
    case 'converter_install_failed':
      return 'converter_install';
    case 'ui_stalled':
      return 'stalled';
    case 'zero_elements':
    case 'no_products':
    case 'empty':
      return 'empty';
    default:
      return 'generic';
  }
}

type Translate = (key: string, options?: Record<string, unknown>) => string;

export interface ConversionErrorVars {
  /** Upper-case file format, for example `RVT`. */
  format?: string;
  /** The time limit in minutes. */
  minutes?: number;
}

/** Title and "what to do" text for an error kind. Literal keys so the locale gates can see them. */
export function conversionErrorText(
  t: Translate,
  kind: ConversionErrorKind,
  vars: ConversionErrorVars = {},
): { title: string; body: string } {
  const v = { format: vars.format || 'CAD', minutes: vars.minutes ?? 30 };
  switch (kind) {
    case 'timeout':
      return {
        title: t('conv.err_timeout_title', { defaultValue: 'The conversion took too long' }),
        body: t('conv.err_timeout_body', {
          defaultValue:
            'The converter was stopped after {{minutes}} minutes. Very large or complex files can need longer. Export a smaller part of the model (one discipline or one level) and upload it again, or ask your administrator to raise the time limit.',
          ...v,
        }),
      };
    case 'unreadable':
      return {
        title: t('conv.err_unreadable_title', { defaultValue: 'This file could not be read' }),
        body: t('conv.err_unreadable_body', {
          defaultValue:
            'The file may be damaged, or saved in a newer {{format}} version than the converter supports. Open it in your design software, save a copy (for DWG, an older version such as 2018), and upload that copy.',
          ...v,
        }),
      };
    case 'converter_install':
      return {
        title: t('conv.err_converter_title', { defaultValue: 'The converter is not ready' }),
        body: t('conv.err_converter_body', {
          defaultValue:
            'The converter for {{format}} files could not be installed or started. Press Install converter and wait for it to finish. If it fails again, check that the server can reach the internet, or ask your administrator to install it.',
          ...v,
        }),
      };
    case 'stalled':
      return {
        title: t('conv.err_stalled_title', { defaultValue: 'No answer from the server' }),
        body: t('conv.err_stalled_body', {
          defaultValue:
            'We stopped waiting after {{minutes}} minutes. The server may still be working, so check the project list before uploading again.',
          ...v,
        }),
      };
    case 'empty':
      return {
        title: t('conv.err_empty_title', { defaultValue: 'Nothing to import' }),
        body: t('conv.err_empty_body', {
          defaultValue:
            'The file was read, but it holds no building elements. Check in your design software that the model has walls, slabs or other objects, then upload it again.',
        }),
      };
    default:
      return {
        title: t('conv.err_generic_title', { defaultValue: 'The conversion failed' }),
        body: t('conv.err_generic_body', {
          defaultValue:
            'Something went wrong while converting this file. Try again. If it keeps failing, upload a smaller or re-saved copy of the file.',
        }),
      };
  }
}

/** Label and one-line hint of a stage. */
export function stageText(t: Translate, id: ConversionStageId, vars: { format?: string } = {}): { label: string; hint: string } {
  const format = vars.format || 'CAD';
  switch (id) {
    case 'upload':
      return {
        label: t('conv.stage_upload', { defaultValue: 'Uploading the file' }),
        hint: t('conv.stage_upload_hint', { defaultValue: 'Sending the file to the server. Keep this tab open until it finishes.' }),
      };
    case 'converter':
      return {
        label: t('conv.stage_converter', { defaultValue: 'Preparing the converter' }),
        hint: t('conv.stage_converter_hint', {
          defaultValue: 'Needed once, the first time you use this format. Later files skip this step.',
        }),
      };
    case 'convert':
      return {
        label: t('conv.stage_convert', { defaultValue: 'Converting the file' }),
        hint: t('conv.stage_convert_hint', {
          defaultValue: 'The converter is reading your {{format}} file. This is the slow step.',
          format,
        }),
      };
    case 'model3d':
      return {
        label: t('conv.stage_model3d', { defaultValue: 'Building the 3D view' }),
        hint: t('conv.stage_model3d_hint', { defaultValue: 'Saving the geometry so the model can be shown in 3D.' }),
      };
    case 'table':
      return {
        label: t('conv.stage_table', { defaultValue: 'Reading the element table' }),
        hint: t('conv.stage_table_hint', { defaultValue: 'Storing every element with its properties and quantities.' }),
      };
    default:
      return {
        label: t('conv.stage_entities', { defaultValue: 'Reading the drawing' }),
        hint: t('conv.stage_entities_hint', { defaultValue: 'Storing layers and shapes so you can measure on the drawing.' }),
      };
  }
}
