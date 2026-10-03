/**
 * Company names contain spaces, ampersands and slashes ("Ultra Jaya Milk Industry
 * & Trading Company, Tbk"), so every link to one has to encode the segment.
 * Centralised here so a link built in three places cannot disagree with the
 * route that resolves it.
 */
export function companyPath(company: string): string {
  return `/companies/${encodeURIComponent(company)}`
}