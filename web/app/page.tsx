import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import ShelfExplorer from '@/components/ShelfExplorer'
import { parseDataPayload, type DataPayload } from '@/lib/data'
// Before shelf.css so the tour overrides there win at equal specificity.
import 'driver.js/dist/driver.css'
import './shelf.css'

async function loadInitialPayload(): Promise<DataPayload> {
  const source = await readFile(join(process.cwd(), 'public', 'data.json'), 'utf8')
  return parseDataPayload(source)
}

export default async function HomePage() {
  return <ShelfExplorer initialPayload={await loadInitialPayload()} />
}
