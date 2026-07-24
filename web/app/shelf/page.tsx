import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import type { Metadata } from 'next'
import ShelfExplorer from '@/components/ShelfExplorer'
import type { DataPayload } from '@/lib/data'
import './shelf.css'

export const metadata: Metadata = {
  title: 'CVS Radar｜貨架標籤版',
  description: '超商商品評價雷達的貨架邊條標籤介面試作。',
  alternates: { canonical: '/shelf' },
}

async function loadInitialPayload(): Promise<DataPayload> {
  const source = await readFile(join(process.cwd(), 'public', 'data.json'), 'utf8')
  return JSON.parse(source) as DataPayload
}

export default async function ShelfPage() {
  return <ShelfExplorer initialPayload={await loadInitialPayload()} />
}
