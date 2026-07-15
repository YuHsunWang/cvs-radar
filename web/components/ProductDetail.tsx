import { ExternalLink, MessageSquareText, ThumbsUp, TriangleAlert, UserRound } from 'lucide-react'
import { Product } from '@/lib/data'

type ProductDetailProps = {
  product: Product
}

export default function ProductDetail({ product }: ProductDetailProps) {
  const hasPosts = product.postUrls.length > 0

  return (
    <div className="mt-4 rounded-lg border border-slate-200 bg-[#FFFDF8] p-3">
      <section>
        <h3 className="flex items-center gap-2 font-black text-slate-950">
          <UserRound size={20} className="text-[#0F7C7C]" aria-hidden="true" />
          作者評價
        </h3>
        <blockquote className="mt-3 rounded-r-md border-l-4 border-[#0F7C7C] bg-slate-50 px-3 py-2.5 text-sm font-semibold leading-6 text-slate-700">
          {product.excerpt || '未擷取到足夠的作者評價，請查看原文。'}
        </blockquote>
      </section>

      <section className="mt-4 border-t border-slate-200 pt-4">
        <h3 className="flex items-center gap-2 font-black text-slate-950">
          <MessageSquareText size={20} className="text-[#0F7C7C]" aria-hidden="true" />
          留言評價
        </h3>
        <div className="mt-3 grid grid-cols-1 gap-3 rounded-lg border border-slate-200 p-3 min-[380px]:grid-cols-2">
          <div>
            <h4 className="mb-2 flex items-center gap-1.5 font-black text-[#0F7C7C]">
              <ThumbsUp size={17} aria-hidden="true" />
              大家喜歡的點
            </h4>
            <ul className="space-y-1 text-sm font-semibold text-slate-700">
              {(product.likes.length ? product.likes : ['無']).slice(0, 4).map((item) => (
                <li key={item}>• {item}</li>
              ))}
            </ul>
          </div>
          <div className="border-t border-slate-200 pt-3 min-[380px]:border-l min-[380px]:border-t-0 min-[380px]:pl-3 min-[380px]:pt-0">
            <h4 className="mb-2 flex items-center gap-1.5 font-black text-[#D64545]">
              <TriangleAlert size={17} aria-hidden="true" />
              需要留意的點
            </h4>
            <ul className="space-y-1 text-sm font-semibold text-slate-700">
              {(product.cautions.length ? product.cautions : ['無']).slice(0, 4).map((item) => (
                <li key={item}>• {item}</li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {hasPosts ? (
        <section className="mt-4 border-t border-slate-200 pt-4">
          <h3 className="flex items-center gap-2 font-black text-slate-950">
            <ExternalLink size={20} className="text-[#0F7C7C]" aria-hidden="true" />
            原文連結
          </h3>
          <div className="mt-2 flex flex-wrap gap-2">
            {product.postUrls.map((url, index) => (
              <a
                key={url}
                href={url}
                target="_blank"
                rel="noreferrer"
                aria-label={`${product.productName}原文 ${index + 1}，另開新分頁`}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-sm font-bold text-[#0F7C7C] underline decoration-[#0F7C7C]/30 underline-offset-4 hover:bg-[#0F7C7C]/5"
              >
                原文 {index + 1}
                <ExternalLink size={14} aria-hidden="true" />
              </a>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  )
}
