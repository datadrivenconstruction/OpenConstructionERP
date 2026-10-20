// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** Translated text for a failed conversion. A known ``errorCode`` wins; a
 *  legacy row without one keeps its English message, minus any converter
 *  dump after "Details:" (it named server paths). */
export function conversionErrorText(
  errorCode: string | null | undefined,
  message: string | null,
  t: (key: string, opts: { defaultValue: string }) => string,
): string | null {
  switch (errorCode) {
    case 'convert_failed':
      return t('dwg_takeoff.conv_err_convert_failed', {
        defaultValue:
          'The DWG converter could not read this file. It may be damaged or saved in a form the converter does not support. Open it in your CAD application, save it as DXF or as DWG 2018, and upload that file. You can delete this drawing below.',
      });
    case 'parse_failed':
      return t('dwg_takeoff.conv_err_parse_failed', {
        defaultValue:
          'The drawing could not be read. Open it in your CAD application, save it as DXF or as DWG 2018, and upload that file. You can delete this drawing below.',
      });
    case 'not_dwg':
      return t('dwg_takeoff.conv_err_not_dwg', {
        defaultValue:
          'This file does not look like a valid DWG. If you renamed a PDF or ZIP archive to .dwg, upload the original CAD file instead.',
      });
    case 'dwg_too_old':
      return t('dwg_takeoff.conv_err_dwg_too_old', {
        defaultValue:
          'This DWG is older than the supported format. Re-save it as DWG 2010 or newer in your CAD application and upload it again.',
      });
    case 'convert_timeout':
      return t('dwg_takeoff.conv_err_convert_timeout', {
        defaultValue:
          'The conversion took longer than this server allows. Upload the drawing as DXF, or ask your administrator to raise the conversion time limit.',
      });
    default:
      break;
  }
  if (!message) return null;
  const cut = message.indexOf(' Details:');
  return cut >= 0 ? message.slice(0, cut) : message;
}
