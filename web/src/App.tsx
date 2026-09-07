import type { ReactElement } from 'react'
import { Route, Routes } from 'react-router'

import { RequireAuth } from './auth/RequireAuth'
import { Home } from './routes/Home'
import { Login } from './routes/Login'

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
        <Route path="/" element={<Home />} />
      </Route>
    </Routes>
  )
}
