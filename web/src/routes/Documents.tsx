import { useState } from 'react'
import type { ReactElement, SyntheticEvent } from 'react'
import {
  BriefcaseIcon,
  GitCompareArrowsIcon,
  MessagesSquareIcon,
  PlusIcon,
} from 'lucide-react'
import { Link, useNavigate } from 'react-router'

import type { Document, Ingested } from '../api/documents'
import {
  MAX_PAGE_SIZE,
  PAGE_SIZE,
  useDeleteDocument,
  useDocuments,
  useIngestFile,
  useIngestText,
  useIngestUrl,
} from '../api/documents'
import { useStartInterview } from '../api/interview'
import { useMatch } from '../api/matching'
import { useResumes } from '../api/resumes'
import { useSession } from '../auth/session'
import { ago } from '../time'
import {
  Alert,
  Button,
  EmptyState,
  Field,
  Muted,
  Notice,
  PageHeader,
  Score,
  Sheet,
  Skeleton,
  StageRail,
  Status,
  Thinking,
  reachedOf,
} from '../ui'
import { newest } from './Posting'
import type { Arrival } from './Posting'

const MAX_CONTENT_LENGTH = 200_000
/** Mirrors MAX_CONTENT_LENGTH in app/schemas/document.py, so a paste that
 *  cannot be stored is refused before it is embedded rather than after. */

const UPLOAD_TYPES = '.pdf,.docx,.txt,.md'

const SUMMARY =
  'cursor-pointer text-sm font-medium text-ink-soft hover:text-accent'

/**
 * Open the posting an ingestion stored, or the one it turned out to duplicate.
 *
 * The next step after adding a posting is nearly always matching a CV against
 * it, and that happens on the posting's page. Whether it was already there
 * (FR-1) goes along, so that page can say nothing new was stored.
 */
function useOpenPosting(): (result: Ingested) => void {
  const navigate = useNavigate()

  return (result: Ingested) => {
    const arrival: Arrival = { duplicate: result.duplicate }
    void navigate(`/documents/${result.document.id}`, { state: arrival })
  }
}

/** Why an ingestion failed, in the API's own words. */
function Failure({ error }: { error: Error | null }): ReactElement | null {
  return error ? <Alert>{error.message}</Alert> : null
}

/** The address of a posting: the one way in that asks nothing of the user
 *  but a link they already have open, so it comes first (FR-1). */
function AddByUrl(): ReactElement {
  const [url, setUrl] = useState('')
  const ingest = useIngestUrl()
  const open = useOpenPosting()

  function onSubmit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>): void {
    event.preventDefault()
    ingest.mutate(url.trim(), { onSuccess: open })
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

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={ingest.isPending}>
          Read the posting
        </Button>
        {/* Fetching the page, reading its requirements and embedding it
            takes seconds: a sentence, not a changed label. */}
        {ingest.isPending ? <Thinking>Reading the posting…</Thinking> : null}
      </div>

      <Failure error={ingest.error} />
    </form>
  )
}

function AddByFile(): ReactElement {
  // Keyed so a successful upload empties the control: the value of a file
  // input cannot be set from script, and remounting it is the way to clear it.
  const [generation, setGeneration] = useState(0)
  const [file, setFile] = useState<File | null>(null)
  const ingest = useIngestFile()
  const open = useOpenPosting()

  function onSubmit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>): void {
    event.preventDefault()

    if (!file) {
      return
    }

    ingest.mutate(file, {
      onSuccess: (result) => {
        setFile(null)
        setGeneration((current) => current + 1)
        open(result)
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
            className={`${className} file:mr-3 file:rounded-control file:border-0 file:bg-accent-soft file:px-3 file:py-1 file:text-sm file:text-accent-strong`}
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null)
            }}
          />
        )}
      </Field>

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={ingest.isPending || !file}>
          Upload
        </Button>
        {ingest.isPending ? <Thinking>Reading the file…</Thinking> : null}
      </div>

      <Failure error={ingest.error} />
    </form>
  )
}

function AddByText(): ReactElement {
  const [content, setContent] = useState('')
  const ingest = useIngestText()
  const open = useOpenPosting()
  const tooLong = content.length > MAX_CONTENT_LENGTH

  function onSubmit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>): void {
    event.preventDefault()

    if (tooLong) {
      return
    }

    ingest.mutate(content, { onSuccess: open })
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

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={ingest.isPending || tooLong}>
          Store
        </Button>
        {ingest.isPending ? <Thinking>Storing the posting…</Thinking> : null}
      </div>

      <Failure error={ingest.error} />
    </form>
  )
}

/**
 * Deleting a posting, for administrators (FR-6). Two steps in place rather
 * than window.confirm: the second step says what is lost, and it can be
 * tested and styled like everything else on the page.
 */
function DeletePosting({
  document,
  onDeleted,
}: {
  document: Document
  onDeleted: (name: string) => void
}): ReactElement {
  const [confirming, setConfirming] = useState(false)
  const remove = useDeleteDocument()
  const name = document.title ?? 'Untitled'

  if (!confirming) {
    return (
      <div className="flex flex-col gap-2">
        <div className="flex">
          <Button
            type="button"
            variant="quiet"
            size="sm"
            // Named after the posting: a list of identical "Delete" buttons
            // is one button to a screen reader, repeated.
            aria-label={`Delete ${name}`}
            onClick={() => {
              remove.reset()
              setConfirming(true)
            }}
          >
            Delete
          </Button>
        </div>
        {remove.error ? <Alert>{remove.error.message}</Alert> : null}
      </div>
    )
  }

  return (
    <div
      role="group"
      aria-label={`Confirm deleting ${name}`}
      className="flex flex-col gap-2 rounded-control bg-sunken p-3"
    >
      <p className="text-sm">
        This removes the posting and its chunks for good. Matches already in
        anyone’s history stay, without a link to it.
      </p>
      <div className="flex gap-2">
        <Button
          type="button"
          variant="danger"
          disabled={remove.isPending}
          onClick={() => {
            remove.mutate(document.id, {
              onSuccess: () => {
                onDeleted(name)
              },
              onSettled: () => {
                setConfirming(false)
              },
            })
          }}
        >
          {remove.isPending ? 'Deleting…' : 'Delete for good'}
        </Button>
        <Button
          type="button"
          variant="secondary"
          disabled={remove.isPending}
          onClick={() => {
            setConfirming(false)
          }}
        >
          Cancel
        </Button>
      </div>
    </div>
  )
}


function hostOf(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

function requirements(count: number | null): string {
  if (count === null) {
    return 'requirements not read'
  }

  return count === 1 ? '1 requirement' : `${String(count)} requirements`
}

/** What a row can start, and on which resume. */
interface RowActions {
  resumeId: string | undefined
  busy: boolean
  pending: 'match' | 'practise' | null
  error: Error | null
  onMatch: () => void
  onPractise: () => void
}

/**
 * One posting as a row: what it is, how old, whether it was read, how far you
 * got with it -- and the two things to do with it, right here, on the newest
 * resume.
 *
 * From md the row is a grid, so stages and scores stand in columns and can be
 * compared down the list; below it the parts wrap, with room kept for the
 * title.
 */
function PostingRow({
  document,
  admin,
  actions,
  onDeleted,
}: {
  document: Document
  admin: boolean
  actions: RowActions
  onDeleted: (name: string) => void
}): ReactElement {
  const unread = !document.requirement_count
  const name = document.title ?? 'Untitled'

  return (
    <li className="flex flex-col gap-2 py-3 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 md:grid md:grid-cols-[minmax(0,1fr)_auto_4rem_auto]">
        <div className="min-w-48 flex-1">
          <h3 className="truncate font-bold">
            <Link
              to={`/documents/${document.id}`}
              className="hover:text-accent hover:underline"
            >
              {name}
            </Link>
          </h3>
          <p className="text-sm text-ink-faint">
            {document.source_url ? hostOf(document.source_url) : 'uploaded'}
            {', '}
            <time
              dateTime={document.created_at}
              title={new Date(document.created_at).toLocaleString()}
            >
              {ago(document.created_at)}
            </time>
            {', '}
            {requirements(document.requirement_count)}
          </p>
        </div>

        <StageRail reached={reachedOf(document.stage)} compact />
        <span className="w-16 text-right">
          {document.best_score === null ? (
            <>
              <span aria-hidden="true" className="text-ink-faint">
                —
              </span>
              <span className="sr-only">Not matched yet</span>
            </>
          ) : (
            <Score value={document.best_score} size="sm" />
          )}
        </span>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            type="button"
            size="sm"
            variant="secondary"
            icon={GitCompareArrowsIcon}
            aria-label={`Match my CV with ${name}`}
            disabled={actions.busy || !actions.resumeId}
            onClick={actions.onMatch}
          >
            Match
          </Button>
          <Button
            type="button"
            size="sm"
            variant="secondary"
            icon={MessagesSquareIcon}
            aria-label={`Practise an interview for ${name}`}
            title={unread ? 'Its requirements have not been read yet' : undefined}
            disabled={actions.busy || !actions.resumeId || unread}
            onClick={actions.onPractise}
          >
            Practise
          </Button>
        </div>
      </div>

      {actions.pending === 'match' ? <Thinking>Matching your CV…</Thinking> : null}
      {actions.pending === 'practise' ? (
        <Thinking>Preparing questions…</Thinking>
      ) : null}
      {actions.error ? <Alert>{actions.error.message}</Alert> : null}

      {/* A posting with no chunks is in the database and invisible to
          retrieval, which is worth saying rather than leaving as a zero --
          as a notice, not an error: nothing the reader did failed. */}
      {document.chunk_count === 0 ? (
        <Notice>No chunks: nothing about this posting can be retrieved.</Notice>
      ) : null}

      {admin ? <DeletePosting document={document} onDeleted={onDeleted} /> : null}
    </li>
  )
}

/** The three ways a posting comes in (FR-1), the address first. */
function AddPanel(): ReactElement {
  return (
    <Sheet className="flex max-w-2xl flex-col gap-2">
      <AddByUrl />

      <details className="border-t border-line pt-3">
        <summary className={SUMMARY}>…or upload a file</summary>
        <AddByFile />
      </details>

      <details className="border-t border-line pt-3">
        <summary className={SUMMARY}>…or paste the text</summary>
        <AddByText />
      </details>
    </Sheet>
  )
}

/**
 * The knowledge base as a list you work from: each posting a row with Match and
 * Practise right in it, and adding one behind a button -- open from the start
 * while there is nothing to list.
 */
export function Documents(): ReactElement {
  const [shown, setShown] = useState(PAGE_SIZE)
  const documents = useDocuments(shown)
  const listed = documents.data ?? []
  // A convenience, not a guard: the API refuses a non-administrator anyway.
  const admin = useSession().data?.is_admin === true
  // The last deletion, said once over the list: the row just disappears, and
  // a row that vanishes without a word reads as a glitch. Replaced by the next.
  const [deleted, setDeleted] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const empty = documents.isSuccess && listed.length === 0
  const panelOpen = adding || empty

  // Only asked for once there is a row to act on: an empty base has nothing
  // to match, and the request would be one more thing to wait for.
  const resumes = useResumes(listed.length > 0)
  const resumeId = newest(resumes.data ?? [])?.id
  const match = useMatch()
  const start = useStartInterview()
  const navigate = useNavigate()
  const busy = match.isPending || start.isPending

  function actionsFor(document: Document): RowActions {
    const matchHere = match.variables?.documentId === document.id
    const startHere = start.variables?.documentId === document.id

    return {
      resumeId,
      busy,
      pending:
        match.isPending && matchHere
          ? 'match'
          : start.isPending && startHere
            ? 'practise'
            : null,
      error: (matchHere ? match.error : null) ?? (startHere ? start.error : null),
      onMatch: () => {
        if (resumeId) {
          start.reset()
          match.mutate(
            { resumeId, documentId: document.id },
            {
              onSuccess: (result) => {
                void navigate(`/matches/${result.id}`)
              },
            },
          )
        }
      },
      onPractise: () => {
        if (resumeId) {
          match.reset()
          start.mutate(
            { resumeId, documentId: document.id },
            {
              onSuccess: (interview) => {
                void navigate(`/interviews/${interview.id}`)
              },
            },
          )
        }
      },
    }
  }

  return (
    <>
      <PageHeader
        title="Postings"
        description="Shared by every account: postings added by anyone are listed here."
        actions={
          <Button
            type="button"
            icon={PlusIcon}
            aria-expanded={panelOpen}
            aria-controls="add-posting"
            onClick={() => {
              setAdding((open) => !open)
            }}
          >
            Add posting
          </Button>
        }
      />

      {panelOpen ? (
        <section id="add-posting" aria-label="Add a job posting">
          <AddPanel />
        </section>
      ) : null}

      {deleted ? <Status>Posting deleted: {deleted}.</Status> : null}

      {resumes.isSuccess && resumes.data.length === 0 ? (
        <Notice>
          Matching and practising use your resume.{' '}
          <Link to="/resumes" className="text-accent underline underline-offset-2">
            Add a resume first
          </Link>
          .
        </Notice>
      ) : null}

      {documents.isPending ? (
        <Skeleton lines={4} label="Loading the knowledge base…" />
      ) : null}
      {documents.error ? (
        <Alert
          onRetry={() => {
            void documents.refetch()
          }}
        >
          {documents.error.message}
        </Alert>
      ) : null}

      {empty ? (
        <EmptyState
          icon={BriefcaseIcon}
          title="The knowledge base is empty."
          action={
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={() => {
                window.document.getElementById('posting-url')?.focus()
              }}
            >
              Add the first posting
            </Button>
          }
        >
          Add a job posting by its address, a file or pasted text.
        </EmptyState>
      ) : null}

      {listed.length > 0 ? (
        <Sheet>
          <ul aria-label="Postings" className="flex flex-col divide-y divide-line">
            {listed.map((document) => (
              <PostingRow
                key={document.id}
                document={document}
                admin={admin}
                actions={actionsFor(document)}
                onDeleted={setDeleted}
              />
            ))}
          </ul>
        </Sheet>
      ) : null}

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
                setShown((current) => Math.min(current + PAGE_SIZE, MAX_PAGE_SIZE))
              }}
            >
              Load more
            </Button>
          </div>
        )
      ) : null}
    </>
  )
}
