import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  CircularProgress,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Link,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink } from 'react-router'
import { api, type Paginated, type SystemRule, type TeamRule, type WeeklyMenu } from '../api'
import { addDays, fromIso } from '../calendar'
import { useLabels } from '../labels'
import { useTeam } from '../team'

const MAX_INSTRUCTIONS = 2000

type Loaded = { menu: WeeklyMenu | null; rules: TeamRule[]; system: SystemRule[] }

/**
 * "Tell me how to plan it": the week's own instructions, and which team rules apply. Saved on
 * the week's menu (created if there is none yet), so whoever regenerates finds them again.
 */
export function PlanWeekDialog({ weekStart, generating, onClose, onSaved }: {
  weekStart: string
  generating: boolean
  onClose: () => void
  // `generate`: the user asked to generate the week with these settings.
  onSaved: (generate: boolean) => void
}) {
  const { t, i18n } = useTranslation()
  const labels = useLabels()
  const { team } = useTeam()
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [instructions, setInstructions] = useState('')
  const [useTeamRules, setUseTeamRules] = useState(true)
  const [excluded, setExcluded] = useState<Set<number>>(new Set())
  const [showSystem, setShowSystem] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)

  useEffect(() => {
    Promise.all([
      api<Paginated<WeeklyMenu>>(`/menus/?team=${team.id}&week_start=${weekStart}`),
      api<Paginated<TeamRule>>(`/team-rules/?team=${team.id}`),
      api<SystemRule[]>('/system-rules/'),
    ]).then(([menus, rules, system]) => {
      const menu = menus.results[0] ?? null
      setLoaded({ menu, rules: rules.results, system: system.filter((rule) => rule.active) })
      if (menu) {
        setInstructions(menu.instructions)
        setUseTeamRules(menu.use_team_rules)
        setExcluded(new Set(menu.excluded_rules))
      }
    })
  }, [team.id, weekStart])

  const format = new Intl.DateTimeFormat(i18n.resolvedLanguage, { day: 'numeric', month: 'short' })
  const monday = fromIso(weekStart)
  const range = t('calendar.week', { start: format.format(monday), end: format.format(addDays(monday, 6)) })

  function toggle(rule: TeamRule, on: boolean) {
    setExcluded((current) => {
      const next = new Set(current)
      if (on) next.delete(rule.id)
      else next.add(rule.id)
      return next
    })
  }

  async function save(generate: boolean) {
    if (!loaded) return
    setBusy(true)
    setError(false)
    // Only rules that still exist: one may have been deleted since the week was saved.
    const settings = {
      instructions,
      use_team_rules: useTeamRules,
      excluded_rules: loaded.rules.filter((rule) => excluded.has(rule.id)).map((rule) => rule.id),
    }
    try {
      if (loaded.menu) {
        await api(`/menus/${loaded.menu.id}/`, { method: 'PATCH', body: JSON.stringify(settings) })
      } else {
        await api('/menus/', { method: 'POST', body: JSON.stringify({ team: team.id, week_start: weekStart, ...settings }) })
      }
      onSaved(generate)
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>
        {t('plan.title')}
        <Typography variant="body2" color="text.secondary">{range}</Typography>
      </DialogTitle>
      <DialogContent>
        {!loaded ? (
          <CircularProgress sx={{ display: 'block', mx: 'auto', my: 4 }} />
        ) : (
          // The top padding keeps the first field's label clear of the title.
          <Stack spacing={3} sx={{ pt: 1 }}>
            {error && <Alert severity="error">{t('common.error')}</Alert>}
            <TextField multiline minRows={3} fullWidth autoFocus value={instructions}
              label={t('plan.instructions')} placeholder={t('plan.placeholder')}
              helperText={t('plan.instructionsHint')}
              onChange={(e) => setInstructions(e.target.value)}
              slotProps={{ htmlInput: { maxLength: MAX_INSTRUCTIONS }, inputLabel: { shrink: true } }} />

            <Box>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>{t('plan.teamRules')}</Typography>
              {loaded.rules.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  {t('plan.noTeamRules')}{' '}
                  <Link component={RouterLink} to="/week">{t('plan.setUpWeek')}</Link>
                </Typography>
              ) : (
                <Stack>
                  <FormControlLabel label={t('plan.useTeamRules')}
                    control={<Checkbox checked={useTeamRules} onChange={(e) => setUseTeamRules(e.target.checked)} />} />
                  <Stack sx={{ pl: 4 }}>
                    {loaded.rules.map((rule) => (
                      <FormControlLabel key={rule.id} label={rule.text} disabled={!useTeamRules}
                        sx={{ alignItems: 'flex-start', '& .MuiCheckbox-root': { pt: 0.5 }, '& .MuiFormControlLabel-label': { pt: 0.75 } }}
                        control={<Checkbox size="small" checked={!excluded.has(rule.id)}
                          onChange={(e) => toggle(rule, e.target.checked)} />} />
                    ))}
                  </Stack>
                </Stack>
              )}
            </Box>

            <Box>
              <Button size="small" color="inherit" onClick={() => setShowSystem((v) => !v)}
                endIcon={showSystem ? <ExpandLessIcon /> : <ExpandMoreIcon />} sx={{ ml: -1 }}>
                {t('plan.systemRules', { count: loaded.system.length })}
              </Button>
              <Collapse in={showSystem}>
                <Box component="ul" sx={{ m: 0, pl: 3 }}>
                  {loaded.system.map((rule) => (
                    <Typography component="li" key={rule.id} variant="body2" color="text.secondary">
                      {labels.systemRule(rule)}
                    </Typography>
                  ))}
                </Box>
              </Collapse>
            </Box>
            <Typography variant="body2" color="text.secondary">{t('plan.precedence')}</Typography>
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t('common.cancel')}</Button>
        <Button onClick={() => void save(false)} disabled={!loaded || busy}>{t('common.save')}</Button>
        <Tooltip title={generating ? t('menuFab.generating') : ''}>
          {/* The span keeps the tooltip working on a disabled button. */}
          <span>
            <Button variant="contained" onClick={() => void save(true)} disabled={!loaded || busy || generating}>
              {t('plan.generate')}
            </Button>
          </span>
        </Tooltip>
      </DialogActions>
    </Dialog>
  )
}
