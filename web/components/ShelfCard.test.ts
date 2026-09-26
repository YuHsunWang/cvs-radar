import React from 'react'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { renderToStaticMarkup } from 'react-dom/server'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'
import { Product, sortProducts } from '../lib/data'

// Next preserves JSX for its own compiler. Compile the real components locally
// for these SSR tests, including aliases, without changing the app/test config.
const require = createRequire(import.meta.url)
const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const modules = new Map<string, { exports: Record<string, unknown> }>()
function loadSource(filename: string): Record<string, unknown> {
  const cached = modules.get(filename)
  if (cached) return cached.exports
  const module = { exports: {} }
  modules.set(filename, module)
  const compiled = ts.transpileModule(readFileSync(filename, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
    fileName: filename,
  }).outputText
  const localRequire = (id: string): unknown => {
    if (!id.startsWith('@/') && !id.startsWith('.')) return require(id)
    const path = id.startsWith('@/') ? resolve(webRoot, id.slice(2)) : resolve(dirname(filename), id)
    return loadSource(`${path}${path.includes('/components/') ? '.tsx' : '.ts'}`)
  }
  new Function('require', 'module', 'exports', compiled)(localRequire, module, module.exports)
  return module.exports
}
const ShelfCard = loadSource(resolve(webRoot, 'components/ShelfCard.tsx')).default as typeof import('./ShelfCard').default
const ShelfExplorer = loadSource(resolve(webRoot, 'components/ShelfExplorer.tsx')).default as typeof import('./ShelfExplorer').default

function product(overrides: Partial<Product> = {}): Product {
  return {
    id: 'reviewed', brand: '全家', productName: '測試商品', price: 50,
    category: '飲料', fairScore: 70, recommendationScore: 78,
    consensus: '一致好評', confidence: '中', nPosts: 1, nComments: 2,
    rawComments: 2, eligibleComments: 2, uniqueEligibleCommenters: 2,
    independentThreads: 1, volumeLevel: '中等', positivePct: 60,
    neutralPct: 20, negativePct: 20, likes: [], cautions: [], excerpt: '',
    reviewProvisional: false, postUrls: [], latestDate: '2026-06-15', kcal: null,
    ...overrides,
  }
}

function card(item: Product, rank = 1, expanded = false) {
  return renderToStaticMarkup(
    React.createElement(ShelfCard, { product: item, rank, isExpanded: expanded, onToggle: () => {} }),
  )
}

describe('truthful shelf results', () => {
  it('never awards the lowest scores for occupying the first three ascending-sort positions', () => {
    const sorted = sortProducts([
      product({ id: 'high', recommendationScore: 91 }),
      product({ id: 'unknown', recommendationScore: null, confidence: '低' }),
      product({ id: 'low', recommendationScore: 12 }),
      product({ id: 'middle', recommendationScore: 45 }),
    ], 'comprehensiveAsc')

    expect(sorted.map((item) => item.id)).toEqual(['low', 'middle', 'high', 'unknown'])
    sorted.forEach((item, index) => {
      const html = card(item, index + 1)
      expect(html).not.toMatch(/sl-(?:medal|gold|silver|bronze|top)\b/)
      expect(html).toContain(`<span class="sl-slot">${String(index + 1).padStart(2, '0')}</span>`)
    })
  })

  it('shows the calibrated score in static HTML before any scroll observer or effect can run', () => {
    const html = card(product({ fairScore: 20, recommendationScore: 78 }))
    expect(html).toContain('<span class="sl-s-num">78</span>')
    expect(html).not.toContain('>0<')
  })

  it('withholds numeric scores even when an unpublishable underlying score exists', () => {
    const html = card(product({ fairScore: 70, recommendationScore: null, confidence: '低' }))
    expect(html).toContain('暫無')
    expect(html).toContain('評分・樣本少')
    expect(html).not.toContain('class="sl-s-num"')
    expect(html).not.toContain('>70<')
  })

  it('identifies post dates and historical prices without implying shelf availability', () => {
    const html = card(product())
    expect(html).toContain('最新心得 2026/06/15')
    expect(html).toContain('價格 $50')
    expect(html).not.toContain('上架')
    const missing = card(product({ latestDate: null, price: null }))
    expect(missing).toContain('心得日期不明')
    expect(missing).not.toContain('價格')
    expect(missing).not.toContain('$0')
  })

  it('shows official calories only when a catalogue value exists', () => {
    // An unmatched product must show nothing: a placeholder like 0 大卡 would
    // read as a real (and very wrong) figure.
    expect(card(product({ kcal: 318 }))).toContain('318 大卡')
    expect(card(product({ kcal: 318 }), 1, true)).toContain('取自官網標示的整份數值')
    const missing = card(product({ kcal: null }), 1, true)
    expect(missing).not.toContain('大卡')
  })

  it('names the product exactly once and names missing identity honestly', () => {
    // The expanded panel used to repeat the name so a clamped one stayed
    // readable. It no longer does, so the heading on the collapsed card is the
    // only place identity lives — and it must carry the full name, not a
    // truncated copy, or expanding would lose information.
    const name = '非常長的商品名稱'.repeat(12)
    const expanded = card(product({ productName: name }), 1, true)
    expect(expanded).toContain(`<h2 class="sl-pname">${name}</h2>`)
    expect(expanded.split(name).length - 1).toBe(1)

    const missing = card(product({ productName: '  ', category: '' }), 1, true)
    expect(missing).toContain('<h2 class="sl-pname">商品名稱待確認</h2>')
    expect(missing.split('商品名稱待確認').length - 1).toBe(1)
    expect(missing).toContain('<span class="sl-tag">其他</span>')
  })

  it('keeps sort and filter controls available even when there are no results', () => {
    const html = renderToStaticMarkup(React.createElement(ShelfExplorer, { initialPayload: {
      products: [], generatedAt: '', siteBuiltAt: '2026-09-08T00:00:00Z',
    } }))
    expect(html).toContain('排序：近期推薦')
    expect(html).toContain('全部商品')
    expect(html).toContain('篩選 0')
    expect(html).toContain('沒有符合條件的商品')
    expect(html).toContain('資料更新 更新時間不明')
    expect(html).not.toContain('2026/09/08')
    expect(html).not.toContain('上架更新')
  })
})
