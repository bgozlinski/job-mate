import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'

const container = document.getElementById('root')

// Thrown rather than narrowed away with a non-null assertion: if the element
// is missing the page is broken, and a message naming the reason beats a
// blank screen and "Cannot read properties of null".
if (!container) {
  throw new Error('No #root element to mount into')
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
