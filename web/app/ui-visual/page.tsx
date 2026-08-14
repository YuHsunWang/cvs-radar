import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import type { Metadata } from 'next'
import type { DataPayload, Product } from '@/lib/data'
import VariantB from '@/components/product-detail-variants/VariantB'
import VariantBClaude from '@/components/product-detail-variants/VariantBClaude'
import VariantBCodex from '@/components/product-detail-variants/VariantBCodex'
import VariantBCompact from '@/components/product-detail-variants/VariantBCompact'
import '../shelf.css'

export const metadata: Metadata = {
  title: 'Variant B visual takes | CVS Radar',
  robots: { index: false, follow: false },
}

// Same six edge cases the A–D comparison uses, so the two rounds stay comparable.
const PREVIEW_CASES = [
  { id: '全家::皮蛋辣拌麵', label: '密集：3 喜歡／3 留意' },
  { id: '7-11::飲料小夥伴吊飾', label: '不對稱：有喜歡、無留意' },
  { id: '全家::紅心芭樂', label: '空白兩側：無喜歡／無留意' },
  { id: '全家::起司蛋糕霜淇淋', label: '多作者：摘要含「；」' },
  { id: '7-11::切達起司貝果', label: '暫定整理' },
  { id: '7-11::茶裏王茉莉龍井', label: '無作者摘要' },
] as const

const TAKES = [
  {
    key: 'base',
    name: 'B · 原樣（未做視覺）',
    description: '選定的資訊架構，仍是通用面板樣式 — 作為對照組。',
    Component: VariantB,
  },
  {
    key: 'claude',
    name: 'B · 貨架標籤背面（Claude）',
    description: '延伸 shelf.css 既有系統：暖黑墨線、mono 微標、單據紙底。',
    Component: VariantBClaude,
  },
  {
    key: 'codex',
    name: 'B · Codex 版',
    description: 'Codex 的視覺詮釋。',
    Component: VariantBCodex,
  },
  {
    key: 'compact',
    name: 'B · 緊湊版（Claude）',
    description: '同一套設計語言，拿掉每項的外框，兩種極性共用一個標題與清單。',
    Component: VariantBCompact,
  },
] as const

async function loadPayload(): Promise<DataPayload> {
  const source = await readFile(join(process.cwd(), 'public', 'data.json'), 'utf8')
  return JSON.parse(source) as DataPayload
}

function selectPreviewProducts(payload: DataPayload): Array<{ product: Product; label: string }> {
  return PREVIEW_CASES.map(({ id, label }) => {
    const product = payload.products.find((candidate) => candidate.id === id)
    if (!product) throw new Error(`Preview product not found: ${id}`)
    return { product, label }
  })
}

export default async function UiVisualPage() {
  const cases = selectPreviewProducts(await loadPayload())

  return (
    <div className="sl-page">
      <header className="mb-5 border-b-2 border-[#17130e] pb-3">
        <h1 className="text-xl font-black text-[#17130e]">Variant B — 視覺設計比較</h1>
        <p className="mt-1 text-sm font-semibold text-[#6e685d]">
          資訊架構固定，只比視覺。每組六個真實邊界案例。
        </p>
      </header>

      <div className="flex flex-col gap-8">
        {TAKES.map((take) => (
          <section key={take.key} className="min-w-0">
            <h2 className="text-lg font-black text-[#17130e]">{take.name}</h2>
            <p className="mt-1 text-sm font-semibold text-[#6e685d]">{take.description}</p>

            <div className="mt-4 flex flex-col gap-5">
              {cases.map(({ product, label }) => (
                <article
                  key={`${take.key}-${product.id}`}
                  className="overflow-hidden rounded-[5px] border border-[#d9d5ca] bg-white"
                >
                  <div className="border-b border-[#d9d5ca] bg-[#fbfaf6] px-3 py-2">
                    <p className="font-mono text-[10.5px] font-bold uppercase tracking-[0.12em] text-[#6e685d]">
                      {label}
                    </p>
                    <h3 className="text-base font-black text-[#17130e]">
                      {product.brand} · {product.productName}
                    </h3>
                  </div>
                  <take.Component product={product} />
                </article>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
