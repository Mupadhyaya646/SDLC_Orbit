import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ThemeProvider } from './state/ThemeContext'
import { SessionProvider } from './state/SessionContext'
import App from './App'
import './styles/theme.css'

const queryClient = new QueryClient()

createRoot(document.getElementById('app') as HTMLElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <SessionProvider>
          <App />
        </SessionProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
)
