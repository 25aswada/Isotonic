import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'

import { Button, EmptyState, ErrorState, LoadingPanel, MetricCard, Pill, Surface, TeamLogo } from '../components/ui'
import {
  getComboBoard,
  getComboCollection,
  getComboCandidates,
  getComboPositions,
  getComboState,
  logComboTrade,
  previewComboTrade,
  tradeComboCandidates,
} from '../lib/api'
import { formatDateTime, money, moneySigned, pct, pct0 } from '../lib/format'
import { isLeague, normalizeLeague } from '../lib/navigation'
import type { ComboCollectionRecord, ComboLegRecord, League, PaperBankroll, PaperTraderCandidate, PositionRecord } from '../types'

const MAX_COMBO_LEGS = 8

function ComboCandidateCard({
  candidate,
  busy,
  onTrade,
}: {
  candidate: PaperTraderCandidate
  busy: boolean
  onTrade: () => void
}) {
  let legs: ComboLegRecord[] = []
  try {
    legs = JSON.parse(String(candidate.legs_json ?? '[]')) as ComboLegRecord[]
  } catch {
    legs = []
  }

  return (
    <article className="paper-ticket">
      <div className="paper-ticket__top">
        <div className="paper-ticket__copy">
          <span className="section-kicker">Kalshi combo idea</span>
          <h3>{String(candidate.combo_label ?? candidate.contract_team ?? 'Combo')}</h3>
          <p>
            {candidate.away_team} at {candidate.home_team}
            {candidate.tipoff_utc ? ` · ${formatDateTime(candidate.tipoff_utc)}` : ''}
          </p>
        </div>
        <Button disabled={busy} onClick={onTrade}>
          {busy ? 'Trading…' : 'Trade'}
        </Button>
      </div>

      <div className="combo-leg-list">
        {legs.map((leg, index) => (
          <div key={`${leg.market_ticker ?? index}`} className="combo-leg-pill">
            <span>{leg.display ?? leg.title ?? leg.market_ticker}</span>
            <strong>{pct0(leg.model_prob)}</strong>
          </div>
        ))}
      </div>

      <div className="paper-ticket__signal-row">
        <div className="paper-ticket__signal">
          <span>Model</span>
          <strong className="paper-prob paper-prob--good">{pct0(candidate.model_prob)}</strong>
        </div>
        <div className="paper-ticket__signal">
          <span>Market</span>
          <strong className="paper-value paper-value--info">{pct0(candidate.market_prob)}</strong>
        </div>
        <div className="paper-ticket__signal">
          <span>Entry</span>
          <strong className="paper-value paper-value--info">{pct0(candidate.entry_price)}</strong>
        </div>
        <div className="paper-ticket__signal">
          <span>Edge</span>
          <strong className={(candidate.edge ?? 0) >= 0 ? 'is-good' : 'is-bad'}>{pct(candidate.edge)}</strong>
        </div>
      </div>

      <div className="paper-ticket__metrics">
        <div>
          <span>Stake</span>
          <strong className="paper-value paper-value--info">{money(candidate.stake)}</strong>
        </div>
        <div>
          <span>Expected profit</span>
          <strong className={(candidate.expected_profit ?? 0) >= 0 ? 'is-good' : 'is-bad'}>{money(candidate.expected_profit)}</strong>
        </div>
        <div>
          <span>Payout</span>
          <strong className="is-good">{money(Number(candidate.payout_if_win ?? 0))}</strong>
        </div>
        <div>
          <span>Contracts</span>
          <strong>{String(candidate.contracts ?? '—')}</strong>
        </div>
      </div>
    </article>
  )
}

function ComboManualBuilder({
  bankroll,
  collections,
}: {
  bankroll: PaperBankroll
  collections: ComboCollectionRecord[]
}) {
  const queryClient = useQueryClient()
  const [collectionTicker, setCollectionTicker] = useState('')
  const [selectedLegs, setSelectedLegs] = useState<string[]>([])
  const [customStake, setCustomStake] = useState(50)

  const selectedCollection = useMemo(
    () => collections.find((collection) => collection.collection_ticker === collectionTicker) ?? collections[0] ?? null,
    [collectionTicker, collections],
  )

  const detailQuery = useQuery({
    queryKey: ['combo-collection', selectedCollection?.collection_ticker],
    queryFn: () => getComboCollection(String(selectedCollection?.collection_ticker ?? '')),
    enabled: Boolean(selectedCollection?.collection_ticker),
  })

  const selectedDetail = detailQuery.data ?? selectedCollection

  const selectedLegRecords = useMemo(
    () => selectedDetail?.legs.filter((leg) => selectedLegs.includes(String(leg.market_ticker))) ?? [],
    [selectedDetail, selectedLegs],
  )

  const previewQuery = useQuery({
    queryKey: ['combo-preview', selectedDetail?.collection_ticker, selectedLegs, customStake],
    queryFn: () => previewComboTrade(String(selectedDetail?.collection_ticker ?? ''), selectedLegs, customStake),
    enabled: Boolean(selectedDetail?.collection_ticker && selectedLegs.length >= 2 && customStake > 0),
    refetchInterval: selectedLegs.length >= 2 ? 15_000 : false,
  })

  const placeMutation = useMutation({
    mutationFn: () => logComboTrade(String(selectedDetail?.collection_ticker ?? ''), selectedLegs, customStake),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['combo-state'] })
      void queryClient.invalidateQueries({ queryKey: ['combo-candidates'] })
      void queryClient.invalidateQueries({ queryKey: ['combo-positions'] })
      setSelectedLegs([])
    },
  })

  const preview = previewQuery.data?.trade

  return (
    <Surface className="stack-panel">
      <div className="stack-panel__header">
        <div>
          <span className="section-kicker">Manual combo builder</span>
          <h3>Build a same-game combo</h3>
        </div>
        <Pill tone="accent">{money(bankroll.available_cash)} free</Pill>
      </div>

      <div className="combo-builder">
        <div className="combo-builder__controls">
          <div>
            <label>Game</label>
            <select
              value={selectedCollection?.collection_ticker ?? ''}
              onChange={(event) => {
                setCollectionTicker(event.target.value)
                setSelectedLegs([])
              }}
            >
              {(collections ?? []).map((collection) => (
                <option key={collection.collection_ticker} value={collection.collection_ticker}>
                  {collection.away_team} @ {collection.home_team}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label>Dollar amount</label>
            <div className="paper-manual__money-input">
              <span>$</span>
              <input
                type="number"
                min="1"
                step="1"
                value={customStake}
                onChange={(event) => setCustomStake(Number(event.target.value))}
              />
            </div>
          </div>
        </div>

        <div className="combo-builder__layout">
          <div className="combo-builder__selection">
            {selectedCollection ? (
              <>
                <div className="combo-builder__game">
                  <div className="preview-row__team">
                    <TeamLogo team={selectedCollection.away_team} size={18} />
                    <span>{selectedCollection.away_team}</span>
                  </div>
                  <span>@</span>
                  <div className="preview-row__team">
                    <TeamLogo team={selectedCollection.home_team} size={18} />
                    <span>{selectedCollection.home_team}</span>
                  </div>
                  <Pill tone="neutral">{selectedCollection.tipoff_utc ? formatDateTime(selectedCollection.tipoff_utc) : 'Today'}</Pill>
                </div>

                <div className="combo-builder__selection-header">
                  <span className="section-kicker">Official legs</span>
                  <Pill tone="neutral">{selectedLegs.length}/{MAX_COMBO_LEGS} selected</Pill>
                </div>

                <div className="combo-builder__legs">
                  {(selectedDetail?.legs ?? []).map((leg) => {
                    const active = selectedLegs.includes(String(leg.market_ticker))
                    const disabled = !active && selectedLegs.length >= MAX_COMBO_LEGS
                    return (
                      <button
                        key={String(leg.market_ticker)}
                        className={`combo-leg-card ${active ? 'is-active' : ''}`}
                        disabled={disabled}
                        onClick={() =>
                          setSelectedLegs((current) =>
                            current.includes(String(leg.market_ticker))
                              ? current.filter((ticker) => ticker !== String(leg.market_ticker))
                              : [...current, String(leg.market_ticker)].slice(0, MAX_COMBO_LEGS),
                          )
                        }
                      >
                        <span>{leg.display ?? leg.title ?? leg.market_ticker}</span>
                        <small>{leg.market_type}</small>
                        <strong>{pct0(leg.entry_price)}</strong>
                        <em className={(leg.edge ?? 0) >= 0 ? 'is-good' : 'is-bad'}>{pct(leg.edge)}</em>
                      </button>
                    )
                  })}
                </div>
              </>
            ) : null}
          </div>

          {preview ? (
            <div className="trade-ticket combo-builder__ticket">
            <div className="trade-ticket__header">
              <div className="trade-ticket__outcome">
                <span className="trade-ticket__label">Outcome</span>
                <div className="trade-ticket__team-row">
                  <strong>{String(preview.combo_label ?? preview.contract_team ?? 'Combo')}</strong>
                </div>
              </div>
              <Pill tone="accent">Kalshi combo</Pill>
            </div>

            <div className="combo-leg-list combo-leg-list--ticket">
              {selectedLegRecords.map((leg, index) => (
                <div key={`${leg.market_ticker ?? index}`} className="combo-leg-pill">
                  <span>{leg.display ?? leg.title}</span>
                  <strong>{pct0(leg.model_prob)}</strong>
                </div>
              ))}
            </div>

            <div className="trade-ticket__price-hero">
              <div className="trade-ticket__price-block trade-ticket__price-block--price">
                <span>Price</span>
                <strong>{Math.round(Number(preview.entry_price ?? 0) * 100)}¢</strong>
              </div>
              <div className="trade-ticket__price-block trade-ticket__price-block--contracts">
                <span>Contracts</span>
                <strong>{String(preview.contracts ?? '—')}</strong>
              </div>
            </div>

            <div className="trade-ticket__summary">
              <div className="trade-ticket__row">
                <span>You pay</span>
                <strong className="trade-ticket__outlay">{money(preview.stake)}</strong>
              </div>
              <div className="trade-ticket__row">
                <span>Fees</span>
                <strong className="trade-ticket__fee">{money(Number(preview.entry_fee ?? 0))}</strong>
              </div>
              <div className="trade-ticket__row trade-ticket__row--total">
                <span>Total cost</span>
                <strong className="trade-ticket__total">{money(Number(preview.stake ?? 0) + Number(preview.entry_fee ?? 0))}</strong>
              </div>
            </div>

            <div className="trade-ticket__probabilities">
              <div className="trade-ticket__prob">
                <span>Model</span>
                <strong className="trade-ticket__edge">{pct0(preview.model_prob)}</strong>
              </div>
              <div className="trade-ticket__prob">
                <span>Market</span>
                <strong className="trade-ticket__market">{pct0(preview.market_prob)}</strong>
              </div>
              <div className="trade-ticket__prob">
                <span>Break even</span>
                <strong className="trade-ticket__breakeven">{pct0(preview.break_even_prob)}</strong>
              </div>
              <div className="trade-ticket__prob">
                <span>Payout</span>
                <strong className="trade-ticket__cash-after">{money(Number(preview.payout_if_win ?? 0))}</strong>
              </div>
            </div>

            <Button disabled={placeMutation.isPending} onClick={() => placeMutation.mutate()}>
              {placeMutation.isPending ? 'Placing…' : `Buy combo — ${money(preview.stake)}`}
            </Button>
          </div>
          ) : (
            <div className="paper-manual__empty combo-builder__ticket">
              <strong>{previewQuery.isFetching ? 'Pricing combo…' : 'Build a combo ticket'}</strong>
              <p>Choose two or three official Kalshi legs from one NBA game to preview the combo ticket.</p>
            </div>
          )}
        </div>
      </div>
    </Surface>
  )
}

function ComboPositionsPanel({ items, title }: { items: PositionRecord[]; title: string }) {
  return (
    <Surface className="stack-panel">
      <div className="stack-panel__header">
        <div>
          <span className="section-kicker">{title === 'Open combos' ? 'Open combos' : 'Settled combos'}</span>
          <h3>{title}</h3>
        </div>
        <Pill>{items.length}</Pill>
      </div>
      {items.length ? (
        <div className="position-list">
          {items.slice(0, 12).map((item, index) => (
            <div className="position-row" key={`${item.trade_id ?? index}`}>
              <div className="position-row__main">
                <div className="position-row__title">
                  <strong>{String(item.combo_label ?? item.contract_team ?? 'Combo')}</strong>
                  <div className="position-row__game">
                    <span className="preview-row__team">
                      <TeamLogo team={item.away_team as string} size={16} />
                      <span>{item.away_team}</span>
                    </span>
                    <span>@</span>
                    <span className="preview-row__team">
                      <TeamLogo team={item.home_team as string} size={16} />
                      <span>{item.home_team}</span>
                    </span>
                  </div>
                </div>
                <div className="position-row__meta">
                  <span>{item.tipoff_utc ? formatDateTime(item.tipoff_utc) : 'Tipoff unknown'}</span>
                </div>
              </div>
              <div className="position-row__stats">
                <div>
                  <span>Entry</span>
                  <strong className="paper-value paper-value--info">{pct0(item.entry_price)}</strong>
                </div>
                <div>
                  <span>Current</span>
                  <strong className={(Number(item.current_value ?? 0) - Number(item.stake ?? 0)) >= 0 ? 'is-good' : 'is-bad'}>
                    {money(item.current_value ?? item.stake)}
                  </strong>
                </div>
                <div>
                  <span>Stake</span>
                  <strong className="paper-value paper-value--info">{money(item.stake)}</strong>
                </div>
                <div>
                  <span>P/L</span>
                  <strong className={Number(item.pnl ?? item.unrealized_pnl ?? 0) >= 0 ? 'is-good' : 'is-bad'}>
                    {moneySigned(Number(item.pnl ?? item.unrealized_pnl ?? 0))}
                  </strong>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <EmptyState title={`No ${title.toLowerCase()}`} body="Combo positions will appear here once tickets are placed." />
      )}
    </Surface>
  )
}

export default function CombosPage() {
  const params = useParams()
  const queryClient = useQueryClient()
  const league: League = isLeague(params.league) ? params.league : normalizeLeague(params.league)
  const [busyCandidateId, setBusyCandidateId] = useState<string | null>(null)

  const comboState = useQuery({
    queryKey: ['combo-state'],
    queryFn: getComboState,
    enabled: league === 'nba',
  })
  const comboBoard = useQuery({
    queryKey: ['combo-board'],
    queryFn: getComboBoard,
    enabled: league === 'nba',
  })
  const comboCandidates = useQuery({
    queryKey: ['combo-candidates'],
    queryFn: getComboCandidates,
    enabled: league === 'nba',
  })
  const comboPositions = useQuery({
    queryKey: ['combo-positions'],
    queryFn: getComboPositions,
    enabled: league === 'nba',
  })

  const tradeMutation = useMutation({
    mutationFn: (candidateIds: string[]) => tradeComboCandidates(candidateIds),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['combo-state'] })
      void queryClient.invalidateQueries({ queryKey: ['combo-candidates'] })
      void queryClient.invalidateQueries({ queryKey: ['combo-positions'] })
    },
    onSettled: () => setBusyCandidateId(null),
  })

  if (league !== 'nba') {
    return <ErrorState title="Combos unavailable for NCAA" body="The combo surface is currently built for Kalshi's NBA combo collections only." />
  }
  if (comboState.isLoading || comboBoard.isLoading || comboCandidates.isLoading || comboPositions.isLoading) {
    return <LoadingPanel label="Loading combo board" />
  }
  if (!comboState.data || comboBoard.isError || comboCandidates.isError || comboPositions.isError) {
    return <ErrorState title="Combos unavailable" body="The combo APIs did not return a usable payload." />
  }

  const bankroll = comboState.data.bankroll
  const candidates = comboCandidates.data?.candidates ?? []
  const collections = comboBoard.data?.collections ?? []
  const openPositions = comboPositions.data?.open ?? []
  const settledPositions = comboPositions.data?.settled ?? []

  return (
    <div className="page-grid">
      <div className="metric-grid">
        <MetricCard label="Available cash" value={money(bankroll.available_cash)} hint="Combo bankroll ready now" />
        <MetricCard label="Open combos" value={comboState.data.open_count} hint="Active combo tickets" />
        <MetricCard label="Settled combos" value={comboState.data.settled_count} hint="Closed combo ledger" />
        <MetricCard label="Collections" value={collections.length} hint="Official Kalshi NBA combo boards" />
      </div>

      <ComboManualBuilder bankroll={bankroll} collections={collections} />

      <Surface className="stack-panel">
        <div className="stack-panel__header">
          <div>
            <span className="section-kicker">Best combos</span>
            <h3>Model-ranked same-game ideas</h3>
          </div>
          <Pill tone="accent">{candidates.length}</Pill>
        </div>
        {candidates.length ? (
          <div className="paper-ticket-list">
            {candidates.map((candidate) => (
              <ComboCandidateCard
                key={candidate.candidate_id}
                candidate={candidate}
                busy={busyCandidateId === candidate.candidate_id && tradeMutation.isPending}
                onTrade={() => {
                  setBusyCandidateId(candidate.candidate_id)
                  tradeMutation.mutate([candidate.candidate_id])
                }}
              />
            ))}
          </div>
        ) : (
          <EmptyState title="No combo ideas right now" body="No same-game combo currently clears the model ranking rules." />
        )}
      </Surface>

      <ComboPositionsPanel items={openPositions} title="Open combos" />
      <ComboPositionsPanel items={settledPositions} title="Settled combos" />
    </div>
  )
}
