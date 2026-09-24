import type { ReactElement } from 'react'
import { MessagesSquareIcon } from 'lucide-react'
import { Link, useNavigate } from 'react-router'

import { useStartInterview } from '../api/interview'
import { PairPicker } from './PairPicker'

/**
 * Start a mock interview on one posting, for one of your resumes (FR-4),
 * starting from nothing.
 *
 * The same pairing as a match, on purpose: the questions come from what the
 * posting asks for, the ones your resume does not cover first.
 */
export function Interview(): ReactElement {
  const start = useStartInterview()
  const navigate = useNavigate()

  return (
    <PairPicker
      title="Practise an interview"
      description="Questions come from the posting's requirements, the ones your resume does not show first. Each answer is judged and gets one tip."
      aside={
        <Link
          to="/history?kind=interviews"
          className="text-sm text-accent hover:underline"
        >
          Your past interviews
        </Link>
      }
      submit="Start the interview"
      icon={MessagesSquareIcon}
      thinking="Preparing questions…"
      pending={start.isPending}
      error={start.error}
      onStart={(pairing) => {
        start.mutate(pairing, {
          onSuccess: (interview) => {
            void navigate(`/interviews/${interview.id}`)
          },
        })
      }}
    />
  )
}
