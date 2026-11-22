import { CakeSlice, Cookie, Croissant, CupSoda, IceCreamCone, Package, Soup, type LucideIcon } from 'lucide-react'

// Shared by the shelf card and the product page, kept hook-free so the
// server-rendered page can import it.

// One icon per category group so neighbouring cards differ at a glance.
export const CATEGORY_ICON: Record<string, LucideIcon> = {
  正餐: Soup,
  甜點: CakeSlice,
  冰品: IceCreamCone,
  飲料: CupSoda,
  麵包: Croissant,
  零食: Cookie,
  其他: Package,
}

export function scoreTone(score: number | null): string {
  if (score === null) return 'sl-na'
  if (score >= 85) return 'sl-great'
  if (score >= 70) return 'sl-good'
  if (score >= 50) return 'sl-mid'
  return 'sl-low'
}
