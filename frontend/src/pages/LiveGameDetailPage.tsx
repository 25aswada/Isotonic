import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'

import { Button, ConfirmationOverlay, Surface, LoadingPanel, ErrorState, Pill } from '../components/ui'
import { getGameDetail, getPaperState, logCustomPaperTrade, previewCustomPaperTrade } from '../lib/api'
import { money, pct0, titleCase } from '../lib/format'
import { isLeague, normalizeLeague } from '../lib/navigation'
import { TeamLogo } from '../components/ui'
import type { League, ProbSnapshot, LiveGame } from '../types'

const AWAY_COLOR = '#e8647c'   // soft rose
const HOME_COLOR = '#5b9cf6'   // soft blue
const NBA_REGULATION_SECONDS = 48 * 60
const NCAAB_REGULATION_SECONDS = 40 * 60
const NBA_PERIOD_SECONDS = 12 * 60
const NCAAB_PERIOD_SECONDS = 20 * 60
const OVERTIME_SECONDS = 5 * 60
const TIME_LABEL_FORMATTER = new Intl.DateTimeFormat('en-US', {
  hour: 'numeric',
  minute: '2-digit',
  hour12: true,
})

/* ── Game-time helpers ──────────────────────────────── */

/** Format a period + clock snapshot into a short game-time label, e.g. "H1 14:02" */
function formatGameTime(period?: string | number, clock?: string): string {
  const p = String(period ?? '').trim().toUpperCase()
  const c = (clock ?? '').trim()
  if (!p && !c) return ''
  // Shorten common labels
  const short = p
    .replace(/^1ST$/i, 'H1').replace(/^2ND$/i, 'H2')
    .replace(/^1ST HALF$/i, 'H1').replace(/^2ND HALF$/i, 'H2')
    .replace(/^Q(\d)$/i, 'Q$1')
    .replace(/^HALF$/i, 'HT')
    .replace(/^OT(\d?)$/i, (_m, n) => n ? `OT${n}` : 'OT')
  return c ? `${short} ${c}` : short
}

function parseClockToSeconds(clock?: string): number {
  const text = String(clock ?? '').trim()
  if (!text || !text.includes(':')) return 0
  const [minutes, seconds] = text.split(':', 2)
  const mm = Number(minutes)
  const ss = Number(seconds)
  if (!Number.isFinite(mm) || !Number.isFinite(ss)) return 0
  return Math.max(0, (mm * 60) + ss)
}

function elapsedGameSeconds(league: League, period?: string | number, clock?: string): number | null {
  const remaining = parseClockToSeconds(clock)

  if (league === 'nba') {
    const text = String(period ?? '').trim().toUpperCase()
    const qMatch = text.match(/^Q(\d+)$/)
    const otMatch = text.match(/^OT(\d+)?$/)
    if (qMatch) {
      const quarter = Number(qMatch[1])
      if (!Number.isFinite(quarter) || quarter <= 0) return null
      return ((quarter - 1) * NBA_PERIOD_SECONDS) + Math.max(0, NBA_PERIOD_SECONDS - remaining)
    }
    if (otMatch) {
      const overtime = Number(otMatch[1] || '1')
      return NBA_REGULATION_SECONDS + ((overtime - 1) * OVERTIME_SECONDS) + Math.max(0, OVERTIME_SECONDS - remaining)
    }
    const numeric = Number(period)
    if (Number.isFinite(numeric) && numeric > 0) {
      if (numeric <= 4) return ((numeric - 1) * NBA_PERIOD_SECONDS) + Math.max(0, NBA_PERIOD_SECONDS - remaining)
      return NBA_REGULATION_SECONDS + ((numeric - 5) * OVERTIME_SECONDS) + Math.max(0, OVERTIME_SECONDS - remaining)
    }
    return null
  }

  const text = String(period ?? '').trim().toUpperCase()
  const firstHalf = text === 'H1' || text === '1ST' || text === '1ST HALF'
  const secondHalf = text === 'H2' || text === '2ND' || text === '2ND HALF'
  const otMatch = text.match(/^OT(\d+)?$/)
  if (firstHalf) return Math.max(0, NCAAB_PERIOD_SECONDS - remaining)
  if (secondHalf) return NCAAB_PERIOD_SECONDS + Math.max(0, NCAAB_PERIOD_SECONDS - remaining)
  if (otMatch) {
    const overtime = Number(otMatch[1] || '1')
    return NCAAB_REGULATION_SECONDS + ((overtime - 1) * OVERTIME_SECONDS) + Math.max(0, OVERTIME_SECONDS - remaining)
  }
  const numeric = Number(period)
  if (Number.isFinite(numeric) && numeric > 0) {
    if (numeric <= 2) return ((numeric - 1) * NCAAB_PERIOD_SECONDS) + Math.max(0, NCAAB_PERIOD_SECONDS - remaining)
    return NCAAB_REGULATION_SECONDS + ((numeric - 3) * OVERTIME_SECONDS) + Math.max(0, OVERTIME_SECONDS - remaining)
  }
  return null
}

/* ── Chart data builder ─────────────────────────────── */

function buildChartData(history: ProbSnapshot[], league: League, game?: LiveGame) {
  const points = history.map((snap) => ({
    tsMs: Number(new Date(snap.ts).valueOf()),
    gameTime: formatGameTime(snap.period, snap.clock),
    elapsedSeconds: elapsedGameSeconds(league, snap.period, snap.clock),
    modelHome: snap.model_home != null ? +(snap.model_home * 100).toFixed(1) : null,
    modelAway: snap.model_away != null ? +(snap.model_away * 100).toFixed(1) : null,
    marketHome: snap.market_home != null ? +(snap.market_home * 100).toFixed(1) : null,
    marketAway: snap.market_away != null ? +(snap.market_away * 100).toFixed(1) : null,
    score: `${snap.away_score} - ${snap.home_score}`,
  }))

  const pregameHome = game?.pregame_home_prob != null ? Number(game.pregame_home_prob) * 100 : null
  const pregameAway = game?.pregame_away_prob != null
    ? Number(game.pregame_away_prob) * 100
    : pregameHome != null ? 100 - pregameHome : null
  const seededMarketHome = points.find((point) => point.marketHome != null)?.marketHome ?? (game?.kalshi_home_prob != null ? Number(game.kalshi_home_prob) * 100 : null)
  const seededMarketAway = points.find((point) => point.marketAway != null)?.marketAway ?? (game?.kalshi_away_prob != null ? Number(game.kalshi_away_prob) * 100 : null)
  const startTsMs = Number(new Date(game?.tipoff_utc ?? history[0]?.ts ?? Date.now()).valueOf())

  const seededPoints = [
    {
      tsMs: Number.isFinite(startTsMs) ? startTsMs : Date.now(),
      gameTime: 'Start',
      elapsedSeconds: 0,
      modelHome: pregameHome,
      modelAway: pregameAway,
      marketHome: seededMarketHome,
      marketAway: seededMarketAway,
      score: '0 - 0',
    },
    ...points,
  ]

  const deduped = seededPoints.filter((point, index, arr) => {
    if (index === 0) return true
    const prev = arr[index - 1]
    return point.tsMs !== prev.tsMs
      || point.modelHome !== prev.modelHome
      || point.modelAway !== prev.modelAway
      || point.marketHome !== prev.marketHome
      || point.marketAway !== prev.marketAway
      || point.score !== prev.score
  })

  const len = deduped.length
  return deduped.map((point, i) => ({
    idx: i,
    isLast: i === len - 1,
    ...point,
  }))
}

/** Pulsing dot on the last data point */
function LastDot(color: string, size: 'model' | 'market' = 'model') {
  const r = size === 'model' ? 5 : 3.5
  const pulseR = size === 'model' ? 12 : 8
  return (props: { cx?: number; cy?: number; payload?: { isLast?: boolean } }) => {
    if (!props.payload?.isLast || props.cx == null || props.cy == null) return null
    return (
      <g>
        <circle cx={props.cx} cy={props.cy} r={pulseR} fill={color} opacity={0}>
          <animate attributeName="r" from={String(r)} to={String(pulseR)} dur="1.5s" repeatCount="indefinite" />
          <animate attributeName="opacity" from="0.5" to="0" dur="1.5s" repeatCount="indefinite" />
        </circle>
        <circle cx={props.cx} cy={props.cy} r={r} fill={color} stroke="none" />
      </g>
    )
  }
}

function buildXAxis(data: ReturnType<typeof buildChartData>) {
  const minTs = data.reduce((min, point) => Math.min(min, point.tsMs ?? Number.POSITIVE_INFINITY), Number.POSITIVE_INFINITY)
  const maxTs = data.reduce((max, point) => Math.max(max, point.tsMs ?? 0), 0)
  const safeMin = Number.isFinite(minTs) ? minTs : Date.now()
  const rawMax = Math.max(maxTs, safeMin + 60_000)
  const span = rawMax - safeMin
  const rightPad = Math.max(Math.round(span * 0.05), 30_000)
  const safeMax = rawMax + rightPad
  const ticks = [safeMin]
  const segments = 4
  for (let i = 1; i < segments; i += 1) {
    ticks.push(safeMin + Math.round((span * i) / segments))
  }
  ticks.push(rawMax)

  return {
    domain: [safeMin, safeMax] as [number, number],
    ticks: Array.from(new Set(ticks)).sort((a, b) => a - b),
    tickFormatter: (value: number) => TIME_LABEL_FORMATTER.format(new Date(value)).toLowerCase(),
  }
}

/* ── Tooltip ────────────────────────────────────────── */

function ProbTooltip({ active, payload }: {
  active?: boolean
  payload?: Array<{
    name: string
    value: number
    color: string
    dataKey: string
    payload?: ReturnType<typeof buildChartData>[number]
  }>
}) {
  if (!active || !payload?.length) return null
  const dp = payload[0]?.payload as ReturnType<typeof buildChartData>[number] | undefined
  return (
    <div className="game-detail-tooltip">
      {dp?.gameTime && <div className="game-detail-tooltip__time">{dp.gameTime}</div>}
      {dp?.score && <div className="game-detail-tooltip__score">{dp.score}</div>}
      <div className="game-detail-tooltip__divider" />
      {payload.map((e) => (
        <div key={e.dataKey} className="game-detail-tooltip__row" style={{ color: e.color }}>
          <span>{e.name}</span>
          <strong>{e.value?.toFixed(1)}%</strong>
        </div>
      ))}
    </div>
  )
}

/* ── Edge labels (right side of chart) ──────────────── */

function buildEdgeLabels(
  chartData: ReturnType<typeof buildChartData>,
  yDomain: [number, number],
  awayTeam: string,
  homeTeam: string,
) {
  if (!chartData.length) return []
  const last = chartData[chartData.length - 1]
  const entries = [
    { key: 'away', value: last.modelAway, market: last.marketAway, team: awayTeam, color: AWAY_COLOR, isHome: false },
    { key: 'home', value: last.modelHome, market: last.marketHome, team: homeTeam, color: HOME_COLOR, isHome: true },
  ]

  const [lo, hi] = yDomain
  const range = hi - lo || 1

  const labels = entries
    .filter((e) => e.value != null && e.team)
    .map((e) => ({
      key: e.key,
      team: e.team,
      pct: `${e.value!.toFixed(0)}%`,
      marketPct: e.market != null ? `${e.market.toFixed(0)}%` : null,
      topPct: Math.max(4, Math.min(96, ((hi - e.value!) / range) * 100)),
      marketTopPct: e.market != null ? Math.max(4, Math.min(96, ((hi - e.market) / range) * 100)) : null,
      color: e.color,
      isHome: e.isHome,
    }))
    .sort((a, b) => a.topPct - b.topPct)

  // Nudge overlapping labels apart (min 12% gap)
  for (let i = 1; i < labels.length; i++) {
    const gap = labels[i].topPct - labels[i - 1].topPct
    if (gap < 12) {
      labels[i - 1].topPct -= (12 - gap) / 2
      labels[i].topPct += (12 - gap) / 2
    }
  }

  return labels
}

/* ── Dynamic Y domain ───────────────────────────────── */

function dynamicYDomain(data: ReturnType<typeof buildChartData>): { domain: [number, number]; ticks: number[] } {
  const vals: number[] = []
  for (const d of data) {
    if (d.modelHome != null) vals.push(d.modelHome)
    if (d.modelAway != null) vals.push(d.modelAway)
    if (d.marketHome != null) vals.push(d.marketHome)
    if (d.marketAway != null) vals.push(d.marketAway)
  }
  if (!vals.length) return { domain: [0, 100], ticks: [0, 25, 50, 75, 100] }

  const rawMin = Math.min(...vals)
  const rawMax = Math.max(...vals)
  const pad = Math.max((rawMax - rawMin) * 0.15, 8)
  const lo = Math.max(0, Math.floor((rawMin - pad) / 5) * 5)
  const hi = Math.min(100, Math.ceil((rawMax + pad) / 5) * 5)
  const step = (hi - lo) > 40 ? 10 : 5
  const ticks: number[] = []
  for (let v = lo; v <= hi; v += step) ticks.push(v)
  return { domain: [lo, hi], ticks }
}

function LiveTradePanel({ league, game }: { league: League; game: LiveGame }) {
  const queryClient = useQueryClient()
  const [selectedTeam, setSelectedTeam] = useState<string>(String(game.home_team ?? ''))
  const [customStake, setCustomStake] = useState(50)
  const [marketSource, setMarketSource] = useState('kalshi')
  const [confirmation, setConfirmation] = useState<{ title: string; body: string } | null>(null)

  useEffect(() => {
    setSelectedTeam(String(game.home_team ?? ''))
  }, [game.game_id, game.home_team])

  const paperState = useQuery({
    queryKey: ['paper-state', league],
    queryFn: () => getPaperState(league),
    refetchInterval: 15_000,
  })

  const bankroll = paperState.data?.bankroll
  const availableCash = bankroll?.available_cash ?? 0

  const manualPreview = useQuery({
    queryKey: ['live-detail-paper-preview', league, game.game_id, selectedTeam, customStake, marketSource],
    queryFn: () => previewCustomPaperTrade(
      league,
      String(game.home_team ?? ''),
      String(game.away_team ?? ''),
      selectedTeam,
      customStake,
      marketSource,
    ),
    enabled: Boolean(game.home_team && game.away_team && selectedTeam && customStake > 0),
    refetchInterval: selectedTeam ? 15_000 : false,
  })

  const customTradeMutation = useMutation({
    mutationFn: () => logCustomPaperTrade(
      league,
      String(game.home_team ?? ''),
      String(game.away_team ?? ''),
      selectedTeam,
      customStake,
      marketSource,
    ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['paper-state', league] })
      void queryClient.invalidateQueries({ queryKey: ['paper-positions', league] })
      void queryClient.invalidateQueries({ queryKey: ['live-detail-paper-preview', league, game.game_id] })
      setConfirmation({
        title: `${selectedTeam} live paper trade placed`,
        body: `${money(customStake)} was deployed on ${selectedTeam} via ${titleCase(marketSource)} from the live game screen.`,
      })
    },
  })

  const previewTrade = manualPreview.data?.trade

  return (
    <Surface className="game-detail-trade">
      <div className="stack-panel__header">
        <div>
          <span className="section-kicker">Live paper trade</span>
          <h3>Trade this game</h3>
        </div>
        <Pill tone="accent">{money(availableCash)} free</Pill>
      </div>

      <div className="game-detail-trade__body">
        <div className="game-detail-trade__controls">
          <div className="game-detail-trade__matchup">
            <div className="game-detail-trade__matchup-team">
              <TeamLogo team={(game.away_full_name ?? game.away_team) as string} size={18} />
              <span>{game.away_team}</span>
            </div>
            <span>@</span>
            <div className="game-detail-trade__matchup-team">
              <TeamLogo team={(game.home_full_name ?? game.home_team) as string} size={18} />
              <span>{game.home_team}</span>
            </div>
          </div>

          <div className="paper-manual__controls game-detail-trade__control-grid">
            <div>
              <label>Side</label>
              <div className="paper-manual__side-picks">
                <button
                  className={selectedTeam === game.away_team ? 'is-selected' : ''}
                  onClick={() => setSelectedTeam(String(game.away_team ?? ''))}
                >
                  {game.away_team || 'Away'}
                </button>
                <button
                  className={selectedTeam === game.home_team ? 'is-selected' : ''}
                  onClick={() => setSelectedTeam(String(game.home_team ?? ''))}
                >
                  {game.home_team || 'Home'}
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
              <label>Stake</label>
              <div className="paper-manual__money-input">
                <span>$</span>
                <input
                  type="number"
                  min="1"
                  max={Math.max(1, Math.floor(availableCash))}
                  step="1"
                  value={customStake}
                  onChange={(e) => setCustomStake(Number(e.target.value))}
                />
              </div>
            </div>
          </div>
        </div>

        <div className="game-detail-trade__ticket">
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
                <Pill tone="accent">{titleCase(String(previewTrade.market_source ?? marketSource))}</Pill>
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
            <div className="paper-manual__empty game-detail-trade__empty">
              <strong>{manualPreview.isFetching ? 'Pricing trade…' : 'Build a live ticket'}</strong>
              <p>Choose a side and stake to preview the live paper trade with the current market price.</p>
            </div>
          )}

          {customTradeMutation.error ? (
            <div className="paper-error-message">
              Error: {customTradeMutation.error instanceof Error ? customTradeMutation.error.message : 'Unknown error'}
            </div>
          ) : null}
        </div>
      </div>
      <ConfirmationOverlay
        open={Boolean(confirmation)}
        title={confirmation?.title ?? ''}
        body={confirmation?.body ?? ''}
        onClose={() => setConfirmation(null)}
      />
    </Surface>
  )
}

/* ── Page component ─────────────────────────────────── */

export default function LiveGameDetailPage() {
  const params = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const league: League = isLeague(params.league) ? params.league : normalizeLeague(params.league)
  const gameId = params.gameId ?? ''

  const detailQuery = useQuery({
    queryKey: ['live-game', league, gameId],
    queryFn: () => getGameDetail(league, gameId),
    refetchInterval: 1_000,
    enabled: !!gameId,
  })

  useEffect(() => {
    if (league !== 'nba') return
    const source = new EventSource('/api/live/stream')
    source.addEventListener('games', () => {
      queryClient.invalidateQueries({ queryKey: ['live-game', league, gameId] })
    })
    return () => source.close()
  }, [league, gameId, queryClient])

  const game = detailQuery.data?.game
  const history = detailQuery.data?.history ?? []
  const chartData = useMemo(() => buildChartData(history, league, game), [history, league, game])
  const xAxis = useMemo(() => buildXAxis(chartData), [chartData])
  const yAxis = useMemo(() => dynamicYDomain(chartData), [chartData])
  const edgeLabels = useMemo(
    () => buildEdgeLabels(chartData, yAxis.domain, (game?.away_team ?? '') as string, (game?.home_team ?? '') as string),
    [chartData, yAxis.domain, game?.away_team, game?.home_team],
  )

  const chartContainerRef = useRef<HTMLDivElement>(null)

  if (detailQuery.isLoading && !detailQuery.data) return <LoadingPanel label="Loading game detail" />
  if (!game) return <ErrorState title="Game not found" body="Could not load game data." />

  const homeProb = Number(game.live_home_prob ?? game.pregame_home_prob ?? game.home_win_prob ?? 0.5)
  const awayProb = Number(game.live_away_prob ?? game.pregame_away_prob ?? game.away_win_prob ?? 0.5)
  const kalshiHome = game.kalshi_home_prob != null ? Number(game.kalshi_home_prob) : null
  const kalshiAway = game.kalshi_away_prob != null ? Number(game.kalshi_away_prob) : null
  const isLive = game.game_status === 2
  const isFinal = game.game_status === 3
  const latestPlay = (game.latest_play as { text?: string; clock?: string; period?: string; scoring_play?: boolean } | undefined) ?? undefined

  return (
    <div className="game-detail-page">
      <div className="game-detail-back">
        <Button tone="ghost" onClick={() => navigate(`/app/${league}/live`)}>
          <ArrowLeft size={16} />
          Back to live board
        </Button>
      </div>

      {/* Score header */}
      <Surface className="game-detail-hero">
        <div className="game-detail-hero__status">
          {isLive && <span className="game-detail-hero__live-dot" />}
          <span className={isLive ? 'game-detail-hero__live-text' : ''}>
            {isLive ? 'LIVE' : isFinal ? 'FINAL' : 'UPCOMING'}
          </span>
          {game.period_label && <span>{game.period_label}</span>}
          {game.clock_display && <span>{game.clock_display}</span>}
        </div>

        <div className="game-detail-hero__body">
          <div className="game-detail-hero__summary">
            <div className="game-detail-hero__teams">
              <div className="game-detail-hero__team">
                <TeamLogo team={(game.away_full_name ?? game.away_team) as string} size={48} />
                <div className="game-detail-hero__team-info">
                  <strong style={{ color: AWAY_COLOR }}>{game.away_team}</strong>
                  <span className="game-detail-hero__score">{game.away_score ?? 0}</span>
                </div>
              </div>
              <div className="game-detail-hero__vs"><span>vs</span></div>
              <div className="game-detail-hero__team game-detail-hero__team--right">
                <TeamLogo team={(game.home_full_name ?? game.home_team) as string} size={48} />
                <div className="game-detail-hero__team-info">
                  <strong style={{ color: HOME_COLOR }}>{game.home_team}</strong>
                  <span className="game-detail-hero__score">{game.home_score ?? 0}</span>
                </div>
              </div>
            </div>

            <div className="game-detail-hero__probs">
              <div className="game-detail-hero__prob-group">
                <span className="game-detail-hero__prob-label">Model</span>
                <div className="game-detail-hero__prob-row">
                  <Pill tone={awayProb > homeProb ? 'good' : 'neutral'}>
                    {game.away_team} {pct0(awayProb)}
                  </Pill>
                  <Pill tone={homeProb > awayProb ? 'good' : 'neutral'}>
                    {game.home_team} {pct0(homeProb)}
                  </Pill>
                </div>
              </div>
              {kalshiHome != null && (
                <div className="game-detail-hero__prob-group">
                  <span className="game-detail-hero__prob-label">Market</span>
                  <div className="game-detail-hero__prob-row">
                    <Pill tone="neutral">{game.away_team} {pct0(kalshiAway)}</Pill>
                    <Pill tone="neutral">{game.home_team} {pct0(kalshiHome)}</Pill>
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="game-detail-hero__updates">
            <div className="game-detail-hero__updates-card">
              <div className="game-detail-hero__updates-head">
                <span className="section-kicker">Live Update</span>
                <Pill tone={latestPlay?.scoring_play ? 'accent' : 'neutral'}>
                  {latestPlay?.period ?? game.period_label ?? 'Live'}
                  {latestPlay?.clock ? ` ${latestPlay.clock}` : game.clock_display ? ` ${game.clock_display}` : ''}
                </Pill>
              </div>
              <strong className="game-detail-hero__updates-title">
                {latestPlay?.text ?? (isLive ? 'Tracking live game flow and waiting for the next ESPN summary play.' : 'Live updates will appear here once the game starts.')}
              </strong>
              <div className="game-detail-hero__updates-meta">
                <div>
                  <span>State</span>
                  <strong>{isLive ? 'In progress' : isFinal ? 'Final' : 'Pregame'}</strong>
                </div>
                <div>
                  <span>Score</span>
                  <strong>{game.away_team} {game.away_score ?? 0} - {game.home_score ?? 0} {game.home_team}</strong>
                </div>
              </div>
            </div>
          </div>
        </div>
      </Surface>

      <LiveTradePanel league={league} game={game} />

      {/* Chart */}
      <Surface className="game-detail-chart">
        <div className="game-detail-chart__container" ref={chartContainerRef}>
          {chartData.length < 2 ? (
            <div className="game-detail-chart__empty">
              <p>Probability data will appear once the game is in progress.</p>
            </div>
          ) : (
            <>
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={chartData} margin={{ top: 8, right: 132, bottom: 8, left: 28 }}>
                <XAxis
                  type="number"
                  dataKey="tsMs"
                  domain={xAxis.domain}
                  ticks={xAxis.ticks}
                  tickFormatter={xAxis.tickFormatter}
                  tick={{ fill: 'rgba(255,255,255,0.35)', fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                  allowDataOverflow
                  minTickGap={24}
                />
                <YAxis
                  domain={yAxis.domain}
                  ticks={yAxis.ticks}
                  tickFormatter={(v: number) => `${v}%`}
                  axisLine={false}
                  tickLine={false}
                  tick={{ fill: 'rgba(255,255,255,0.32)', fontSize: 11 }}
                  width={36}
                  orientation="left"
                />
                {yAxis.ticks.map((v) => (
                  <ReferenceLine
                    key={v}
                    y={v}
                    stroke="rgba(255,255,255,0.06)"
                    strokeDasharray="3 6"
                  />
                ))}
                <Tooltip content={<ProbTooltip />} cursor={{ stroke: 'rgba(255,255,255,0.08)' }} />

                <Line
                  type="stepAfter"
                  dataKey="marketAway"
                  name={`${game.away_team} Market`}
                  stroke={AWAY_COLOR}
                  strokeWidth={1.5}
                  strokeOpacity={0.32}
                  strokeDasharray="6 5"
                  dot={LastDot(AWAY_COLOR, 'market')}
                  activeDot={false}
                  connectNulls
                  isAnimationActive={false}
                />
                <Line
                  type="stepAfter"
                  dataKey="marketHome"
                  name={`${game.home_team} Market`}
                  stroke={HOME_COLOR}
                  strokeWidth={1.5}
                  strokeOpacity={0.32}
                  strokeDasharray="6 5"
                  dot={LastDot(HOME_COLOR, 'market')}
                  activeDot={false}
                  connectNulls
                  isAnimationActive={false}
                />
                <Line
                  type="stepAfter"
                  dataKey="modelAway"
                  name={game.away_team as string}
                  stroke={AWAY_COLOR}
                  strokeWidth={3}
                  dot={LastDot(AWAY_COLOR)}
                  activeDot={{ r: 4, strokeWidth: 0, fill: AWAY_COLOR }}
                  connectNulls
                  isAnimationActive={false}
                />
                <Line
                  type="stepAfter"
                  dataKey="modelHome"
                  name={game.home_team as string}
                  stroke={HOME_COLOR}
                  strokeWidth={3}
                  dot={LastDot(HOME_COLOR)}
                  activeDot={{ r: 4, strokeWidth: 0, fill: HOME_COLOR }}
                  connectNulls
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>

            {/* End-of-line labels */}
            {edgeLabels.length > 0 && (
              <div className="game-detail-chart__edge-labels">
                {edgeLabels.map((l) => (
                  <>
                    <div
                      key={`${l.key}-live`}
                      className={`game-detail-chart__edge-label ${l.isHome ? 'is-home' : 'is-away'}`}
                      style={{ top: `${l.topPct}%`, color: l.color }}
                    >
                      <span className="game-detail-chart__edge-copy">
                        <span className="game-detail-chart__edge-team">{l.team}</span>
                        <span className="game-detail-chart__edge-pct">{l.pct}</span>
                      </span>
                    </div>
                    {l.marketPct && l.marketTopPct != null ? (
                      <div
                        key={`${l.key}-market`}
                        className={`game-detail-chart__edge-label game-detail-chart__edge-label--market ${l.isHome ? 'is-home' : 'is-away'}`}
                        style={{ top: `${l.marketTopPct}%`, color: l.color }}
                      >
                        <span className="game-detail-chart__edge-copy">
                          <span className="game-detail-chart__edge-market">mrkt: {l.marketPct}</span>
                        </span>
                      </div>
                    ) : null}
                  </>
                ))}
              </div>
            )}
            </>
          )}
        </div>
      </Surface>

      {/* Info cards */}
      <div className="game-detail-info">
        {game.pred_away_score != null && game.pred_home_score != null && (
          <Surface className="game-detail-info__card">
            <span className="section-kicker">Predicted Score</span>
            <strong>{game.away_team} {game.pred_away_score} - {game.pred_home_score} {game.home_team}</strong>
          </Surface>
        )}
        {game.pregame_home_prob != null && (
          <Surface className="game-detail-info__card">
            <span className="section-kicker">Pregame Model</span>
            <strong>
              {game.away_team} {pct0(1 - Number(game.pregame_home_prob))} / {pct0(game.pregame_home_prob)} {game.home_team}
            </strong>
          </Surface>
        )}
        {(game.live_home_edge != null || game.live_away_edge != null) && (
          <Surface className="game-detail-info__card">
            <span className="section-kicker">Live Edge</span>
            <strong>
              {game.away_team} {pct0(game.live_away_edge)} / {pct0(game.live_home_edge)} {game.home_team}
            </strong>
          </Surface>
        )}
      </div>
    </div>
  )
}
