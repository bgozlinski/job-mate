import { useState } from 'react'
import type { ReactElement, ReactNode, SyntheticEvent } from 'react'
import {
  BriefcaseIcon,
  GitCompareArrowsIcon,
  MessagesSquareIcon,
  PlusIcon,
  Trash2Icon,
} from 'lucide-react'
import { Link, useNavigate, useSearchParams } from 'react-router'

import type { Document, Imported, Ingested } from '../api/documents'
import {
  pageCount,
  useApply,
  useDeleteDocument,
  useDocuments,
  useIngestFile,
  useIngestText,
  useImportSearch,
  useIngestUrl,
  useWithdraw,
} from '../api/documents'
import { useStartInterview } from '../api/interview'
import { useMatch } from '../api/matching'
import { useResumes } from '../api/resumes'
import type { Resume } from '../api/resumes'
import { day, dayOf, today } from '../time'
import {
  Alert,
  Button,
  EmptyState,
  Field,
  Notice,
  GoToPage,
  PageSize,
  Pagination,
  PageHeader,
  Score,
  Sheet,
  Skeleton,
  StageRail,
  Status,
  Thinking,
  pageFrom,
  pageKeeping,
  pagedSearch,
  reachedOf,
  sizeFrom,
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

/** How an import from a search went, in one sentence. */
function importSummary(result: Imported): string {
  if (result.added === 0 && result.failed.length === 0 && !result.stopped) {
    return result.known === 1
      ? 'Nothing new: the one posting listed is already here.'
      : `Nothing new: all ${String(result.known)} postings listed are already here.`
  }

  const added = result.added === 1 ? '1 new posting' : `${String(result.added)} new postings`

  if (result.known === 0) {
    return `Added ${added}.`
  }

  return result.known === 1
    ? `Added ${added}; 1 was already here.`
    : `Added ${added}; ${String(result.known)} were already here.`
}

/** The last part of a posting address: enough to tell which one failed. */
function slugOf(url: string): string {
  return url.split('/').filter(Boolean).pop() ?? url
}

/**
 * A search you filtered on the board, pasted as its address: every posting on
 * its first page that you do not have yet is added, one after another (FR-1).
 * Pasting the same search again adds only what appeared since.
 */
function AddBySearch(): ReactElement {
  const [url, setUrl] = useState('')
  const { mutation: importing, progress } = useImportSearch()
  const result = importing.data

  function onSubmit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>): void {
    event.preventDefault()
    importing.mutate(url.trim())
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3 pt-3">
      <Field
        id="search-url"
        label="Search results URL"
        hint="The first page of results is read once; postings you already have are skipped."
      >
        {(className, id) => (
          <input
            id={id}
            type="url"
            required
            placeholder="https://justjoin.it/job-offers/all-locations/python?..."
            className={className}
            value={url}
            onChange={(event) => {
              setUrl(event.target.value)
            }}
          />
        )}
      </Field>

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={importing.isPending}>
          Import new postings
        </Button>
        {importing.isPending ? (
          <Thinking>
            {progress
              ? `Adding ${String(progress.done + 1)} of ${String(progress.total)}…`
              : 'Reading the search…'}
          </Thinking>
        ) : null}
      </div>

      {importing.error ? <Alert>{importing.error.message}</Alert> : null}
      {result ? <Status>{importSummary(result)}</Status> : null}
      {result?.stopped ? (
        <Alert>
          {result.stopped}. {result.skipped} left: import the same search again
          later to add them.
        </Alert>
      ) : null}
      {result && result.failed.length > 0 ? (
        <Alert>
          Could not add {result.failed.length === 1 ? '1 posting' : `${String(result.failed.length)} postings`}:
          <ul className="mt-1 list-disc pl-5">
            {result.failed.map((failure) => (
              <li key={failure.url}>
                {slugOf(failure.url)}: {failure.reason}
              </li>
            ))}
          </ul>
        </Alert>
      ) : null}
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

/** A cell with nothing in it: a dash to the eye, words to a screen reader. */
function Missing({ said }: { said: string }): ReactElement {
  return (
    <>
      <span aria-hidden="true" className="text-ink-faint">
        —
      </span>
      <span className="sr-only">{said}</span>
    </>
  )
}

function hostOf(url: string): string {
  try {
    return new URL(url).host
  } catch {
    return url
  }
}

/** Where and how the job is done, as far as anyone said: "Warszawa, remote". */
function locationOf(document: Document): string | null {
  const said = [document.city, document.work_mode].filter(Boolean)

  return said.length > 0 ? said.join(', ') : null
}

function resumeName(resume: { original_filename?: string | null }): string {
  return resume.original_filename ?? 'Pasted text'
}

const COLUMNS = [
  'Company',
  'Role',
  'Location',
  'Link',
  'Posted',
  'Added',
  'Applied',
  'Resume',
] as const

/**
 * One cell of the register. Below lg the table becomes a stack of entries,
 * and each cell carries its column's name before its value, since the header
 * row is no longer where the eye can find it.
 */
function Cell({
  label,
  className = '',
  children,
}: {
  label?: (typeof COLUMNS)[number]
  className?: string
  children: ReactNode
}): ReactElement {
  return (
    <td
      data-label={label}
      className={
        'align-top lg:py-3 lg:pr-4 ' +
        (label
          ? 'max-lg:grid max-lg:grid-cols-[6rem_minmax(0,1fr)] max-lg:gap-2 max-lg:before:text-ink-faint max-lg:before:content-[attr(data-label)] '
          : '') +
        className
      }
    >
      {children}
    </td>
  )
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
 * Recording an application, or changing or taking back one already recorded:
 * the day (today where you are, unless you say otherwise) and the resume that
 * went out (the main one, unless you pick another).
 */
function ApplicationForm({
  document,
  resumes,
  onClose,
}: {
  document: Document
  resumes: Resume[]
  onClose: () => void
}): ReactElement {
  const name = document.title ?? 'Untitled'
  const applied = document.applied_on !== null
  const [appliedOn, setAppliedOn] = useState(document.applied_on ?? today())
  const [resumeId, setResumeId] = useState(
    document.applied_resume?.id ?? newest(resumes)?.id ?? '',
  )
  const apply = useApply()
  const withdraw = useWithdraw()
  const busy = apply.isPending || withdraw.isPending

  function onSubmit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>): void {
    event.preventDefault()
    apply.mutate(
      { documentId: document.id, appliedOn, resumeId },
      { onSuccess: onClose },
    )
  }

  if (resumes.length === 0) {
    return (
      <Notice>
        An application names the resume you sent.{' '}
        <Link to="/resumes" className="text-accent underline underline-offset-2">
          Add a resume first
        </Link>
        .
      </Notice>
    )
  }

  return (
    <form
      aria-label={`Application to ${name}`}
      onSubmit={onSubmit}
      className="flex flex-col gap-3 rounded-control bg-sunken p-3"
    >
      <div className="flex flex-wrap items-end gap-3">
        <Field id={`applied-on-${document.id}`} label="Applied on">
          {(className, id) => (
            <input
              id={id}
              type="date"
              required
              max={today()}
              className={`${className} w-auto tabular-nums`}
              value={appliedOn}
              onChange={(event) => {
                setAppliedOn(event.target.value)
              }}
            />
          )}
        </Field>
        <Field id={`applied-resume-${document.id}`} label="With resume">
          {(className, id) => (
            <select
              id={id}
              required
              className={`${className} w-auto`}
              value={resumeId}
              onChange={(event) => {
                setResumeId(event.target.value)
              }}
            >
              {resumes.map((resume) => (
                <option key={resume.id} value={resume.id}>
                  {resumeName(resume)}
                  {resume.target_role ? ` — ${resume.target_role}` : ''}
                </option>
              ))}
            </select>
          )}
        </Field>
      </div>

      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="sm" disabled={busy}>
          {apply.isPending ? 'Saving…' : 'Save'}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={busy}
          onClick={onClose}
        >
          Cancel
        </Button>
        {applied ? (
          <Button
            type="button"
            size="sm"
            variant="quiet"
            disabled={busy}
            onClick={() => {
              withdraw.mutate(document.id, { onSuccess: onClose })
            }}
          >
            {withdraw.isPending ? 'Taking back…' : 'Not applied after all'}
          </Button>
        ) : null}
      </div>

      {apply.error ? <Alert>{apply.error.message}</Alert> : null}
      {withdraw.error ? <Alert>{withdraw.error.message}</Alert> : null}
    </form>
  )
}

/**
 * Deleting one of your postings (FR-6). Two steps in place rather than
 * window.confirm: the second step says what is lost, and it can be tested and
 * styled like everything else on the page.
 */
function ConfirmDelete({
  document,
  onDeleted,
  onClose,
}: {
  document: Document
  onDeleted: (name: string) => void
  onClose: () => void
}): ReactElement {
  const remove = useDeleteDocument()
  const name = document.title ?? 'Untitled'

  return (
    <div
      role="group"
      aria-label={`Confirm deleting ${name}`}
      className="flex flex-col gap-2 rounded-control bg-sunken p-3"
    >
      <p className="text-sm">
        This removes the posting and its chunks for good. Your matches stay in
        your history, without a link to it.
      </p>
      <div className="flex gap-2">
        <Button
          type="button"
          size="sm"
          variant="danger"
          disabled={remove.isPending}
          onClick={() => {
            remove.mutate(document.id, {
              onSuccess: () => {
                onDeleted(name)
              },
            })
          }}
        >
          {remove.isPending ? 'Deleting…' : 'Delete for good'}
        </Button>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          disabled={remove.isPending}
          onClick={onClose}
        >
          Cancel
        </Button>
      </div>
      {remove.error ? <Alert>{remove.error.message}</Alert> : null}
    </div>
  )
}

/**
 * One posting as an entry in the register: who, what, where it was published
 * and when, when you added it, and when you applied and with what. The day of
 * an application is drawn as a stamp -- the one mark on the page that says a
 * thing was sent.
 *
 * Its own tbody, because what opens under it -- the application form, the
 * confirmation of a delete, a wait or a failure -- is a second row that
 * belongs to it.
 */
function RegisterEntry({
  document,
  resumes,
  actions,
  onDeleted,
}: {
  document: Document
  resumes: Resume[]
  actions: RowActions
  onDeleted: (name: string) => void
}): ReactElement {
  const [open, setOpen] = useState<'application' | 'delete' | null>(null)
  const unread = !document.requirement_count
  const name = document.title ?? 'Untitled'
  const close = (): void => {
    setOpen(null)
  }
  const toggle = (what: 'application' | 'delete'): void => {
    setOpen(open === what ? null : what)
  }
  const underneath =
    open !== null ||
    actions.pending !== null ||
    actions.error !== null ||
    document.chunk_count === 0

  return (
    <tbody className="border-b border-line last:border-b-0 max-lg:block max-lg:py-4 max-lg:first:pt-0 max-lg:last:pb-0">
      <tr className="max-lg:flex max-lg:flex-col max-lg:gap-1.5">
        <Cell label="Company" className="lg:max-w-40">
          {document.company ?? <Missing said="not stated" />}
        </Cell>
        <Cell className="max-lg:order-first lg:min-w-48">
          <Link
            to={`/documents/${document.id}`}
            className="font-bold text-ink hover:text-accent hover:underline"
          >
            {document.role ?? name}
          </Link>
          <span className="mt-1 flex items-center gap-2 text-xs text-ink-faint">
            <StageRail reached={reachedOf(document.stage)} compact />
            {document.best_score === null ? null : (
              <Score value={document.best_score} size="sm" />
            )}
            {document.requirement_count === null ? 'requirements not read' : null}
          </span>
        </Cell>
        <Cell label="Location" className="lg:max-w-40">
          {locationOf(document) ?? <Missing said="not stated" />}
        </Cell>
        <Cell label="Link">
          {document.source_url ? (
            <a
              href={document.source_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent underline-offset-2 hover:underline"
            >
              {hostOf(document.source_url)}
              <span className="sr-only"> (opens in a new tab)</span>
            </a>
          ) : (
            <Missing said="no link" />
          )}
        </Cell>
        <Cell label="Posted" className="whitespace-nowrap tabular-nums">
          {document.posted_on ? (
            <time dateTime={document.posted_on}>{day(document.posted_on)}</time>
          ) : (
            <Missing said="not stated" />
          )}
        </Cell>
        <Cell label="Added" className="whitespace-nowrap tabular-nums">
          <time
            dateTime={document.created_at}
            title={new Date(document.created_at).toLocaleString()}
          >
            {dayOf(document.created_at)}
          </time>
        </Cell>
        <Cell label="Applied" className="whitespace-nowrap">
          {document.applied_on ? (
            <span>
              <button
                type="button"
                aria-label={`Applied ${day(document.applied_on)}: change the application to ${name}`}
                aria-expanded={open === 'application'}
                onClick={() => {
                  toggle('application')
                }}
                className="inline-block -rotate-[1.5deg] rounded-control border-2 border-accent px-1.5 py-0.5 text-sm font-bold tabular-nums text-accent hover:bg-accent-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                <time dateTime={document.applied_on}>{day(document.applied_on)}</time>
              </button>
            </span>
          ) : (
            <span>
              <Button
                type="button"
                size="sm"
                variant="secondary"
                aria-label={`Mark ${name} as applied`}
                aria-expanded={open === 'application'}
                onClick={() => {
                  toggle('application')
                }}
              >
                Mark as applied
              </Button>
            </span>
          )}
        </Cell>
        <Cell label="Resume" className="lg:max-w-40">
          {document.applied_resume ? (
            <span
              className="block truncate"
              title={document.applied_resume.target_role ?? undefined}
            >
              {resumeName(document.applied_resume)}
            </span>
          ) : document.applied_on ? (
            <span className="text-ink-faint italic">deleted resume</span>
          ) : (
            <Missing said="not applied" />
          )}
        </Cell>
        <Cell className="max-lg:pt-1 lg:pr-0">
          <div className="flex items-center gap-1 lg:justify-end">
            <Button
              type="button"
              size="sm"
              variant="secondary"
              icon={GitCompareArrowsIcon}
              aria-label={`Match my CV with ${name}`}
              title="Match my CV"
              disabled={actions.busy || !actions.resumeId}
              onClick={actions.onMatch}
            >
              <span className="lg:sr-only">Match</span>
            </Button>
            <Button
              type="button"
              size="sm"
              variant="secondary"
              icon={MessagesSquareIcon}
              aria-label={`Practise an interview for ${name}`}
              title={
                unread ? 'Its requirements have not been read yet' : 'Practise an interview'
              }
              disabled={actions.busy || !actions.resumeId || unread}
              onClick={actions.onPractise}
            >
              <span className="lg:sr-only">Practise</span>
            </Button>
            <Button
              type="button"
              size="sm"
              variant="quiet"
              icon={Trash2Icon}
              // Named after the posting: a list of identical "Delete" buttons
              // is one button to a screen reader, repeated.
              aria-label={`Delete ${name}`}
              title="Delete"
              aria-expanded={open === 'delete'}
              onClick={() => {
                toggle('delete')
              }}
            >
              <span className="lg:sr-only">Delete</span>
            </Button>
          </div>
        </Cell>
      </tr>

      {underneath ? (
        <tr className="max-lg:block">
          <td
            colSpan={COLUMNS.length + 1}
            className="pb-3 max-lg:block max-lg:pt-3"
          >
            <div className="flex flex-col gap-2">
              {open === 'application' ? (
                <ApplicationForm document={document} resumes={resumes} onClose={close} />
              ) : null}
              {open === 'delete' ? (
                <ConfirmDelete document={document} onDeleted={onDeleted} onClose={close} />
              ) : null}
              {actions.pending === 'match' ? (
                <Thinking>Matching your CV…</Thinking>
              ) : null}
              {actions.pending === 'practise' ? (
                <Thinking>Preparing questions…</Thinking>
              ) : null}
              {actions.error ? <Alert>{actions.error.message}</Alert> : null}
              {/* A posting with no chunks is in the database and invisible to
                  retrieval, which is worth saying rather than leaving as a zero
                  -- as a notice, not an error: nothing the reader did failed. */}
              {document.chunk_count === 0 ? (
                <Notice>No chunks: nothing about this posting can be retrieved.</Notice>
              ) : null}
            </div>
          </td>
        </tr>
      ) : null}
    </tbody>
  )
}

/** The register's column names: read by a screen reader, drawn from lg up. */
function RegisterHead(): ReactElement {
  return (
    <thead className="max-lg:sr-only">
      <tr className="border-b border-line text-left text-xs text-ink-faint">
        {COLUMNS.map((column) => (
          <th key={column} scope="col" className="pr-4 pb-2 font-semibold">
            {column}
          </th>
        ))}
        <th scope="col" className="pb-2">
          <span className="sr-only">Actions</span>
        </th>
      </tr>
    </thead>
  )
}

/** The three ways a posting comes in (FR-1), the address first. */
function AddPanel(): ReactElement {
  return (
    <Sheet className="flex max-w-2xl flex-col gap-2">
      <AddByUrl />

      <details className="border-t border-line pt-3">
        <summary className={SUMMARY}>…or import a whole search</summary>
        <AddBySearch />
      </details>

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

/** The address of one page of the postings, at one size: the defaults are bare. */
function pageHref(page: number, size: number): string {
  return `/documents${pagedSearch(page, size)}`
}

/**
 * Your postings as a register you work from: each one a row with where it was
 * published, when you added it and when you applied with which resume, Match
 * and Practise right in it, and adding one behind a button -- open from the
 * start while there is nothing to list. A numbered page at a time, the page in
 * the address.
 */
export function Documents(): ReactElement {
  const [params] = useSearchParams()
  const page = pageFrom(params.get('page'))
  const size = sizeFrom(params.get('size'))
  const documents = useDocuments(page, size)
  const listed = documents.data?.items ?? []
  const total = documents.data?.total ?? 0
  const pages = pageCount(total, size)
  // The last deletion, said once over the list: the row just disappears, and
  // a row that vanishes without a word reads as a glitch. Replaced by the next.
  const [deleted, setDeleted] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const empty = documents.isSuccess && total === 0
  // A page number past the end: typed in, or the last row of the last page
  // deleted. The postings are there, just not on this page.
  const pastEnd = documents.isSuccess && total > 0 && listed.length === 0
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
        description="Every posting you added, and when you applied to it."
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
        <Skeleton lines={4} label="Loading your postings…" />
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
          title="No postings yet."
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
          <table aria-label="Postings" className="w-full text-sm max-lg:block">
            <RegisterHead />
            {listed.map((document) => (
              <RegisterEntry
                key={document.id}
                document={document}
                resumes={resumes.data ?? []}
                actions={actionsFor(document)}
                onDeleted={setDeleted}
              />
            ))}
          </table>
        </Sheet>
      ) : null}

      {pastEnd ? (
        <Notice>
          There is no page {page}: your postings fill {pages === 1 ? '1 page' : `${String(pages)} pages`}.{' '}
          <Link to={pageHref(pages, size)} className="text-accent underline underline-offset-2">
            Go to the last page
          </Link>
          .
        </Notice>
      ) : null}

      <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-2">
        <Pagination
          page={page}
          count={pages}
          hrefFor={(n) => pageHref(n, size)}
          label="Pages of postings"
        />
        <PageSize
          id="postings-page-size"
          size={size}
          total={total}
          onChange={(next) => {
            void navigate(pageHref(pageKeeping(page, size, next), next))
          }}
        />
        <GoToPage id="postings-go-to" count={pages} hrefFor={(n) => pageHref(n, size)} />
      </div>
    </>
  )
}
