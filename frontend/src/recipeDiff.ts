import type { Recipe, RecipeLine } from './api'

// How an ingredient line differs between a variant and its original.
export type LineMark = 'added' | 'changed' | 'removed'

const perPerson = (line: RecipeLine, servings: number) =>
  line.quantity == null || line.unit === 'tt' ? null : Number(line.quantity) / servings

/** What a variant changed in the ingredients of its original: lines added or with another
 * quantity (per person, so a different number of servings is not a difference) in the
 * variant, lines removed from it in the original. */
export function compareIngredients(variant: Recipe, original: Recipe) {
  const theirs = new Map(original.ingredients.map((line) => [line.ingredient, line]))
  const ours = new Map(variant.ingredients.map((line) => [line.ingredient, line]))
  const inVariant: Record<number, LineMark> = {}
  const inOriginal: Record<number, LineMark> = {}
  for (const [id, line] of ours) {
    const other = theirs.get(id)
    if (!other) {
      inVariant[id] = 'added'
      continue
    }
    const a = perPerson(line, variant.servings)
    const b = perPerson(other, original.servings)
    const differs = line.unit !== other.unit || (a === null) !== (b === null)
      || (a !== null && b !== null && Math.abs(a - b) > Math.max(a, b) * 0.05)
    if (differs) inVariant[id] = inOriginal[id] = 'changed'
  }
  for (const id of theirs.keys()) if (!ours.has(id)) inOriginal[id] = 'removed'
  const sameSteps = variant.steps.length === original.steps.length
    && variant.steps.every((step, i) => step.trim() === original.steps[i].trim())
  return { inVariant, inOriginal, sameSteps }
}
