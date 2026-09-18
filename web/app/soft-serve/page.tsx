import type { Metadata } from 'next'
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import SoftServeZone from '@/components/SoftServeZone'
import type { DataPayload } from '@/lib/data'
import '../shelf.css'
import '../soft-serve.css'

export const metadata: Metadata = {
  title: '霜淇淋專區 | CVS Radar',
  description:
    '全家與 7-11 期間限定霜淇淋的 PTT 評價整理:同一口味單吃與雙拼的綜合評分對照,以及最新討論時間。',
  alternates: { canonical: './' },
  openGraph: {
    title: '霜淇淋專區 | CVS Radar',
    description: '同一口味單吃好還是雙拼好?用 PTT 討論的綜合評分直接對照。',
    url: './',
  },
}

async function loadInitialPayload(): Promise<DataPayload> {
  const source = await readFile(join(process.cwd(), 'public', 'data.json'), 'utf8')
  return JSON.parse(source) as DataPayload
}

export default async function SoftServePage() {
  return <SoftServeZone initialPayload={await loadInitialPayload()} />
}
