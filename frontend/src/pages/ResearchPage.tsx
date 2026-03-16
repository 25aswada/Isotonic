import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Activity, Trophy } from 'lucide-react'
import { useParams } from 'react-router-dom'

import { EmptyState, ErrorState, LoadingPanel, MetricCard, Pill, Surface } from '../components/ui'
import {
  getBracket,
  getMatchup,
  getMatchupTeams,
  getNcaabTeams,
  getTeamExplorer,
  getTeamExplorerTeams,
} from '../lib/api'
import { integer, num, pct, pct0, sparklinePath } from '../lib/format'
import { isLeague, leagueLabels, normalizeLeague } from '../lib/navigation'
import { teamAccent } from '../lib/teamColor'
import { usePersistentState } from '../hooks/usePersistentState'
import type { League, MatchupResponse, NcaabTeamRecord, TeamExplorerResponse } from '../types'

type ResearchTab = 'matchup' | 'teams' | 'bracket'

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
          ['Def rating', statsA.def_rtg, statsB.def_rtg],
          ['Pace', statsA.pace, statsB.pace],
        ]
      : [
          ['Elo', statsA.elo, statsB.elo],
          ['Net rating', statsA.net_rtg, statsB.net_rtg],
          ['Off rating', statsA.off_rtg, statsB.off_rtg],
          ['Def rating', statsA.def_rtg, statsB.def_rtg],
          ['Win %', statsA.win_pct, statsB.win_pct],
        ]

  const eloA = (data.elo_history_a ?? []).map((entry) => Number(entry.elo ?? 0))
  const eloB = (data.elo_history_b ?? []).map((entry) => Number(entry.elo ?? 0))

  return (
    <div className="page-grid">
      <Surface className="hero-panel hero-panel--matchup" tone="accent">
        <div className="hero-matchup">
          <div className="hero-matchup__team">
            <span>{teamA}</span>
            <strong style={{ color: teamAccent(teamA) }}>{pct0(probA)}</strong>
          </div>
          <div className="hero-matchup__divider">vs</div>
          <div className="hero-matchup__team">
            <span>{teamB}</span>
            <strong style={{ color: teamAccent(teamB) }}>{pct0(probB)}</strong>
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
            {rows.map(([label, left, right]) => (
              <div className="comparison-table__row" key={String(label)}>
                <span className="comparison-table__value">{typeof left === 'number' ? num(left) : '—'}</span>
                <div>
                  <small>{label}</small>
                  <div className="comparison-table__track">
                    <i style={{ width: `${50 + ((Number(left ?? 0) - Number(right ?? 0)) / (Math.abs(Number(left ?? 0)) + Math.abs(Number(right ?? 0)) + 1)) * 50}%` }} />
                  </div>
                </div>
                <span className="comparison-table__value">{typeof right === 'number' ? num(right) : '—'}</span>
              </div>
            ))}
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
          {eloA.length && eloB.length ? (
            <svg className="sparkline-chart" viewBox="0 0 260 88" role="img" aria-label="Elo trajectory">
              <path className="sparkline-chart__line sparkline-chart__line--subtle" d={sparklinePath(eloA)} />
              <path className="sparkline-chart__line" d={sparklinePath(eloB)} />
            </svg>
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
              <td>{team.TeamName ?? team.team_name}</td>
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

function BracketBoard({ rows }: { rows: Array<Record<string, string | number | null>> }) {
  const grouped = rows.reduce<Record<string, Array<Record<string, string | number | null>>>>((accumulator, row) => {
    const key = String(row.region ?? 'Region')
    accumulator[key] = accumulator[key] ?? []
    accumulator[key].push(row)
    return accumulator
  }, {})

  return (
    <div className="bracket-grid">
      {Object.entries(grouped).map(([region, regionRows]) => (
        <Surface className="stack-panel" key={region}>
          <div className="stack-panel__header">
            <div>
              <span className="section-kicker">Projected region</span>
              <h3>{region}</h3>
            </div>
            <Trophy size={16} />
          </div>
          <div className="bracket-list">
            {regionRows.slice(0, 8).map((row, index) => (
              <div className="preview-row" key={`${region}-${index}`}>
                <div className="preview-row__title">
                  <strong>{row.winner_name ?? 'Projected winner'}</strong>
                  <span>
                    {row.team_a_name} vs {row.team_b_name}
                  </span>
                </div>
                <div className="preview-row__meta">
                  <span>{row.round}</span>
                  <span>{pct(Number(row.win_prob ?? 0))}</span>
                </div>
              </div>
            ))}
          </div>
        </Surface>
      ))}
    </div>
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
