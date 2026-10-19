import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { createAuth } from './setup'
import './styles.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App auth={createAuth()} />
  </StrictMode>,
)
