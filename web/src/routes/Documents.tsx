import { useState } from 'react'
import type { ReactElement, SyntheticEvent } from 'react'

import type { Document, Ingested } from '../api/documents'
import {
  MAX_PAGE_SIZE,
  PAGE_SIZE,
  useDocuments,
  useIngestFile,
  useIngestText,
  useIngestUrl,
} from '../api/documents'

const MAX_CONTENT_LENGTH = 200_000
/** Mirrors MAX_CONTENT_LENGTH in app/schemas/document.py, so a paste that
 *  cannot be stored is refused before it is embedded rather than after. */

const UPLOAD_TYPES = '.pdf,.docx,.txt,.md'

function chunks(count: number): string {
  return count === 1 ? '1 chunk' : `${String(count)} chunks`
}

/** What came of an ingestion: a new posting, or the one it duplicates. */
function Outcome({
  result,
  error,
}: {
  result: Ingested | undefined
  error: Error | null
}): ReactElement | null {
  if (error) {
    return <p role="alert">{error.message}</p>
  }

  if (!result) {
    return null
  }

  return (
    <p role="status">
      {result.duplicate
        ? `Already in the knowledge base as ${result.document.id}.`
        : `Stored as ${result.document.id} (${chunks(result.document.chunk_count)}).`}
    </p>
  )
}

/** The address of a posting: the one way in that asks nothing of the user
 *  but a link they already have open, so it comes first (FR-1). */
function AddByUrl(): ReactElement {
  const [url, setUrl] = useState('')
  const ingest = useIngestUrl()

  function onSubmit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>): void {
    event.preventDefault()
    ingest.mutate(url.trim(), { onSuccess: () => { setUrl('') } })
  }

  return (
    <form onSubmit={onSubmit}>
      <label htmlFor="posting-url">Job posting URL</label>
      <input
        id="posting-url"
        type="url"
        required
        placeholder="https://justjoin.it/job-offer/..."
        value={url}
        onChange={(event) => { setUrl(event.target.value) }}
      />
      <button type="submit" disabled={ingest.isPending}>
        {ingest.isPending ? 'Reading the posting…' : 'Read the posting'}
      </button>

      <Outcome result={ingest.data} error={ingest.error} />
    </form>
  )
}

function AddByFile(): ReactElement {
  // Keyed so a successful upload empties the control: the value of a file
  // input cannot be set from script, and remounting it is the way to clear it.
  const [generation, setGeneration] = useState(0)
  const [file, setFile] = useState<File | null>(null)
  const ingest = useIngestFile()

  function onSubmit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>): void {
    event.preventDefault()

    if (!file) {
      return
    }

    ingest.mutate(file, {
      onSuccess: () => {
        setFile(null)
        setGeneration((current) => current + 1)
      },
    })
  }

  return (
    <form onSubmit={onSubmit}>
      <label htmlFor={`posting-file-${String(generation)}`}>
        Job posting file (PDF, DOCX or text)
      </label>
      <input
        id={`posting-file-${String(generation)}`}
        key={generation}
        type="file"
        accept={UPLOAD_TYPES}
        // Deliberately not `required`. The submit button is disabled until a
        // file is chosen and onSubmit returns without one, so it adds no
        // guarantee -- and jsdom's constraint validation does not see files
        // set by a test, so with it the form silently never submits and the
        // upload path cannot be covered at all.
        onChange={(event) => { setFile(event.target.files?.[0] ?? null) }}
      />
      <button type="submit" disabled={ingest.isPending || !file}>
        {ingest.isPending ? 'Reading the file…' : 'Upload'}
      </button>

      <Outcome result={ingest.data} error={ingest.error} />
    </form>
  )
}

function AddByText(): ReactElement {
  const [content, setContent] = useState('')
  const ingest = useIngestText()
  const tooLong = content.length > MAX_CONTENT_LENGTH

  function onSubmit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>): void {
    event.preventDefault()

    if (tooLong) {
      return
    }

    ingest.mutate(content, { onSuccess: () => { setContent('') } })
  }

  return (
    <form onSubmit={onSubmit}>
      <label htmlFor="posting-text">Job posting text</label>
      <textarea
        id="posting-text"
        rows={10}
        required
        value={content}
        onChange={(event) => { setContent(event.target.value) }}
      />

      {tooLong ? (
        <p role="alert">
          The text is longer than {MAX_CONTENT_LENGTH.toLocaleString('en')}{' '}
          characters.
        </p>
      ) : null}

      <button type="submit" disabled={ingest.isPending || tooLong}>
        {ingest.isPending ? 'Storing…' : 'Store'}
      </button>

      <Outcome result={ingest.data} error={ingest.error} />
    </form>
  )
}

function Posting({ document }: { document: Document }): ReactElement {
  const stored = new Date(document.created_at)

  return (
    <li>
      <h3>{document.title ?? 'Untitled'}</h3>
      <p>
        <time dateTime={document.created_at}>{stored.toLocaleString()}</time>
        {' · '}
        <span>{chunks(document.chunk_count)}</span>
      </p>

      {document.source_url ? (
        <p>
          <a href={document.source_url} target="_blank" rel="noreferrer">
            {document.source_url}
          </a>
        </p>
      ) : null}

      {/* A posting with no chunks is in the database and invisible to
          retrieval, which is worth saying rather than leaving as a zero. */}
      {document.chunk_count === 0 ? (
        <p role="alert">No chunks: nothing about this posting can be retrieved.</p>
      ) : null}
    </li>
  )
}

/** The knowledge base, and the three ways into it (FR-1). */
export function Documents(): ReactElement {
  const [shown, setShown] = useState(PAGE_SIZE)
  const documents = useDocuments(shown)

  return (
    <>
      <section aria-labelledby="add">
        <h2 id="add">Add a job posting</h2>

        <AddByUrl />

        <details>
          <summary>…or upload a file</summary>
          <AddByFile />
        </details>

        <details>
          <summary>…or paste the text</summary>
          <AddByText />
        </details>
      </section>

      <section aria-labelledby="base">
        <h2 id="base">Knowledge base</h2>
        <p>
          Shared by every account: postings added by anyone are listed here.
        </p>

        {documents.isPending ? <p>Loading…</p> : null}
        {documents.error ? <p role="alert">{documents.error.message}</p> : null}

        {documents.data?.length === 0 ? (
          <p>Nothing in the knowledge base yet.</p>
        ) : null}

        <ul>
          {documents.data?.map((document) => (
            <Posting key={document.id} document={document} />
          ))}
        </ul>

        {/* A short page is the end of the listing: the route returns no total,
            so this is how a caller learns there is nothing more. */}
        {documents.data && documents.data.length >= shown ? (
          shown >= MAX_PAGE_SIZE ? (
            <p>The listing returns at most {MAX_PAGE_SIZE} postings.</p>
          ) : (
            <button
              type="button"
              onClick={() => {
                setShown((current) => Math.min(current + PAGE_SIZE, MAX_PAGE_SIZE))
              }}
            >
              Load more
            </button>
          )
        ) : null}
      </section>
    </>
  )
}
