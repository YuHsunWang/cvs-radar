import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import ProductExplorer from '@/components/ProductExplorer'
import type { DataPayload } from '@/lib/data'

async function loadInitialPayload(): Promise<DataPayload> {
  const source = await readFile(join(process.cwd(), 'public', 'data.json'), 'utf8')
  return JSON.parse(source) as DataPayload
}

export default async function HomePage() {
  return <ProductExplorer initialPayload={await loadInitialPayload()} />
}
