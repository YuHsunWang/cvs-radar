import { Search, X } from 'lucide-react'

type SearchBarProps = {
  value: string
  onChange: (value: string) => void
}

export default function SearchBar({ value, onChange }: SearchBarProps) {
  return (
    <label className="relative block">
      <span className="sr-only">搜尋商品或品牌</span>
      <Search aria-hidden="true" size={19} className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-slate-400" />
      <input
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="搜尋商品或品牌"
        className="w-full appearance-none rounded-lg border border-slate-200 bg-white py-3 pl-11 pr-11 text-base font-semibold text-slate-900 shadow-sm outline-none placeholder:text-slate-400 focus:border-[#0F7C7C] focus:ring-2 focus:ring-[#0F7C7C]/20 [&::-webkit-search-cancel-button]:appearance-none"
      />
      {value ? (
        <button
          type="button"
          aria-label="清除搜尋"
          onClick={() => onChange('')}
          className="absolute right-2 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-md text-slate-500 hover:bg-slate-100"
        >
          <X size={18} />
        </button>
      ) : null}
    </label>
  )
}
