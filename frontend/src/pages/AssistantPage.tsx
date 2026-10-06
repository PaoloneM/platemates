import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import AutoIcon from '@mui/icons-material/AutoAwesomeOutlined'
import SendIcon from '@mui/icons-material/Send'
import {
  Alert,
  Box,
  Button,
  Card,
  CardActions,
  CardContent,
  CircularProgress,
  IconButton,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink, useNavigate, useParams } from 'react-router'
import { api, ApiError, type AssistantSession } from '../api'

function Bubble({ role, children }: { role: 'user' | 'assistant'; children: React.ReactNode }) {
  const mine = role === 'user'
  return (
    <Box sx={{ display: 'flex', justifyContent: mine ? 'flex-end' : 'flex-start' }}>
      <Paper
        elevation={0}
        sx={{
          px: 2,
          py: 1.25,
          maxWidth: '85%',
          borderRadius: 3,
          whiteSpace: 'pre-wrap',
          bgcolor: mine ? 'primary.main' : 'action.hover',
          color: mine ? 'primary.contrastText' : 'text.primary',
        }}
      >
        {children}
      </Paper>
    </Box>
  )
}

/** Seconds since `since`, ticking while the assistant is working. */
function useElapsed(since: number | null) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (since == null) return
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [since])
  return since == null ? 0 : Math.max(0, Math.round((now - since) / 1000))
}

/** A conversation with the recipe assistant, ending in a draft to review in the editor. */
export function AssistantPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { id } = useParams()
  const [session, setSession] = useState<AssistantSession | null>(null)
  const [text, setText] = useState('')
  const [waitingSince, setWaitingSince] = useState<number | null>(null)
  const [pending, setPending] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const elapsed = useElapsed(waitingSince)
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api<AssistantSession>(`/assistant/sessions/${id}/`)
      .then(setSession)
      .catch(() => setError(t('assistant.notFound')))
  }, [id, t])

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [session, pending])

  async function send() {
    const message = text.trim()
    if (!message || waitingSince != null) return
    setText('')
    setPending(message)
    setError(null)
    setWaitingSince(Date.now())
    try {
      setSession(
        await api<AssistantSession>(`/assistant/sessions/${id}/messages/`, {
          method: 'POST',
          body: JSON.stringify({ text: message }),
        }),
      )
    } catch (e) {
      setText(message)
      setError(e instanceof ApiError && e.status === 503 ? t('assistant.unavailable') : t('common.error'))
    } finally {
      setPending(null)
      setWaitingSince(null)
    }
  }

  if (error && !session) return <Alert severity="error">{error}</Alert>
  if (!session) return <CircularProgress sx={{ display: 'block', mx: 'auto', mt: 6 }} />

  const open = session.status === 'open'
  const draft = session.draft

  return (
    <Stack spacing={2} sx={{ maxWidth: 760, mx: 'auto' }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <IconButton component={RouterLink} to="/" aria-label={t('book.title')}>
          <ArrowBackIcon />
        </IconButton>
        <Typography variant="h1">{t(`assistant.mode.${session.mode}`)}</Typography>
      </Stack>

      <Stack spacing={1.5}>
        <Bubble role="assistant">{t(`assistant.intro.${session.mode}`)}</Bubble>
        {session.transcript.map((m, i) => (
          <Bubble key={i} role={m.role}>
            {m.text || (m.draft ? t('assistant.draftReady') : '…')}
          </Bubble>
        ))}
        {pending && <Bubble role="user">{pending}</Bubble>}
        {waitingSince != null && (
          <Stack direction="row" spacing={1.5} sx={{ alignItems: 'center', color: 'text.secondary', pl: 1 }}>
            <CircularProgress size={18} />
            <Typography variant="body2">{t('assistant.thinking', { seconds: elapsed })}</Typography>
          </Stack>
        )}
      </Stack>

      {draft && (
        <Card sx={{ borderColor: 'primary.main' }}>
          <CardContent>
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 1 }}>
              <AutoIcon color="primary" />
              <Typography variant="h3">{draft.title || t('assistant.untitled')}</Typography>
            </Stack>
            <Typography variant="body2" color="text.secondary">
              {[
                t('recipe.servings', { count: draft.servings }),
                t('assistant.ingredientCount', { count: draft.ingredients.length }),
                t('assistant.stepCount', { count: draft.steps.length }),
              ].join(' · ')}
            </Typography>
            <Typography variant="body2" sx={{ mt: 1 }}>
              {draft.ingredients.map((i) => i.name).join(', ')}
            </Typography>
          </CardContent>
          <CardActions sx={{ justifyContent: 'flex-end', px: 2, pb: 2 }}>
            {open ? (
              <Button variant="contained" onClick={() => navigate(`/recipes/new?session=${session.id}`)}>
                {t('assistant.review')}
              </Button>
            ) : (
              session.recipe && (
                <Button component={RouterLink} to={`/recipes/${session.recipe}`}>
                  {t('assistant.openRecipe')}
                </Button>
              )
            )}
          </CardActions>
        </Card>
      )}

      {error && <Alert severity="error">{error}</Alert>}

      {open ? (
        <Stack direction="row" spacing={1} sx={{ alignItems: 'flex-end' }}>
          <TextField
            multiline
            maxRows={8}
            value={text}
            placeholder={draft ? t('assistant.correctPlaceholder') : t(`assistant.placeholder.${session.mode}`)}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              // Enter sends, Shift+Enter starts a new line.
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void send()
              }
            }}
            disabled={waitingSince != null}
            autoFocus
          />
          <IconButton color="primary" onClick={() => void send()} disabled={!text.trim() || waitingSince != null}
            aria-label={t('assistant.send')} sx={{ mb: 0.5 }}>
            <SendIcon />
          </IconButton>
        </Stack>
      ) : (
        <Alert severity="info">{t('assistant.closed')}</Alert>
      )}
      <div ref={bottom} />
    </Stack>
  )
}
