/**
 * Hand a file the page already holds to the browser's download.
 *
 * The bytes are fetched through the API client rather than by a plain link,
 * because only the client renews a stale access cookie: a link followed after
 * the cookie expired would open a 401 instead of a file, and the refresh
 * cookie is scoped to /api/auth/refresh so it could not rescue it.
 *
 * The object URL is released on the next tick rather than straight after the
 * click. Some browsers start the download asynchronously and cancel it when
 * the URL is gone by the time they get to it.
 *
 * Kept apart from the hook that fetches, because jsdom implements neither
 * createObjectURL nor navigation: a test replaces this function and checks
 * what it was handed.
 */
export function saveFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()

  setTimeout(() => {
    URL.revokeObjectURL(url)
  }, 0)
}
