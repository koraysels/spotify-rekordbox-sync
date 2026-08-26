import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import SyncWindow from './SyncWindow.tsx'

// The Sync window is a real OS window running the same bundle; the query
// string decides which root it mounts.
const isSyncWindow = new URLSearchParams(window.location.search).get('view') === 'sync'

createRoot(document.getElementById('root')!).render(
  <StrictMode>{isSyncWindow ? <SyncWindow /> : <App />}</StrictMode>,
)
