import { useEffect, useMemo, useState } from 'react'
import { Search } from 'lucide-react'
import clsx from 'clsx'

import { leagueLabels } from '../lib/navigation'
import type { League } from '../types'

interface CommandItem {
  id: string
  label: string
  subtitle: string
  href: string
}

export function CommandPalette({
  open,
  onClose,
  items,
  currentLeague,
  navigate,
}: {
  open: boolean
  onClose: () => void
  items: CommandItem[]
  currentLeague: League
  navigate: (href: string) => void
}) {
  const [query, setQuery] = useState('')

  useEffect(() => {
    if (!open) setQuery('')
  }, [open])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }

    if (open) window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose, open])

  const filteredItems = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    if (!normalized) return items
    return items.filter((item) =>
      `${item.label} ${item.subtitle} ${item.href}`.toLowerCase().includes(normalized),
    )
  }, [items, query])

  if (!open) return null

  return (
    <div className="command-palette" role="dialog" aria-modal="true">
      <button className="command-palette__backdrop" aria-label="Close palette" onClick={onClose} />
      <div className="command-palette__panel">
        <div className="command-palette__header">
          <div className="command-palette__search">
            <Search size={16} />
            <input
              autoFocus
              placeholder={`Jump anywhere inside ${leagueLabels[currentLeague]}`}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </div>
        </div>
        <div className="command-palette__results">
          {filteredItems.map((item) => (
            <button
              key={item.id}
              className={clsx('command-palette__item', query && 'is-filtered')}
              onClick={() => {
                navigate(item.href)
                onClose()
              }}
            >
              <strong>{item.label}</strong>
              <span>{item.subtitle}</span>
            </button>
          ))}
          {!filteredItems.length ? (
            <div className="command-palette__empty">
              <strong>No route matches</strong>
              <span>Try “live”, “research”, or “system”.</span>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
