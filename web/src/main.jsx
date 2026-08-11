import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

// The design system loads first, so everything below inherits it.
import './theme/index.css'

import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
