import { useEffect, useMemo, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
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

import { Button, Surface, LoadingPanel, ErrorState, Pill } from '../components/ui'
import { getGameDetail } from '../lib/api'
import { pct0 } from '../lib/format'
import { isLeague, normalizeLeague } from '../lib/navigation'
import { TeamLogo } from '../components/ui'
import type { League, ProbSnapshot } from '../types'

const AWAY_COLOR = '#e8647c'   // soft rose
const HOME_COLOR = '#5b9cf6'   // soft blue


function buildChartData(history: ProbSnapshot[]) {
  return history.map((snap) => ({
    epoch: new Date(snap.ts).getTime(),
    modelHome: snap.model_home != null ? +(snap.model_home * 100).toFixed(1) : null,
    modelAway: snap.model_away != null ? +(snap.model_away * 100).toFixed(1) : null,
    marketHome: snap.market_home != null ? +(snap.market_home * 100).toFixed(1) : null,
    marketAway: snap.market_away != null ? +(snap.market_away * 100).toFixed(1) : null,
    score: `${snap.away_score} - ${snap.home_score}`,
  }))
}

const TEN_MIN = 10 * 60 * 1000

/** Rolling 10-minute window anchored to "now", tick every minute */
function buildXAxis(chartData: ReturnType<typeof buildChartData>) {
  if (!chartData.length) return { domain: [0, TEN_MIN] as [number, number], ticks: [] as number[] }
  const now = chartData[chartData.length - 1].epoch
  const windowStart = now - TEN_MIN
  const domain: [number, number] = [windowStart, now]
  // tick every 1 minute, aligned to whole minutes
  const firstTick = Math.ceil(windowStart / 60_000) * 60_000
  const ticks: number[] = []
  for (let t = firstTick; t <= now; t += 60_000) ticks.push(t)
  return { domain, ticks }
}

function formatEpoch(epoch: number) {
  const d = new Date(epoch)
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true }).toLowerCase()
}

function ProbTooltip({ active, payload }: {
  active?: boolean
  payload?: Array<{ name: string; value: number; color: string; dataKey: string }>
}) {
  if (!active || !payload?.length) return null
  const dp = payload[0]?.payload as ReturnType<typeof buildChartData>[number] | undefined
  return (
    <div className="game-detail-tooltip">
      {dp?.epoch && <div className="game-detail-tooltip__time">{formatEpoch(dp.epoch)}</div>}
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

/** Build right-edge label positions from Y domain */
function buildEdgeLabels(
  chartData: ReturnType<typeof buildChartData>,
  yDomain: [number, number],
  awayTeam: string,
  homeTeam: string,
) {
  if (!chartData.length) return []
  const last = chartData[chartData.length - 1]
  const entries = [
    { key: 'modelAway', value: last.modelAway, isMarket: false, isHome: false },
    { key: 'modelHome', value: last.modelHome, isMarket: false, isHome: true },
    { key: 'marketAway', value: last.marketAway, isMarket: true, isHome: false },
    { key: 'marketHome', value: last.marketHome, isMarket: true, isHome: true },
  ]

  const [lo, hi] = yDomain
  const range = hi - lo || 1

  const labels = entries
    .filter((e) => e.value != null)
    .map((e) => ({
      key: e.key,
      team: e.isHome ? homeTeam : awayTeam,
      pct: `${e.value!.toFixed(0)}%`,
      topPct: ((hi - e.value!) / range) * 100,
      isMarket: e.isMarket,
      color: e.isHome ? HOME_COLOR : AWAY_COLOR,
    }))
    .sort((a, b) => a.topPct - b.topPct)

  // Nudge overlapping labels apart
  for (let i = 1; i < labels.length; i++) {
    const gap = labels[i].topPct - labels[i - 1].topPct
    if (gap < 5) {
      labels[i - 1].topPct -= (5 - gap) / 2
      labels[i].topPct += (5 - gap) / 2
    }
  }

  return labels
}

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
  const chartData = useMemo(() => buildChartData(history), [history])
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

  return (
    <div className="page-grid">
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

        <div className="game-detail-hero__teams">
          <div className="game-detail-hero__team">
            <TeamLogo team={game.away_team as string} size={56} />
            <div className="game-detail-hero__team-info">
              <strong style={{ color: AWAY_COLOR }}>{game.away_team}</strong>
              <span className="game-detail-hero__score">{game.away_score ?? 0}</span>
            </div>
          </div>
          <div className="game-detail-hero__vs"><span>vs</span></div>
          <div className="game-detail-hero__team game-detail-hero__team--right">
            <TeamLogo team={game.home_team as string} size={56} />
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
      </Surface>

      {/* Chart */}
      <Surface className="game-detail-chart">
        <div className="game-detail-chart__container" ref={chartContainerRef}>
          {chartData.length < 2 ? (
            <div className="game-detail-chart__empty">
              <p>Probability data will appear once the game is in progress.</p>
              <p>Snapshots are recorded every ~3 seconds during live play.</p>
            </div>
          ) : (
            <>
            <ResponsiveContainer width="100%" height={360}>
              <LineChart data={chartData} margin={{ top: 16, right: 100, bottom: 4, left: 8 }}>
                <XAxis
                  dataKey="epoch"
                  type="number"
                  domain={xAxis.domain}
                  ticks={xAxis.ticks}
                  tickFormatter={formatEpoch}
                  tick={{ fill: 'rgba(255,255,255,0.35)', fontSize: 11 }}
                  axisLine={false}
                  tickLine={false}
                />
                <YAxis
                  domain={yAxis.domain}
                  ticks={yAxis.ticks}
                  hide
                />
                {yAxis.ticks.map((v) => (
                  <ReferenceLine
                    key={v}
                    y={v}
                    stroke="rgba(255,255,255,0.06)"
                    strokeDasharray="2 6"
                    label={{ value: `${v}%`, position: 'left', fill: 'rgba(255,255,255,0.2)', fontSize: 10 }}
                  />
                ))}
                <Tooltip content={<ProbTooltip />} cursor={{ stroke: 'rgba(255,255,255,0.1)' }} />

                {/* Model lines — solid */}
                <Line
                  type="monotone"
                  dataKey="modelAway"
                  name={game.away_team as string}
                  stroke={AWAY_COLOR}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 0, fill: AWAY_COLOR }}
                  connectNulls
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="modelHome"
                  name={game.home_team as string}
                  stroke={HOME_COLOR}
                  strokeWidth={2}
                  dot={false}
                  activeDot={{ r: 4, strokeWidth: 0, fill: HOME_COLOR }}
                  connectNulls
                  isAnimationActive={false}
                />

                {/* Market lines — faded */}
                <Line
                  type="monotone"
                  dataKey="marketAway"
                  name={`${game.away_team} Mkt`}
                  stroke={AWAY_COLOR}
                  strokeWidth={1}
                  strokeOpacity={0.3}
                  dot={false}
                  activeDot={false}
                  connectNulls
                  isAnimationActive={false}
                />
                <Line
                  type="monotone"
                  dataKey="marketHome"
                  name={`${game.home_team} Mkt`}
                  stroke={HOME_COLOR}
                  strokeWidth={1}
                  strokeOpacity={0.3}
                  dot={false}
                  activeDot={false}
                  connectNulls
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>

            {/* End-of-line labels */}
            {edgeLabels.length > 0 && (
              <div className="game-detail-chart__edge-labels">
                {edgeLabels.filter(l => !l.isMarket).map((l) => (
                  <div
                    key={l.key}
                    className="game-detail-chart__edge-label"
                    style={{ top: `${l.topPct}%`, color: l.color }}
                  >
                    <span className="game-detail-chart__edge-dot" style={{ background: l.color }} />
                    <span className="game-detail-chart__edge-team">{l.team}</span>
                    <span className="game-detail-chart__edge-pct">{l.pct}</span>
                  </div>
                ))}
                {edgeLabels.filter(l => l.isMarket).map((l) => (
                  <div
                    key={l.key}
                    className="game-detail-chart__edge-label game-detail-chart__edge-label--market"
                    style={{ top: `${l.topPct}%`, color: l.color }}
                  >
                    <span className="game-detail-chart__edge-dot game-detail-chart__edge-dot--market" style={{ background: l.color }} />
                    <span className="game-detail-chart__edge-team">{l.pct}</span>
                  </div>
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
