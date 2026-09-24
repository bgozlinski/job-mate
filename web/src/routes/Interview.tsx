import { useState } from 'react'
import type { ReactElement, SyntheticEvent } from 'react'
import { Link, useNavigate } from 'react-router'

import { MAX_PAGE_SIZE, useDocuments } from '../api/documents'
import { useStartInterview } from '../api/interview'
import { useResumes } from '../api/resumes'
import { Alert, Button, Card, Field, Muted, PageTitle } from '../ui'

const LINK = 'text-accent underline underline-offset-2'

/**
 * Start a mock interview on one posting, for one of your resumes (FR-4).
 *
 * The same pairing as a match, on purpose: the questions come from what the
 * posting asks for, the ones your resume does not cover first.
 */
export function Interview(): ReactElement {
  const resumes = useResumes()
  const documents = useDocuments(MAX_PAGE_SIZE)
  const start = useStartInterview()
  const navigate = useNavigate()

  const [resumeId, setResumeId] = useState('')
  const [documentId, setDocumentId] = useState('')

  function onSubmit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>): void {
    event.preventDefault()

    if (resumeId && documentId) {
      start.mutate(
        { resumeId, documentId },
        {
          onSuccess: (interview) => {
            void navigate(`/interviews/${interview.id}`)
          },
        },
      )
    }
  }

  const noResumes = resumes.data?.length === 0
  const noDocuments = documents.data?.length === 0

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <PageTitle>Practise an interview</PageTitle>
          <Muted>
            Questions come from the posting&apos;s requirements, the ones your resume
            does not show first. Each answer is judged and gets one tip.
          </Muted>
        </div>
        <Link to="/interviews" className="text-sm text-accent hover:underline">
          Your past interviews
        </Link>
      </div>

      {noResumes ? (
        <Alert>
          No resumes yet.{' '}
          <Link to="/resumes" className={LINK}>
            Add one
          </Link>{' '}
          first.
        </Alert>
      ) : null}

      {noDocuments ? (
        <Alert>
          Nothing in the knowledge base yet.{' '}
          <Link to="/documents" className={LINK}>
            Add a job posting
          </Link>{' '}
          first.
        </Alert>
      ) : null}

      <Card className="max-w-2xl">
        <form
          aria-label="Start an interview"
          onSubmit={onSubmit}
          className="flex flex-col gap-4"
        >
          <Field id="interview-resume" label="Resume">
            {(className, id) => (
              <select
                id={id}
                required
                className={className}
                value={resumeId}
                onChange={(event) => {
                  setResumeId(event.target.value)
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

          <Field id="interview-document" label="Job posting">
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

          <div className="flex">
            <Button
              type="submit"
              disabled={start.isPending || !resumeId || !documentId}
            >
              {start.isPending ? 'Preparing questions…' : 'Start the interview'}
            </Button>
          </div>
        </form>
      </Card>

      {start.error ? <Alert>{start.error.message}</Alert> : null}
    </>
  )
}
