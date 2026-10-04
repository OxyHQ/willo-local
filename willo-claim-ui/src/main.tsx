import { BloomProvider } from '@oxy.so/bloom/provider'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

const rootElement = document.getElementById('root')
if (rootElement === null) {
  throw new Error('willo-claim-ui: #root element is missing from index.html')
}

// Configured exactly like Willo's own app (packages/frontend/app/_layout.tsx
// in OxyHQ/Willo): Bloom resolves the palette from Willo's seed at runtime,
// follows the OS light/dark preference, loads its fonts and paints the
// document background — no hand-written or generated theme here.
createRoot(rootElement).render(
  <StrictMode>
    <BloomProvider defaultMode="system" seed="#00537f" secondaryColor="#625007" tertiaryColor="#8e3205">
      <App />
    </BloomProvider>
  </StrictMode>,
)
