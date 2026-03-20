import { useEffect, useMemo, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'

import { Button, EmptyState, ErrorState, MetricCard, Pill, Surface, TeamLogo } from '../components/ui'
import {
  getAutoTradeStatus,
  getPaperCandidates,
  getPaperPositions,
  getPaperState,
  logPaperTrades,
  previewCustomPaperTrade,
  tradePaperCandidates,
  updateAutoTrade,
  deletePaperTrade,
  logCustomPaperTrade,
} from '../lib/api'
import { formatAgeSeconds, formatDateTime, money, moneySigned, pct, pct0, titleCase } from '../lib/format'
import { isLeague, leagueLabels, normalizeLeague } from '../lib/navigation'
import { teamAccent } from '../lib/teamColor'
import type {
  AutoTradeConfig,
  AutoTradeStatus,
  League,
  PaperBankroll,
  PaperTraderCandidate,
  PositionRecord,
} from '../types'

type ValueTone = 'good' | 'bad' | 'info' | 'warn' | 'neutral'

function probabilityTone(value: number | null | undefined, other: number | null | undefined) {
  if (value == null || other == null) return 'neutral'
  if (value === other) return 'neutral'
  return value > other ? 'good' : 'bad'
}

function signedTone(value: number | null | undefined): ValueTone {
  if (value == null || Number.isNaN(Number(value))) return 'neutral'
  if (Number(value) > 0) return 'good'
  if (Number(value) < 0) return 'bad'
  return 'neutral'
}

function positiveTone(value: number | null | undefined): ValueTone {
  if (value == null || Number.isNaN(Number(value))) return 'neutral'
  return Number(value) > 0 ? 'good' : 'neutral'
}

function valueClass(tone: ValueTone) {
  return tone === 'neutral' ? 'paper-value' : `paper-value paper-value--${tone}`
}

function positionStage(position: PositionRecord) {
  if (position.status === 'settled' || position.trade_stage === 'settled') {
    return { label: 'Settled', tone: 'neutral' as const }
  }

  const tipoff = position.tipoff_utc ? new Date(position.tipoff_utc) : null
  if (tipoff && !Number.isNaN(tipoff.valueOf()) && tipoff.valueOf() <= Date.now()) {
    return { label: 'Settling', tone: 'accent' as const }
  }

  return { label: 'Open', tone: 'good' as const }
}

function portfolioMessage(bankroll: PaperBankroll, candidateCount: number, openCount: number) {
  if ((bankroll.available_cash ?? 0) <= 0) {
    return 'No cash is available. Let existing positions settle before adding new paper trades.'
  }
  if (candidateCount > 0) {
    return `${candidateCount} trade${candidateCount === 1 ? '' : 's'} are ready to review and place from the current board.`
  }
  if (openCount > 0) {
    return 'Capital is already deployed. The queue is clear for now while open positions keep moving.'
  }
  return 'The paper book is funded and ready. Waiting for the next edge that clears the rules.'
}

function autoTradeSummary(status: AutoTradeStatus) {
  if (!status.available) return status.reason ?? 'Auto trade is not available for this league yet.'
  if (!status.enabled) return 'Auto trade is paused. Manual paper trading is still available.'
  if (status.mode === 'dry-run') return 'Dry-run mode is active. Cycles simulate trades without logging them.'
  return 'Auto trade is armed. Eligible early lines will be paper-traded automatically during active hours.'
}

function ManualTradePanel({ league, bankroll }: { league: League; bankroll: PaperBankroll }) {
  const [homeTeam, setHomeTeam] = useState('')
  const [awayTeam, setAwayTeam] = useState('')
  const [selectedTeam, setSelectedTeam] = useState('')
  const [customStake, setCustomStake] = useState(50)
  const [marketSource, setMarketSource] = useState('kalshi')
  
  const queryClient = useQueryClient()
  
  // Get available games for manual betting
  const { data: liveData } = useQuery({
    queryKey: ['live', league],
    queryFn: () => {
      if (league === 'nba') {
        return fetch('/api/live').then(r => r.json())
      } else {
        return fetch('/api/ncaab/live').then(r => r.json())
      }
    },
  })
  
  const availableGames = useMemo(() => {
    const games = [...(liveData?.in_progress ?? []), ...(liveData?.upcoming ?? [])]
    return games.map((game: any) => ({
      id: String(game.game_id ?? `${game.away_team}@${game.home_team}`),
      homeTeam: game.home_team,
      awayTeam: game.away_team,
      tipoffUtc: game.tipoff_utc,
      statusText: game.game_status_text,
      homeMarket: game.kalshi_home_prob,
      awayMarket: game.kalshi_away_prob,
    }))
  }, [liveData])

  const manualPreview = useQuery({
    queryKey: ['manual-paper-preview', league, homeTeam, awayTeam, selectedTeam, customStake, marketSource],
    queryFn: () => previewCustomPaperTrade(league, homeTeam, awayTeam, selectedTeam, customStake, marketSource),
    enabled: Boolean(homeTeam && awayTeam && selectedTeam && customStake > 0),
    refetchInterval: selectedTeam ? 15_000 : false,
  })
  
  const customTradeMutation = useMutation({
    mutationFn: () => logCustomPaperTrade(league, homeTeam, awayTeam, selectedTeam, customStake, marketSource),
    onSuccess: () => {
      // Invalidate queries to refresh data
      void queryClient.invalidateQueries({ queryKey: ['paper-state', league] })
      void queryClient.invalidateQueries({ queryKey: ['paper-positions', league] })
      void queryClient.invalidateQueries({ queryKey: ['paper-candidates', league] })
      void queryClient.invalidateQueries({ queryKey: ['manual-paper-preview', league] })
      
      setSelectedTeam('')
    },
  })

  const previewTrade = manualPreview.data?.trade

  return (
    <Surface className="stack-panel">
      <div className="stack-panel__header">
        <div>
          <span className="section-kicker">Manual trade</span>
          <h3>Trade any game</h3>
        </div>
        <Pill tone="accent">{money(bankroll.available_cash)} free</Pill>
      </div>

      <div className="paper-manual">
        <div className="paper-manual__board">
          {availableGames.map((game: any) => {
            const isSelected = game.homeTeam === homeTeam && game.awayTeam === awayTeam
            return (
              <button
                key={game.id}
                className={`paper-manual__game ${isSelected ? 'is-selected' : ''}`}
                onClick={() => {
                  setHomeTeam(game.homeTeam)
                  setAwayTeam(game.awayTeam)
                  setSelectedTeam('')
                }}
              >
                <div className="paper-manual__teams">
                  <div className="preview-row__team">
                    <TeamLogo team={game.awayTeam as string} size={16} />
                    <span>{game.awayTeam}</span>
                  </div>
                  <span>@</span>
                  <div className="preview-row__team">
                    <TeamLogo team={game.homeTeam as string} size={16} />
                    <span>{game.homeTeam}</span>
                  </div>
                </div>
                <small>{game.tipoffUtc ? formatDateTime(game.tipoffUtc) : game.statusText || 'Today'}</small>
              </button>
            )
          })}
        </div>

        <div className="paper-manual__ticket">
          <div className="paper-manual__controls">
            <div>
              <label>Side</label>
              <div className="paper-manual__side-picks">
                <button
                  className={selectedTeam && selectedTeam === awayTeam ? 'is-selected' : ''}
                  disabled={!awayTeam}
                  onClick={() => setSelectedTeam(awayTeam)}
                >
                  {awayTeam || 'Away'}
                </button>
                <button
                  className={selectedTeam && selectedTeam === homeTeam ? 'is-selected' : ''}
                  disabled={!homeTeam}
                  onClick={() => setSelectedTeam(homeTeam)}
                >
                  {homeTeam || 'Home'}
                </button>
              </div>
            </div>

            <div>
              <label>Market</label>
              <select value={marketSource} onChange={(e) => setMarketSource(e.target.value)}>
                <option value="kalshi">Kalshi</option>
                {league === 'nba' ? <option value="polymarket">Polymarket</option> : null}
              </select>
            </div>

            <div>
              <label>Dollar amount</label>
              <div className="paper-manual__money-input">
                <span>$</span>
                <input
                  type="number"
                  min="1"
                  max={Math.max(1, Math.floor(bankroll.available_cash ?? 0))}
                  step="1"
                  value={customStake}
                  onChange={(e) => setCustomStake(Number(e.target.value))}
                />
              </div>
            </div>
          </div>

          {previewTrade ? (
            <div className="trade-ticket">
              <div className="trade-ticket__header">
                <div className="trade-ticket__outcome">
                  <span className="trade-ticket__label">Outcome</span>
                  <div className="trade-ticket__team-row">
                    <TeamLogo team={previewTrade.contract_team as string} size={22} />
                    <strong>{previewTrade.contract_team} wins</strong>
                  </div>
                </div>
                <Pill tone="accent">{titleCase(previewTrade.market_source)}</Pill>
              </div>

              <div className="trade-ticket__price-hero">
                <div className="trade-ticket__price-block trade-ticket__price-block--price">
                  <span>Price</span>
                  <strong>{Math.round(Number(previewTrade.entry_price ?? 0) * 100)}¢</strong>
                </div>
                <div className="trade-ticket__price-block trade-ticket__price-block--contracts">
                  <span>Contracts</span>
                  <strong>{String(previewTrade.contracts ?? previewTrade.net_shares ?? '—')}</strong>
                </div>
              </div>

              <div className="trade-ticket__summary">
                <div className="trade-ticket__row">
                  <span>You pay</span>
                  <strong className="trade-ticket__outlay">{money(previewTrade.stake)}</strong>
                </div>
                <div className="trade-ticket__row">
                  <span>Fees</span>
                  <strong className="trade-ticket__fee">{money(Number(previewTrade.entry_fee ?? 0))}</strong>
                </div>
                <div className="trade-ticket__row trade-ticket__row--total">
                  <span>Total cost</span>
                  <strong className="trade-ticket__total">{money(Number(previewTrade.stake ?? 0) + Number(previewTrade.entry_fee ?? 0))}</strong>
                </div>
              </div>

              <div className="trade-ticket__payout">
                <div className="trade-ticket__payout-row">
                  <span>Payout if win</span>
                  <strong className="trade-ticket__win">{money(Number(previewTrade.payout_if_win ?? 0))}</strong>
                </div>
                <div className="trade-ticket__payout-row">
                  <span>Profit if win</span>
                  <strong className="trade-ticket__win">
                    +{money(Number(previewTrade.payout_if_win ?? 0) - Number(previewTrade.stake ?? 0) - Number(previewTrade.entry_fee ?? 0))}
                  </strong>
                </div>
                <div className="trade-ticket__payout-row trade-ticket__payout-row--dim">
                  <span>Loss if wrong</span>
                  <strong className="trade-ticket__loss">-{money(Number(previewTrade.stake ?? 0) + Number(previewTrade.entry_fee ?? 0))}</strong>
                </div>
              </div>

              <div className="trade-ticket__probabilities">
                <div className="trade-ticket__prob">
                  <span>Model</span>
                  <strong className={Number(previewTrade.model_prob ?? 0) > Number(previewTrade.market_prob ?? 0) ? 'trade-ticket__edge' : ''}>{pct0(previewTrade.model_prob)}</strong>
                </div>
                <div className="trade-ticket__prob">
                  <span>Market</span>
                  <strong className="trade-ticket__market">{pct0(previewTrade.market_prob)}</strong>
                </div>
                <div className="trade-ticket__prob">
                  <span>Break even</span>
                  <strong className="trade-ticket__breakeven">{pct0(previewTrade.break_even_prob)}</strong>
                </div>
                <div className="trade-ticket__prob">
                  <span>Cash after</span>
                  <strong className="trade-ticket__cash-after">{money(previewTrade.cash_after_trade)}</strong>
                </div>
              </div>

              <Button
                disabled={customTradeMutation.isPending || !selectedTeam}
                onClick={() => customTradeMutation.mutate()}
              >
                {customTradeMutation.isPending ? 'Placing…' : `Buy ${previewTrade.contract_team} — ${money(previewTrade.stake)}`}
              </Button>
            </div>
          ) : (
            <div className="paper-manual__empty">
              <strong>{manualPreview.isFetching ? 'Pricing trade…' : 'Build a ticket'}</strong>
              <p>Select a game, choose a side, and enter a dollar amount to preview the trade like a normal Kalshi ticket.</p>
            </div>
          )}

          {customTradeMutation.error ? (
            <div className="paper-error-message">
              Error: {customTradeMutation.error instanceof Error ? customTradeMutation.error.message : 'Unknown error'}
            </div>
          ) : null}
        </div>
      </div>
    </Surface>
  )
}

function PortfolioHero({
  bankroll,
  openCount,
  settledCount,
  candidateCount,
}: {
  bankroll: PaperBankroll
  openCount: number
  settledCount: number
  candidateCount: number
}) {
  const pnl = bankroll.realized_pnl ?? 0
  const unrealized = bankroll.unrealized_pnl ?? 0
  const total = pnl + unrealized
  const isPositive = total >= 0

  return (
    <Surface className={`pnl-hero surface--${isPositive ? 'accent' : 'danger'}`}>
      <div className="pnl-hero__inner">
        <div className="pnl-hero__main">
          <span className="section-kicker">Portfolio</span>
          <div className={`pnl-hero__value ${isPositive ? 'is-good' : 'is-bad'}`}>
            {moneySigned(total)}
          </div>
          <div className="pnl-hero__return">{portfolioMessage(bankroll, candidateCount, openCount)}</div>
          <div className="paper-explainer">
            <small>What this means</small>
            <span>
              Available cash is what you can deploy right now. Open risk is already committed to active paper trades.
            </span>
          </div>
        </div>
        <div className="pnl-hero__breakdown">
          <div className="pnl-hero__row">
            <span>Realized P/L</span>
            <strong className={pnl >= 0 ? 'is-good' : 'is-bad'}>{moneySigned(pnl)}</strong>
          </div>
          <div className="pnl-hero__row">
            <span>Unrealized P/L</span>
            <strong className={unrealized >= 0 ? 'is-good' : 'is-bad'}>{moneySigned(unrealized)}</strong>
          </div>
          <div className="pnl-hero__row">
            <span>Open positions</span>
            <strong>{openCount}</strong>
          </div>
          <div className="pnl-hero__row">
            <span>Settled trades</span>
            <strong>{settledCount}</strong>
          </div>
        </div>
      </div>
    </Surface>
  )
}

function CandidateCard({
  candidate,
  busy,
  onTrade,
}: {
  candidate: PaperTraderCandidate
  busy: boolean
  onTrade: () => void
}) {
  const modelProb = Number(candidate.model_prob ?? 0)
  const marketProb = Number(candidate.market_prob ?? candidate.entry_price ?? 0)
  const modelTone = probabilityTone(modelProb, marketProb)
  const marketTone = probabilityTone(marketProb, modelProb)
  const expectedProfitTone = signedTone(candidate.expected_profit)
  const kellyTone = positiveTone(candidate.kelly_pct)
  const contractTeam = candidate.contract_team ?? candidate.bet_side ?? 'Candidate'

  return (
    <article className="paper-ticket">
      <div className="paper-ticket__top">
        <div className="paper-ticket__copy">
          <span className="section-kicker">{titleCase(candidate.market_source ?? 'market')} candidate</span>
          <h3>{contractTeam}</h3>
          <p>
            {candidate.away_team} at {candidate.home_team}
            {candidate.tipoff_utc ? ` · ${formatDateTime(candidate.tipoff_utc)}` : ''}
          </p>
        </div>
        <Button disabled={busy} onClick={onTrade}>
          {busy ? 'Trading…' : 'Trade'}
        </Button>
      </div>

      <div className="paper-ticket__teams">
        <div className="paper-ticket__team">
          <div className="paper-ticket__team-head">
            <TeamLogo team={candidate.away_team as string} size={24} />
            <span style={{ color: teamAccent(candidate.away_team as string) }}>{candidate.away_team}</span>
          </div>
          <small>{candidate.bet_side === 'away' ? 'Target side' : 'Opposing side'}</small>
        </div>
        <div className="paper-ticket__team paper-ticket__team--right">
          <div className="paper-ticket__team-head paper-ticket__team-head--right">
            <TeamLogo team={candidate.home_team as string} size={24} />
            <span style={{ color: teamAccent(candidate.home_team as string) }}>{candidate.home_team}</span>
          </div>
          <small>{candidate.bet_side === 'home' ? 'Target side' : 'Opposing side'}</small>
        </div>
      </div>

      <div className="paper-ticket__signal-row">
        <div className="paper-ticket__signal">
          <span>Model</span>
          <strong className={`paper-prob paper-prob--${modelTone}`}>{pct0(modelProb)}</strong>
        </div>
        <div className="paper-ticket__signal">
          <span>Market</span>
          <strong className={`paper-prob paper-prob--${marketTone}`}>{pct0(marketProb)}</strong>
        </div>
        <div className="paper-ticket__signal">
          <span>Entry</span>
          <strong className={valueClass('info')}>{pct0(candidate.entry_price)}</strong>
        </div>
        <div className="paper-ticket__signal">
          <span>Edge</span>
          <strong className={(candidate.edge ?? 0) >= 0 ? 'is-good' : 'is-bad'}>{pct(candidate.edge)}</strong>
        </div>
      </div>

      <div className="paper-ticket__metrics">
        <div>
          <span>Stake</span>
          <strong className={valueClass('info')}>{money(candidate.stake)}</strong>
        </div>
        <div>
          <span>Expected profit</span>
          <strong className={valueClass(expectedProfitTone)}>{money(candidate.expected_profit)}</strong>
        </div>
        <div>
          <span>Kelly</span>
          <strong className={valueClass(kellyTone)}>{pct(candidate.kelly_pct)}</strong>
        </div>
        <div>
          <span>Cash after</span>
          <strong className={valueClass('info')}>{money(candidate.cash_after_trade)}</strong>
        </div>
      </div>

      <details className="paper-ticket__details">
        <summary>Why this trade</summary>
        <div className="paper-ticket__detail-grid">
          <div>
            <span>What this means</span>
            <strong>
              The model prices {contractTeam} at {pct0(modelProb)} while the market is closer to {pct0(marketProb)}.
            </strong>
          </div>
          <div>
            <span>Stake sizing</span>
            <strong>{pct(candidate.kelly_pct)} Kelly sizing keeps the paper book inside the bankroll rules.</strong>
          </div>
          <div>
            <span>Execution</span>
            <strong>
              {titleCase(candidate.market_source ?? 'market')} entry {pct0(candidate.entry_price)}
              {candidate.entry_slippage != null ? ` after ${pct(candidate.entry_slippage)} slippage` : ''}
            </strong>
          </div>
          <div>
            <span>Tipoff</span>
            <strong>{candidate.tipoff_utc ? formatDateTime(candidate.tipoff_utc) : 'Time unavailable'}</strong>
          </div>
        </div>
      </details>
    </article>
  )
}

function OpenPositionsPanel({ items, onDelete }: { items: PositionRecord[]; onDelete?: (tradeId: string) => void }) {
  return (
    <Surface className="stack-panel">
      <div className="stack-panel__header">
        <div>
          <span className="section-kicker">Open positions</span>
          <h3>Capital at work</h3>
        </div>
        <Pill>{items.length}</Pill>
      </div>
      {items.length ? (
        <div className="position-list">
          {items.slice(0, 12).map((item, index) => {
            const stage = positionStage(item)
            const currentValue = item.current_value ?? item.stake
            const livePnl = currentValue != null && item.stake != null ? Number(currentValue) - Number(item.stake) : null
            const currentTone = signedTone(livePnl)

            return (
              <div className="position-row" key={`${item.trade_id ?? index}`}>
                <div className="position-row__main">
                  <div className="position-row__title">
                    <strong>{item.contract_team ?? item.bet_side ?? 'Position'}</strong>
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
                    <Pill tone={stage.tone}>{stage.label}</Pill>
                    {item.auto_placed ? <span>Auto placed</span> : <span>Manual</span>}
                    <span>{item.tipoff_utc ? formatDateTime(item.tipoff_utc) : 'Tipoff unknown'}</span>
                  </div>
                </div>
                <div className="position-row__stats">
                  <div>
                    <span>Entry</span>
                    <strong className={valueClass('info')}>{pct0(item.entry_price)}</strong>
                  </div>
                  <div>
                    <span>Kalshi</span>
                    <strong className={valueClass(
                      item.current_mark_price != null && item.entry_price != null
                        ? Number(item.current_mark_price) >= Number(item.entry_price) ? 'good' : 'bad'
                        : 'info'
                    )}>{pct0(item.current_mark_price ?? item.entry_price)}</strong>
                  </div>
                  <div>
                    <span>Current</span>
                    <strong className={valueClass(currentTone)}>{money(currentValue)}</strong>
                  </div>
                  <div>
                    <span>Stake</span>
                    <strong className={valueClass('info')}>{money(item.stake)}</strong>
                  </div>
                  <div>
                    <span>Fees</span>
                    <strong className={valueClass('bad')}>
                      {money((Number(item.entry_fee ?? 0)) + (Number(item.current_exit_fee ?? 0)))}
                    </strong>
                  </div>
                  <div>
                    <span>P/L</span>
                    <strong className={livePnl == null ? '' : livePnl >= 0 ? 'is-good' : 'is-bad'}>
                      {moneySigned(livePnl)}
                    </strong>
                  </div>
                </div>
                {onDelete && item.trade_id && (
                  <button
                    className="icon-button icon-button--danger position-row__delete"
                    title="Remove trade"
                    onClick={() => onDelete(String(item.trade_id))}
                  >
                    <Trash2 size={14} />
                  </button>
                )}
              </div>
            )
          })}
        </div>
      ) : (
        <EmptyState title="No open positions" body="Nothing is currently active in the paper book." />
      )}
    </Surface>
  )
}

function SettledPositionsPanel({ items }: { items: PositionRecord[] }) {
  return (
    <Surface className="table-surface">
      <div className="stack-panel__header paper-section-header">
        <div>
          <span className="section-kicker">Settled positions</span>
          <h3>Closed trade ledger</h3>
        </div>
        <Pill>{items.length}</Pill>
      </div>
      {items.length ? (
        <table className="data-table-modern">
          <thead>
            <tr>
              <th>Date</th>
              <th>Game</th>
              <th>Position</th>
              <th>Source</th>
              <th>Entry</th>
              <th>Stake</th>
              <th>Result</th>
              <th>P/L</th>
            </tr>
          </thead>
          <tbody>
            {items.slice(0, 20).map((item, index) => (
              <tr key={`${item.trade_id ?? index}`}>
                <td>{item.placed_at ? formatDateTime(item.placed_at) : '—'}</td>
                <td>
                  <div className="table-matchup">
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
                </td>
                <td>{item.contract_team ?? item.bet_side ?? '—'}</td>
                <td>{titleCase(item.market_source)}</td>
                <td className={valueClass('info')}>{pct0(item.entry_price)}</td>
                <td className={valueClass('info')}>{money(item.stake)}</td>
                <td className={Number(item.win ?? 0) === 1 ? 'is-good' : 'is-bad'}>{Number(item.win ?? 0) === 1 ? 'Win' : 'Loss'}</td>
                <td className={(item.pnl ?? 0) >= 0 ? 'is-good' : 'is-bad'}>{moneySigned(item.pnl)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <EmptyState title="No settled trades" body="Closed trades will show up here with realized P/L and outcomes." />
      )}
    </Surface>
  )
}

function AutoTradePanel({
  league,
  status,
  busyAction,
  actionMessage,
  onAction,
}: {
  league: League
  status: AutoTradeStatus | undefined
  busyAction: AutoTradeConfig['action'] | null
  actionMessage: string
  onAction: (action: AutoTradeConfig['action']) => void
}) {
  if (league !== 'nba') {
    return (
      <Surface className="stack-panel">
        <div className="stack-panel__header">
          <div>
            <span className="section-kicker">Auto trade</span>
            <h3>Unavailable for NCAA</h3>
          </div>
          <Pill>Read only</Pill>
        </div>
        <EmptyState
          title="Auto trade unavailable for NCAA"
          body="The NCAA paper book is manual only in v1. Status and controls will stay hidden until backend support exists."
        />
      </Surface>
    )
  }

  if (!status) {
    return (
      <Surface className="stack-panel">
        <div className="stack-panel__header">
          <div>
            <span className="section-kicker">Auto trade</span>
            <h3>Control surface unavailable</h3>
          </div>
        </div>
        <ErrorState title="Auto-trade status unavailable" body="The server did not return the current auto-trade state." />
      </Surface>
    )
  }

  const stateTone = !status.available ? 'danger' : !status.enabled ? 'neutral' : status.mode === 'dry-run' ? 'accent' : 'good'
  const nextRunText = status.next_run
    ? formatDateTime(status.next_run)
    : status.enabled
      ? 'Waiting for next cycle'
      : 'Paused'
  const modeValueTone: ValueTone = !status.available ? 'warn' : !status.enabled ? 'warn' : status.mode === 'dry-run' ? 'info' : 'good'
  const resultValueTone: ValueTone = status.last_error ? 'bad' : (status.new_bets_placed ?? 0) > 0 ? 'good' : 'neutral'

  return (
    <Surface className="stack-panel">
      <div className="stack-panel__header">
        <div>
          <span className="section-kicker">Auto trade</span>
          <h3>Rules and controls</h3>
        </div>
        <Pill tone={stateTone}>{!status.available ? 'Unavailable' : !status.enabled ? 'Paused' : status.mode === 'dry-run' ? 'Dry run' : 'Armed'}</Pill>
      </div>

      <p className="paper-copy">{autoTradeSummary(status)}</p>

      <div className="paper-auto__actions">
        <Button disabled={busyAction != null} onClick={() => onAction('arm')}>
          {busyAction === 'arm' ? 'Arming…' : 'Arm auto trade'}
        </Button>
        <Button tone="secondary" disabled={busyAction != null} onClick={() => onAction('pause')}>
          {busyAction === 'pause' ? 'Pausing…' : 'Pause auto trade'}
        </Button>
        <Button tone="ghost" disabled={busyAction != null} onClick={() => onAction('run_dry_cycle')}>
          {busyAction === 'run_dry_cycle' ? 'Running…' : 'Run dry cycle'}
        </Button>
      </div>

      {actionMessage ? <Pill tone="accent">{actionMessage}</Pill> : null}

      <div className="paper-auto__grid">
        <div>
          <span>Mode</span>
          <strong className={valueClass(modeValueTone)}>{status.mode === 'dry-run' ? 'Dry run' : 'Armed'}</strong>
        </div>
        <div>
          <span>Next run</span>
          <strong className={valueClass('info')}>{nextRunText}</strong>
        </div>
        <div>
          <span>Last run</span>
          <strong className={valueClass('info')}>{status.last_run ? formatAgeSeconds((Date.now() - new Date(status.last_run).valueOf()) / 1000) : 'No runs yet'}</strong>
        </div>
        <div>
          <span>Result</span>
          <strong className={valueClass(resultValueTone)}>{status.last_message ?? `${status.new_bets_placed ?? 0} trades last cycle`}</strong>
        </div>
        <div>
          <span>Games checked</span>
          <strong className={valueClass('info')}>{status.games_checked ?? 0}</strong>
        </div>
        <div>
          <span>Trades placed</span>
          <strong className={valueClass(positiveTone(status.new_bets_placed))}>{status.new_bets_placed ?? 0}</strong>
        </div>
      </div>

      <div className="paper-explainer">
        <small>Auto-trade rules</small>
        <span>
          Polls every {Math.round((status.poll_seconds ?? 0) / 60) || 0} minutes, watches {status.sources?.join(' + ') ?? 'configured markets'},
          and only trades when edge clears {pct(status.min_edge)} during active hours {status.active_hours?.[0]}:00-{status.active_hours?.[1]}:00.
        </span>
      </div>

      {status.last_error ? (
        <div className="paper-error-inline">
          <small>Last error</small>
          <span>{status.last_error}</span>
        </div>
      ) : null}
    </Surface>
  )
}

export default function PaperTraderPage() {
  const params = useParams()
  const queryClient = useQueryClient()
  const league: League = isLeague(params.league) ? params.league : normalizeLeague(params.league)
  const [statusMessage, setStatusMessage] = useState('')
  const [autoStatusMessage, setAutoStatusMessage] = useState('')
  const [busyCandidateId, setBusyCandidateId] = useState<string | null>(null)
  const [busyAutoAction, setBusyAutoAction] = useState<AutoTradeConfig['action'] | null>(null)
  const [dismissedCandidateIds, setDismissedCandidateIds] = useState<string[]>([])

  const paperState = useQuery({
    queryKey: ['paper-state', league],
    queryFn: () => getPaperState(league),
  })
  const paperCandidates = useQuery({
    queryKey: ['paper-candidates', league],
    queryFn: () => getPaperCandidates(league),
  })
  const paperPositions = useQuery({
    queryKey: ['paper-positions', league],
    queryFn: () => getPaperPositions(league),
  })
  const autoTrade = useQuery({
    queryKey: ['auto-trade', league],
    queryFn: () => getAutoTradeStatus(league),
  })

  function invalidatePaperQueries() {
    void queryClient.invalidateQueries({ queryKey: ['paper-state', league] })
    void queryClient.invalidateQueries({ queryKey: ['paper-candidates', league] })
    void queryClient.invalidateQueries({ queryKey: ['paper-positions', league] })
    void queryClient.invalidateQueries({ queryKey: ['tracker', league] })
    void queryClient.invalidateQueries({ queryKey: ['auto-trade', league] })
  }

  const tradeMutation = useMutation({
    mutationFn: (candidateIds: string[]) => tradePaperCandidates(league, candidateIds),
    onSuccess: (data) => {
      setStatusMessage(data.message ?? `Logged ${data.logged ?? 0} trade${data.logged === 1 ? '' : 's'}.`)
      if (busyCandidateId) {
        setDismissedCandidateIds((current) => Array.from(new Set([...current, busyCandidateId])))
      }
      invalidatePaperQueries()
    },
    onError: () => {
      setStatusMessage('Trade could not be logged.')
    },
    onSettled: () => {
      setBusyCandidateId(null)
    },
  })

  const bulkTradeMutation = useMutation({
    mutationFn: () => logPaperTrades(league),
    onSuccess: (data) => {
      setStatusMessage(data.message ?? `Logged ${data.logged ?? 0} trades.`)
      setDismissedCandidateIds((current) => Array.from(new Set([...current, ...candidates.map((candidate) => candidate.candidate_id)])))
      invalidatePaperQueries()
    },
    onError: () => {
      setStatusMessage('Bulk paper trade logging failed.')
    },
  })

  const autoTradeMutation = useMutation({
    mutationFn: (action: AutoTradeConfig['action']) => updateAutoTrade({ action }),
    onSuccess: (data) => {
      setAutoStatusMessage(data.last_message ?? autoTradeSummary(data))
      invalidatePaperQueries()
    },
    onError: () => {
      setAutoStatusMessage('Auto-trade control update failed.')
    },
    onSettled: () => {
      setBusyAutoAction(null)
    },
  })

  const rawCandidates = useMemo(() => paperCandidates.data?.candidates ?? [], [paperCandidates.data?.candidates])
  const openPositions = useMemo(() => paperPositions.data?.open ?? [], [paperPositions.data?.open])
  const settledPositions = useMemo(() => paperPositions.data?.settled ?? [], [paperPositions.data?.settled])

  useEffect(() => {
    const activeCandidateIds = new Set(rawCandidates.map((candidate) => candidate.candidate_id))
    setDismissedCandidateIds((current) => current.filter((candidateId) => activeCandidateIds.has(candidateId)))
  }, [rawCandidates])

  const existingTradeIds = useMemo(
    () =>
      new Set(
        [...openPositions, ...settledPositions]
          .map((item) => String(item.trade_id ?? ''))
          .filter(Boolean),
      ),
    [openPositions, settledPositions],
  )

  const candidates = useMemo(
    () =>
      rawCandidates.filter(
        (candidate) =>
          !dismissedCandidateIds.includes(candidate.candidate_id)
          && !existingTradeIds.has(String(candidate.trade_id ?? '')),
      ),
    [dismissedCandidateIds, existingTradeIds, rawCandidates],
  )

  const deleteTradeM = useMutation({
    mutationFn: deletePaperTrade,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['paper-positions'] })
      queryClient.invalidateQueries({ queryKey: ['paper-state'] })
      queryClient.invalidateQueries({ queryKey: ['paper-candidates', league] })
    },
  })
  const handleDeleteTrade = (tradeId: string) => deleteTradeM.mutate(tradeId)

  if (paperState.isLoading || paperCandidates.isLoading || paperPositions.isLoading) {
    return <Surface className="loading-panel"><div><strong>Assembling Paper Trader</strong><p>Loading the portfolio, trade queue, and live ledger.</p></div></Surface>
  }

  if (paperState.isError || paperCandidates.isError || paperPositions.isError || !paperState.data) {
    return (
      <ErrorState
        title="Paper Trader unavailable"
        body="One or more paper-trader endpoints failed, so the trading workspace could not be assembled."
      />
    )
  }

  const bankroll = paperState.data.bankroll as PaperBankroll
  const equityTone = signedTone((bankroll.estimated_equity ?? 0) - (bankroll.starting_bankroll ?? 0))
  const queueTone = candidates.length ? 'good' : 'neutral'

  return (
    <div className="page-grid">
      <PortfolioHero
        bankroll={bankroll}
        openCount={paperState.data.open_count ?? openPositions.length}
        settledCount={paperState.data.settled_count ?? settledPositions.length}
        candidateCount={candidates.length}
      />

      <div className="metric-grid">
        <MetricCard
          label="Available cash"
          value={<span className={valueClass('info')}>{money(bankroll.available_cash)}</span>}
          hint="What can be deployed right now"
        />
        <MetricCard
          label="Open risk"
          value={<span className={valueClass('warn')}>{money(bankroll.open_risk)}</span>}
          hint="Capital already committed to active trades"
          accent={bankroll.open_risk > 0 ? 'warn' : 'default'}
        />
        <MetricCard
          label="Estimated equity"
          value={<span className={valueClass(equityTone)}>{money(bankroll.estimated_equity)}</span>}
          hint="Cash plus marked open positions"
          accent={equityTone === 'good' ? 'good' : equityTone === 'bad' ? 'warn' : 'default'}
        />
        <MetricCard
          label="Trade queue"
          value={<span className={valueClass(queueTone)}>{candidates.length}</span>}
          hint="Eligible ideas ready for review"
          accent={candidates.length ? 'good' : 'default'}
        />
      </div>

      <div className="paper-layout">
        <div className="paper-layout__main">
          <ManualTradePanel league={league} bankroll={bankroll} />
          
          <Surface className="stack-panel">
            <div className="stack-panel__header">
              <div>
                <span className="section-kicker">Trade queue</span>
                <h3>Review and place candidate trades</h3>
              </div>
              <div className="paper-actions">
                <Button
                  tone="secondary"
                  disabled={!candidates.length || bulkTradeMutation.isPending}
                  onClick={() => bulkTradeMutation.mutate()}
                >
                  {bulkTradeMutation.isPending ? 'Logging…' : 'Trade all eligible'}
                </Button>
                {statusMessage ? <Pill tone="accent">{statusMessage}</Pill> : null}
              </div>
            </div>
            <p className="paper-copy">
              Primary manual flow: review each ticket, understand the gap between model and market, then place the trade.
            </p>
            {candidates.length ? (
              <div className="paper-ticket-list">
                {candidates.map((candidate) => (
                  <CandidateCard
                    key={candidate.candidate_id}
                    candidate={candidate}
                    busy={busyCandidateId === candidate.candidate_id && tradeMutation.isPending}
                    onTrade={() => {
                      setBusyCandidateId(candidate.candidate_id)
                      setStatusMessage('')
                      tradeMutation.mutate([candidate.candidate_id])
                    }}
                  />
                ))}
              </div>
            ) : bankroll.available_cash <= 0 ? (
              <EmptyState
                title="No cash available"
                body="The queue is blocked because the paper book has no free capital right now."
              />
            ) : (
              <EmptyState
                title="No candidates right now"
                body={`No ${leagueLabels[league]} trade currently clears the paper-trading rules.`}
              />
            )}
          </Surface>

          <OpenPositionsPanel items={openPositions} onDelete={handleDeleteTrade} />
          <SettledPositionsPanel items={settledPositions} />
        </div>

        <div className="paper-layout__side">
          {autoTrade.isLoading ? (
            <Surface className="stack-panel">
              <div className="stack-panel__header">
                <div>
                  <span className="section-kicker">Auto trade</span>
                  <h3>Loading controls</h3>
                </div>
              </div>
              <p className="paper-copy">Loading auto-trade status and the latest background loop state.</p>
            </Surface>
          ) : (
            <AutoTradePanel
              league={league}
              status={autoTrade.data}
              busyAction={busyAutoAction}
              actionMessage={autoTradeMutation.isPending ? 'Updating auto-trade controls…' : autoStatusMessage}
              onAction={(action) => {
                setBusyAutoAction(action)
                setAutoStatusMessage('')
                autoTradeMutation.mutate(action)
              }}
            />
          )}
        </div>
      </div>
    </div>
  )
}
