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
import { Activity, Trophy } from 'lucide-react'
import { useParams } from 'react-router-dom'

import { EmptyState, ErrorState, LoadingPanel, MetricCard, Pill, Surface, TeamLogo } from '../components/ui'
import {
  getBracket,
  getMatchup,
  getMatchupTeams,
  getNcaabTeams,
  getTeamExplorer,
  getTeamExplorerTeams,
} from '../lib/api'
import { formatDate, integer, num, pct, pct0, sparklinePath } from '../lib/format'
import { isLeague, leagueLabels, normalizeLeague } from '../lib/navigation'
import { teamAccent } from '../lib/teamColor'

import { usePersistentState } from '../hooks/usePersistentState'
import type { League, MatchupResponse, NcaabTeamRecord, TeamExplorerResponse } from '../types'

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

function MatchupSurface({ data, league }: { data: MatchupResponse; league: League }) {
  const teamA = String(data.team_a ?? 'Team A')
  const teamB = String(data.team_b ?? 'Team B')
  const probA = Number(data.pred_prob_a ?? data.team_a_win_prob ?? 0.5)
  const probB = Number(data.pred_prob_b ?? data.team_b_win_prob ?? 1 - probA)
  const statsA = data.stats_a ?? {}
  const statsB = data.stats_b ?? {}

  const rows =
    league === 'nba'
      ? [
          ['Elo', statsA.elo, statsB.elo],
          ['Net rating', statsA.net_rtg, statsB.net_rtg],
          ['Off rating', statsA.off_rtg, statsB.off_rtg],
          ['Def rating', statsA.def_rtg, statsB.def_rtg, true],
          ['Pace', statsA.pace, statsB.pace],
        ]
      : [
          ['Elo', statsA.elo, statsB.elo],
          ['Net rating', statsA.net_rtg, statsB.net_rtg],
          ['Off rating', statsA.off_rtg, statsB.off_rtg],
          ['Def rating', statsA.def_rtg, statsB.def_rtg, true],
          ['Win %', statsA.win_pct, statsB.win_pct],
        ]

  const teamAColor = teamAccent(teamA)
  const teamBColor = teamAccent(teamB)

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
            {data.seed_baseline_prob != null ? <Pill>{pct(data.seed_baseline_prob)}</Pill> : null}
          </div>
        </div>
      </Surface>

      <div className="content-grid">
        <Surface className="stack-panel">
          <div className="stack-panel__header">
            <div>
              <span className="section-kicker">Head-to-head numbers</span>
              <h3>Core comparison</h3>
            </div>
            <Activity size={16} />
          </div>
          <div className="comparison-table">
            {rows.map(([label, left, right, lowerBetter]) => {
              const vA = Number(left ?? 0)
              const vB = Number(right ?? 0)
              const shift = Math.min(vA, vB, 0) - 0.001
              const sA = vA - shift, sB = vB - shift
              const total = sA + sB
              const shareA = total > 0 ? (sA / total) * 100 : 50
              const shareB = 100 - shareA
              const aWins = lowerBetter ? vA < vB : vA > vB
              const bWins = lowerBetter ? vB < vA : vB > vA
              return (
                <div className="comparison-table__row" key={String(label)}>
                  <span className="comparison-table__value" style={{ color: aWins ? 'var(--good)' : bWins ? 'var(--bad)' : 'var(--text)' }}>
                    {typeof left === 'number' ? num(left) : '—'}
                  </span>
                  <div>
                    <small>{label}</small>
                    <div className="comparison-table__track comparison-table__track--split">
                      <i style={{ width: `${shareA}%`, background: teamAColor }} />
                      <i style={{ width: `${shareB}%`, background: teamBColor }} />
                    </div>
                  </div>
                  <span className="comparison-table__value" style={{ color: bWins ? 'var(--good)' : aWins ? 'var(--bad)' : 'var(--text)' }}>
                    {typeof right === 'number' ? num(right) : '—'}
                  </span>
                </div>
              )
            })}
          </div>
        </Surface>

        <Surface className="stack-panel">
          <div className="stack-panel__header">
            <div>
              <span className="section-kicker">Form line</span>
              <h3>Elo trajectory</h3>
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
                    <Line
                      type="monotone"
                      dataKey="teamAValue"
                      name={teamA}
                      stroke={teamAColor}
                      strokeWidth={3}
                      dot={false}
                      activeDot={{ r: 5, stroke: teamAColor, strokeWidth: 2, fill: '#0c0c0d' }}
                      connectNulls
                    />
                    <Line
                      type="monotone"
                      dataKey="teamBValue"
                      name={teamB}
                      stroke={teamBColor}
                      strokeWidth={3}
                      dot={false}
                      activeDot={{ r: 5, stroke: teamBColor, strokeWidth: 2, fill: '#0c0c0d' }}
                      connectNulls
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </>
          ) : (
            <EmptyState title="No Elo history" body="Historical matchup context is not available for this pair yet." />
          )}
        </Surface>
      </div>
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

function NcaaTeamsTable({ teams }: { teams: NcaabTeamRecord[] }) {
  return (
    <Surface className="table-surface">
      <table className="data-table-modern">
        <thead>
          <tr>
            <th>Team</th>
            <th>Seed</th>
            <th>Elo</th>
            <th>Win%</th>
            <th>Net</th>
            <th>Margin</th>
          </tr>
        </thead>
        <tbody>
          {teams.slice(0, 40).map((team) => (
            <tr key={String(team.TeamName ?? team.team_name)}>
              <td>
                <div className="table-team">
                  <TeamLogo team={String(team.TeamName ?? team.team_name)} size={18} />
                  <span>{team.TeamName ?? team.team_name}</span>
                </div>
              </td>
              <td>{team.Seed ?? team.seed_num ?? '—'}</td>
              <td>{integer(team.elo as number)}</td>
              <td>{pct(team.win_pct as number)}</td>
              <td>{num(team.net_rtg as number)}</td>
              <td>{num(team.avg_margin as number)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Surface>
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

function bracketNumber(value: string | number | null | undefined) {
  if (value == null) return null
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

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

function bracketTeamWinProb(row: BracketRow, side: 'a' | 'b') {
  const winProb = bracketNumber(row.win_prob)
  if (winProb == null) return null

  const winner = String(row.winner_name ?? '')
  const team = bracketTeamName(row, side)
  if (!winner) return side === 'a' ? winProb : 1 - winProb
  return winner === team ? winProb : 1 - winProb
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
  const winProb = bracketTeamWinProb(row, side)

  return (
    <div className={`tournament-match__team ${isWinner ? 'is-winner' : winner ? 'is-loser' : ''}`}>
      <div className="tournament-match__team-main">
        <span className="tournament-match__seed">{seed ?? '—'}</span>
        <TeamLogo team={team} size={16} className="tournament-match__logo" />
        <span className="tournament-match__name">{team}</span>
      </div>
      <span className="tournament-match__prob">{winProb != null ? pct0(winProb) : '—'}</span>
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

function BracketBoard({ rows }: { rows: BracketRow[] }) {
  const seedLookup = useMemo(() => buildBracketSeedLookup(rows), [rows])
  const playInRows = rows.filter((row) => row.round === 'First Four')
  const semifinalRows = rows.filter((row) => row.round === 'Final Four')
  const titleRow = rows.find((row) => row.round === 'National Championship')
  const champion = String(titleRow?.winner_name ?? 'Projected champion')
  const championProb = titleRow
    ? bracketTeamWinProb(titleRow, champion === bracketTeamName(titleRow, 'a') ? 'a' : 'b')
    : null

  return (
    <Surface className="tournament-board" tone="accent">
      <div className="tournament-board__hero">
        <span className="section-kicker">Men&apos;s tournament</span>
        <h2>Projected Bracket</h2>
        <p>{champion !== 'Projected champion' ? `${champion} is the current model champion.` : 'Current simulated path through the field.'}</p>
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
              <RegionBracket key={region} region={region} rows={rows} seedLookup={seedLookup} side="left" />
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
              <Trophy size={18} />
              <span>Projected champion</span>
            </div>
            <TeamLogo team={champion} size={34} />
            <strong>{champion}</strong>
            <p>{championProb != null ? `${pct0(championProb)} in the title matchup.` : 'Current title-game winner.'}</p>
          </div>
          </div>

          <div className="tournament-board__side">
            {BRACKET_REGION_SIDES.right.map((region) => (
              <RegionBracket key={region} region={region} rows={rows} seedLookup={seedLookup} side="right" />
            ))}
          </div>
        </div>
      </div>
    </Surface>
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
    if (!teamA) setTeamA(matchupTeams.data.teams[0])
    if (!teamB) setTeamB(matchupTeams.data.teams[1] ?? matchupTeams.data.teams[0])
  }, [matchupTeams.data?.teams, setTeamA, setTeamB, teamA, teamB])

  const matchup = useQuery({
    queryKey: ['matchup', league, teamA, teamB],
    queryFn: () => getMatchup(league, teamA, teamB),
    enabled: Boolean(teamA && teamB && teamA !== teamB),
  })

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

  const ncaabTeams = useQuery({
    queryKey: ['ncaab-teams'],
    queryFn: getNcaabTeams,
    enabled: league === 'ncaab' && tab === 'teams',
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
        matchup.isLoading ? (
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
        ncaabTeams.isLoading ? (
          <LoadingPanel label="Loading current team table" />
        ) : ncaabTeams.isError || !ncaabTeams.data ? (
          <ErrorState title="NCAA teams unavailable" body="The NCAA team feature table could not be loaded." />
        ) : (
          <NcaaTeamsTable teams={ncaabTeams.data.teams ?? []} />
        )
      ) : null}

      {tab === 'bracket' ? (
        bracket.isLoading ? (
          <LoadingPanel label="Projecting the bracket board" />
        ) : bracket.isError || !bracket.data ? (
          <ErrorState title="Bracket unavailable" body="The current projected bracket could not be loaded." />
        ) : (
          <BracketBoard rows={bracket.data.bracket ?? []} />
        )
      ) : null}
    </div>
  )
}
