import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  metadataBase: new URL('https://cvs-radar.vercel.app/'),
  title: 'CVS Radar | 超商商品評價雷達',
  description: '整合 PTT CVS 公開心得、留言情緒、可信度權重與貝氏評分的手機優先超商商品推薦工具。',
  keywords: ['超商新品', '便利商店', 'PTT CVS', '情感分析', 'NLP', '商品推薦'],
  alternates: {
    canonical: './',
  },
  openGraph: {
    title: 'CVS Radar | 超商商品評價雷達',
    description: '把分散的超商商品心得整理成推薦分、共識、聲量與可查證的購買依據。',
    url: './',
    siteName: 'CVS Radar',
    locale: 'zh_TW',
    type: 'website',
  },
  twitter: {
    card: 'summary',
    title: 'CVS Radar | 超商商品評價雷達',
    description: '以 NLP、可信度權重與貝氏評分整理超商商品心得。',
  },
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="zh-Hant-TW">
      <body>{children}</body>
    </html>
  )
}
