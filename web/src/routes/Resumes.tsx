import { useState } from 'react'
import type { ReactElement, SyntheticEvent } from 'react'
import { FileTextIcon } from 'lucide-react'

import { saveFile } from '../api/download'
import type { ExportFormat, Resume } from '../api/resumes'
import {
  MAX_RESUME_LENGTH,
  MAX_TARGET_ROLE_LENGTH,
  useCreateResume,
  useDeleteResume,
  useExportResume,
  useResumes,
  useUploadResume,
} from '../api/resumes'
import {
  Alert,
  Button,
  Card,
  EmptyState,
  Field,
  Muted,
  PageTitle,
  Skeleton,
  Status,
  Thinking,
} from '../ui'

const UPLOAD_TYPES = '.pdf,.docx,.txt,.md'

const EXPORTS: { format: ExportFormat; label: string }[] = [
  { format: 'pdf', label: 'PDF' },
  { format: 'docx', label: 'Word' },
  { format: 'md', label: 'Markdown' },
]

const SUMMARY =
  'cursor-pointer text-sm font-medium text-ink-soft hover:text-accent'

function TargetRole({
  id,
  value,
  onChange,
}: {
  id: string
  value: string
  onChange: (next: string) => void
}): ReactElement {
  return (
    <Field id={id} label="Target role (optional)">
      {(className, fieldId) => (
        <input
          id={fieldId}
          type="text"
          maxLength={MAX_TARGET_ROLE_LENGTH}
          placeholder="Backend developer"
          className={className}
          value={value}
          onChange={(event) => {
            onChange(event.target.value)
          }}
        />
      )}
    </Field>
  )
}

function AddByFile(): ReactElement {
  // Keyed so a successful upload empties the control: the value of a file
  // input cannot be set from script, and remounting it is the way to clear it.
  const [generation, setGeneration] = useState(0)
  const [file, setFile] = useState<File | null>(null)
  const [targetRole, setTargetRole] = useState('')
  const upload = useUploadResume()

  function onSubmit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>): void {
    event.preventDefault()

    if (!file) {
      return
    }

    upload.mutate(
      { file, targetRole },
      {
        onSuccess: () => {
          setFile(null)
          setTargetRole('')
          setGeneration((current) => current + 1)
        },
      },
    )
  }

  return (
    // Named so the two forms on this page are distinguishable: both carry a
    // "Target role" field, and an unnamed form is not a landmark, so a screen
    // reader would announce the same label twice with nothing to tell them
    // apart.
    <form
      aria-label="Upload a resume"
      onSubmit={onSubmit}
      className="flex flex-col gap-3"
    >
      <Field
        id={`resume-file-${String(generation)}`}
        label="Resume file (PDF, DOCX or text)"
      >
        {(className, id) => (
          <input
            id={id}
            key={generation}
            type="file"
            accept={UPLOAD_TYPES}
            // Deliberately not `required`: the button below is disabled without
            // a file, and jsdom's constraint validation does not see files set
            // by a test, so the attribute would make this path untestable.
            className={`${className} file:mr-3 file:rounded-md file:border-0 file:bg-accent-soft file:px-3 file:py-1 file:text-sm file:text-accent-strong`}
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null)
            }}
          />
        )}
      </Field>

      <TargetRole
        id={`resume-file-role-${String(generation)}`}
        value={targetRole}
        onChange={setTargetRole}
      />

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={upload.isPending || !file}>
          Upload
        </Button>
        {/* Reading a file and the skills in it takes a model call: seconds,
            not a blink, so it gets a sentence rather than a changed label. */}
        {upload.isPending ? <Thinking>Reading the resume…</Thinking> : null}
      </div>

      {upload.error ? <Alert>{upload.error.message}</Alert> : null}
    </form>
  )
}

function AddByText(): ReactElement {
  const [content, setContent] = useState('')
  const [targetRole, setTargetRole] = useState('')
  const create = useCreateResume()
  const tooLong = content.length > MAX_RESUME_LENGTH

  function onSubmit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>): void {
    event.preventDefault()

    if (tooLong) {
      return
    }

    create.mutate(
      { content, targetRole },
      {
        onSuccess: () => {
          setContent('')
          setTargetRole('')
        },
      },
    )
  }

  return (
    <form
      aria-label="Paste a resume"
      onSubmit={onSubmit}
      className="flex flex-col gap-3 pt-3"
    >
      <Field id="resume-text" label="Resume text">
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

      <TargetRole id="resume-text-role" value={targetRole} onChange={setTargetRole} />

      {tooLong ? (
        <Alert>
          The text is longer than {MAX_RESUME_LENGTH.toLocaleString('en')}{' '}
          characters.
        </Alert>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={create.isPending || tooLong}>
          Save
        </Button>
        {create.isPending ? <Thinking>Saving your resume…</Thinking> : null}
      </div>

      {create.error ? <Alert>{create.error.message}</Alert> : null}
    </form>
  )
}

/**
 * Take a resume away as a file (FR-5). The version downloaded is the one
 * stored: an improved resume is a version its owner wrote, and exporting only
 * converts it.
 */
function Download({ resume, name }: { resume: Resume; name: string }): ReactElement {
  const download = useExportResume()

  return (
    <div className="flex flex-col gap-2">
      <div
        role="group"
        aria-label={`Download ${name}`}
        className="flex flex-wrap items-center gap-2"
      >
        <span className="text-sm text-ink-faint">Download:</span>
        {EXPORTS.map(({ format, label }) => (
          <Button
            key={format}
            type="button"
            variant="secondary"
            disabled={download.isPending}
            // The format alone would be three identical "PDF" buttons per
            // list to a screen reader, one for every resume on the page.
            aria-label={`Download ${name} as ${label}`}
            onClick={() => {
              download.mutate(
                { id: resume.id, format },
                {
                  onSuccess: ({ blob, filename }) => {
                    saveFile(blob, filename)
                  },
                },
              )
            }}
          >
            {label}
          </Button>
        ))}
      </div>

      {download.error ? <Alert>{download.error.message}</Alert> : null}
    </div>
  )
}

function Stored({
  resume,
  onDeleted,
}: {
  resume: Resume
  onDeleted: (name: string) => void
}): ReactElement {
  const [confirming, setConfirming] = useState(false)
  const remove = useDeleteResume()
  const created = new Date(resume.created_at)
  const name = resume.original_filename ?? 'Pasted text'

  return (
    <li>
      <Card className="flex flex-col gap-2">
        <h3 className="font-medium">{name}</h3>
        <p className="text-sm text-ink-faint">
          <time dateTime={resume.created_at}>{created.toLocaleString()}</time>
          {' · '}
          <span>{resume.target_role ?? 'no target role'}</span>
          {' · '}
          <span>{resume.content.length.toLocaleString('en')} characters</span>
        </p>

        {/* Behind a click on purpose: a resume can be a hundred thousand
            characters, and drawing every one of them for every row makes the
            page crawl by the third one. */}
        <details>
          <summary className={SUMMARY}>Show text</summary>
          <pre className="mt-2 max-h-72 overflow-auto rounded-lg bg-surface p-3 font-mono text-xs whitespace-pre-wrap text-ink-soft">
            {resume.content}
          </pre>
        </details>

        <Download resume={resume} name={name} />

        {/* Two presses rather than a native confirm(): deleting is the one
            irreversible thing on this page, and window.confirm is a dialog
            jsdom does not implement, so a guard built on it could not be
            covered by a test. */}
        <div className="flex gap-2">
          {confirming ? (
            <>
              <Button
                type="button"
                variant="danger"
                disabled={remove.isPending}
                onClick={() => {
                  remove.mutate(resume.id, {
                    onSuccess: () => {
                      onDeleted(name)
                    },
                  })
                }}
              >
                {remove.isPending ? 'Deleting…' : `Really delete ${name}`}
              </Button>
              <Button
                type="button"
                variant="secondary"
                onClick={() => {
                  setConfirming(false)
                }}
              >
                Cancel
              </Button>
            </>
          ) : (
            <Button
              type="button"
              variant="quiet"
              onClick={() => {
                setConfirming(true)
              }}
            >
              Delete {name}
            </Button>
          )}
        </div>

        {remove.error ? <Alert>{remove.error.message}</Alert> : null}
      </Card>
    </li>
  )
}

/** Put the cursor in the file picker: the first step of adding a resume. */
function focusUpload(): void {
  document
    .querySelector<HTMLInputElement>('form[aria-label="Upload a resume"] input[type="file"]')
    ?.focus()
}

/** The caller's own resumes, and the two ways to add one (FR-2). */
export function Resumes(): ReactElement {
  const resumes = useResumes()
  // The last deletion, said once over the list: the row just disappears, and
  // a row that vanishes without a word reads as a glitch. Replaced by the next.
  const [deleted, setDeleted] = useState<string | null>(null)

  return (
    <>
      <section aria-labelledby="add-resume" className="flex flex-col gap-4">
        <PageTitle>
          <span id="add-resume">Add a resume</span>
        </PageTitle>

        <Card className="flex max-w-2xl flex-col gap-2">
          <AddByFile />

          <details className="border-t border-line pt-3">
            <summary className={SUMMARY}>…or paste the text</summary>
            <AddByText />
          </details>
        </Card>
      </section>

      <section aria-labelledby="your-resumes" className="flex flex-col gap-4">
        <div>
          <PageTitle>
            <span id="your-resumes">Your resumes</span>
          </PageTitle>
          <Muted>Only yours: nobody else can read or delete them.</Muted>
        </div>

        {deleted ? <Status>Deleted {deleted}.</Status> : null}

        {resumes.isPending ? <Skeleton lines={3} label="Loading your resumes…" /> : null}
        {resumes.error ? (
          <Alert
            onRetry={() => {
              void resumes.refetch()
            }}
          >
            {resumes.error.message}
          </Alert>
        ) : null}

        {resumes.data?.length === 0 ? (
          <EmptyState
            icon={FileTextIcon}
            title="No resumes yet."
            action={
              <Button type="button" variant="secondary" size="sm" onClick={focusUpload}>
                Add your first resume
              </Button>
            }
          >
            Upload a PDF, Word or text file, or paste the text.
          </EmptyState>
        ) : null}

        <ul className="flex flex-col gap-3">
          {resumes.data?.map((resume) => (
            <Stored key={resume.id} resume={resume} onDeleted={setDeleted} />
          ))}
        </ul>
      </section>
    </>
  )
}
