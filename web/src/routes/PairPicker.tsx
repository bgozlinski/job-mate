import { useState } from 'react'
import type { ReactElement, ReactNode, SyntheticEvent } from 'react'
import { Link } from 'react-router'
import type { LucideIcon } from 'lucide-react'

import { MAX_PAGE_SIZE, useDocuments } from '../api/documents'
import type { Pairing } from '../api/matching'
import { useResumes } from '../api/resumes'
import { Alert, Button, Field, Notice, PageHeader, Sheet, Thinking } from '../ui'
import { newest } from './Posting'

const LINK = 'text-accent underline underline-offset-2'

/**
 * Pick a resume and a posting, then start something on the pair: a match or
 * an interview. The posting's own page does the same with the posting already
 * chosen; this is the way in that starts from nothing.
 *
 * The resume defaults to the newest, as on the posting page -- the person has
 * one main resume, and asking every time would be a step with one answer.
 */
export function PairPicker({
  title,
  description,
  aside,
  submit,
  icon,
  thinking,
  pending,
  error,
  onStart,
}: {
  title: string
  description: ReactNode
  aside?: ReactNode
  submit: string
  icon: LucideIcon
  thinking: string
  pending: boolean
  error: Error | null
  onStart: (pairing: Pairing) => void
}): ReactElement {
  const resumes = useResumes()
  const documents = useDocuments(MAX_PAGE_SIZE)

  const [pickedResume, setPickedResume] = useState('')
  const [documentId, setDocumentId] = useState('')
  // '' means nothing picked yet, so || rather than ??: an empty pick falls
  // through to the newest resume.
  const resumeId = pickedResume || (newest(resumes.data ?? [])?.id ?? '')

  function onSubmit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>): void {
    event.preventDefault()

    if (resumeId && documentId) {
      onStart({ resumeId, documentId })
    }
  }

  // Both lists are needed before anything can be picked, and either being
  // empty is a dead end with a specific way out -- so each is named rather
  // than folded into one "nothing to pick" message.
  const noResumes = resumes.data?.length === 0
  const noDocuments = documents.data?.length === 0

  return (
    <>
      <PageHeader title={title} description={description} actions={aside} />

      {/* Notices, not alerts: an empty list is a step to take first, not
          something that went wrong. */}
      {noResumes ? (
        <Notice>
          No resumes yet.{' '}
          <Link to="/resumes" className={LINK}>
            Add one
          </Link>{' '}
          first.
        </Notice>
      ) : null}

      {noDocuments ? (
        <Notice>
          Nothing in the knowledge base yet.{' '}
          <Link to="/documents" className={LINK}>
            Add a job posting
          </Link>{' '}
          first.
        </Notice>
      ) : null}

      <Sheet className="max-w-2xl">
        <form aria-label={title} onSubmit={onSubmit} className="flex flex-col gap-4">
          <Field id="pair-resume" label="Resume">
            {(className, id) => (
              <select
                id={id}
                required
                className={className}
                value={resumeId}
                onChange={(event) => {
                  setPickedResume(event.target.value)
                }}
              >
                <option value="">Choose a resume</option>
                {resumes.data?.map((resume) => (
                  <option key={resume.id} value={resume.id}>
                    {resume.original_filename ?? 'Pasted text'}
                    {resume.target_role ? ` — ${resume.target_role}` : ''}
                  </option>
                ))}
              </select>
            )}
          </Field>

          <Field id="pair-document" label="Job posting">
            {(className, id) => (
              <select
                id={id}
                required
                className={className}
                value={documentId}
                onChange={(event) => {
                  setDocumentId(event.target.value)
                }}
              >
                <option value="">Choose a posting</option>
                {documents.data?.map((document) => (
                  <option key={document.id} value={document.id}>
                    {document.title ?? 'Untitled'}
                  </option>
                ))}
              </select>
            )}
          </Field>

          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="submit"
              icon={icon}
              disabled={pending || !resumeId || !documentId}
            >
              {submit}
            </Button>
            {pending ? <Thinking>{thinking}</Thinking> : null}
          </div>
        </form>
      </Sheet>

      {error ? <Alert>{error.message}</Alert> : null}
    </>
  )
}
