import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { EmptyState, ErrorState, LoadingPanel, MetricCard, Pill, Surface } from '../components/ui'
import { getAccuracy, getTracker } from '../lib/api'
import { formatDate, pct, titleCase } from '../lib/format'
import { buildLeaguePath, isLeague, leagueLabels, normalizeLeague } from '../lib/navigation'
import { usePersistentState } from '../hooks/usePersistentState'
import type { AccuracyResponse, League, TrackerResponse } from '../types'

type HistoryTab = 'tracker' | 'accuracy'

function ChartSurface({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <Surface className="stack-panel">
      <div className="stack-panel__header">
        <div>
          <span className="section-kicker">Chart</span>
          <h3>{title}</h3>
        </div>
      </div>
      <div className="chart-wrap">{children}</div>
    </Surface>
  )
}

function TrackerPanel({ data }: { data: TrackerResponse }) {
  return (
    <div className="page-grid">
      <div className="metric-grid">
        <MetricCard label="Record" value={`${data.summary.wins ?? 0}-${data.summary.losses ?? 0}`} />
        <MetricCard label="Win rate" value={pct(data.summary.win_rate)} />
        <MetricCard label="Flat ROI" value={pct(data.summary.flat_roi)} />
        <MetricCard label="Total bets" value={data.summary.total_bets ?? 0} />
      </div>
      <ChartSurface title="Cumulative P/L">
        <ResponsiveContainer width="100%" height={240}>
          <AreaChart data={data.cumulative_pnl}>
            <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
            <XAxis dataKey="game_date" tickLine={false} axisLine={false} />
            <YAxis tickLine={false} axisLine={false} />
            <Tooltip />
            <Area type="monotone" dataKey="cumulative" stroke="#7b8dff" fill="rgba(123,141,255,0.18)" />
          </AreaChart>
        </ResponsiveContainer>
      </ChartSurface>
      <Surface className="table-surface">
        <table className="data-table-modern">
          <thead>
            <tr>
              <th>Date</th>
              <th>Game</th>
              <th>Position</th>
              <th>Entry</th>
              <th>P/L</th>
            </tr>
          </thead>
          <tbody>
            {data.bets.slice(0, 30).map((bet, index) => (
              <tr key={`${bet.trade_id ?? index}`}>
                <td>{formatDate(bet.game_date)}</td>
                <td>
                  {bet.away_team} @ {bet.home_team}
                </td>
                <td>{bet.contract_team ?? bet.bet_side ?? '—'}</td>
                <td>{pct(bet.entry_price, 0)}</td>
                <td className={(bet.pnl ?? 0) >= 0 ? 'is-good' : 'is-bad'}>
                  {bet.pnl == null ? '—' : `${bet.pnl >= 0 ? '+' : '-'}$${Math.abs(Number(bet.pnl)).toFixed(2)}`}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Surface>
    </div>
  )
}

function AccuracyPanel({ league, data }: { league: League; data: AccuracyResponse }) {
  if (data.error) {
    return (
      <EmptyState
        title={`${leagueLabels[league]} metrics unavailable`}
        body="The model metrics endpoint reports that the model has not been trained yet."
      />
    )
  }

  if (league === 'ncaab') {
    const metrics = data.metrics ?? {}
    return (
      <div className="page-grid">
        <div className="metric-grid">
          <MetricCard label="Accuracy" value={pct(Number(metrics.accuracy ?? 0))} />
          <MetricCard label="AUC-ROC" value={String(metrics.auc_roc ?? '—')} />
          <MetricCard label="Brier score" value={String(metrics.brier_score ?? '—')} />
          <MetricCard label="Games" value={String(metrics.n_games ?? metrics.num_games ?? '—')} />
        </div>
        <Surface className="table-surface">
          <table className="data-table-modern">
            <thead>
              <tr>
                <th>Metric</th>
                <th>Value</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(metrics).map(([key, value]) => (
                <tr key={key}>
                  <td>{titleCase(key)}</td>
                  <td>{String(value ?? '—')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Surface>
      </div>
    )
  }

  const backtest = Object.entries(data.backtest ?? {}).map(([threshold, values]) => ({
    threshold,
    terminal: values.cumulative_pnl?.at(-1) ?? 0,
  }))

  return (
    <div className="page-grid">
      <div className="metric-grid">
        <MetricCard label="Accuracy" value={pct(Number(data.metrics?.accuracy ?? 0))} />
        <MetricCard label="AUC-ROC" value={String(data.metrics?.auc_roc ?? '—')} />
        <MetricCard label="Brier score" value={String(data.metrics?.brier_score ?? '—')} />
        <MetricCard label="Games" value={String(data.metrics?.n_games ?? '—')} />
      </div>

      <div className="content-grid">
        <ChartSurface title="Calibration curve">
          <ResponsiveContainer width="100%" height={240}>
            <LineChart data={data.calibration}>
              <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
              <XAxis dataKey="mean_predicted" tickLine={false} axisLine={false} />
              <YAxis tickLine={false} axisLine={false} />
              <Tooltip />
              <Line type="monotone" dataKey="fraction_positive" stroke="#8dd3ff" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </ChartSurface>
        <ChartSurface title="ROI backtest">
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={backtest}>
              <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
              <XAxis dataKey="threshold" tickLine={false} axisLine={false} />
              <YAxis tickLine={false} axisLine={false} />
              <Tooltip />
              <Bar dataKey="terminal" fill="#7b8dff" radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartSurface>
      </div>

      <Surface className="table-surface">
        <table className="data-table-modern">
          <thead>
            <tr>
              <th>Feature</th>
              <th>Importance</th>
            </tr>
          </thead>
          <tbody>
            {(data.feature_importance ?? []).slice(0, 15).map((row, index) => (
              <tr key={`${row.feature ?? index}`}>
                <td>{row.feature ?? 'Feature'}</td>
                <td>{Number(row.importance ?? row.gain ?? 0).toFixed(3)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Surface>
    </div>
  )
}

export default function HistoryPage() {
  const params = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const league: League = isLeague(params.league) ? params.league : normalizeLeague(params.league)
  const [tab, setTab] = usePersistentState<HistoryTab>(`isotonic:${league}:history-tab`, 'tracker')

  useEffect(() => {
    const requested = searchParams.get('tab')
    if (requested === 'paper') {
      navigate(buildLeaguePath(league, 'paper-trader'), { replace: true })
      return
    }
    if (requested === 'accuracy' || requested === 'tracker') {
      setTab(requested)
    }
  }, [league, navigate, searchParams, setTab])

  const tracker = useQuery({
    queryKey: ['tracker', league],
    queryFn: () => getTracker(league),
    enabled: tab === 'tracker',
  })
  const accuracy = useQuery({
    queryKey: ['accuracy', league],
    queryFn: () => getAccuracy(league),
    enabled: tab === 'accuracy',
  })

  function changeTab(nextTab: HistoryTab) {
    setTab(nextTab)
    setSearchParams({ tab: nextTab }, { replace: true })
  }

  return (
    <div className="page-grid">
      <Surface className="filter-bar">
        <div className="segmented-control" role="tablist" aria-label="History sections">
          {(['tracker', 'accuracy'] as HistoryTab[]).map((item) => (
            <button key={item} className={item === tab ? 'is-active' : ''} onClick={() => changeTab(item)}>
              {titleCase(item)}
            </button>
          ))}
        </div>
        <Pill tone="accent">Paper Trader moved to its own tab</Pill>
      </Surface>

      {tab === 'tracker' ? (
        tracker.isLoading ? (
          <LoadingPanel label="Loading tracked performance" />
        ) : tracker.isError || !tracker.data ? (
          <ErrorState title="Tracker unavailable" body="The bet-tracker endpoint did not return usable data." />
        ) : (
          <TrackerPanel data={tracker.data} />
        )
      ) : null}

      {tab === 'accuracy' ? (
        accuracy.isLoading ? (
          <LoadingPanel label="Loading model accuracy" />
        ) : accuracy.isError || !accuracy.data ? (
          <ErrorState title="Accuracy unavailable" body="The model accuracy endpoint did not return usable data." />
        ) : (
          <AccuracyPanel league={league} data={accuracy.data} />
        )
      ) : null}
    </div>
  )
}
