import { CircularProgress } from '@mui/material'
import { useTranslation } from 'react-i18next'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router'
import { AuthProvider } from './auth/AuthProvider'
import { ThemeSync } from './components/ThemeMode'
import { useAuth } from './auth/context'
import { AppShell } from './components/AppShell'
import { RealtimeProvider } from './realtime'
import { TeamProvider } from './team'
import { AssistantPage } from './pages/AssistantPage'
import { CalendarPage } from './pages/CalendarPage'
import { InvitePage } from './pages/InvitePage'
import { IngredientsPage } from './pages/manage/IngredientsPage'
import { CachePage } from './pages/manage/CachePage'
import { DraftsPage } from './pages/manage/DraftsPage'
import { SettingsPage } from './pages/manage/SettingsPage'
import { TransferPage } from './pages/manage/TransferPage'
import { MonitoringPage } from './pages/MonitoringPage'
import { ShoppingListPage } from './pages/ShoppingListPage'
import { ShoppingPage } from './pages/ShoppingPage'
import { UsagePage } from './pages/manage/UsagePage'
import { SearchProbePage } from './pages/manage/SearchProbePage'
import { ActivityStatsPage } from './pages/manage/ActivityStatsPage'
import { InviteRequestsPage } from './pages/manage/InviteRequestsPage'
import { SystemRulesPage } from './pages/manage/SystemRulesPage'
import { ManageIndex, ManageLayout } from './pages/manage/ManageLayout'
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
      <RealtimeProvider>
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
            <Route path="/manage" element={<ManageIndex />} />
            <Route path="/manage/ingredients" element={<ManageLayout><IngredientsPage /></ManageLayout>} />
            <Route path="/manage/rules" element={<ManageLayout><SystemRulesPage /></ManageLayout>} />
            <Route path="/manage/drafts" element={<ManageLayout><DraftsPage /></ManageLayout>} />
            <Route path="/manage/settings" element={<ManageLayout><SettingsPage /></ManageLayout>} />
            <Route path="/manage/transfer" element={<ManageLayout><TransferPage /></ManageLayout>} />
            <Route path="/manage/usage" element={<ManageLayout><UsagePage /></ManageLayout>} />
            <Route path="/manage/cache" element={<ManageLayout><CachePage /></ManageLayout>} />
            <Route path="/manage/search-probe" element={<ManageLayout><SearchProbePage /></ManageLayout>} />
            <Route path="/manage/activity" element={<ManageLayout><ActivityStatsPage /></ManageLayout>} />
            <Route path="/manage/invite-requests" element={<ManageLayout><InviteRequestsPage /></ManageLayout>} />
            <Route path="/monitoring" element={<MonitoringPage />} />
            <Route path="/shopping" element={<ShoppingPage />} />
            <Route path="/shopping/:id" element={<ShoppingListPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </AppShell>
      </RealtimeProvider>
    </TeamProvider>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ThemeSync />
        <Routes>
          <Route path="/invite/:token" element={<InvitePage />} />
          <Route path="*" element={<Protected />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
