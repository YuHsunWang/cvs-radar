import { brands } from '@/lib/data'

const brandStyles: Record<string, string> = {
  '7-11': 'border-[#007A53] text-[#007A53] data-[selected=true]:bg-[#007A53]',
  全家: 'border-[#0B75D1] text-[#0B75D1] data-[selected=true]:bg-[#0B75D1]',
  萊爾富: 'border-[#E51F26] text-[#E51F26] data-[selected=true]:bg-[#E51F26]',
  OK: 'border-[#EF7D00] text-[#D66F00] data-[selected=true]:bg-[#EF7D00]',
  美聯社: 'border-[#6C3DBF] text-[#6C3DBF] data-[selected=true]:bg-[#6C3DBF]',
  其他: 'border-slate-500 text-slate-500 data-[selected=true]:bg-slate-500',
}

type BrandChipsProps = {
  selectedBrand: string | null
  onSelect: (brand: string | null) => void
}

export default function BrandChips({ selectedBrand, onSelect }: BrandChipsProps) {
  return (
    <div className="flex flex-wrap gap-2.5" aria-label="便利商店品牌">
      {brands.map((brand) => {
        const selected = selectedBrand === brand
        return (
          <button
            key={brand}
            type="button"
            aria-pressed={selected}
            data-selected={selected}
            onClick={() => onSelect(selected ? null : brand)}
            className={`${brandStyles[brand]} rounded-full border-2 bg-white px-4 py-2 text-base font-black transition data-[selected=true]:text-white`}
          >
            {brand}
          </button>
        )
      })}
    </div>
  )
}
