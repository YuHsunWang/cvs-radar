import { ExternalLink } from 'lucide-react'
import { trackOutboundPttClick } from '@/lib/analytics'
import type { Product } from '@/lib/data'

export type VariantProps = {
  product: Product
}

export function excerptSegments(product: Product): string[] {
  if (!product.excerpt) return []
  return product.excerpt
    .split('；')
    .map((segment) => segment.trim())
    .filter(Boolean)
}

export function ProvisionalNote({ product }: VariantProps) {
  if (!product.reviewProvisional) return null

  return (
    <p className="mt-2 text-xs font-bold text-amber-700" role="note">
      暫定整理，模型標註完成後會更新
    </p>
  )
}

export function SourceLinks({ product }: VariantProps) {
  if (product.postUrls.length === 0) return null

  return (
    <section className="mt-4 border-t border-slate-200 pt-4">
      <h3 className="flex items-center gap-2 font-black text-slate-950">
        <ExternalLink size={20} className="text-[#0F7C7C]" aria-hidden="true" />
        原文連結
      </h3>
      <div className="mt-2 flex min-w-0 flex-wrap gap-2">
        {product.postUrls.map((url, index) => (
          <a
            key={url}
            href={url}
            target="_blank"
            rel="noreferrer"
            onClick={() => trackOutboundPttClick(product.id)}
            aria-label={`${product.productName}原文 ${index + 1}，另開新分頁`}
            className="inline-flex max-w-full items-center gap-1 rounded-md px-2 py-1 text-sm font-bold text-[#0F7C7C] underline decoration-[#0F7C7C]/30 underline-offset-4 hover:bg-[#0F7C7C]/5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[#0F7C7C]"
          >
            原文 {index + 1}
            <ExternalLink size={14} aria-hidden="true" />
          </a>
        ))}
      </div>
    </section>
  )
}
