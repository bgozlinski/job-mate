import type { ReactElement } from 'react'
import { Navigate, Route, Routes } from 'react-router'

import { RequireAuth } from './auth/RequireAuth'
import { Documents } from './routes/Documents'
import { History, MatchDetail } from './routes/History'
import { Match } from './routes/Match'
import { Layout } from './routes/Layout'
import { Login } from './routes/Login'
import { Resumes } from './routes/Resumes'

/**
 * The route table. Deliberately without a router of its own: the browser gets
 * one in main.tsx and a test gets a memory router, so the same tree can be
 * rendered at any URL without a real address bar.
 */
export function App(): ReactElement {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />

      <Route element={<RequireAuth />}>
        <Route element={<Layout />}>
          {/* The knowledge base is where the application starts: FR-3 has the
              user pick a posting, and there is nothing to pick until one is
              here. */}
          <Route index element={<Navigate to="/documents" replace />} />
          <Route path="/documents" element={<Documents />} />
          <Route path="/resumes" element={<Resumes />} />
          <Route path="/match" element={<Match />} />
          <Route path="/matches" element={<History />} />
          <Route path="/matches/:matchId" element={<MatchDetail />} />
        </Route>
      </Route>
    </Routes>
  )
}
