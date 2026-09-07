import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { UseMutationResult, UseQueryResult } from '@tanstack/react-query'

import { api } from './client'
import { detailOf } from './errors'
import type { components } from './schema'

export type Document = components['schemas']['DocumentRead']

export const PAGE_SIZE = 20
export const MAX_PAGE_SIZE = 100
/** What the listing route will return at most; asking for more is a 422. */

export const documentsKey = ['documents'] as const

/** Whether a posting was stored, or turned out to already be there (FR-1). */
export interface Ingested {
  document: Document
  duplicate: boolean
}

/**
 * The knowledge base, newest first, as one growing page.
 *
 * Read from offset 0 with a growing limit rather than paged by offset, and
 * not with useInfiniteQuery, because the list shifts under the reader: every
 * ingestion inserts at the top, so a second page fetched at offset 20 after
 * one arrived repeats the row that has just been pushed down. Asking for
 * "the first N, again" cannot show anything twice.
 *
 * The cost is refetching rows already on screen, which is a listing without
 * content -- ids, titles and counts -- and cheap enough to prefer over a
 * duplicate nobody can explain.
 */
export function useDocuments(shown: number): UseQueryResult<Document[]> {
  return useQuery({
    queryKey: [...documentsKey, shown],
    queryFn: async () => {
      const { data, error } = await api.GET('/documents', {
        params: { query: { limit: shown, offset: 0 } },
      })

      if (!data) {
        throw new Error(detailOf(error) ?? 'Could not read the knowledge base')
      }

      return data
    },
  })
}

/**
 * Turn one of the three ingestion responses into a result the page can show.
 *
 * 201 and 200 are both success and the difference is the whole point of
 * deduplication (FR-1): the second says this posting is already here and
 * names the document it landed in the first time. Reporting it as an error
 * would turn a feature into a failure; reporting it as a plain success would
 * hide that nothing new was stored.
 */
function ingested(
  data: Document | undefined,
  error: unknown,
  status: number,
): Ingested {
  if (!data) {
    throw new Error(detailOf(error) ?? `Could not ingest the posting (${String(status)})`)
  }

  return { document: data, duplicate: status === 200 }
}

function useIngestion<Input>(
  send: (input: Input) => Promise<Ingested>,
): UseMutationResult<Ingested, Error, Input> {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: send,
    onSuccess: async () => {
      // Every page of the listing, whatever its size: the key is a prefix, so
      // this invalidates the one on screen without knowing how far the reader
      // has scrolled.
      await queryClient.invalidateQueries({ queryKey: documentsKey })
    },
  })
}

/** Ingest a posting from the address it is published at (FR-1, NFR-5). */
export function useIngestUrl(): UseMutationResult<Ingested, Error, string> {
  return useIngestion(async (url: string) => {
    const { data, error, response } = await api.POST('/documents/from-url', {
      body: { url, metadata: {} },
    })

    return ingested(data, error, response.status)
  })
}

/** Ingest a posting from text somebody pasted. */
export function useIngestText(): UseMutationResult<Ingested, Error, string> {
  return useIngestion(async (content: string) => {
    const { data, error, response } = await api.POST('/documents', {
      body: { content, metadata: {} },
    })

    return ingested(data, error, response.status)
  })
}

/** Ingest a posting from a PDF, DOCX or text file. */
export function useIngestFile(): UseMutationResult<Ingested, Error, File> {
  return useIngestion(async (file: File) => {
    const { data, error, response } = await api.POST('/documents/upload', {
      // openapi-typescript renders `format: binary` as string, which is what
      // the JSON Schema says and not what goes on the wire. The cast is to
      // that declaration rather than around a real type error: the value
      // never reaches the default serialiser, because bodySerializer below
      // builds the request body instead.
      body: { file: file as unknown as string },
      // openapi-fetch would otherwise send JSON. FormData is built here and
      // no Content-Type is set anywhere: the browser writes it, together with
      // the multipart boundary, and a header set by hand loses the boundary.
      //
      // The name is passed as the third argument rather than left to be read
      // off the File. FormData only keeps a filename it is given or one it
      // recognises on a File, and anything it treats as a plain Blob is sent
      // as "blob" -- which the API stores as the document's title, because a
      // filename is the only name an upload comes with.
      bodySerializer: () => {
        const form = new FormData()
        form.set('file', file, file.name)

        return form
      },
    })

    return ingested(data, error, response.status)
  })
}
