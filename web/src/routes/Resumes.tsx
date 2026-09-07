import { useState } from 'react'
import type { ReactElement, SyntheticEvent } from 'react'

import type { Resume } from '../api/resumes'
import {
  MAX_RESUME_LENGTH,
  MAX_TARGET_ROLE_LENGTH,
  useCreateResume,
  useDeleteResume,
  useResumes,
  useUploadResume,
} from '../api/resumes'

const UPLOAD_TYPES = '.pdf,.docx,.txt,.md'

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
    <>
      <label htmlFor={id}>Target role (optional)</label>
      <input
        id={id}
        type="text"
        maxLength={MAX_TARGET_ROLE_LENGTH}
        placeholder="Backend developer"
        value={value}
        onChange={(event) => { onChange(event.target.value) }}
      />
    </>
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
    // "Target role" field, and an unnamed form is not a landmark, so a
    // screen reader would announce the same label twice with nothing to
    // tell them apart.
    <form aria-label="Upload a resume" onSubmit={onSubmit}>
      <label htmlFor={`resume-file-${String(generation)}`}>
        Resume file (PDF, DOCX or text)
      </label>
      <input
        id={`resume-file-${String(generation)}`}
        key={generation}
        type="file"
        accept={UPLOAD_TYPES}
        // Deliberately not `required`: the button below is disabled without a
        // file, and jsdom's constraint validation does not see files set by a
        // test, so the attribute would make this path untestable.
        onChange={(event) => { setFile(event.target.files?.[0] ?? null) }}
      />

      <TargetRole
        id={`resume-file-role-${String(generation)}`}
        value={targetRole}
        onChange={setTargetRole}
      />

      <button type="submit" disabled={upload.isPending || !file}>
        {upload.isPending ? 'Reading the resume…' : 'Upload'}
      </button>

      {upload.error ? <p role="alert">{upload.error.message}</p> : null}
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
    <form aria-label="Paste a resume" onSubmit={onSubmit}>
      <label htmlFor="resume-text">Resume text</label>
      <textarea
        id="resume-text"
        rows={10}
        required
        value={content}
        onChange={(event) => { setContent(event.target.value) }}
      />

      <TargetRole id="resume-text-role" value={targetRole} onChange={setTargetRole} />

      {tooLong ? (
        <p role="alert">
          The text is longer than {MAX_RESUME_LENGTH.toLocaleString('en')} characters.
        </p>
      ) : null}

      <button type="submit" disabled={create.isPending || tooLong}>
        {create.isPending ? 'Storing…' : 'Save'}
      </button>

      {create.error ? <p role="alert">{create.error.message}</p> : null}
    </form>
  )
}

function Stored({ resume }: { resume: Resume }): ReactElement {
  const [confirming, setConfirming] = useState(false)
  const remove = useDeleteResume()
  const created = new Date(resume.created_at)
  const name = resume.original_filename ?? 'Pasted text'

  return (
    <li>
      <h3>{name}</h3>
      <p>
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
        <summary>Show text</summary>
        <pre>{resume.content}</pre>
      </details>

      {/* Two presses rather than a native confirm(): deleting is the one
          irreversible thing on this page, and window.confirm is a dialog
          jsdom does not implement, so a guard built on it could not be
          covered by a test. */}
      {confirming ? (
        <>
          <button
            type="button"
            disabled={remove.isPending}
            onClick={() => { remove.mutate(resume.id) }}
          >
            {remove.isPending ? 'Deleting…' : `Really delete ${name}`}
          </button>
          <button type="button" onClick={() => { setConfirming(false) }}>
            Cancel
          </button>
        </>
      ) : (
        <button type="button" onClick={() => { setConfirming(true) }}>
          Delete {name}
        </button>
      )}

      {remove.error ? <p role="alert">{remove.error.message}</p> : null}
    </li>
  )
}

/** The caller's own resumes, and the two ways to add one (FR-2). */
export function Resumes(): ReactElement {
  const resumes = useResumes()

  return (
    <>
      <section aria-labelledby="add-resume">
        <h2 id="add-resume">Add a resume</h2>

        <AddByFile />

        <details>
          <summary>…or paste the text</summary>
          <AddByText />
        </details>
      </section>

      <section aria-labelledby="your-resumes">
        <h2 id="your-resumes">Your resumes</h2>
        <p>Only yours: nobody else can read or delete them.</p>

        {resumes.isPending ? <p>Loading…</p> : null}
        {resumes.error ? <p role="alert">{resumes.error.message}</p> : null}

        {resumes.data?.length === 0 ? <p>No resumes stored yet.</p> : null}

        <ul>
          {resumes.data?.map((resume) => (
            <Stored key={resume.id} resume={resume} />
          ))}
        </ul>
      </section>
    </>
  )
}
