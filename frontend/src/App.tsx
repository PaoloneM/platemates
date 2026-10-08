import { CircularProgress } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router'
import { AuthProvider } from './auth/AuthProvider'
import { useAuth } from './auth/context'
import { AppShell } from './components/AppShell'
import { TeamProvider } from './team'
import { AssistantPage } from './pages/AssistantPage'
import { CalendarPage } from './pages/CalendarPage'
import { InvitePage } from './pages/InvitePage'
import { IngredientsPage } from './pages/manage/IngredientsPage'
import { SystemRulesPage } from './pages/manage/SystemRulesPage'
import { ManageLayout } from './pages/manage/ManageLayout'
import { LoginPage } from './pages/LoginPage'
import { MealPage } from './pages/MealPage'
import { NoTeamPage } from './pages/NoTeamPage'
import { RecipeBookPage } from './pages/RecipeBookPage'
import { RecipeDetailPage } from './pages/RecipeDetailPage'
import { RecipeEditorPage } from './pages/RecipeEditorPage'
import { TeamPage } from './pages/TeamPage'
import { WeekPage } from './pages/WeekPage'

/** Everything except invitations requires a signed-in user who belongs to a team. */
function Protected() {
  const { t } = useTranslation()
  const { me, error } = useAuth()
  const location = useLocation()

  if (error) return <p>{t('health.unreachable', { error })}</p>
  if (!me) return <CircularProgress sx={{ display: 'block', mx: 'auto', mt: 8 }} />
  if (!me.authenticated) return <LoginPage next={location.pathname + location.search} />
  if (me.teams.length === 0) return <NoTeamPage />
  return (
    <TeamProvider>
      <AppShell>
        <Routes>
          <Route path="/" element={<CalendarPage />} />
          <Route path="/calendar/:date/:meal" element={<MealPage />} />
          <Route path="/recipes" element={<RecipeBookPage />} />
          <Route path="/recipes/new" element={<RecipeEditorPage />} />
          <Route path="/recipes/:id" element={<RecipeDetailPage />} />
          <Route path="/recipes/:id/edit" element={<RecipeEditorPage />} />
          <Route path="/assistant/:id" element={<AssistantPage />} />
          <Route path="/team" element={<TeamPage />} />
          <Route path="/week" element={<WeekPage />} />
          <Route path="/manage" element={<Navigate to="/manage/ingredients" replace />} />
          <Route path="/manage/ingredients" element={<ManageLayout><IngredientsPage /></ManageLayout>} />
          <Route path="/manage/rules" element={<ManageLayout><SystemRulesPage /></ManageLayout>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppShell>
    </TeamProvider>
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
