/**
 * Reading the reason out of an error the API returned.
 *
 * Every failure this application shows a person comes through here, because
 * the API's own message is almost always the useful one: which host the
 * allowlist refused (NFR-5), that an address and a password did not match,
 * that a document is longer than the limit. Replacing those with "something
 * went wrong" would leave the user guessing at a rule they cannot see.
 *
 * Written defensively because the value is whatever came back over the wire.
 * A 502 from a proxy is not a FastAPI error object, and neither is an HTML
 * page from something in between.
 */
export function detailOf(error: unknown): string | null {
  if (typeof error !== 'object' || error === null || !('detail' in error)) {
    return null
  }

  const { detail } = error

  if (typeof detail === 'string') {
    return detail
  }

  // FastAPI reports validation failures as a list of objects. The first
  // one's msg is the half worth showing; the rest of it names the field by
  // its position in the request body, which means nothing to a reader.
  if (Array.isArray(detail)) {
    const first: unknown = detail[0]

    if (typeof first === 'object' && first !== null && 'msg' in first) {
      const { msg } = first

      if (typeof msg === 'string') {
        return msg
      }
    }
  }

  return null
}
