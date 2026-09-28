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
const SoftServeZone = loadSource(resolve(webRoot, 'components/SoftServeZone.tsx')).default as typeof import('./SoftServeZone').default

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

function card(item: Product, expanded = false) {
  return renderToStaticMarkup(
    React.createElement(ShelfCard, { product: item, rank: 1, isExpanded: expanded, onToggle: () => {} }),
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
    sorted.forEach((item) => {
      const html = card(item)
      expect(html).not.toMatch(/sl-(?:medal|gold|silver|bronze|top|slot)\b/)
    })
  })

  it('shows the calibrated score in static HTML before any scroll observer or effect can run', () => {
    const html = card(product({ fairScore: 20, recommendationScore: 78 }))
    expect(html).toContain('<span class="sl-score sl-good">78</span>')
    expect(html).not.toContain('>0<')
  })

  it('uses the approved 70/50 score bands and a dash when the sample cannot support a score', () => {
    for (const [score, tone] of [[70, 'good'], [69, 'mid'], [50, 'mid'], [49, 'low']] as const) {
      expect(card(product({ recommendationScore: score }))).toContain(`<span class="sl-score sl-${tone}">${score}</span>`)
    }
    const html = card(product({ fairScore: 70, recommendationScore: null, confidence: '低' }))
    expect(html).toContain('<span class="sl-score sl-na">—</span>')
    expect(html).not.toContain('>70<')
    const css = readFileSync(resolve(webRoot, 'app/shelf.css'), 'utf8')
    for (const [tone, background, color] of [
      ['good', '#e2f2e7', '#176b3a'],
      ['mid', '#fbefd6', '#7a5500'],
      ['low', '#fbe3df', '#a52a20'],
      ['na', '#eeedea', '#6e685e'],
    ]) {
      expect(css).toContain(`.sl-score.sl-${tone} { background: ${background}; color: ${color}; }`)
    }
  })

  it('places each channel colour only on its dot, including the unknown fallback', () => {
    const css = readFileSync(resolve(webRoot, 'app/shelf.css'), 'utf8')
    for (const [brand, color] of [
      ['7-11', '#f26522'], ['全家', '#00a651'], ['萊爾富', '#1f4fa8'],
      ['OK', '#f5a623'], ['美廉社', '#6c3dbf'],
    ]) {
      expect(card(product({ brand }))).toContain(`<span class="sl-channel-dot" data-brand="${brand}" aria-hidden="true"></span>${brand}`)
      expect(css).toContain(`.sl-channel-dot[data-brand="${brand}"] { background: ${color}; }`)
    }
    expect(card(product({ brand: '不明通路' }))).toContain('<span class="sl-channel-dot" data-brand="其他" aria-hidden="true"></span>其他')
    expect(css).toContain('border-radius: 50%; background: #9ca3af;')
    expect(css).not.toContain('--sl-brand')
  })

  it('keeps price in the quiet meta line and post dates in expanded detail', () => {
    const html = card(product())
    expect(html).toContain('$50 · 1 篇心得')
    expect(html).not.toContain('最新心得 2026/06/15')
    expect(card(product(), true)).toContain('最新心得 2026/06/15')
    expect(html).not.toContain('上架')
    const missing = card(product({ latestDate: null, price: null }))
    expect(missing).toContain('1 篇心得')
    expect(missing).not.toContain(' · 1 篇心得')
    expect(missing).not.toContain('$0')
    expect(card(product({ latestDate: null }), true)).toContain('心得日期不明')
  })

  it('shows official calories only when a catalogue value exists', () => {
    // An unmatched product must show nothing: a placeholder like 0 大卡 would
    // read as a real (and very wrong) figure.
    expect(card(product({ kcal: 318 }))).not.toContain('318 大卡')
    expect(card(product({ kcal: 318 }), true)).toContain('取自官網標示的整份數值')
    const missing = card(product({ kcal: null }), true)
    expect(missing).not.toContain('大卡')
  })

  it('names the product exactly once and names missing identity honestly', () => {
    // The expanded panel used to repeat the name so a clamped one stayed
    // readable. It no longer does, so the heading on the collapsed card is the
    // only place identity lives — and it must carry the full name, not a
    // truncated copy, or expanding would lose information.
    const name = '非常長的商品名稱'.repeat(12)
    const expanded = card(product({ productName: name }), true)
    expect(expanded).toContain(`<h2 class="sl-pname">${name}</h2>`)
    expect(expanded.split(name).length - 1).toBe(1)

    const missing = card(product({ productName: '  ', category: '' }), true)
    expect(missing).toContain('<h2 class="sl-pname">商品名稱待確認</h2>')
    expect(missing.split('商品名稱待確認').length - 1).toBe(1)
    expect(missing).toContain('分類：其他')
  })

  it('reserves the card face for channel, name, meta and score while keeping context in detail', () => {
    const item = product({ consensus: '褒貶不一', likes: ['香氣足'], cautions: ['偏甜'], kcal: 318 })
    const collapsed = card(item)
    expect(collapsed).toContain('<span class="sl-channel"><span class="sl-channel-dot" data-brand="全家" aria-hidden="true"></span>全家</span>')
    expect(collapsed).not.toMatch(/sl-rail|聲量|褒貶不一|香氣足|318 大卡|分類：/)
    const expanded = card(item, true)
    expect(expanded).toContain('分類：飲料')
    expect(expanded).toContain('共識：褒貶不一')
    expect(expanded).toContain('目前列表第 1 項')
    expect(expanded).toContain('討論量：3')
    expect(expanded).toContain('2 位網友留言')
    expect(expanded).toContain('香氣足')
    expect(expanded).toContain('偏甜')
  })

  it('keeps sort and filter controls available even when there are no results', () => {
    const html = renderToStaticMarkup(React.createElement(ShelfExplorer, { initialPayload: {
      products: [], generatedAt: '', siteBuiltAt: '2026-09-08T00:00:00Z',
    } }))
    // Default sort is score high→low so the list opens on the scan the card is built for.
    expect(html).toContain('排序：評分高→低')
    expect(html).toContain('全部商品')
    // Product counts were dropped from the page on purpose; they add nothing to picking a product.
    expect(html).not.toContain('本區')
    expect(html).not.toContain('項商品')
    expect(html).toContain('篩選 0')
    expect(html).toContain('沒有符合條件的商品')
    expect(html).toContain('更新時間不明')
    expect(html).not.toContain('2026/09/08')
    expect(html).not.toContain('上架更新')
  })

  it('does not show a product count on the soft-serve page either', () => {
    // Counts were dropped site-wide; the soft-serve aisle bar must not bring one back.
    const html = renderToStaticMarkup(React.createElement(SoftServeZone, { initialPayload: {
      products: [product({ productName: '香草霜淇淋', category: '冰品' })], generatedAt: '', siteBuiltAt: '',
    } }))
    expect(html).toContain('分數＝綜合評分／滿分 100')
    expect(html).not.toContain('本區')
  })
})
