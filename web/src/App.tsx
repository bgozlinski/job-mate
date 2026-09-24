import type { ReactElement } from 'react'
import { Navigate, Route, Routes } from 'react-router'

import { RequireAuth } from './auth/RequireAuth'
import { Documents } from './routes/Documents'
import { History } from './routes/History'
import { InterviewSession } from './routes/InterviewSession'
import { Layout } from './routes/Layout'
import { Login } from './routes/Login'
import { MatchDetail } from './routes/MatchDetail'
import { Posting } from './routes/Posting'
import { Resumes } from './routes/Resumes'

/**
 * The route table. Deliberately without a router of its own: the browser gets
 * one in main.tsx and a test gets a memory router, so the same tree can be
 * rendered at any URL without a real address bar.
 *
 * Three places -- postings, resumes, history -- because the work revolves
 * around a posting: matching and practising are actions on its page, not
 * places of their own. The addresses those used to have redirect, so a
 * bookmark still lands somewhere sensible.
 */
export function App(): ReactElement {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
          <Route index element={<Navigate to="/documents" replace />} />
          <Route path="/documents" element={<Documents />} />
          <Route path="/documents/:documentId" element={<Posting />} />
          <Route path="/resumes" element={<Resumes />} />
          <Route path="/history" element={<History />} />
          <Route path="/matches/:matchId" element={<MatchDetail />} />
          <Route path="/interviews/:sessionId" element={<InterviewSession />} />

          <Route path="/match" element={<Navigate to="/documents" replace />} />
          <Route path="/interview" element={<Navigate to="/documents" replace />} />
          <Route
            path="/matches"
            element={<Navigate to="/history?kind=matches" replace />}
          />
          <Route
            path="/interviews"
            element={<Navigate to="/history?kind=interviews" replace />}
          />
        </Route>
      </Route>
    </Routes>
  )
}
