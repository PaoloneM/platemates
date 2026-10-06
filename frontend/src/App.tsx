import { CircularProgress } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { BrowserRouter, Route, Routes, useLocation } from 'react-router'
import { AuthProvider } from './auth/AuthProvider'
import { useAuth } from './auth/context'
import { AppShell } from './components/AppShell'
import { FamilyProvider } from './family'
import { InvitePage } from './pages/InvitePage'
import { LoginPage } from './pages/LoginPage'
import { NoFamilyPage } from './pages/NoFamilyPage'
import { RecipeBookPage } from './pages/RecipeBookPage'
import { RecipeDetailPage } from './pages/RecipeDetailPage'
import { RecipeEditorPage } from './pages/RecipeEditorPage'

/** Everything except invitations requires a signed-in user who belongs to a family. */
function Protected() {
  const { t } = useTranslation()
  const { me, error } = useAuth()
  const location = useLocation()

  if (error) return <p>{t('health.unreachable', { error })}</p>
  if (!me) return <CircularProgress sx={{ display: 'block', mx: 'auto', mt: 8 }} />
  if (!me.authenticated) return <LoginPage next={location.pathname + location.search} />
  if (me.families.length === 0) return <NoFamilyPage />
  return (
    <FamilyProvider>
      <AppShell>
        <Routes>
          <Route path="/" element={<RecipeBookPage />} />
          <Route path="/recipes/new" element={<RecipeEditorPage />} />
          <Route path="/recipes/:id" element={<RecipeDetailPage />} />
          <Route path="/recipes/:id/edit" element={<RecipeEditorPage />} />
          <Route path="*" element={<RecipeBookPage />} />
        </Routes>
      </AppShell>
    </FamilyProvider>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/invite/:token" element={<InvitePage />} />
          <Route path="*" element={<Protected />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
