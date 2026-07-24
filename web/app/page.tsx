import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import ShelfExplorer from '@/components/ShelfExplorer'
import type { DataPayload } from '@/lib/data'
import './shelf/shelf.css'

async function loadInitialPayload(): Promise<DataPayload> {
  const source = await readFile(join(process.cwd(), 'public', 'data.json'), 'utf8')
  return JSON.parse(source) as DataPayload
}

export default async function HomePage() {
  return <ShelfExplorer initialPayload={await loadInitialPayload()} />
}
