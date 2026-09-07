import { useState } from 'react'
import type { ReactElement, SyntheticEvent } from 'react'
import { Link } from 'react-router'

import { MAX_PAGE_SIZE, useDocuments } from '../api/documents'
import { useMatch } from '../api/matching'
import { useResumes } from '../api/resumes'
import { Alert, Button, Card, Field, PageTitle } from '../ui'
import { MatchResult } from './MatchResult'

const LINK = 'text-accent underline underline-offset-2'

/** Match a resume against a job posting (FR-3). */
export function Match(): ReactElement {
  const resumes = useResumes()
  const documents = useDocuments(MAX_PAGE_SIZE)
  const match = useMatch()

  const [resumeId, setResumeId] = useState('')
  const [documentId, setDocumentId] = useState('')

  function onSubmit(event: SyntheticEvent<HTMLFormElement, SubmitEvent>): void {
    event.preventDefault()

    if (resumeId && documentId) {
      match.mutate({ resumeId, documentId })
    }
  }

  // Both lists are needed before anything can be picked, and either being
  // empty is a dead end with a specific way out -- so each is named rather
  // than folded into one "nothing to match" message.
  const noResumes = resumes.data?.length === 0
  const noDocuments = documents.data?.length === 0

  return (
    <>
      <PageTitle>Match a resume against a posting</PageTitle>

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
          aria-label="Match a resume"
          onSubmit={onSubmit}
          className="flex flex-col gap-4"
        >
          <Field id="match-resume" label="Resume">
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

          <Field id="match-document" label="Job posting">
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
              disabled={match.isPending || !resumeId || !documentId}
            >
              {match.isPending ? 'Matching…' : 'Match'}
            </Button>
          </div>
        </form>
      </Card>

      {match.error ? <Alert>{match.error.message}</Alert> : null}
      {match.data ? <MatchResult match={match.data} /> : null}
    </>
  )
}
