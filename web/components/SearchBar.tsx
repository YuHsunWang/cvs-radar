import { Search, X } from 'lucide-react'

type SearchBarProps = {
  value: string
  onChange: (value: string) => void
}

export default function SearchBar({ value, onChange }: SearchBarProps) {
  return (
    <label className="sl-search">
      <span className="sr-only">搜尋商品或品牌</span>
      <Search aria-hidden="true" size={19} className="sl-search-icon" />
      <input
        type="search"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder="搜尋商品或品牌"
        className="sl-search-input"
      />
      {value ? (
        <button
          type="button"
          aria-label="清除搜尋"
          onClick={() => onChange('')}
          className="sl-search-clear"
        >
          <X size={17} aria-hidden="true" />
        </button>
      ) : null}
    </label>
  )
}
