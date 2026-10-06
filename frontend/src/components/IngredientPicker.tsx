import { Autocomplete, TextField, createFilterOptions } from '@mui/material'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type Ingredient, type Paginated } from '../api'

export type PickedIngredient = Pick<Ingredient, 'id' | 'name' | 'category' | 'default_unit'> & {
  season_months: number[]
}

type Option = PickedIngredient | { create: string }

const filter = createFilterOptions<Option>()

/**
 * Searches the shared ingredient catalog as the user types (name or alias). When nothing
 * matches exactly, offers to add the typed name as a new ingredient.
 */
export function IngredientPicker({
  value,
  onChange,
  onCreate,
  error,
}: {
  value: PickedIngredient | null
  onChange: (ingredient: PickedIngredient | null) => void
  onCreate: (name: string) => void
  error?: boolean
}) {
  const { t } = useTranslation()
  const [input, setInput] = useState('')
  const [options, setOptions] = useState<PickedIngredient[]>([])

  useEffect(() => {
    const term = input.trim()
    if (!term) return
    let cancelled = false
    const timer = setTimeout(() => {
      api<Paginated<Ingredient>>(`/ingredients/?search=${encodeURIComponent(term)}`)
        .then((page) => {
          if (cancelled) return
          setOptions(page.results.map((i) => ({ ...i, season_months: i.season_months.months })))
        })
        .catch(() => undefined)
    }, 200)
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [input])

  return (
    <Autocomplete<Option>
      value={value}
      options={input.trim() ? options : []}
      filterOptions={(opts, state) => {
        const filtered = filter(opts, state)
        const term = state.inputValue.trim().toLowerCase()
        const exact = opts.some((o) => 'name' in o && o.name === term)
        if (term && !exact) filtered.push({ create: state.inputValue.trim() })
        return filtered
      }}
      getOptionLabel={(o) => ('create' in o ? o.create : o.name)}
      isOptionEqualToValue={(a, b) => 'id' in a && 'id' in b && a.id === b.id}
      renderOption={(props, o) => {
        const { key, ...rest } = props as typeof props & { key: string }
        return (
          <li key={key} {...rest}>
            {'create' in o ? t('ingredient.addNamed', { name: o.create }) : o.name}
          </li>
        )
      }}
      onInputChange={(_, v) => setInput(v)}
      onChange={(_, o) => {
        if (o && 'create' in o) onCreate(o.create)
        else onChange(o)
      }}
      noOptionsText={t('ingredient.typeToSearch')}
      renderInput={(params) => (
        <TextField {...params} label={t('recipe.ingredient')} size="small" error={error} />
      )}
    />
  )
}
