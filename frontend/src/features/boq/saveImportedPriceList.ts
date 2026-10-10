/**
 * Keep the price list of an imported XPWE bill as a cost database.
 *
 * An XPWE (or PWE) export carries the price list the bill is priced from next
 * to the bill itself. The bill import reads only the bill; this hands the same
 * file to the regional price-list import, so the estimator does not have to
 * upload it a second time from the cost database page.
 */
import {
  importUploadedPriceList,
  uploadPriceList,
  type PriceListImportResult,
} from '@/features/costs/regionalPriceListApi';

/** Whether a finished bill import came from a file that also holds a price list. */
export function carriesPriceList(sourceFormat: string | null | undefined): boolean {
  return sourceFormat === 'xpwe';
}

/**
 * Upload the file to the price-list import and import it under the name the
 * server suggests. The preview count is passed on so the server can refuse
 * when the file changed between the two steps.
 */
export async function saveImportedPriceList(file: File): Promise<PriceListImportResult> {
  const { uploadId, preview } = await uploadPriceList(file);
  return importUploadedPriceList(uploadId, preview.source.suggested_catalog_name, {}, preview.counts.rows);
}
