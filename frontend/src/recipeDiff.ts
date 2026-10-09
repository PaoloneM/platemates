import type { Recipe, RecipeLine } from './api'

// How an ingredient line differs between a variant and its original.
export type LineMark = 'added' | 'changed' | 'removed'

const perPerson = (line: RecipeLine, servings: number) =>
  line.quantity == null || line.unit === 'tt' ? null : Number(line.quantity) / servings

/** What a variant changed in the ingredients of its original: lines added or with another
 * quantity (per person, so a different number of servings is not a difference) in the
 * variant, lines removed from it in the original. */
export function compareIngredients(variant: Recipe, original: Recipe) {
  // An ingredient may appear on several lines (flour for the pastry and for the custard):
  // compare each ingredient's total per person, unit by unit.
  const totals = (recipe: Recipe) => {
    const result = new Map<number, Map<string, number | null>>()
    for (const line of recipe.ingredients) {
      const units = result.get(line.ingredient) ?? new Map<string, number | null>()
      const amount = perPerson(line, recipe.servings)
      const before = units.get(line.unit)
      units.set(line.unit, amount === null || before === null ? null : (before ?? 0) + amount)
      result.set(line.ingredient, units)
    }
    return result
  }
  const ours = totals(variant)
  const theirs = totals(original)
  const inVariant: Record<number, LineMark> = {}
  const inOriginal: Record<number, LineMark> = {}
  for (const [id, units] of ours) {
    const other = theirs.get(id)
    if (!other) {
      inVariant[id] = 'added'
      continue
    }
    const differs = units.size !== other.size || [...units].some(([unit, a]) => {
      if (!other.has(unit)) return true
      const b = other.get(unit)!
      if (a === null || b === null) return a !== b
      return Math.abs(a - b) > Math.max(a, b) * 0.05
    })
    if (differs) inVariant[id] = inOriginal[id] = 'changed'
  }
  for (const id of theirs.keys()) if (!ours.has(id)) inOriginal[id] = 'removed'
  const sameSteps = variant.steps.length === original.steps.length
    && variant.steps.every((step, i) => step.trim() === original.steps[i].trim())
  return { inVariant, inOriginal, sameSteps }
}
