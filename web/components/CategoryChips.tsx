import { categoryKeys, type CategoryKey } from '@/lib/data'

type CategoryChipsProps = {
  selectedCategory: CategoryKey | null
  onSelect: (category: CategoryKey | null) => void
}

export default function CategoryChips({ selectedCategory, onSelect }: CategoryChipsProps) {
  return (
    <section aria-labelledby="category-filter-label">
      <h2 id="category-filter-label" className="mb-2 text-sm font-black text-slate-700">
        想吃什麼？
      </h2>
      <div className="flex flex-wrap gap-2" aria-label="商品分類">
        <button
          type="button"
          aria-pressed={selectedCategory === null}
          onClick={() => onSelect(null)}
          className="min-h-11 rounded-full border border-slate-300 bg-white px-3 py-2 text-sm font-black text-slate-700 transition hover:border-[#0F7C7C] data-[selected=true]:border-[#0F7C7C] data-[selected=true]:bg-[#0F7C7C] data-[selected=true]:text-white"
          data-selected={selectedCategory === null}
        >
          全部
        </button>
        {categoryKeys.map((category) => {
          const selected = selectedCategory === category
          return (
            <button
              key={category}
              type="button"
              aria-pressed={selected}
              onClick={() => onSelect(selected ? null : category)}
              className="min-h-11 rounded-full border border-slate-300 bg-white px-3 py-2 text-sm font-black text-slate-700 transition hover:border-[#0F7C7C] data-[selected=true]:border-[#0F7C7C] data-[selected=true]:bg-[#0F7C7C] data-[selected=true]:text-white"
              data-selected={selected}
            >
              {category}
            </button>
          )
        })}
      </div>
    </section>
  )
}
