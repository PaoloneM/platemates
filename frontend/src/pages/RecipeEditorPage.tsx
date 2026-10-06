import AddIcon from '@mui/icons-material/Add'
import ArrowDownIcon from '@mui/icons-material/ArrowDownward'
import ArrowUpIcon from '@mui/icons-material/ArrowUpward'
import AutoIcon from '@mui/icons-material/AutoAwesomeOutlined'
import CloseIcon from '@mui/icons-material/Close'
import DeleteIcon from '@mui/icons-material/DeleteOutlined'
import {
  Alert,
  Autocomplete,
  createFilterOptions,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  FormControlLabel,
  Grid,
  IconButton,
  InputAdornment,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link as RouterLink, useNavigate, useParams, useSearchParams } from 'react-router'
import {
  api,
  ApiError,
  type AssistantSession,
  type Course,
  type Cuisine,
  type DraftLine,
  type KitchenTool,
  type Recipe,
  type Unit,
  type Visibility,
} from '../api'
import { IngredientDialog } from '../components/IngredientDialog'
import { IngredientPicker, type PickedIngredient } from '../components/IngredientPicker'
import { SeasonPicker } from '../components/SeasonPicker'
import { ToolDialog } from '../components/ToolDialog'
import { useFamily } from '../family'
import { COURSES, UNITS, useDescribeMonths, useLabels } from '../labels'

type Line = {
  key: number
  ingredient: PickedIngredient | null
  // From an assistant draft: what it proposed for this line, kept until the user resolves it.
  suggestion?: DraftLine
  // Set when the draft name was matched to a catalog entry by similarity, not exactly.
  matchedFrom?: string
  quantity: string
  unit: Unit
  optional: boolean
  note: string
}

type Form = {
  title: string
  description: string
  course: Course
  cuisine: Cuisine | string | null
  servings: string
  prep: string
  cook: string
  tools: KitchenTool[]
  lines: Line[]
  steps: string[]
  // Derived from the ingredients unless the user takes it over.
  seasonAuto: boolean
  seasonMonths: number[]
  climateMonths: number[]
  visibility: Visibility
  sourceUrl: string
}

const toolFilter = createFilterOptions<KitchenTool | { create: string }>()

let nextKey = 1
const newLine = (): Line => ({
  key: nextKey++,
  ingredient: null,
  quantity: '',
  unit: 'g',
  optional: false,
  note: '',
})

const EMPTY: Form = {
  title: '',
  description: '',
  course: 'single',
  cuisine: null,
  servings: '2',
  prep: '',
  cook: '',
  tools: [],
  lines: [],
  steps: [''],
  seasonAuto: true,
  seasonMonths: [],
  climateMonths: [],
  visibility: 'shared',
  sourceUrl: '',
}

/** Same rule as the backend (`Recipe.derive_season_months`), for a live preview. */
function deriveSeason(lines: Line[]): number[] {
  const lists = lines
    .filter((l) => l.ingredient && !l.optional)
    .map((l) => (l.ingredient!.season_months.length ? l.ingredient!.season_months : []))
  const all = Array.from({ length: 12 }, (_, i) => i + 1)
  const asMonths = (m: number[]) => (m.length ? m : all)
  let months = lists.reduce((acc, m) => acc.filter((x) => asMonths(m).includes(x)), all)
  if (months.length === 0) months = [...new Set(lists.flatMap(asMonths))].sort((a, b) => a - b)
  return months.length === 12 ? [] : months
}

function fromRecipe(r: Recipe, tools: KitchenTool[]): Form {
  return {
    title: r.title,
    description: r.description,
    course: r.course,
    cuisine: r.cuisine ? { id: r.cuisine, name: r.cuisine_name ?? '' } : null,
    servings: String(r.servings),
    prep: r.prep_minutes?.toString() ?? '',
    cook: r.cook_minutes?.toString() ?? '',
    tools: tools.filter((t) => r.tools.includes(t.id)),
    lines: r.ingredients.map((l) => ({
      key: nextKey++,
      ingredient: {
        id: l.ingredient,
        name: l.ingredient_name ?? '',
        category: l.ingredient_category ?? 'other',
        default_unit: l.unit,
        season_months: l.ingredient_season_months ?? [],
      },
      quantity: l.quantity == null ? '' : String(Number(l.quantity)),
      unit: l.unit,
      optional: l.optional,
      note: l.note,
    })),
    steps: r.steps.length ? r.steps : [''],
    seasonAuto: r.provenance.season_months !== 'user',
    seasonMonths: r.season_months.months,
    climateMonths: r.climate_months.months,
    visibility: r.visibility,
    sourceUrl: r.source_url,
  }
}

/** Turn an assistant draft into the editor's form: everything stays to be reviewed. */
function fromDraft(session: AssistantSession, cuisines: Cuisine[]): Form {
  const d = session.draft!
  return {
    ...EMPTY,
    title: d.title,
    description: d.description,
    course: d.course,
    cuisine: cuisines.find((c) => c.name.toLowerCase() === d.cuisine.toLowerCase()) ?? (d.cuisine || null),
    servings: String(d.servings),
    prep: d.prep_minutes?.toString() ?? '',
    cook: d.cook_minutes?.toString() ?? '',
    lines: d.ingredients.map((line, index) => {
      const match = session.matches[index]
      const candidate = match?.candidates.find((c) => c.id === match.match)
      return {
        key: nextKey++,
        ingredient: candidate
          ? { id: candidate.id, name: candidate.name, category: candidate.category,
              default_unit: candidate.default_unit, season_months: candidate.season_months }
          : null,
        suggestion: line,
        matchedFrom: candidate && !match.exact ? line.name : undefined,
        quantity: line.quantity ?? '',
        unit: line.unit,
        optional: line.optional,
        note: line.note,
      }
    }),
    steps: d.steps.length ? d.steps : [''],
    climateMonths: d.climate_months,
    sourceUrl: d.source_url ?? '',
  }
}

function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <Card>
      <CardContent>
        <Stack direction="row" sx={{ alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
          <Typography variant="h2">{title}</Typography>
          {action}
        </Stack>
        {children}
      </CardContent>
    </Card>
  )
}

/**
 * Create or edit a recipe. Also the place where drafts proposed by the assistant will be
 * reviewed: everything stays editable until the user saves.
 */
export function RecipeEditorPage() {
  const { t } = useTranslation()
  const labels = useLabels()
  const describeMonths = useDescribeMonths()
  const navigate = useNavigate()
  const { id } = useParams()
  const [params] = useSearchParams()
  const sessionId = params.get('session')
  const { family } = useFamily()
  const editing = id != null

  // Editing or reviewing a draft: show a spinner until the data is loaded, rather than an empty
  // form the user might start typing into.
  const [form, setForm] = useState<Form | null>(
    editing || sessionId ? null : { ...EMPTY, lines: [newLine()] },
  )
  const [cuisines, setCuisines] = useState<Cuisine[]>([])
  const [tools, setTools] = useState<KitchenTool[]>([])
  const [creatingTool, setCreatingTool] = useState<string | null>(null)
  const [creating, setCreating] = useState<
    { name: string; lineKey: number; suggestion?: DraftLine } | null
  >(null)
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  // Photos the draft was read from, shown beside it for comparison.
  const [photos, setPhotos] = useState<AssistantSession['attachments']>([])

  useEffect(() => {
    if (!sessionId || editing) return
    Promise.all([
      api<AssistantSession>(`/assistant/sessions/${sessionId}/`),
      api<Cuisine[]>('/cuisines/'),
    ])
      .then(([session, all]) => {
        setForm(session.draft ? fromDraft(session, all) : { ...EMPTY, lines: [newLine()] })
        setPhotos(session.attachments)
      })
      .catch(() => setErrors({ load: t('assistant.notFound') }))
  }, [sessionId, editing, t])

  useEffect(() => {
    api<Cuisine[]>('/cuisines/').then(setCuisines).catch(() => undefined)
    api<KitchenTool[]>('/kitchen-tools/')
      .then((all) => {
        setTools(all)
        if (editing) {
          api<Recipe>(`/recipes/${id}/`)
            .then((r) => setForm(fromRecipe(r, all)))
            .catch(() => setErrors({ load: t('recipe.notFound') }))
        }
      })
      .catch(() => setErrors({ load: t('common.error') }))
  }, [editing, id, t])

  const derived = useMemo(() => (form ? deriveSeason(form.lines) : []), [form])

  if (errors.load) return <Alert severity="error">{errors.load}</Alert>
  if (!form) return <CircularProgress sx={{ display: 'block', mx: 'auto', mt: 6 }} />

  const set = <K extends keyof Form>(key: K, value: Form[K]) =>
    setForm((f) => (f ? { ...f, [key]: value } : f))
  const setLine = (key: number, patch: Partial<Line>) =>
    set('lines', form.lines.map((l) => (l.key === key ? { ...l, ...patch } : l)))
  const moveLine = (index: number, delta: number) => {
    const lines = [...form.lines]
    const [line] = lines.splice(index, 1)
    lines.splice(index + delta, 0, line)
    set('lines', lines)
  }
  const setStep = (index: number, value: string) =>
    set('steps', form.steps.map((s, i) => (i === index ? value : s)))

  async function resolveCuisine(): Promise<number | null> {
    const c = form!.cuisine
    if (c == null || c === '') return null
    if (typeof c !== 'string') return c.id
    const existing = cuisines.find((x) => x.name.toLowerCase() === c.trim().toLowerCase())
    if (existing) return existing.id
    const created = await api<Cuisine>('/cuisines/', {
      method: 'POST',
      body: JSON.stringify({ name: c.trim() }),
    })
    return created.id
  }

  async function save() {
    const problems: Record<string, string> = {}
    if (!form!.title.trim()) problems.title = t('editor.required')
    if (!(Number(form!.servings) >= 1)) problems.servings = t('editor.servingsInvalid')
    if (form!.lines.some((l) => l.suggestion && !l.ingredient)) problems.save = t('editor.unresolved')
    if (Object.keys(problems).length) {
      setErrors(problems)
      return
    }
    setSaving(true)
    setErrors({})
    try {
      const f = form!
      const payload: Record<string, unknown> = {
        title: f.title.trim(),
        description: f.description.trim(),
        course: f.course,
        cuisine: await resolveCuisine(),
        servings: Number(f.servings),
        prep_minutes: f.prep ? Number(f.prep) : null,
        cook_minutes: f.cook ? Number(f.cook) : null,
        tools: f.tools.map((x) => x.id),
        ingredients: f.lines
          .filter((l) => l.ingredient)
          .map((l) => ({
            ingredient: l.ingredient!.id,
            quantity: l.unit === 'tt' || l.quantity === '' ? null : l.quantity.replace(',', '.'),
            unit: l.unit,
            optional: l.optional,
            note: l.note.trim(),
          })),
        steps: f.steps,
        climate_months: { months: f.climateMonths },
        visibility: f.visibility,
        source_url: f.sourceUrl.trim(),
      }
      if (!f.seasonAuto) payload.season_months = { months: f.seasonMonths }
      else if (editing) payload.season_months = { auto: true }
      if (!editing) payload.family = family.id

      const saved = await api<Recipe>(editing ? `/recipes/${id}/` : '/recipes/', {
        method: editing ? 'PATCH' : 'POST',
        body: JSON.stringify(payload),
      })
      if (sessionId && !editing) {
        await api(`/assistant/sessions/${sessionId}/close/`, {
          method: 'POST',
          body: JSON.stringify({ recipe: saved.id }),
        }).catch(() => undefined)
      }
      navigate(`/recipes/${saved.id}`, { replace: editing || !!sessionId })
    } catch (e) {
      const body = e instanceof ApiError ? (e.body as Record<string, unknown>) : null
      const first = body && Object.entries(body)[0]
      setErrors({
        save: first ? `${first[0]}: ${JSON.stringify(first[1])}` : t('common.error'),
      })
      setSaving(false)
    }
  }

  const seasonShown = form.seasonAuto ? derived : form.seasonMonths

  return (
    <Stack spacing={3}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <IconButton onClick={() => navigate(-1)} aria-label={t('common.cancel')}>
          <CloseIcon />
        </IconButton>
        <Typography variant="h1" sx={{ flex: 1 }}>
          {editing ? t('editor.editTitle') : t('editor.newTitle')}
        </Typography>
        <Button variant="contained" onClick={() => void save()} disabled={saving}>
          {t('common.save')}
        </Button>
      </Stack>
      {sessionId && !editing && (
        <Alert severity="info" icon={<AutoIcon />}
          action={<Button color="inherit" size="small" component={RouterLink} to={`/assistant/${sessionId}`}>
            {t('editor.backToAssistant')}
          </Button>}>
          {t('editor.fromAssistant')}
        </Alert>
      )}
      {errors.save && <Alert severity="error">{errors.save}</Alert>}

      {photos.length > 0 && (
        <Section title={t('editor.sourcePhotos')}>
          <Stack spacing={2}>
            {photos.map((photo) => {
              const src = `/api/assistant/sessions/${sessionId}/attachments/${photo.id}/`
              return (
                <Stack key={photo.id} direction={{ xs: 'column', sm: 'row' }} spacing={2}>
                  <Box component="a" href={src} target="_blank" rel="noopener" sx={{ flex: 'none' }}>
                    <Box component="img" src={src} alt={t('editor.sourcePhotos')}
                      sx={{ width: { xs: '100%', sm: 220 }, borderRadius: 2, display: 'block' }} />
                  </Box>
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography variant="subtitle2" gutterBottom>
                      {t('editor.readFromPhoto')}
                    </Typography>
                    <Typography variant="body2" component="pre"
                      sx={{ whiteSpace: 'pre-wrap', fontFamily: 'inherit', m: 0, color: 'text.secondary',
                        maxHeight: 260, overflow: 'auto' }}>
                      {photo.transcription}
                    </Typography>
                  </Box>
                </Stack>
              )
            })}
          </Stack>
        </Section>
      )}

      <Section title={t('editor.about')}>
        <Grid container spacing={2}>
          <Grid size={12}>
            <TextField
              label={t('editor.title')}
              value={form.title}
              onChange={(e) => set('title', e.target.value)}
              error={!!errors.title}
              helperText={errors.title}
              required
            />
          </Grid>
          <Grid size={12}>
            <TextField
              label={t('editor.description')}
              value={form.description}
              onChange={(e) => set('description', e.target.value)}
              multiline
              minRows={2}
            />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <TextField select label={t('editor.course')} value={form.course}
              onChange={(e) => set('course', e.target.value as Course)}>
              {COURSES.map((c) => (
                <MenuItem key={c} value={c}>
                  {labels.course(c)}
                </MenuItem>
              ))}
            </TextField>
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <Autocomplete<Cuisine, false, false, true>
              freeSolo
              options={cuisines}
              value={form.cuisine}
              getOptionLabel={(o) => (typeof o === 'string' ? o : o.name)}
              onChange={(_, v) => set('cuisine', v)}
              onInputChange={(_, v, reason) => reason === 'input' && set('cuisine', v)}
              renderInput={(params) => (
                <TextField {...params} label={t('editor.cuisine')} helperText={t('editor.cuisineHint')} />
              )}
            />
          </Grid>
          <Grid size={{ xs: 12, sm: 4 }}>
            <TextField label={t('editor.servings')} type="number" value={form.servings}
              onChange={(e) => set('servings', e.target.value)} error={!!errors.servings}
              helperText={errors.servings ?? t('editor.servingsHint')}
              slotProps={{ htmlInput: { min: 1 } }} />
          </Grid>
          <Grid size={{ xs: 6, sm: 4 }}>
            <TextField label={t('editor.prep')} type="number" value={form.prep}
              onChange={(e) => set('prep', e.target.value)}
              slotProps={{ htmlInput: { min: 0 }, input: { endAdornment: <InputAdornment position="end">min</InputAdornment> } }} />
          </Grid>
          <Grid size={{ xs: 6, sm: 4 }}>
            <TextField label={t('editor.cook')} type="number" value={form.cook}
              onChange={(e) => set('cook', e.target.value)}
              slotProps={{ htmlInput: { min: 0 }, input: { endAdornment: <InputAdornment position="end">min</InputAdornment> } }} />
          </Grid>
          <Grid size={12}>
            <Autocomplete<KitchenTool | { create: string }, true>
              multiple
              // Alphabetical in the interface language, not by the stored (English) names.
              options={[...tools].sort((a, b) => labels.tool(a).localeCompare(labels.tool(b)))}
              value={form.tools}
              getOptionLabel={(o) => ('create' in o ? o.create : labels.tool(o))}
              isOptionEqualToValue={(a, b) => 'id' in a && 'id' in b && a.id === b.id}
              filterOptions={(options, state) => {
                const filtered = toolFilter(options, state)
                const typed = state.inputValue.trim()
                const known = options.some(
                  (o) => 'id' in o && labels.tool(o).toLowerCase() === typed.toLowerCase(),
                )
                // Not in the list: offer to add it, as for ingredients.
                if (typed && !known) filtered.push({ create: typed })
                return filtered
              }}
              renderOption={(props, o) => {
                const { key, ...rest } = props as typeof props & { key: string }
                return (
                  <li key={key} {...rest}>
                    {'create' in o ? t('tool.addNamed', { name: o.create }) : labels.tool(o)}
                  </li>
                )
              }}
              onChange={(_, values) => {
                const created = values.find((v) => 'create' in v)
                if (created && 'create' in created) setCreatingTool(created.create)
                else set('tools', values as KitchenTool[])
              }}
              renderInput={(params) => <TextField {...params} label={t('editor.tools')} />}
            />
          </Grid>
        </Grid>
      </Section>

      <Section
        title={t('recipe.ingredients')}
        action={
          <Button startIcon={<AddIcon />} onClick={() => set('lines', [...form.lines, newLine()])}>
            {t('editor.addIngredient')}
          </Button>
        }
      >
        <Stack spacing={2}>
          {form.lines.length === 0 && (
            <Typography color="text.secondary">{t('recipe.noIngredients')}</Typography>
          )}
          {form.lines.map((line, index) => (
            <Grid container spacing={1} key={line.key}
              sx={{ alignItems: 'center', pb: 2, borderBottom: 1, borderColor: 'divider' }}>
              <Grid size={{ xs: 12, md: 5 }}>
                <IngredientPicker
                  value={line.ingredient}
                  onChange={(ingredient) =>
                    setLine(line.key, {
                      ingredient,
                      matchedFrom: undefined,
                      unit: ingredient && !line.suggestion ? ingredient.default_unit : line.unit,
                    })
                  }
                  onCreate={(name) => setCreating({ name, lineKey: line.key, suggestion: line.suggestion })}
                  error={!!line.suggestion && !line.ingredient}
                />
                {line.suggestion && !line.ingredient && (
                  <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mt: 0.5 }}>
                    <Typography variant="caption" color="warning.main">
                      {t('editor.newIngredient', { name: line.suggestion.name })}
                    </Typography>
                    <Button size="small" onClick={() =>
                      setCreating({ name: line.suggestion!.name, lineKey: line.key, suggestion: line.suggestion })}>
                      {t('editor.create')}
                    </Button>
                  </Stack>
                )}
                {line.matchedFrom && line.ingredient && (
                  <Typography variant="caption" color="warning.main" sx={{ display: 'block', mt: 0.5 }}>
                    {t('editor.similarMatch', { name: line.matchedFrom, match: line.ingredient.name })}
                  </Typography>
                )}
              </Grid>
              <Grid size={{ xs: 4, md: 2 }}>
                <TextField size="small" label={t('editor.quantity')} value={line.unit === 'tt' ? '' : line.quantity}
                  disabled={line.unit === 'tt'} inputMode="decimal"
                  onChange={(e) => setLine(line.key, { quantity: e.target.value })} />
              </Grid>
              <Grid size={{ xs: 4, md: 2 }}>
                <TextField size="small" select label={t('ingredient.unit')} value={line.unit}
                  onChange={(e) => setLine(line.key, { unit: e.target.value as Unit })}>
                  {UNITS.map((u) => (
                    <MenuItem key={u} value={u}>
                      {labels.unit(u)}
                    </MenuItem>
                  ))}
                </TextField>
              </Grid>
              <Grid size={{ xs: 4, md: 3 }} sx={{ display: 'flex', justifyContent: 'flex-end' }}>
                <Tooltip title={t('editor.moveUp')}>
                  <span>
                    <IconButton size="small" disabled={index === 0} onClick={() => moveLine(index, -1)}>
                      <ArrowUpIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
                <Tooltip title={t('editor.moveDown')}>
                  <span>
                    <IconButton size="small" disabled={index === form.lines.length - 1}
                      onClick={() => moveLine(index, 1)}>
                      <ArrowDownIcon fontSize="small" />
                    </IconButton>
                  </span>
                </Tooltip>
                <Tooltip title={t('common.delete')}>
                  <IconButton size="small"
                    onClick={() => set('lines', form.lines.filter((l) => l.key !== line.key))}>
                    <DeleteIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </Grid>
              <Grid size={{ xs: 12, md: 9 }}>
                <TextField size="small" label={t('editor.note')} placeholder={t('editor.notePlaceholder')}
                  value={line.note} onChange={(e) => setLine(line.key, { note: e.target.value })} />
              </Grid>
              <Grid size={{ xs: 12, md: 3 }}>
                <FormControlLabel
                  control={<Checkbox size="small" checked={line.optional}
                    onChange={(e) => setLine(line.key, { optional: e.target.checked })} />}
                  label={t('recipe.optional')}
                />
              </Grid>
            </Grid>
          ))}
        </Stack>
      </Section>

      <Section
        title={t('recipe.steps')}
        action={
          <Button startIcon={<AddIcon />} onClick={() => set('steps', [...form.steps, ''])}>
            {t('editor.addStep')}
          </Button>
        }
      >
        <Stack spacing={2}>
          {form.steps.map((step, index) => (
            <Stack direction="row" spacing={1} key={index} sx={{ alignItems: 'flex-start' }}>
              <Typography sx={{ pt: 1, minWidth: 24, fontWeight: 600 }}>{index + 1}.</Typography>
              <TextField multiline minRows={2} value={step} placeholder={t('editor.stepPlaceholder')}
                onChange={(e) => setStep(index, e.target.value)} />
              <IconButton onClick={() => set('steps', form.steps.filter((_, i) => i !== index))}
                aria-label={t('common.delete')}>
                <DeleteIcon fontSize="small" />
              </IconButton>
            </Stack>
          ))}
        </Stack>
      </Section>

      <Section title={t('recipe.season')}>
        <Stack spacing={3}>
          <Box>
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                {t('editor.ingredientSeason')}
              </Typography>
              {form.seasonAuto && (
                <Chip size="small" icon={<AutoIcon />} label={t('editor.computed')} variant="outlined" />
              )}
            </Stack>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              {form.seasonAuto
                ? t('editor.seasonAutoHint', { season: describeMonths(derived) })
                : t('editor.seasonUserHint')}
            </Typography>
            <SeasonPicker
              key={form.seasonAuto ? 'auto' : 'user'}
              months={seasonShown}
              onChange={(months) => setForm({ ...form, seasonAuto: false, seasonMonths: months })}
            />
            {!form.seasonAuto && (
              <Button size="small" startIcon={<AutoIcon />} sx={{ mt: 1 }}
                onClick={() => set('seasonAuto', true)}>
                {t('editor.backToComputed')}
              </Button>
            )}
          </Box>
          <Box>
            <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
              {t('editor.climateSeason')}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
              {t('editor.climateHint')}
            </Typography>
            <SeasonPicker months={form.climateMonths} onChange={(m) => set('climateMonths', m)} />
          </Box>
        </Stack>
      </Section>

      <Section title={t('editor.sharing')}>
        <Stack spacing={2}>
          <FormControlLabel
            control={
              <Switch checked={form.visibility === 'shared'}
                onChange={(e) => set('visibility', e.target.checked ? 'shared' : 'private')} />
            }
            label={t('editor.shareWithFamilies')}
          />
          <Typography variant="body2" color="text.secondary">
            {form.visibility === 'shared' ? t('editor.sharedHint') : t('editor.privateHint')}
          </Typography>
          <TextField label={t('editor.source')} value={form.sourceUrl} type="url"
            placeholder="https://" onChange={(e) => set('sourceUrl', e.target.value)} />
        </Stack>
      </Section>

      <Box sx={{ display: 'flex', justifyContent: 'flex-end', gap: 1 }}>
        <Button onClick={() => navigate(-1)}>{t('common.cancel')}</Button>
        <Button variant="contained" size="large" onClick={() => void save()} disabled={saving}>
          {t('common.save')}
        </Button>
      </Box>

      {creatingTool != null && (
        <ToolDialog
          initialName={creatingTool}
          onClose={() => setCreatingTool(null)}
          onCreated={(tool) => {
            setTools((all) => [...all, tool])
            set('tools', [...form.tools, tool])
            setCreatingTool(null)
          }}
        />
      )}

      {creating && (
        <IngredientDialog
          initialName={creating.name}
          suggestion={creating.suggestion}
          onClose={() => setCreating(null)}
          onCreated={(ingredient) => {
            const line = form.lines.find((l) => l.key === creating.lineKey)
            setLine(creating.lineKey, {
              ingredient: { ...ingredient, season_months: ingredient.season_months.months },
              // A draft line keeps the unit the assistant used with its quantity.
              unit: line?.suggestion ? line.unit : ingredient.default_unit,
            })
            setCreating(null)
          }}
        />
      )}
    </Stack>
  )
}
