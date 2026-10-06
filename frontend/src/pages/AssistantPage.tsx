import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import AutoIcon from '@mui/icons-material/AutoAwesomeOutlined'
import PhotoIcon from '@mui/icons-material/PhotoCameraOutlined'
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
import { api, ApiError, apiUpload, type AssistantSession } from '../api'
import { SearchResults } from '../components/SearchResults'
import { downscalePhoto } from '../images'

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

function Photo({ src }: { src: string }) {
  return (
    <Box
      component="img"
      src={src}
      alt=""
      sx={{ display: 'block', maxWidth: 240, maxHeight: 240, borderRadius: 2, mb: 0.5 }}
    />
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
  const [pending, setPending] = useState<{ text: string; photo?: string } | null>(null)
  const photoInput = useRef<HTMLInputElement>(null)
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

  async function post(body: FormData | { text: string }, shown: { text: string; photo?: string }) {
    setPending(shown)
    setError(null)
    setWaitingSince(Date.now())
    try {
      const url = `/assistant/sessions/${id}/messages/`
      setSession(
        body instanceof FormData
          ? await apiUpload<AssistantSession>(url, body)
          : await api<AssistantSession>(url, { method: 'POST', body: JSON.stringify(body) }),
      )
      return true
    } catch (e) {
      setError(e instanceof ApiError && e.status === 503 ? t('assistant.unavailable') : t('common.error'))
      return false
    } finally {
      if (shown.photo) URL.revokeObjectURL(shown.photo)
      setPending(null)
      setWaitingSince(null)
    }
  }

  async function send() {
    const message = text.trim()
    if (!message || waitingSince != null) return
    setText('')
    if (!(await post({ text: message }, { text: message }))) setText(message)
  }

  async function sendPhoto(file: File | undefined) {
    if (!file || waitingSince != null) return
    let image: Blob
    try {
      image = await downscalePhoto(file)
    } catch {
      setError(t('assistant.photoUnreadable'))
      return
    }
    const form = new FormData()
    form.append('image', image, 'photo.jpg')
    // Whatever was typed goes with the photo, e.g. "this is the second page".
    const message = text.trim()
    if (message) form.append('text', message)
    setText('')
    if (!(await post(form, { text: message, photo: URL.createObjectURL(image) }))) setText(message)
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
        {session.transcript.map((m, i) =>
          m.results ? (
            <SearchResults
              key={i}
              results={m.results}
              notice={m.notice}
              disabled={waitingSince != null || !open}
              onImport={(url) => void post({ text: url }, { text: url })}
            />
          ) : // A photo sent alone is shown as is, without a bubble around it.
          m.attachment != null && !m.text ? (
            <Box key={i} sx={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Photo src={`/api/assistant/sessions/${session.id}/attachments/${m.attachment}/`} />
            </Box>
          ) : (
          <Bubble key={i} role={m.role}>
            {m.attachment != null && (
              <Photo src={`/api/assistant/sessions/${session.id}/attachments/${m.attachment}/`} />
            )}
            {m.error
              ? t(`assistant.importError.${m.error}`, { defaultValue: t('assistant.importError.generic') })
              : m.text || (m.draft ? t('assistant.draftReady') : '…')}
          </Bubble>
          ),
        )}
        {pending && (
          <Bubble role="user">
            {pending.photo && <Photo src={pending.photo} />}
            {pending.text}
          </Bubble>
        )}
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
            autoFocus={session.mode !== 'photo'}
          />
          <input
            ref={photoInput}
            type="file"
            accept="image/*"
            // On phones, open the back camera directly; desktops get a file picker.
            capture="environment"
            hidden
            onChange={(e) => {
              void sendPhoto(e.target.files?.[0])
              e.target.value = ''
            }}
          />
          <IconButton
            color={session.mode === 'photo' ? 'primary' : 'default'}
            onClick={() => photoInput.current?.click()}
            disabled={waitingSince != null}
            aria-label={t('assistant.addPhoto')}
            sx={{ mb: 0.5 }}
          >
            <PhotoIcon />
          </IconButton>
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
