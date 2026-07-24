import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import type { Metadata } from 'next'
import ProductExplorer from '@/components/ProductExplorer'
import type { DataPayload } from '@/lib/data'

export const metadata: Metadata = {
  title: 'CVS Radar｜經典版',
  description: '超商商品評價雷達的經典卡片列表介面。',
  alternates: { canonical: '/classic' },
}

async function loadInitialPayload(): Promise<DataPayload> {
  const source = await readFile(join(process.cwd(), 'public', 'data.json'), 'utf8')
  return JSON.parse(source) as DataPayload
}

export default async function ClassicPage() {
  return <ProductExplorer initialPayload={await loadInitialPayload()} />
}
