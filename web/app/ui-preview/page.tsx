import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import type { Metadata } from 'next'
import type { DataPayload, Product } from '@/lib/data'
import VariantA from '@/components/product-detail-variants/VariantA'
import VariantB from '@/components/product-detail-variants/VariantB'
import VariantC from '@/components/product-detail-variants/VariantC'
import VariantD from '@/components/product-detail-variants/VariantD'

export const metadata: Metadata = {
  title: 'Review UI variants | CVS Radar',
  robots: { index: false, follow: false },
}

const PREVIEW_CASES = [
  { id: '全家::皮蛋辣拌麵', label: '密集：3 喜歡／3 留意' },
  { id: '7-11::飲料小夥伴吊飾', label: '不對稱：有喜歡、無留意' },
  { id: '全家::紅心芭樂', label: '空白兩側：無喜歡／無留意' },
  { id: '全家::起司蛋糕霜淇淋', label: '多作者：摘要含「；」' },
  { id: '7-11::切達起司貝果', label: '暫定整理' },
  { id: '7-11::茶裏王茉莉龍井', label: '無作者摘要' },
] as const

const VARIANTS = [
  {
    key: 'a',
    name: 'Variant A · 作者先說',
    description: '把濃縮作者摘要放在最前面，再用兩側清單補上取捨。',
    Component: VariantA,
  },
  {
    key: 'b',
    name: 'Variant B · 評價標籤',
    description: '先掃描可快速辨識的短標籤，作者摘要退到補充位置。',
    Component: VariantB,
  },
  {
    key: 'c',
    name: 'Variant C · 訊號平衡',
    description: '先看兩側數量與相對份量，空側直接讓位給明確提示。',
    Component: VariantC,
  },
  {
    key: 'd',
    name: 'Variant D · 現場筆記',
    description: '把多作者摘要做成短筆記流，再把證據壓成兩句行動提示。',
    Component: VariantD,
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

export default async function UiPreviewPage() {
  const products = selectPreviewProducts(await loadPayload())

  return (
    <main className="min-h-screen w-full overflow-x-hidden bg-[#F7F5EF] px-3 py-6 text-slate-950 sm:px-6 sm:py-10">
      <div className="mx-auto w-full max-w-3xl">
        <header className="min-w-0">
          <p className="text-xs font-black uppercase tracking-[0.18em] text-[#0F7C7C]">CVS Radar · UI review</p>
          <h1 className="mt-2 break-words text-2xl font-black tracking-tight sm:text-3xl">Expanded review variants</h1>
          <p className="mt-2 max-w-2xl text-sm font-semibold leading-6 text-slate-600">
            同一批真實產品、四種閱讀順序；請特別檢查 360px 下空白兩側是否像有意設計。
          </p>
        </header>

        <div className="mt-8 space-y-10">
          {VARIANTS.map(({ key, name, description, Component }) => (
            <section key={key} className="min-w-0">
              <div className="min-w-0 border-b-2 border-slate-900 pb-3">
                <p className="text-xs font-black uppercase tracking-[0.16em] text-slate-500">{key}</p>
                <h2 className="mt-1 break-words text-xl font-black">{name}</h2>
                <p className="mt-1 break-words text-sm font-semibold leading-5 text-slate-600">{description}</p>
              </div>

              <div className="mt-4 space-y-5">
                {products.map(({ product, label }) => (
                  <article
                    key={product.id}
                    className="min-w-0 overflow-hidden rounded-xl border border-slate-300 bg-white/70 p-3 shadow-sm"
                  >
                    <header className="flex min-w-0 flex-wrap items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="text-xs font-black text-[#0F7C7C]">{label}</p>
                        <h3 className="mt-1 break-words text-base font-black text-slate-950">
                          {product.brand} · {product.productName}
                        </h3>
                      </div>
                      <p className="shrink-0 text-right text-xs font-bold leading-5 text-slate-500">
                        喜歡 {product.likes.length} · 留意 {product.cautions.length}
                        <br />
                        {product.excerpt ? '有作者摘要' : '無作者摘要'}
                      </p>
                    </header>
                    <Component product={product} />
                  </article>
                ))}
              </div>
            </section>
          ))}
        </div>
      </div>
    </main>
  )
}
