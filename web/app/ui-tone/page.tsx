import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import type { Metadata } from 'next'
import type { DataPayload, Product } from '@/lib/data'
import VariantBCompact from '@/components/product-detail-variants/VariantBCompact'
import VariantBCompactTones, {
  type Treatment,
} from '@/components/product-detail-variants/VariantBCompactTones'
import '../shelf.css'

export const metadata: Metadata = {
  title: 'Polarity treatments | CVS Radar',
  robots: { index: false, follow: false },
}

// Layout is settled, so this page only needs the cases where polarity reading
// actually matters: both sides present, one side only, and neither.
const CASES = [
  { id: '全家::皮蛋辣拌麵', label: '3 喜歡 / 3 留意' },
  { id: '7-11::飲料小夥伴吊飾', label: '只有喜歡' },
  { id: '7-11::切達起司貝果', label: '1 喜歡 / 3 留意' },
  { id: '全家::起司蛋糕霜淇淋', label: '3 / 3 ＋ 多作者摘要' },
  { id: '全家::紅心芭樂', label: '兩側都空' },
] as const

const TONES: Array<{ key: string; name: string; note: string; treatment: Treatment | null }> = [
  { key: 'now', name: '目前（細線 ＋／－）', note: '對照組。', treatment: null },
  { key: 't1', name: 'T1 · 分組色塊', note: '兩組各自有底色與色條，並帶小標。分組最明確，色彩面積最大。', treatment: 't1' },
  { key: 't2', name: 'T2 · 實心色塊符號', note: '不加底色，把 ＋／－ 做成白字實心方塊。最省色彩、辨識靠形狀。', treatment: 't2' },
  { key: 't3', name: 'T3 · 語意圖示', note: '用讚／警告圖示取代符號，留意側字重加粗。語意最直接。', treatment: 't3' },
]

async function loadPayload(): Promise<DataPayload> {
  const source = await readFile(join(process.cwd(), 'public', 'data.json'), 'utf8')
  return JSON.parse(source) as DataPayload
}

function pick(payload: DataPayload): Array<{ product: Product; label: string }> {
  return CASES.map(({ id, label }) => {
    const product = payload.products.find((candidate) => candidate.id === id)
    if (!product) throw new Error(`Preview product not found: ${id}`)
    return { product, label }
  })
}

export default async function UiTonePage() {
  const cases = pick(await loadPayload())

  return (
    <div className="sl-page">
      <header className="mb-5 border-b-2 border-[#17130e] pb-3">
        <h1 className="text-xl font-black text-[#17130e]">喜歡／留意的辨識度</h1>
        <p className="mt-1 text-sm font-semibold text-[#6e685d]">
          版面固定，只換辨識裝置。每種都同時用顏色與形狀，不單靠顏色。
        </p>
      </header>

      <div className="flex flex-col gap-8">
        {TONES.map((tone) => (
          <section key={tone.key} className="min-w-0">
            <h2 className="text-lg font-black text-[#17130e]">{tone.name}</h2>
            <p className="mt-1 text-sm font-semibold text-[#6e685d]">{tone.note}</p>
            <div className="mt-3 flex flex-col gap-4">
              {cases.map(({ product, label }) => (
                <article
                  key={`${tone.key}-${product.id}`}
                  className="overflow-hidden rounded-[5px] border border-[#d9d5ca] bg-white"
                >
                  <div className="border-b border-[#d9d5ca] bg-[#fbfaf6] px-3 py-1.5">
                    <p className="font-mono text-[10px] font-bold uppercase tracking-[0.12em] text-[#6e685d]">
                      {label}
                    </p>
                    <h3 className="text-sm font-black text-[#17130e]">{product.productName}</h3>
                  </div>
                  {tone.treatment ? (
                    <VariantBCompactTones product={product} treatment={tone.treatment} />
                  ) : (
                    <VariantBCompact product={product} />
                  )}
                </article>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
