import { useMemo, useState } from 'react'
import { ChevronDown, ChevronUp, X } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'

import { EmptyState, ErrorState, LoadingPanel, TeamLogo } from '../components/ui'
import {
  getComboBoard,
  getComboCollection,
  getComboPositions,
  getComboState,
  logComboTrade,
  previewComboTrade,
} from '../lib/api'
import { formatDateTime, money, pct0 } from '../lib/format'
import { isLeague, normalizeLeague } from '../lib/navigation'
import { teamAccent } from '../lib/teamColor'
import type { ComboCollectionRecord, ComboLegRecord, League, PositionRecord } from '../types'

const MAX_LEGS = 8

const MARKET_TYPE_LABELS: Record<string, string> = {
  winner: 'Moneyline',
  spread: 'Spread',
  total: 'Game Total',
  points: 'Player Points',
  assists: 'Player Assists',
  rebounds: 'Player Rebounds',
  blocks: 'Player Blocks',
  steals: 'Player Steals',
  threes: 'Player 3-Pointers',
}

const MARKET_TYPE_ORDER = ['winner', 'spread', 'total', 'points', 'assists', 'rebounds', 'blocks', 'steals', 'threes']

function edgeTone(edge: number | null | undefined) {
  const e = Number(edge ?? 0)
  if (e >= 0.08) return 'strong'
  if (e >= 0.03) return 'good'
  if (e >= 0) return 'neutral'
  return 'bad'
}

function ProbBar({ model, market }: { model: number; market: number }) {
  return (
    <div className="kalshi-prob-bar">
      <div className="kalshi-prob-bar__track">
        <div className="kalshi-prob-bar__fill kalshi-prob-bar__fill--model" style={{ width: `${Math.round(model * 100)}%` }} />
      </div>
      <div className="kalshi-prob-bar__track">
        <div className="kalshi-prob-bar__fill kalshi-prob-bar__fill--market" style={{ width: `${Math.round(market * 100)}%` }} />
      </div>
    </div>
  )
}

function LegRow({
  leg,
  selected,
  disabled,
  onToggle,
}: {
  leg: ComboLegRecord
  selected: boolean
  disabled: boolean
  onToggle: () => void
}) {
  const model = Number(leg.model_prob ?? 0)
  const market = Number(leg.market_prob ?? leg.entry_price ?? 0)
  const tone = edgeTone(leg.edge)

  return (
    <button
      className={`kalshi-leg-row ${selected ? 'kalshi-leg-row--selected' : ''} ${disabled ? 'kalshi-leg-row--disabled' : ''}`}
      onClick={onToggle}
      disabled={disabled && !selected}
    >
      <div className="kalshi-leg-row__label">
        <span className="kalshi-leg-row__display">{leg.display ?? leg.title ?? leg.market_ticker}</span>
        <ProbBar model={model} market={market} />
        <div className="kalshi-leg-row__bar-labels">
          <span className="kalshi-leg-row__bar-label kalshi-leg-row__bar-label--model">Model</span>
          <span className="kalshi-leg-row__bar-label kalshi-leg-row__bar-label--market">Market</span>
        </div>
      </div>
      <div className="kalshi-leg-row__right">
        <div className={`kalshi-prob-btn kalshi-prob-btn--${tone}`}>
          {pct0(model)}
        </div>
        <div className="kalshi-leg-row__market-prob">{pct0(market)}</div>
      </div>
    </button>
  )
}

function MarketSection({
  type,
  legs,
  selectedLegs,
  onToggleLeg,
  maxReached,
}: {
  type: string
  legs: ComboLegRecord[]
  selectedLegs: string[]
  onToggleLeg: (ticker: string) => void
  maxReached: boolean
}) {
  const [open, setOpen] = useState(type === 'winner' || type === 'spread')
  const isPlayerProp = !['winner', 'spread', 'total'].includes(type)
  const grouped: Record<string, ComboLegRecord[]> = {}

  for (const leg of legs) {
    const key = (isPlayerProp && leg.player) ? leg.player : '__game__'
    grouped[key] = grouped[key] ?? []
    grouped[key].push(leg)
  }

  const label = MARKET_TYPE_LABELS[type] ?? type

  return (
    <div className="kalshi-section">
      <button className="kalshi-section__header" onClick={() => setOpen((o) => !o)}>
        <span className="kalshi-section__title">{label}</span>
        <span className="kalshi-section__count">{legs.length}</span>
        {open ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
      </button>

      {open && (
        <div className="kalshi-section__body">
          {Object.entries(grouped).map(([player, playerLegs]) => (
            <div key={player} className="kalshi-player-group">
              {player !== '__game__' && (
                <div className="kalshi-player-group__header">{player}</div>
              )}
              {playerLegs.map((leg) => {
                const ticker = String(leg.market_ticker)
                const sel = selectedLegs.includes(ticker)
                return (
                  <LegRow
                    key={ticker}
                    leg={leg}
                    selected={sel}
                    disabled={maxReached && !sel}
                    onToggle={() => onToggleLeg(ticker)}
                  />
                )
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

interface PlacedReceipt {
  legs: ComboLegRecord[]
  stake: number
  payout: number
  modelProb: number
  marketProb: number
  game: string
}

function ComboTicket({
  collection,
  selectedLegs,
  allLegs,
  onRemoveLeg,
  onClear,
  onTradeConfirmed,
  bankrollCash,
}: {
  collection: ComboCollectionRecord | null
  selectedLegs: string[]
  allLegs: ComboLegRecord[]
  onRemoveLeg: (ticker: string) => void
  onClear: () => void
  onTradeConfirmed: (receipt: PlacedReceipt) => void
  bankrollCash: number
}) {
  const [stake, setStake] = useState(50)
  const queryClient = useQueryClient()

  const selectedLegRecords = useMemo(
    () => allLegs.filter((l) => selectedLegs.includes(String(l.market_ticker))),
    [allLegs, selectedLegs],
  )

  const previewQuery = useQuery({
    queryKey: ['combo-preview', collection?.collection_ticker, selectedLegs, stake],
    queryFn: () => previewComboTrade(String(collection?.collection_ticker ?? ''), selectedLegs, stake),
    enabled: Boolean(collection?.collection_ticker && selectedLegs.length >= 2 && stake > 0),
    refetchInterval: selectedLegs.length >= 2 ? 20_000 : false,
  })

  const placeMutation = useMutation({
    mutationFn: () => logComboTrade(String(collection?.collection_ticker ?? ''), selectedLegs, stake),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['combo-state'] })
      void queryClient.invalidateQueries({ queryKey: ['combo-positions'] })
      const preview = previewQuery.data?.trade
      onTradeConfirmed({
        legs: selectedLegRecords,
        stake,
        payout: Number(preview?.payout_if_win ?? 0),
        modelProb: Number(preview?.model_prob ?? 0),
        marketProb: Number(preview?.market_prob ?? 0),
        game: collection ? `${collection.away_team} @ ${collection.home_team}` : '',
      })
    },
  })

  const preview = previewQuery.data?.trade

  if (selectedLegs.length === 0) {
    return (
      <div className="kalshi-ticket kalshi-ticket--empty">
        <div className="kalshi-ticket__empty-icon">◈</div>
        <strong>Build your combo</strong>
        <p>Select 2–{MAX_LEGS} legs from the left to build a same-game combo.</p>
      </div>
    )
  }

  return (
    <div className="kalshi-ticket">
      <div className="kalshi-ticket__header">
        <div>
          <span className="kalshi-ticket__kicker">Combo ticket</span>
          <strong className="kalshi-ticket__leg-count">{selectedLegs.length} leg{selectedLegs.length !== 1 ? 's' : ''}</strong>
        </div>
        <button className="kalshi-ticket__clear" onClick={onClear} title="Clear all">
          <X size={14} />
        </button>
      </div>

      <div className="kalshi-ticket__legs">
        {selectedLegRecords.map((leg) => (
          <div key={String(leg.market_ticker)} className="kalshi-ticket__leg">
            <span>{leg.display ?? leg.title}</span>
            <div className="kalshi-ticket__leg-right">
              <strong>{pct0(leg.model_prob)}</strong>
              <button className="kalshi-ticket__leg-remove" onClick={() => onRemoveLeg(String(leg.market_ticker))}>
                <X size={12} />
              </button>
            </div>
          </div>
        ))}
      </div>

      <div className="kalshi-ticket__stake">
        <label>Stake</label>
        <div className="kalshi-ticket__stake-input">
          <span>$</span>
          <input
            type="number"
            min={1}
            step={5}
            value={stake}
            onChange={(e) => setStake(Math.max(1, Number(e.target.value)))}
          />
        </div>
        <div className="kalshi-ticket__stake-presets">
          {[10, 25, 50, 100].map((amt) => (
            <button key={amt} className={`kalshi-stake-preset ${stake === amt ? 'is-active' : ''}`} onClick={() => setStake(amt)}>
              ${amt}
            </button>
          ))}
        </div>
      </div>

      {preview ? (
        <div className="kalshi-ticket__preview">
          <div className="kalshi-ticket__price-hero">
            <div className="kalshi-ticket__price-block">
              <span>Price</span>
              <strong>{Math.round(Number(preview.entry_price ?? 0) * 100)}¢</strong>
            </div>
            <div className="kalshi-ticket__price-block">
              <span>Payout</span>
              <strong className="is-good">{money(Number(preview.payout_if_win ?? 0))}</strong>
            </div>
          </div>
          <div className="kalshi-ticket__prob-row">
            <div className="kalshi-ticket__prob">
              <span>Model</span>
              <strong className="kalshi-prob--model">{pct0(preview.model_prob)}</strong>
            </div>
            <div className="kalshi-ticket__prob">
              <span>Market</span>
              <strong className="kalshi-prob--market">{pct0(preview.market_prob)}</strong>
            </div>
            <div className="kalshi-ticket__prob">
              <span>Break-even</span>
              <strong>{pct0(preview.break_even_prob)}</strong>
            </div>
          </div>
          <div className="kalshi-ticket__totals">
            <div className="kalshi-ticket__total-row">
              <span>You pay</span>
              <strong>{money(preview.stake)}</strong>
            </div>
            <div className="kalshi-ticket__total-row">
              <span>Fees</span>
              <strong>{money(Number(preview.entry_fee ?? 0))}</strong>
            </div>
          </div>
        </div>
      ) : selectedLegs.length >= 2 ? (
        <div className="kalshi-ticket__pricing">{previewQuery.isFetching ? 'Pricing…' : 'Calculating price…'}</div>
      ) : (
        <div className="kalshi-ticket__pricing">Add {2 - selectedLegs.length} more leg{selectedLegs.length === 1 ? '' : 's'} to price</div>
      )}

      <button
        className="kalshi-ticket__buy-btn"
        disabled={selectedLegs.length < 2 || !preview || placeMutation.isPending}
        onClick={() => placeMutation.mutate()}
      >
        {placeMutation.isPending ? 'Placing…' : preview ? `Buy combo — ${money(preview.stake)}` : 'Buy combo'}
      </button>

      {bankrollCash > 0 && (
        <div className="kalshi-ticket__cash">{money(bankrollCash)} available</div>
      )}
    </div>
  )
}

function PlacedComboReceipt({ receipt, onNewCombo }: { receipt: PlacedReceipt; onNewCombo: () => void }) {
  return (
    <div className="kalshi-ticket kalshi-ticket--placed">
      <div className="kalshi-ticket__placed-badge">✓ Combo placed</div>
      <div className="kalshi-ticket__placed-game">{receipt.game}</div>

      <div className="kalshi-ticket__legs">
        {receipt.legs.map((leg, i) => (
          <div key={String(leg.market_ticker ?? i)} className="kalshi-ticket__leg kalshi-ticket__leg--placed">
            <span>{leg.display ?? leg.title}</span>
            <strong>{pct0(leg.model_prob)}</strong>
          </div>
        ))}
      </div>

      <div className="kalshi-ticket__placed-summary">
        <div className="kalshi-ticket__placed-row">
          <span>Stake</span>
          <strong>{money(receipt.stake)}</strong>
        </div>
        <div className="kalshi-ticket__placed-row">
          <span>Payout if win</span>
          <strong className="is-good">{money(receipt.payout)}</strong>
        </div>
        <div className="kalshi-ticket__placed-row">
          <span>Model prob</span>
          <strong className="kalshi-prob--model">{pct0(receipt.modelProb)}</strong>
        </div>
        <div className="kalshi-ticket__placed-row">
          <span>Market prob</span>
          <strong className="kalshi-prob--market">{pct0(receipt.marketProb)}</strong>
        </div>
      </div>

      <button className="kalshi-ticket__new-btn" onClick={onNewCombo}>
        New combo
      </button>
    </div>
  )
}

function PositionRow({ item }: { item: PositionRecord }) {
  let legs: ComboLegRecord[] = []
  try { legs = JSON.parse(String((item as any).legs_json ?? '[]')) } catch { legs = [] }
  const pnl = Number((item as any).pnl ?? (item as any).unrealized_pnl ?? 0)

  return (
    <div className="kalshi-position-row">
      <div className="kalshi-position-row__left">
        <div className="kalshi-position-row__teams">
          <TeamLogo team={item.away_team as string} size={14} />
          <span>{item.away_team}</span>
          <span className="kalshi-position-row__sep">@</span>
          <TeamLogo team={item.home_team as string} size={14} />
          <span>{item.home_team}</span>
        </div>
        <div className="kalshi-position-row__legs-preview">
          {legs.slice(0, 3).map((l, i) => (
            <span key={i} className="kalshi-position-leg-tag">{l.display ?? l.title}</span>
          ))}
          {legs.length > 3 && <span className="kalshi-position-leg-tag">+{legs.length - 3}</span>}
        </div>
      </div>
      <div className="kalshi-position-row__right">
        <strong>{money((item as any).stake)}</strong>
        <span className={pnl >= 0 ? 'is-good' : 'is-bad'}>{pnl >= 0 ? '+' : ''}{money(pnl)}</span>
        <span className={`kalshi-position-status kalshi-position-status--${item.status}`}>{item.status}</span>
      </div>
    </div>
  )
}

export default function CombosPage() {
  const params = useParams()
  const league: League = isLeague(params.league) ? params.league : normalizeLeague(params.league)

  const [selectedTicker, setSelectedTicker] = useState<string | null>(null)
  const [selectedLegs, setSelectedLegs] = useState<string[]>([])
  const [placedReceipt, setPlacedReceipt] = useState<PlacedReceipt | null>(null)
  const [positionsOpen, setPositionsOpen] = useState(false)

  const boardQuery = useQuery({ queryKey: ['combo-board'], queryFn: getComboBoard, enabled: league === 'nba' })
  const stateQuery = useQuery({ queryKey: ['combo-state'], queryFn: getComboState, enabled: league === 'nba' })
  const positionsQuery = useQuery({ queryKey: ['combo-positions'], queryFn: getComboPositions, enabled: league === 'nba' })

  const collections = boardQuery.data?.collections ?? []

  const activeCollection: ComboCollectionRecord | null = useMemo(() => {
    if (!collections.length) return null
    return collections.find((c) => c.collection_ticker === selectedTicker) ?? collections[0]
  }, [collections, selectedTicker])

  const collectionDetailQuery = useQuery({
    queryKey: ['combo-collection', activeCollection?.collection_ticker],
    queryFn: () => getComboCollection(String(activeCollection?.collection_ticker ?? '')),
    enabled: Boolean(activeCollection?.collection_ticker),
  })

  const allLegs: ComboLegRecord[] = collectionDetailQuery.data?.legs ?? activeCollection?.legs ?? []

  const groupedByType = useMemo(() => {
    const map: Record<string, ComboLegRecord[]> = {}
    for (const leg of allLegs) {
      const t = String(leg.market_type ?? 'other')
      map[t] = map[t] ?? []
      map[t].push(leg)
    }
    return map
  }, [allLegs])

  const orderedTypes = useMemo(() => {
    const known = MARKET_TYPE_ORDER.filter((t) => groupedByType[t])
    const other = Object.keys(groupedByType).filter((t) => !MARKET_TYPE_ORDER.includes(t))
    return [...known, ...other]
  }, [groupedByType])

  function toggleLeg(ticker: string) {
    setSelectedLegs((prev) => {
      if (prev.includes(ticker)) return prev.filter((t) => t !== ticker)
      if (prev.length >= MAX_LEGS) return prev
      return [...prev, ticker]
    })
  }

  function handleCollectionChange(ticker: string) {
    setSelectedTicker(ticker)
    setSelectedLegs([])
    setPlacedReceipt(null)
  }

  if (league !== 'nba') {
    return <ErrorState title="Combos unavailable for NCAA" body="The combo surface is built for Kalshi NBA same-game combos only." />
  }
  if (boardQuery.isLoading || stateQuery.isLoading) return <LoadingPanel label="Loading combo board" />
  if (boardQuery.isError || !boardQuery.data) return <ErrorState title="Combos unavailable" body="The combo board API did not return a usable payload." />
  if (!collections.length) return <EmptyState title="No combo boards today" body="Kalshi hasn't published same-game collections for today's NBA games yet." />

  const bankrollCash = Number(stateQuery.data?.bankroll?.available_cash ?? 0)
  const allPositions = [...(positionsQuery.data?.open ?? []), ...(positionsQuery.data?.settled ?? [])]

  const awayColor = activeCollection ? teamAccent(activeCollection.away_team) : '#8da2ff'
  const homeColor = activeCollection ? teamAccent(activeCollection.home_team) : '#8da2ff'

  return (
    <div className="kalshi-page">
      {/* Game selector strip */}
      <div className="kalshi-game-selector">
        {collections.map((col) => (
          <button
            key={col.collection_ticker}
            className={`kalshi-game-pill ${activeCollection?.collection_ticker === col.collection_ticker ? 'is-active' : ''}`}
            onClick={() => handleCollectionChange(col.collection_ticker)}
          >
            <TeamLogo team={col.away_team} size={16} />
            <span>{col.away_team}</span>
            <span className="kalshi-game-pill__sep">@</span>
            <TeamLogo team={col.home_team} size={16} />
            <span>{col.home_team}</span>
            {col.tipoff_utc && <span className="kalshi-game-pill__time">{formatDateTime(col.tipoff_utc)}</span>}
          </button>
        ))}
      </div>

      <div className="kalshi-layout">
        {/* Left: market browser */}
        <div className="kalshi-browser">
          {activeCollection && (
            <>
              <div className="kalshi-team-header">
                <div className="kalshi-team-header__team">
                  <TeamLogo team={activeCollection.away_team} size={44} />
                  <div className="kalshi-team-header__info">
                    <strong style={{ color: awayColor }}>{activeCollection.away_team}</strong>
                    <span className="kalshi-team-header__prob">{pct0(activeCollection.away_win_prob)}</span>
                  </div>
                </div>
                <div className="kalshi-team-header__vs">
                  <span>vs</span>
                  {activeCollection.tipoff_utc && <small>{formatDateTime(activeCollection.tipoff_utc)}</small>}
                </div>
                <div className="kalshi-team-header__team kalshi-team-header__team--right">
                  <div className="kalshi-team-header__info kalshi-team-header__info--right">
                    <strong style={{ color: homeColor }}>{activeCollection.home_team}</strong>
                    <span className="kalshi-team-header__prob">{pct0(activeCollection.home_win_prob)}</span>
                  </div>
                  <TeamLogo team={activeCollection.home_team} size={44} />
                </div>
              </div>

              <div className="kalshi-win-bar">
                <span style={{ color: awayColor }}>{pct0(activeCollection.away_win_prob)}</span>
                <div className="kalshi-win-bar__track">
                  <div className="kalshi-win-bar__fill" style={{ width: `${Math.round((activeCollection.away_win_prob ?? 0.5) * 100)}%`, background: awayColor }} />
                </div>
                <span style={{ color: homeColor }}>{pct0(activeCollection.home_win_prob)}</span>
              </div>

              <div className="kalshi-leg-legend">
                <span>Market</span>
                <div className="kalshi-leg-legend__bars">
                  <span className="kalshi-leg-legend__model">■ Model</span>
                  <span className="kalshi-leg-legend__market">■ Market</span>
                </div>
                <span>Model%</span>
              </div>
            </>
          )}

          {collectionDetailQuery.isLoading && <LoadingPanel label="Loading legs" />}

          {orderedTypes.map((type) => (
            <MarketSection
              key={type}
              type={type}
              legs={groupedByType[type]}
              selectedLegs={selectedLegs}
              onToggleLeg={toggleLeg}
              maxReached={selectedLegs.length >= MAX_LEGS}
            />
          ))}
        </div>

        {/* Right: ticket col */}
        <div className="kalshi-ticket-col">
          {placedReceipt ? (
            <PlacedComboReceipt receipt={placedReceipt} onNewCombo={() => { setPlacedReceipt(null); setSelectedLegs([]) }} />
          ) : (
            <ComboTicket
              collection={activeCollection}
              selectedLegs={selectedLegs}
              allLegs={allLegs}
              onRemoveLeg={(t) => setSelectedLegs((prev) => prev.filter((x) => x !== t))}
              onClear={() => setSelectedLegs([])}
              onTradeConfirmed={(r) => { setPlacedReceipt(r); setSelectedLegs([]) }}
              bankrollCash={bankrollCash}
            />
          )}

          {allPositions.length > 0 && (
            <div className="kalshi-positions-accordion">
              <button className="kalshi-positions-accordion__header" onClick={() => setPositionsOpen((o) => !o)}>
                <span>My combos ({allPositions.length})</span>
                {positionsOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </button>
              {positionsOpen && (
                <div className="kalshi-positions-list">
                  {allPositions.map((item, i) => (
                    <PositionRow key={String((item as any).trade_id ?? i)} item={item} />
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
