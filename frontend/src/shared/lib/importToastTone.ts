/**​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
 * The tone of the toast that reports how many items an import brought in.
 *
 * An import that answered without error but landed nothing ("0 of 0") is not
 * a success: the user has to look at the file again, so it reads as a warning.
 */
export function importToastTone(imported: number | null | undefined): 'success' | 'warning' {
  return typeof imported === 'number' && imported > 0 ? 'success' : 'warning';
}
