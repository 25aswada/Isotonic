import { useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { BarChart3, Shield, Swords, TrendingUp } from 'lucide-react'
import { useParams } from 'react-router-dom'

import { EmptyState, ErrorState, LoadingPanel, MetricCard, Pill, Surface, TeamLogo } from '../components/ui'
import {
  getBracket,
  getLive,
  getMatchup,
  getMatchupTeams,
  getTeamExplorer,
  getTeamExplorerTeams,
} from '../lib/api'
import { formatDate, integer, num, pct, pct0, sparklinePath } from '../lib/format'
import { isLeague, leagueLabels, normalizeLeague } from '../lib/navigation'
import { teamAccent } from '../lib/teamColor'

import { usePersistentState } from '../hooks/usePersistentState'
import type { League, LivePayload, MatchupResponse, TeamExplorerResponse } from '../types'

type ResearchTab = 'matchup' | 'teams' | 'bracket'

function TrajectoryTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: Array<{ color?: string; name?: string; value?: number }>
  label?: string
}) {
  if (!active || !payload?.length) return null

  return (
    <div className="trajectory-tooltip">
      <div className="trajectory-tooltip__label">{formatDate(label)}</div>
      {payload.map((entry) => (
        <div className="trajectory-tooltip__row" key={entry.name}>
          <span className="trajectory-tooltip__name">
            <i style={{ background: entry.color }} />
            {entry.name}
          </span>
          <strong>{num(entry.value, 1)}</strong>
        </div>
      ))}
    </div>
  )
}

function TeamSelector({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: string[]
  onChange: (value: string) => void
}) {
  return (
    <label className="select-field">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  )
}

/* ── Stat comparison row renderer ────────────────────────── */
type CompRow = [string, number | string | null | undefined, number | string | null | undefined, boolean?]

function ComparisonBlock({
  title,
  icon,
  rows,
  teamAColor,
  teamBColor,
  format: fmt = 'num',
}: {
  title: string
  icon: React.ReactNode
  rows: CompRow[]
  teamAColor: string
  teamBColor: string
  format?: 'num' | 'pct'
}) {
  const display = (v: number | string | null | undefined) => {
    if (v == null) return '—'
    const n = Number(v)
    if (Number.isNaN(n)) return String(v)
    if (fmt === 'pct') return pct(n)
    return num(n)
  }

  return (
    <Surface className="stack-panel">
      <div className="stack-panel__header">
        <div>
          <h3>{title}</h3>
        </div>
        {icon}
      </div>
      <div className="comparison-table">
        {rows
          .filter(([, left, right]) => left != null || right != null)
          .map(([label, left, right, lowerBetter]) => {
            const vA = Number(left ?? 0)
            const vB = Number(right ?? 0)
            const shift = Math.min(vA, vB, 0) - 0.001
            const sA = vA - shift
            const sB = vB - shift
            const total = sA + sB
            const shareA = total > 0 ? (sA / total) * 100 : 50
            const shareB = 100 - shareA
            const aWins = lowerBetter ? vA < vB : vA > vB
            const bWins = lowerBetter ? vB < vA : vB > vA
            return (
              <div className="comparison-table__row" key={String(label)}>
                <span
                  className="comparison-table__value"
                  style={{ color: aWins ? 'var(--good)' : bWins ? 'var(--bad)' : 'var(--text)' }}
                >
                  {display(left)}
                </span>
                <div>
                  <small>{label}</small>
                  <div className="comparison-table__track comparison-table__track--split">
                    <i style={{ width: `${shareA}%`, background: teamAColor }} />
                    <i style={{ width: `${shareB}%`, background: teamBColor }} />
                  </div>
                </div>
                <span
                  className="comparison-table__value"
                  style={{ color: bWins ? 'var(--good)' : aWins ? 'var(--bad)' : 'var(--text)' }}
                >
                  {display(right)}
                </span>
              </div>
            )
          })}
      </div>
    </Surface>
  )
}

function FormTable({
  team,
  form,
}: {
  team: string
  form: Array<Record<string, number | string>>
}) {
  if (!form.length) return null
  const recent = form.slice(-8).reverse()
  const wins = recent.filter((g) => Number(g.win) === 1).length
  const losses = recent.length - wins

  return (
    <Surface className="stack-panel">
      <div className="stack-panel__header">
        <div>
          <span className="section-kicker">Last {recent.length} games</span>
          <h3>
            <TeamLogo team={team} size={16} />
            {team}{' '}
            <span style={{ color: 'var(--text-secondary)', fontWeight: 400, fontSize: '0.85em' }}>
              {wins}-{losses}
            </span>
          </h3>
        </div>
      </div>
      <div className="form-table">
        {recent.map((g, i) => {
          const won = Number(g.win) === 1
          return (
            <div className={`form-table__row ${won ? 'is-win' : 'is-loss'}`} key={i}>
              <span className="form-table__result" style={{ color: won ? 'var(--good)' : 'var(--bad)' }}>
                {won ? 'W' : 'L'}
              </span>
              <span className="form-table__score">
                {g.pts ?? '?'}-{g.opp_pts ?? '?'}
              </span>
              {g.opponent ? <span className="form-table__opp">{String(g.opponent).slice(0, 18)}</span> : null}
              <span className="form-table__date">{formatDate(String(g.game_date ?? ''))}</span>
            </div>
          )
        })}
      </div>
    </Surface>
  )
}

function H2HTable({
  teamA,
  teamB,
  h2h,
  summary,
}: {
  teamA: string
  teamB: string
  h2h: Array<Record<string, number | string>>
  summary: Record<string, number>
}) {
  if (!h2h.length) return null
  const aWins = summary.a_wins ?? 0
  const bWins = summary.b_wins ?? 0
  const leader = aWins > bWins ? teamA : bWins > aWins ? teamB : 'Tied'

  return (
    <Surface className="stack-panel">
      <div className="stack-panel__header">
        <div>
          <span className="section-kicker">Recent matchups</span>
          <h3>
            Head to head{' '}
            <span style={{ color: 'var(--text-secondary)', fontWeight: 400, fontSize: '0.85em' }}>
              {leader === 'Tied' ? `Tied ${aWins}-${bWins}` : `${leader} leads ${Math.max(aWins, bWins)}-${Math.min(aWins, bWins)}`}
            </span>
          </h3>
        </div>
      </div>
      <div className="form-table">
        {h2h
          .slice()
          .reverse()
          .map((g, i) => {
            const winner = String(g.winner ?? '')
            return (
              <div className="form-table__row" key={i}>
                <span className="form-table__result" style={{ color: winner === teamA ? 'var(--good)' : 'var(--bad)' }}>
                  {winner === teamA ? teamA : teamB}
                </span>
                <span className="form-table__score">
                  {g.home_pts ?? '?'}-{g.away_pts ?? '?'}
                </span>
                <span className="form-table__date">{formatDate(String(g.game_date ?? ''))}</span>
              </div>
            )
          })}
      </div>
    </Surface>
  )
}

function MatchupSurface({ data, league }: { data: MatchupResponse; league: League }) {
  const teamA = String(data.team_a ?? 'Team A')
  const teamB = String(data.team_b ?? 'Team B')
  const probA = Number(data.pred_prob_a ?? data.team_a_win_prob ?? 0.5)
  const probB = Number(data.pred_prob_b ?? data.team_b_win_prob ?? 1 - probA)
  const statsA = data.stats_a ?? {}
  const statsB = data.stats_b ?? {}

  const teamAColor = teamAccent(teamA)
  const teamBColor = teamAccent(teamB)

  /* ── Stat categories ── */
  const overallRows: CompRow[] =
    league === 'nba'
      ? [
          ['Elo', statsA.elo, statsB.elo],
          ['Net rating', statsA.net_rtg, statsB.net_rtg],
          ['Win %', statsA.roll_10_win_pct ?? statsA.win_pct, statsB.roll_10_win_pct ?? statsB.win_pct],
          ['Avg margin', statsA.point_diff, statsB.point_diff],
        ]
      : [
          ['Elo', statsA.elo, statsB.elo],
          ['Net rating', statsA.net_rtg, statsB.net_rtg],
          ['Win %', statsA.win_pct, statsB.win_pct],
          ['Avg margin', statsA.avg_margin, statsB.avg_margin],
          ['SRS', statsA.srs, statsB.srs],
          ['SOS', statsA.sos, statsB.sos],
        ]

  const offenseRows: CompRow[] =
    league === 'nba'
      ? [
          ['Off rating', statsA.off_rtg, statsB.off_rtg],
          ['EFG%', statsA.efg_pct, statsB.efg_pct],
          ['TS%', statsA.ts_pct, statsB.ts_pct],
          ['Pace', statsA.pace, statsB.pace],
          ['FT rate', statsA.ft_rate, statsB.ft_rate],
          ['TOV rate', statsA.tov_rate, statsB.tov_rate, true],
        ]
      : [
          ['Off rating', statsA.off_rtg, statsB.off_rtg],
          ['Avg pts for', statsA.avg_score_for, statsB.avg_score_for],
          ['EFG%', statsA.efg, statsB.efg],
          ['Pace', statsA.pace, statsB.pace],
          ['3PT rate', statsA.fg3_rate, statsB.fg3_rate],
          ['FT%', statsA.ft_pct, statsB.ft_pct],
          ['AST rate', statsA.ast_rate, statsB.ast_rate],
          ['TOV rate', statsA.tov_rate, statsB.tov_rate, true],
        ]

  const defenseRows: CompRow[] =
    league === 'nba'
      ? [
          ['Def rating', statsA.def_rtg, statsB.def_rtg, true],
          ['Opp EFG%', statsA.opp_efg_pct, statsB.opp_efg_pct, true],
          ['Opp TOV rate', statsA.opp_tov_rate, statsB.opp_tov_rate],
          ['DREB%', statsA.dreb_pct, statsB.dreb_pct],
          ['OREB%', statsA.oreb_pct, statsB.oreb_pct],
        ]
      : [
          ['Def rating', statsA.def_rtg, statsB.def_rtg, true],
          ['Avg pts against', statsA.avg_score_against, statsB.avg_score_against, true],
          ['Opp EFG%', statsA.opp_efg, statsB.opp_efg, true],
          ['Opp TOV rate', statsA.opp_tov_rate, statsB.opp_tov_rate],
          ['STL rate', statsA.stl_rate, statsB.stl_rate],
          ['BLK rate', statsA.blk_rate, statsB.blk_rate],
          ['DREB%', statsA.dreb_pct, statsB.dreb_pct],
          ['OREB%', statsA.oreb_pct, statsB.oreb_pct],
        ]

  const formRows: CompRow[] =
    league === 'ncaab'
      ? [
          ['Last 10 win %', statsA.last10_win_pct, statsB.last10_win_pct],
          ['Last 10 margin', statsA.last10_margin, statsB.last10_margin],
          ['Consistency (std)', statsA.std_margin, statsB.std_margin, true],
          ['Median rank', statsA.median_rank, statsB.median_rank, true],
          ['Best rank', statsA.best_rank, statsB.best_rank, true],
        ]
      : [
          ['Win streak', statsA.win_streak, statsB.win_streak],
          ['Rest days', statsA.rest_days, statsB.rest_days],
        ]

  /* ── Elo trajectory ── */
  const eloHistory = useMemo(() => {
    const rows = new Map<string, { game_date: string; teamAValue?: number; teamBValue?: number }>()
    for (const entry of data.elo_history_a ?? []) {
      const key = String(entry.game_date ?? '')
      if (!key) continue
      const current = rows.get(key) ?? { game_date: key }
      if (entry.elo != null) current.teamAValue = Number(entry.elo)
      rows.set(key, current)
    }
    for (const entry of data.elo_history_b ?? []) {
      const key = String(entry.game_date ?? '')
      if (!key) continue
      const current = rows.get(key) ?? { game_date: key }
      if (entry.elo != null) current.teamBValue = Number(entry.elo)
      rows.set(key, current)
    }
    return Array.from(rows.values()).sort((left, right) => String(left.game_date).localeCompare(String(right.game_date)))
  }, [data.elo_history_a, data.elo_history_b])

  const eloTrajectory = eloHistory.slice(-24)
  const latestTeamAElo =
    eloHistory.findLast((entry) => entry.teamAValue != null)?.teamAValue ??
    (statsA.elo != null ? Number(statsA.elo) : undefined)
  const latestTeamBElo =
    eloHistory.findLast((entry) => entry.teamBValue != null)?.teamBValue ??
    (statsB.elo != null ? Number(statsB.elo) : undefined)

  return (
    <div className="page-grid">
      {/* ── Hero ── */}
      <Surface className="hero-panel hero-panel--matchup" tone="accent">
        <div className="hero-matchup">
          <div className="hero-matchup__team">
            <TeamLogo team={teamA} size={64} />
            <span>{teamA}</span>
            <strong style={{ color: probA >= probB ? 'var(--good)' : 'var(--bad)' }}>{pct0(probA)}</strong>
          </div>
          <div className="hero-matchup__divider">vs</div>
          <div className="hero-matchup__team">
            <TeamLogo team={teamB} size={64} />
            <span>{teamB}</span>
            <strong style={{ color: probB > probA ? 'var(--good)' : 'var(--bad)' }}>{pct0(probB)}</strong>
          </div>
        </div>
        <div className="hero-panel__copy">
          <span className="hero-panel__eyebrow">{leagueLabels[league]} matchup lab</span>
          <h2>{data.favorite === 'Even' ? 'Model sees a coin flip.' : `${data.favorite} holds the edge.`}</h2>
          <p>
            {data.confidence_label ?? 'Moderate'} confidence · predicted score {integer(data.pred_score_a)}-
            {integer(data.pred_score_b)}
          </p>
          <div className="hero-panel__chips">
            <Pill tone="accent">{data.prediction_source === 'full_model' ? 'Full model' : 'Current model'}</Pill>
            {data.seed_baseline_prob != null ? <Pill>Seed baseline {pct(data.seed_baseline_prob)}</Pill> : null}
            {data.market_odds?.kalshi_a_prob != null ? (
              <Pill>Kalshi {pct0(data.market_odds.kalshi_a_prob)}-{pct0(data.market_odds.kalshi_b_prob ?? 1 - (data.market_odds.kalshi_a_prob ?? 0.5))}</Pill>
            ) : null}
          </div>
        </div>
      </Surface>

      {/* ── Narrative blurb ── */}
      {data.narrative ? (
        <Surface className="narrative-panel">
          <div className="narrative-panel__header">
            <span className="section-kicker">The model's take</span>
          </div>
          {data.narrative.split('\n\n').map((para, i) => (
            <p className="narrative-panel__text" key={i}>{para}</p>
          ))}
          {data.team_a_availability_summary && data.team_a_availability_summary !== 'No major availability flags' ? (
            <p className="narrative-panel__availability">
              <strong>{teamA}:</strong> {data.team_a_availability_summary}
            </p>
          ) : null}
          {data.team_b_availability_summary && data.team_b_availability_summary !== 'No major availability flags' ? (
            <p className="narrative-panel__availability">
              <strong>{teamB}:</strong> {data.team_b_availability_summary}
            </p>
          ) : null}
        </Surface>
      ) : null}

      {/* ── Stat comparison blocks ── */}
      <div className="content-grid">
        <ComparisonBlock
          title="Overall"
          icon={<BarChart3 size={16} />}
          rows={overallRows}
          teamAColor={teamAColor}
          teamBColor={teamBColor}
        />
        <ComparisonBlock
          title="Offense"
          icon={<Swords size={16} />}
          rows={offenseRows}
          teamAColor={teamAColor}
          teamBColor={teamBColor}
        />
      </div>

      <div className="content-grid">
        <ComparisonBlock
          title="Defense"
          icon={<Shield size={16} />}
          rows={defenseRows}
          teamAColor={teamAColor}
          teamBColor={teamBColor}
        />
        <ComparisonBlock
          title="Form & momentum"
          icon={<TrendingUp size={16} />}
          rows={formRows}
          teamAColor={teamAColor}
          teamBColor={teamBColor}
        />
      </div>

      {/* ── Elo trajectory ── */}
      <Surface className="stack-panel">
        <div className="stack-panel__header">
          <div>
            <span className="section-kicker">Season trajectory</span>
            <h3>Elo rating over time</h3>
          </div>
          <Pill>{leagueLabels[league]}</Pill>
        </div>
        {eloTrajectory.length ? (
          <>
            <div className="trajectory-legend">
              <div className="trajectory-legend__item">
                <TeamLogo team={teamA} size={18} />
                <span className="trajectory-legend__line" style={{ background: teamAColor }} />
                <div>
                  <small>{teamA}</small>
                  <strong>{num(latestTeamAElo, 1)}</strong>
                </div>
              </div>
              <div className="trajectory-legend__item">
                <TeamLogo team={teamB} size={18} />
                <span className="trajectory-legend__line" style={{ background: teamBColor }} />
                <div>
                  <small>{teamB}</small>
                  <strong>{num(latestTeamBElo, 1)}</strong>
                </div>
              </div>
            </div>
            <div className="trajectory-chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={eloTrajectory} margin={{ top: 8, right: 10, bottom: 0, left: -20 }}>
                  <CartesianGrid stroke="rgba(255,255,255,0.08)" vertical={false} />
                  <XAxis
                    dataKey="game_date"
                    tickFormatter={(value) => formatDate(String(value))}
                    tickLine={false}
                    axisLine={false}
                    minTickGap={24}
                    tick={{ fill: 'rgba(255,255,255,0.48)', fontSize: 11 }}
                  />
                  <YAxis
                    tickLine={false}
                    axisLine={false}
                    width={44}
                    tick={{ fill: 'rgba(255,255,255,0.48)', fontSize: 11 }}
                    domain={['dataMin - 8', 'dataMax + 8']}
                  />
                  <Tooltip content={<TrajectoryTooltip />} />
                  <Line type="monotone" dataKey="teamAValue" name={teamA} stroke={teamAColor} strokeWidth={3} dot={false} activeDot={{ r: 5, stroke: teamAColor, strokeWidth: 2, fill: '#0c0c0d' }} connectNulls />
                  <Line type="monotone" dataKey="teamBValue" name={teamB} stroke={teamBColor} strokeWidth={3} dot={false} activeDot={{ r: 5, stroke: teamBColor, strokeWidth: 2, fill: '#0c0c0d' }} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </>
        ) : (
          <EmptyState title="No Elo history" body="Historical matchup context is not available for this pair yet." />
        )}
      </Surface>

      {/* ── Recent form ── */}
      {(data.form_a?.length || data.form_b?.length) ? (
        <div className="content-grid">
          {data.form_a?.length ? <FormTable team={teamA} form={data.form_a} /> : null}
          {data.form_b?.length ? <FormTable team={teamB} form={data.form_b} /> : null}
        </div>
      ) : null}

      {/* ── Head-to-head ── */}
      {data.h2h?.length && data.h2h_summary ? (
        <H2HTable teamA={teamA} teamB={teamB} h2h={data.h2h} summary={data.h2h_summary} />
      ) : null}
    </div>
  )
}

function NbaTeamExplorer({ data }: { data: TeamExplorerResponse }) {
  const eloValues = (data.elo_history ?? []).map((entry) => Number(entry.elo ?? 0))
  const offenseValues = (data.rolling_form ?? []).map((entry) => Number(entry.roll_10_pts ?? 0))

  return (
    <div className="page-grid">
      <div className="metric-grid">
        <MetricCard label="Current Elo" value={integer(data.current_elo)} />
        <MetricCard
          label={`Record (${data.record_season ?? 'season'})`}
          value={`${data.season_record?.wins ?? 0}-${data.season_record?.losses ?? 0}`}
        />
        <MetricCard label="Win rate" value={pct(data.win_pct)} />
      </div>

      <div className="content-grid">
        <Surface className="stack-panel">
          <div className="stack-panel__header">
            <div>
              <span className="section-kicker">Season line</span>
              <h3>Elo history</h3>
            </div>
          </div>
          <svg className="sparkline-chart" viewBox="0 0 260 88">
            <path className="sparkline-chart__line" d={sparklinePath(eloValues)} />
          </svg>
        </Surface>
        <Surface className="stack-panel">
          <div className="stack-panel__header">
            <div>
              <span className="section-kicker">Trend line</span>
              <h3>Rolling offense</h3>
            </div>
          </div>
          <svg className="sparkline-chart" viewBox="0 0 260 88">
            <path className="sparkline-chart__line sparkline-chart__line--subtle" d={sparklinePath(offenseValues)} />
          </svg>
        </Surface>
      </div>
    </div>
  )
}

function NcaaTeamExplorer({ data }: { data: TeamExplorerResponse }) {
  const eloValues = (data.elo_history ?? []).map((entry) => Number(entry.elo ?? 0))
  const offenseValues = (data.rolling_form ?? []).map((entry) => Number(entry.roll_10_pts ?? 0))
  const defenseValues = (data.rolling_form ?? []).map((entry) => Number(entry.roll_10_opp_pts ?? 0))

  return (
    <div className="page-grid">
      <div className="metric-grid">
        <MetricCard label="Current Elo" value={integer(data.current_elo)} />
        <MetricCard
          label={`Record (${data.record_season ?? 'season'})`}
          value={`${data.season_record?.wins ?? 0}-${data.season_record?.losses ?? 0}`}
        />
        <MetricCard label="Win rate" value={pct(data.win_pct)} />
        <MetricCard label="Seed" value={String(data.seed ?? '—')} />
        <MetricCard label="Net rating" value={num(data.net_rtg)} />
        <MetricCard label="Avg margin" value={num(data.avg_margin)} />
      </div>

      <div className="content-grid">
        <Surface className="stack-panel">
          <div className="stack-panel__header">
            <div>
              <span className="section-kicker">Season line</span>
              <h3>Elo history</h3>
            </div>
          </div>
          <svg className="sparkline-chart" viewBox="0 0 260 88">
            <path className="sparkline-chart__line" d={sparklinePath(eloValues)} />
          </svg>
        </Surface>
        <Surface className="stack-panel">
          <div className="stack-panel__header">
            <div>
              <span className="section-kicker">Trend line</span>
              <h3>Rolling offense</h3>
            </div>
          </div>
          <svg className="sparkline-chart" viewBox="0 0 260 88">
            <path className="sparkline-chart__line sparkline-chart__line--subtle" d={sparklinePath(offenseValues)} />
          </svg>
        </Surface>
      </div>

      <div className="metric-grid">
        <MetricCard label="Off rating" value={num(data.off_rtg)} />
        <MetricCard label="Def rating" value={num(data.def_rtg)} />
        <MetricCard label="Last 10 win %" value={pct(data.last10_win_pct)} />
        <MetricCard label="Last 10 margin" value={num(data.last10_margin)} />
        <MetricCard label="Median rank" value={integer(data.median_rank)} />
        <MetricCard label="Best rank" value={integer(data.best_rank)} />
      </div>

      <div className="content-grid">
        <Surface className="stack-panel">
          <div className="stack-panel__header">
            <div>
              <span className="section-kicker">Trend line</span>
              <h3>Rolling defense</h3>
            </div>
          </div>
          <svg className="sparkline-chart" viewBox="0 0 260 88">
            <path className="sparkline-chart__line sparkline-chart__line--subtle" d={sparklinePath(defenseValues)} />
          </svg>
        </Surface>
      </div>
    </div>
  )
}

type BracketRow = Record<string, string | number | null>
type BracketSide = 'left' | 'right'

const BRACKET_ROUNDS = ['Round of 64', 'Round of 32', 'Sweet 16', 'Elite 8'] as const
const BRACKET_REGION_SIDES = {
  left: ['East', 'South'],
  right: ['West', 'Midwest'],
} as const satisfies Record<BracketSide, string[]>
const BRACKET_SEED_PAIRS = [
  [1, 16],
  [8, 9],
  [5, 12],
  [4, 13],
  [6, 11],
  [3, 14],
  [7, 10],
  [2, 15],
] as const

function buildBracketSeedLookup(rows: BracketRow[]) {
  const lookup = new Map<string, number>()

  for (const region of Object.values(BRACKET_REGION_SIDES).flat()) {
    const round64 = rows.filter((row) => row.region === region && row.round === 'Round of 64').slice(0, 8)
    round64.forEach((row, index) => {
      const [seedA, seedB] = BRACKET_SEED_PAIRS[index] ?? []
      if (row.team_a_id != null && seedA != null) lookup.set(String(row.team_a_id), seedA)
      if (row.team_b_id != null && seedB != null) lookup.set(String(row.team_b_id), seedB)
    })
  }

  return lookup
}

function bracketTeamSeed(seedLookup: Map<string, number>, row: BracketRow, side: 'a' | 'b') {
  const teamId = row[`team_${side}_id`]
  return teamId != null ? seedLookup.get(String(teamId)) ?? null : null
}

function bracketTeamName(row: BracketRow, side: 'a' | 'b') {
  return String(row[`team_${side}_name`] ?? 'TBD')
}

function bracketNormalizeTeamName(value: string | null | undefined) {
  return String(value ?? '')
    .toLowerCase()
    .replace(/\([^)]*\)/g, ' ')
    .replace(/'/g, '')
    .replace(/\./g, '')
    .replace(/&/g, 'and')
    .replace(/\bsaint\b/g, 'st')
    .replace(/\bst\b/g, 'st')
    .replace(/\bcalifornia\b/g, 'cal')
    .replace(/\bmiami ohio\b/g, 'miami oh')
    .replace(/\bca baptist\b/g, 'cal baptist')
    .replace(/\s+/g, ' ')
    .trim()
}

function bracketNamesMatch(left: string | null | undefined, right: string | null | undefined) {
  const a = bracketNormalizeTeamName(left)
  const b = bracketNormalizeTeamName(right)
  if (!a || !b) return false
  return a === b || a.startsWith(b) || b.startsWith(a) || a.includes(b) || b.includes(a)
}

function buildActualResultLookup(
  liveData?: LivePayload | null,
  bracketResults?: Array<Record<string, string | number | null>>,
) {
  const results: Array<{ winner: string | null; homeTeam: string; awayTeam: string }> = []
  for (const row of bracketResults ?? []) {
    const away = String(row.away_team ?? '').trim()
    const home = String(row.home_team ?? '').trim()
    const winner = String(row.winner_name ?? '').trim()
    if (!away || !home || !winner) continue
    results.push({ winner, awayTeam: away, homeTeam: home })
  }

  const games = [
    ...(liveData?.final ?? []),
    ...(liveData?.in_progress ?? []),
    ...(liveData?.upcoming ?? []),
  ]

  for (const game of games) {
    const away = String(game.away_full_name ?? game.away_team ?? '').trim()
    const home = String(game.home_full_name ?? game.home_team ?? '').trim()
    if (!away || !home) continue

    const isFinal = Number(game.game_status) === 3
    const awayScore = Number(game.away_score ?? 0)
    const homeScore = Number(game.home_score ?? 0)
    const winner = isFinal ? (awayScore > homeScore ? away : home) : null
    results.push({ winner, awayTeam: away, homeTeam: home })
  }

  return results
}

function findActualResult(
  actualResults: Array<{ winner: string | null; homeTeam: string; awayTeam: string }>,
  teamA: string,
  teamB: string,
) {
  return actualResults.find((result) => (
    (bracketNamesMatch(teamA, result.awayTeam) && bracketNamesMatch(teamB, result.homeTeam))
    || (bracketNamesMatch(teamA, result.homeTeam) && bracketNamesMatch(teamB, result.awayTeam))
  ))
}

function mapActualWinnerToBracketTeam(teamA: string, teamB: string, winner: string | null) {
  if (!winner) return null
  if (bracketNamesMatch(teamA, winner)) return teamA
  if (bracketNamesMatch(teamB, winner)) return teamB
  return null
}

function buildCurrentBracketRows(
  rows: BracketRow[],
  liveData?: LivePayload | null,
  bracketResults?: Array<Record<string, string | number | null>>,
) {
  const cleanRow = (row: BracketRow): BracketRow => ({
    ...row,
    winner_id: null,
    winner_name: null,
    win_prob: null,
    sim_win_pct: null,
    is_upset: 0,
    winner_seed: null,
    loser_seed: null,
    winner_seed_edge: null,
  })

  const placeholder = (round: string, region: string, index: number): BracketRow => ({
    round,
    region,
    order: index,
    team_a_id: null,
    team_b_id: null,
    team_a_name: 'TBD',
    team_b_name: 'TBD',
    winner_id: null,
    winner_name: null,
    win_prob: null,
    sim_win_pct: null,
    is_upset: 0,
    winner_seed: null,
    loser_seed: null,
    seed_baseline_prob: null,
    winner_seed_edge: null,
  })
  const withTeams = (row: BracketRow, teamA: string, teamB: string): BracketRow => ({
    ...row,
    team_a_name: teamA,
    team_b_name: teamB,
  })

  const playIns = rows
    .filter((row) => row.round === 'First Four')
    .map(cleanRow)

  const actualResults = buildActualResultLookup(liveData, bracketResults)
  const playInWinnerBySeedRegion = new Map<string, string>()

  for (const row of playIns) {
    const teamA = bracketTeamName(row, 'a')
    const teamB = bracketTeamName(row, 'b')
    const actual = findActualResult(actualResults, teamA, teamB)
    const bracketWinner = mapActualWinnerToBracketTeam(teamA, teamB, actual?.winner ?? null)
    if (bracketWinner) {
      row.winner_name = bracketWinner
      const winnerSeed = row.winner_seed ?? bracketTeamSeed(buildBracketSeedLookup(rows), row, bracketWinner === teamA ? 'a' : 'b')
      if (winnerSeed != null) {
        playInWinnerBySeedRegion.set(`${row.region}::${winnerSeed}`, bracketWinner)
      }
    }
  }

  const regionRows = Object.values(BRACKET_REGION_SIDES)
    .flat()
    .flatMap((region) => {
      const round64 = rows
        .filter((row) => row.region === region && row.round === 'Round of 64')
        .slice(0, 8)
        .map(cleanRow)

      round64.forEach((row, index) => {
        const [seedA, seedB] = BRACKET_SEED_PAIRS[index] ?? []
        if (seedA != null) {
          const playInWinner = playInWinnerBySeedRegion.get(`${region}::${seedA}`)
          if (playInWinner) row.team_a_name = playInWinner
        }
        if (seedB != null) {
          const playInWinner = playInWinnerBySeedRegion.get(`${region}::${seedB}`)
          if (playInWinner) row.team_b_name = playInWinner
        }

        const teamA = bracketTeamName(row, 'a')
        const teamB = bracketTeamName(row, 'b')
        const actual = findActualResult(actualResults, teamA, teamB)
        const bracketWinner = mapActualWinnerToBracketTeam(teamA, teamB, actual?.winner ?? null)
        if (bracketWinner) {
          row.winner_name = bracketWinner
        }
      })

      const round32 = Array.from({ length: 4 }, (_, index) => {
        const sourceA = round64[index * 2]
        const sourceB = round64[(index * 2) + 1]
        return withTeams(
          placeholder('Round of 32', region, index),
          String(sourceA?.winner_name ?? 'TBD'),
          String(sourceB?.winner_name ?? 'TBD'),
        )
      })

      round32.forEach((row) => {
        const teamA = bracketTeamName(row, 'a')
        const teamB = bracketTeamName(row, 'b')
        if (teamA === 'TBD' || teamB === 'TBD') return
        const actual = findActualResult(actualResults, teamA, teamB)
        const bracketWinner = mapActualWinnerToBracketTeam(teamA, teamB, actual?.winner ?? null)
        if (bracketWinner) {
          row.winner_name = bracketWinner
        }
      })

      const sweet16 = Array.from({ length: 2 }, (_, index) => {
        const sourceA = round32[index * 2]
        const sourceB = round32[(index * 2) + 1]
        return withTeams(
          placeholder('Sweet 16', region, index),
          String(sourceA?.winner_name ?? 'TBD'),
          String(sourceB?.winner_name ?? 'TBD'),
        )
      })

      sweet16.forEach((row) => {
        const teamA = bracketTeamName(row, 'a')
        const teamB = bracketTeamName(row, 'b')
        if (teamA === 'TBD' || teamB === 'TBD') return
        const actual = findActualResult(actualResults, teamA, teamB)
        const bracketWinner = mapActualWinnerToBracketTeam(teamA, teamB, actual?.winner ?? null)
        if (bracketWinner) {
          row.winner_name = bracketWinner
        }
      })

      const elite8 = withTeams(
        placeholder('Elite 8', region, 0),
        String(sweet16[0]?.winner_name ?? 'TBD'),
        String(sweet16[1]?.winner_name ?? 'TBD'),
      )

      {
        const teamA = bracketTeamName(elite8, 'a')
        const teamB = bracketTeamName(elite8, 'b')
        if (teamA !== 'TBD' && teamB !== 'TBD') {
          const actual = findActualResult(actualResults, teamA, teamB)
          const bracketWinner = mapActualWinnerToBracketTeam(teamA, teamB, actual?.winner ?? null)
          if (bracketWinner) {
            elite8.winner_name = bracketWinner
          }
        }
      }

      return [
        ...round64,
        ...round32,
        ...sweet16,
        elite8,
      ]
    })

  const eastWinner = regionRows.find((row) => row.region === 'East' && row.round === 'Elite 8')?.winner_name ?? 'TBD'
  const southWinner = regionRows.find((row) => row.region === 'South' && row.round === 'Elite 8')?.winner_name ?? 'TBD'
  const westWinner = regionRows.find((row) => row.region === 'West' && row.round === 'Elite 8')?.winner_name ?? 'TBD'
  const midwestWinner = regionRows.find((row) => row.region === 'Midwest' && row.round === 'Elite 8')?.winner_name ?? 'TBD'

  const finalFourTop = withTeams(
    placeholder('Final Four', 'East vs Midwest', 0),
    String(eastWinner),
    String(midwestWinner),
  )
  const finalFourBottom = withTeams(
    placeholder('Final Four', 'South vs West', 1),
    String(southWinner),
    String(westWinner),
  )

  ;[finalFourTop, finalFourBottom].forEach((row) => {
    const teamA = bracketTeamName(row, 'a')
    const teamB = bracketTeamName(row, 'b')
    if (teamA === 'TBD' || teamB === 'TBD') return
    const actual = findActualResult(actualResults, teamA, teamB)
    const bracketWinner = mapActualWinnerToBracketTeam(teamA, teamB, actual?.winner ?? null)
    if (bracketWinner) {
      row.winner_name = bracketWinner
    }
  })

  const titleGame = withTeams(
    placeholder('National Championship', 'National Championship', 0),
    String(finalFourTop.winner_name ?? 'TBD'),
    String(finalFourBottom.winner_name ?? 'TBD'),
  )

  {
    const teamA = bracketTeamName(titleGame, 'a')
    const teamB = bracketTeamName(titleGame, 'b')
    if (teamA !== 'TBD' && teamB !== 'TBD') {
      const actual = findActualResult(actualResults, teamA, teamB)
      const bracketWinner = mapActualWinnerToBracketTeam(teamA, teamB, actual?.winner ?? null)
      if (bracketWinner) {
        titleGame.winner_name = bracketWinner
      }
    }
  }

  const finalRounds = [finalFourTop, finalFourBottom, titleGame]

  return [...playIns, ...regionRows, ...finalRounds]
}

function BracketTeamRow({
  row,
  side,
  seedLookup,
}: {
  row: BracketRow
  side: 'a' | 'b'
  seedLookup: Map<string, number>
}) {
  const team = bracketTeamName(row, side)
  const seed = bracketTeamSeed(seedLookup, row, side)
  const winner = String(row.winner_name ?? '')
  const isWinner = winner === team

  return (
    <div className={`tournament-match__team ${isWinner ? 'is-winner' : winner ? 'is-loser' : ''}`}>
      <div className="tournament-match__team-main">
        <span className="tournament-match__seed">{seed ?? '—'}</span>
        <TeamLogo team={team} size={16} className="tournament-match__logo" />
        <span className="tournament-match__name">{team}</span>
      </div>
    </div>
  )
}

function BracketMatchCard({
  row,
  seedLookup,
}: {
  row: BracketRow
  seedLookup: Map<string, number>
}) {
  return (
    <div className="tournament-match">
      <BracketTeamRow row={row} side="a" seedLookup={seedLookup} />
      <BracketTeamRow row={row} side="b" seedLookup={seedLookup} />
    </div>
  )
}

function RegionBracket({
  region,
  rows,
  seedLookup,
  side,
}: {
  region: string
  rows: BracketRow[]
  seedLookup: Map<string, number>
  side: BracketSide
}) {
  const orderedRounds = side === 'left' ? [...BRACKET_ROUNDS] : [...BRACKET_ROUNDS].reverse()

  return (
    <section className={`tournament-region tournament-region--${side}`}>
      <div className="tournament-region__header">
        <span className="tournament-region__name">{region}</span>
        <span className="tournament-region__rounds">Round of 64 · 32 · Sweet 16 · Elite 8</span>
      </div>
      <div className="tournament-tree">
        {orderedRounds.map((round) => (
          <div className="tournament-round" key={`${region}-${round}`}>
            <div className="tournament-round__title">
              {round === 'Round of 64'
                ? 'Round of 64'
                : round === 'Round of 32'
                  ? 'Round of 32'
                  : round}
            </div>
            <div className="tournament-round__games">
              {rows
                .filter((row) => row.region === region && row.round === round)
                .map((row, matchIndex) => (
                  <BracketMatchCard
                    key={`${region}-${round}-${matchIndex}`}
                    row={row}
                    seedLookup={seedLookup}
                  />
                ))}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}

function CenterMatch({
  label,
  row,
  seedLookup,
  tone,
}: {
  label: string
  row: BracketRow
  seedLookup: Map<string, number>
  tone?: 'title'
}) {
  return (
    <div className={`tournament-center__match ${tone === 'title' ? 'is-title' : ''}`}>
      <div className="tournament-center__label">{label}</div>
      <BracketTeamRow row={row} side="a" seedLookup={seedLookup} />
      <BracketTeamRow row={row} side="b" seedLookup={seedLookup} />
    </div>
  )
}

function BracketBoard({
  rows,
  liveData,
  bracketResults,
}: {
  rows: BracketRow[]
  liveData?: LivePayload
  bracketResults?: Array<Record<string, string | number | null>>
}) {
  const displayRows = useMemo(
    () => buildCurrentBracketRows(rows, liveData, bracketResults),
    [rows, liveData, bracketResults],
  )
  const seedLookup = useMemo(() => buildBracketSeedLookup(displayRows), [displayRows])
  const playInRows = displayRows.filter((row) => row.round === 'First Four')
  const semifinalRows = displayRows.filter((row) => row.round === 'Final Four')
  const titleRow = displayRows.find((row) => row.round === 'National Championship')
  const projectionDate = String(rows[0]?.projection_date ?? '')

  return (
    <>
      <Surface className="tournament-board" tone="accent">
        <div className="tournament-board__hero">
          <span className="section-kicker">Men&apos;s tournament · official field</span>
          <h2>Current Bracket</h2>
          <p>
            Real current bracket slots only. Future rounds stay `TBD` until results are known.
            {projectionDate ? ` Field snapshot: ${projectionDate}.` : ''}
          </p>
        </div>

        {playInRows.length ? (
          <div className="tournament-playins">
            <span className="tournament-playins__label">First Four</span>
            <div className="tournament-playins__list">
              {playInRows.map((row, index) => (
                <div className="tournament-playins__card" key={`playin-${index}`}>
                  <BracketTeamRow row={row} side="a" seedLookup={seedLookup} />
                  <BracketTeamRow row={row} side="b" seedLookup={seedLookup} />
                </div>
              ))}
            </div>
          </div>
        ) : null}

        <div className="tournament-board__scroller">
          <div className="tournament-board__builder">
            <div className="tournament-board__side">
              {BRACKET_REGION_SIDES.left.map((region) => (
                <RegionBracket key={region} region={region} rows={displayRows} seedLookup={seedLookup} side="left" />
              ))}
            </div>

            <div className="tournament-center">
              {semifinalRows.map((row, index) => (
                <CenterMatch key={`semifinal-${index}`} label="Final Four" row={row} seedLookup={seedLookup} />
              ))}
              {titleRow ? (
                <CenterMatch label="National Championship" row={titleRow} seedLookup={seedLookup} tone="title" />
              ) : null}
              <div className="tournament-center__champion">
                <div className="tournament-center__champion-badge">
                  <span>Awaiting results</span>
                </div>
                <strong>TBD</strong>
                <p>The title path will fill in as the real tournament advances.</p>
              </div>
            </div>

            <div className="tournament-board__side">
              {BRACKET_REGION_SIDES.right.map((region) => (
                <RegionBracket key={region} region={region} rows={displayRows} seedLookup={seedLookup} side="right" />
              ))}
            </div>
          </div>
        </div>
      </Surface>
    </>
  )
}

export default function ResearchPage() {
  const params = useParams()
  const league: League = isLeague(params.league) ? params.league : normalizeLeague(params.league)
  const availableTabs: ResearchTab[] = league === 'nba' ? ['matchup', 'teams'] : ['matchup', 'teams', 'bracket']
  const [tab, setTab] = usePersistentState<ResearchTab>(
    `isotonic:${league}:research-tab`,
    availableTabs[0],
  )
  const [teamA, setTeamA] = usePersistentState(`isotonic:${league}:team-a`, league === 'nba' ? 'BOS' : '')
  const [teamB, setTeamB] = usePersistentState(`isotonic:${league}:team-b`, league === 'nba' ? 'LAL' : '')
  const [teamExplorer, setTeamExplorer] = usePersistentState(`isotonic:${league}:team-explorer`, league === 'nba' ? 'BOS' : '')

  useEffect(() => {
    if (!availableTabs.includes(tab)) setTab(availableTabs[0])
  }, [availableTabs, setTab, tab])

  const matchupTeams = useQuery({
    queryKey: ['matchup-teams', league],
    queryFn: () => getMatchupTeams(league),
  })

  useEffect(() => {
    if (!matchupTeams.data?.teams.length) return
    const teams = matchupTeams.data.teams
    const fallbackA = teams[0] ?? ''
    const fallbackB = teams.find((team) => team !== (teamA || fallbackA)) ?? teams[1] ?? fallbackA

    if (!teamA || !teams.includes(teamA)) {
      setTeamA(fallbackA)
      return
    }

    if (!teamB || !teams.includes(teamB) || teamB === teamA) {
      setTeamB(fallbackB)
    }
  }, [matchupTeams.data?.teams, setTeamA, setTeamB, teamA, teamB])

  const matchup = useQuery({
    queryKey: ['matchup', league, teamA, teamB],
    queryFn: () => getMatchup(league, teamA, teamB),
    enabled: Boolean(teamA && teamB && teamA !== teamB),
  })

  const matchupSelectionReady = Boolean(
    teamA
    && teamB
    && teamA !== teamB
    && matchupTeams.data?.teams?.includes(teamA)
    && matchupTeams.data?.teams?.includes(teamB),
  )

  const explorerTeams = useQuery({
    queryKey: ['team-explorer-teams', league],
    queryFn: () => getTeamExplorerTeams(league),
    enabled: tab === 'teams',
  })

  useEffect(() => {
    if (!explorerTeams.data?.teams.length) return
    if (!teamExplorer) setTeamExplorer(explorerTeams.data.teams[0])
  }, [explorerTeams.data?.teams, setTeamExplorer, teamExplorer])

  const explorerData = useQuery({
    queryKey: ['team-explorer', league, teamExplorer],
    queryFn: () => getTeamExplorer(league, teamExplorer),
    enabled: tab === 'teams' && Boolean(teamExplorer),
  })

  const bracket = useQuery({
    queryKey: ['bracket'],
    queryFn: getBracket,
    enabled: league === 'ncaab' && tab === 'bracket',
  })
  const bracketLive = useQuery({
    queryKey: ['live', 'ncaab', 'bracket'],
    queryFn: () => getLive('ncaab'),
    enabled: league === 'ncaab' && tab === 'bracket',
    refetchInterval: 60_000,
  })

  if (matchupTeams.isLoading) return <LoadingPanel label="Preparing the research deck" />
  if (matchupTeams.isError) {
    return <ErrorState title="Research unavailable" body="The available-team list could not be loaded from the API." />
  }

  return (
    <div className="page-grid">
      <Surface className="filter-bar">
        <div className="segmented-control" role="tablist" aria-label="Research sections">
          {availableTabs.map((item) => (
            <button key={item} className={item === tab ? 'is-active' : ''} onClick={() => setTab(item)}>
              {item === 'matchup' ? 'Matchup' : item === 'teams' ? 'Teams' : 'Bracket'}
            </button>
          ))}
        </div>
        <div className="filter-bar__group">
          <TeamSelector label="Team A" value={teamA} options={matchupTeams.data?.teams ?? []} onChange={setTeamA} />
          <TeamSelector label="Team B" value={teamB} options={matchupTeams.data?.teams ?? []} onChange={setTeamB} />
        </div>
      </Surface>

      {tab === 'matchup' ? (
        !matchupSelectionReady ? (
          <EmptyState title="Choose two different teams" body="Select a valid Team A and Team B to score the matchup." />
        ) : matchup.isLoading ? (
          <LoadingPanel label="Scoring the matchup" />
        ) : matchup.isError || !matchup.data ? (
          <ErrorState title="Matchup unavailable" body="The matchup engine did not return a usable payload." />
        ) : (
          <MatchupSurface data={matchup.data} league={league} />
        )
      ) : null}

      {tab === 'teams' && league === 'nba' ? (
        explorerData.isLoading ? (
          <LoadingPanel label="Loading team explorer" />
        ) : explorerData.isError || !explorerData.data ? (
          <ErrorState title="Team explorer unavailable" body="The team explorer payload could not be loaded." />
        ) : (
          <div className="page-grid">
            <Surface className="filter-bar">
              <div className="filter-bar__group">
                <TeamSelector
                  label="Team"
                  value={teamExplorer}
                  options={explorerTeams.data?.teams ?? []}
                  onChange={setTeamExplorer}
                />
              </div>
            </Surface>
            <NbaTeamExplorer data={explorerData.data as TeamExplorerResponse} />
          </div>
        )
      ) : null}

      {tab === 'teams' && league === 'ncaab' ? (
        explorerData.isLoading ? (
          <LoadingPanel label="Loading team explorer" />
        ) : explorerData.isError || !explorerData.data ? (
          <ErrorState title="Team explorer unavailable" body="The team explorer payload could not be loaded." />
        ) : (
          <div className="page-grid">
            <Surface className="filter-bar">
              <div className="filter-bar__group">
                <TeamSelector
                  label="Team"
                  value={teamExplorer}
                  options={explorerTeams.data?.teams ?? []}
                  onChange={setTeamExplorer}
                />
              </div>
            </Surface>
            <NcaaTeamExplorer data={explorerData.data as TeamExplorerResponse} />
          </div>
        )
      ) : null}

      {tab === 'bracket' ? (
        bracket.isLoading ? (
          <LoadingPanel label="Loading the current bracket" />
        ) : bracket.isError || !bracket.data ? (
          <ErrorState title="Bracket unavailable" body="The current bracket could not be loaded." />
        ) : (
          <BracketBoard
            rows={bracket.data.bracket ?? []}
            liveData={bracketLive.data}
            bracketResults={bracket.data.results}
          />
        )
      ) : null}
    </div>
  )
}
