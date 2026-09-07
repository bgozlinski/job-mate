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
import { Alert, Button, Card, Field, Muted, PageTitle, Status } from '../ui'

const MAX_CONTENT_LENGTH = 200_000
/** Mirrors MAX_CONTENT_LENGTH in app/schemas/document.py, so a paste that
 *  cannot be stored is refused before it is embedded rather than after. */

const UPLOAD_TYPES = '.pdf,.docx,.txt,.md'

const SUMMARY =
  'cursor-pointer text-sm font-medium text-ink-soft hover:text-accent'

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
    return <Alert>{error.message}</Alert>
  }

  if (!result) {
    return null
  }

  return (
    <Status>
      {result.duplicate
        ? `Already in the knowledge base as ${result.document.id}.`
        : `Stored as ${result.document.id} (${chunks(result.document.chunk_count)}).`}
    </Status>
  )
}

/** The address of a posting: the one way in that asks nothing of the user
 *  but a link they already have open, so it comes first (FR-1). */
function AddByUrl(): ReactElement {
  const [url, setUrl] = useState('')
  const ingest = useIngestUrl()

  function onSubmit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>): void {
    event.preventDefault()
    ingest.mutate(url.trim(), {
      onSuccess: () => {
        setUrl('')
      },
    })
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3">
      <Field id="posting-url" label="Job posting URL">
        {(className, id) => (
          <input
            id={id}
            type="url"
            required
            placeholder="https://justjoin.it/job-offer/..."
            className={className}
            value={url}
            onChange={(event) => {
              setUrl(event.target.value)
            }}
          />
        )}
      </Field>

      <div className="flex">
        <Button type="submit" disabled={ingest.isPending}>
          {ingest.isPending ? 'Reading the posting…' : 'Read the posting'}
        </Button>
      </div>

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
    <form onSubmit={onSubmit} className="flex flex-col gap-3 pt-3">
      <Field
        id={`posting-file-${String(generation)}`}
        label="Job posting file (PDF, DOCX or text)"
      >
        {(className, id) => (
          <input
            id={id}
            key={generation}
            type="file"
            accept={UPLOAD_TYPES}
            // Deliberately not `required`. The submit button is disabled until
            // a file is chosen and onSubmit returns without one, so it adds no
            // guarantee -- and jsdom's constraint validation does not see files
            // set by a test, so with it the form silently never submits and the
            // upload path cannot be covered at all.
            className={`${className} file:mr-3 file:rounded-md file:border-0 file:bg-accent-soft file:px-3 file:py-1 file:text-sm file:text-accent-strong`}
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null)
            }}
          />
        )}
      </Field>

      <div className="flex">
        <Button type="submit" disabled={ingest.isPending || !file}>
          {ingest.isPending ? 'Reading the file…' : 'Upload'}
        </Button>
      </div>

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

    ingest.mutate(content, {
      onSuccess: () => {
        setContent('')
      },
    })
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3 pt-3">
      <Field id="posting-text" label="Job posting text">
        {(className, id) => (
          <textarea
            id={id}
            rows={10}
            required
            className={`${className} font-mono text-xs`}
            value={content}
            onChange={(event) => {
              setContent(event.target.value)
            }}
          />
        )}
      </Field>

      {tooLong ? (
        <Alert>
          The text is longer than {MAX_CONTENT_LENGTH.toLocaleString('en')}{' '}
          characters.
        </Alert>
      ) : null}

      <div className="flex">
        <Button type="submit" disabled={ingest.isPending || tooLong}>
          {ingest.isPending ? 'Storing…' : 'Store'}
        </Button>
      </div>

      <Outcome result={ingest.data} error={ingest.error} />
    </form>
  )
}

function Posting({ document }: { document: Document }): ReactElement {
  const stored = new Date(document.created_at)

  return (
    <li>
      <Card className="flex flex-col gap-1">
        <h3 className="font-medium">{document.title ?? 'Untitled'}</h3>
        <p className="text-sm text-ink-faint">
          <time dateTime={document.created_at}>{stored.toLocaleString()}</time>
          {' · '}
          <span>{chunks(document.chunk_count)}</span>
        </p>

        {document.source_url ? (
          <p className="truncate text-sm">
            <a
              href={document.source_url}
              target="_blank"
              rel="noreferrer"
              className="text-accent hover:underline"
            >
              {document.source_url}
            </a>
          </p>
        ) : null}

        {/* A posting with no chunks is in the database and invisible to
            retrieval, which is worth saying rather than leaving as a zero. */}
        {document.chunk_count === 0 ? (
          <Alert>No chunks: nothing about this posting can be retrieved.</Alert>
        ) : null}
      </Card>
    </li>
  )
}

/** The knowledge base, and the three ways into it (FR-1). */
export function Documents(): ReactElement {
  const [shown, setShown] = useState(PAGE_SIZE)
  const documents = useDocuments(shown)

  return (
    <>
      <section aria-labelledby="add" className="flex flex-col gap-4">
        <PageTitle>
          <span id="add">Add a job posting</span>
        </PageTitle>

        <Card className="flex max-w-2xl flex-col gap-2">
          <AddByUrl />

          <details className="border-t border-line pt-3">
            <summary className={SUMMARY}>…or upload a file</summary>
            <AddByFile />
          </details>

          <details className="border-t border-line pt-3">
            <summary className={SUMMARY}>…or paste the text</summary>
            <AddByText />
          </details>
        </Card>
      </section>

      <section aria-labelledby="base" className="flex flex-col gap-4">
        <div>
          <PageTitle>
            <span id="base">Knowledge base</span>
          </PageTitle>
          <Muted>
            Shared by every account: postings added by anyone are listed here.
          </Muted>
        </div>

        {documents.isPending ? <Muted>Loading…</Muted> : null}
        {documents.error ? <Alert>{documents.error.message}</Alert> : null}

        {documents.data?.length === 0 ? (
          <Muted>Nothing in the knowledge base yet.</Muted>
        ) : null}

        <ul className="grid gap-3 sm:grid-cols-2">
          {documents.data?.map((document) => (
            <Posting key={document.id} document={document} />
          ))}
        </ul>

        {/* A short page is the end of the listing: the route returns no total,
            so this is how a caller learns there is nothing more. */}
        {documents.data && documents.data.length >= shown ? (
          shown >= MAX_PAGE_SIZE ? (
            <Muted>The listing returns at most {MAX_PAGE_SIZE} postings.</Muted>
          ) : (
            <div className="flex">
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setShown((current) =>
                    Math.min(current + PAGE_SIZE, MAX_PAGE_SIZE),
                  )
                }}
              >
                Load more
              </Button>
            </div>
          )
        ) : null}
      </section>
    </>
  )
}
