import type { ReactElement } from 'react'
import { GitCompareArrowsIcon } from 'lucide-react'
import { useNavigate } from 'react-router'

import { useMatch } from '../api/matching'
import { PairPicker } from './PairPicker'

/**
 * Match a resume against a job posting (FR-3), starting from nothing.
 *
 * The result opens on its own page, as it does from a posting: that page has
 * the way back to the posting and "Practise interview" on the same pair.
 */
export function Match(): ReactElement {
  const match = useMatch()
  const navigate = useNavigate()

  return (
    <PairPicker
      title="Match a resume against a posting"
      description="See which of the posting's requirements your resume covers, with suggestions for the rest."
      submit="Match"
      icon={GitCompareArrowsIcon}
      thinking="Matching your CV…"
      pending={match.isPending}
      error={match.error}
      onStart={(pairing) => {
        match.mutate(pairing, {
          onSuccess: (result) => {
            void navigate(`/matches/${result.id}`)
          },
        })
      }}
    />
  )
}
