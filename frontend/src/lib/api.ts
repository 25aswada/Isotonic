import type {
  AccuracyResponse,
  AutoTradeConfig,
  AutoTradeStatus,
  BracketResponse,
  League,
  LivePayload,
  MatchupResponse,
  NcaabSummaryResponse,
  PaperTradeActionResult,
  OverviewResponse,
  PaperCandidatesResponse,
  PaperPositionsResponse,
  PaperState,
  PicksResponse,
  TeamExplorerResponse,
  TeamListResponse,
  TeamRowsResponse,
  TrackerResponse,
  SystemAlertsResponse,
  SystemHealth,
} from '../types'

class ApiError extends Error {
  readonly status: number

  constructor(
    message: string,
    status: number,
  ) {
    super(message)
    this.status = status
  }
}

function withQuery(path: string, params?: Record<string, string | number | boolean | undefined>) {
  const url = new URL(path, window.location.origin)
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value != null) url.searchParams.set(key, String(value))
  })
  return url
}

async function fetchJson<T>(path: string, params?: Record<string, string | number | boolean | undefined>) {
  const response = await fetch(withQuery(path, params), {
    headers: {
      Accept: 'application/json',
    },
  })
  if (!response.ok) {
    throw new ApiError(`${response.status} ${response.statusText}`, response.status)
  }
  return (await response.json()) as T
}

async function postJson<T>(
  path: string,
  body?: unknown,
  params?: Record<string, string | number | boolean | undefined>,
) {
  const response = await fetch(withQuery(path, params), {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(body ?? {}),
  })
  if (!response.ok) {
    throw new ApiError(`${response.status} ${response.statusText}`, response.status)
  }
  return (await response.json()) as T
}

export { ApiError }

function normalizePicksResponse(response: PicksResponse): PicksResponse {
  const picks = response.picks ?? []
  const bets = picks.filter((pick) => Boolean(pick.bet))
  const edges = picks
    .map((pick) => Number(pick.best_edge ?? pick.edge))
    .filter((value) => Number.isFinite(value))

  return {
    ...response,
    picks,
    games_analyzed: response.games_analyzed ?? picks.length,
    bets_found: response.bets_found ?? bets.length,
    avg_edge:
      response.avg_edge ?? (edges.length ? edges.reduce((sum, value) => sum + value, 0) / edges.length : 0),
    odds_sources: response.odds_sources ?? Array.from(new Set(picks.flatMap((pick) => {
      const source = typeof pick.best_source === 'string' ? [pick.best_source] : []
      return source
    }))),
  }
}

export function getOverview(league: League) {
  return fetchJson<OverviewResponse>('/api/overview', { league })
}

export async function getPicks(league: League, edgeThreshold: number) {
  const response =
    league === 'nba'
      ? await fetchJson<PicksResponse>('/api/picks', { edge_threshold: edgeThreshold })
      : await fetchJson<PicksResponse>('/api/ncaab/picks', { edge_threshold: edgeThreshold })
  return normalizePicksResponse(response)
}

export async function getLive(league: League) {
  const response =
    league === 'nba'
      ? await fetchJson<LivePayload>('/api/live')
      : await fetchJson<LivePayload>('/api/ncaab/live')

  return {
    ...response,
    fetched_at: response.fetched_at ?? new Date().toISOString(),
    in_progress: response.in_progress ?? [],
    upcoming: response.upcoming ?? [],
    final: response.final ?? [],
  }
}

export async function getMatchupTeams(league: League) {
  return league === 'nba'
    ? fetchJson<TeamListResponse>('/api/matchup/teams')
    : fetchJson<TeamListResponse>('/api/ncaab/matchup/teams')
}

export async function getMatchup(league: League, teamA: string, teamB: string) {
  return league === 'nba'
    ? fetchJson<MatchupResponse>('/api/matchup', { team_a: teamA, team_b: teamB })
    : fetchJson<MatchupResponse>('/api/ncaab/matchup', { team_a: teamA, team_b: teamB })
}

export async function getTeamExplorerTeams(league: League) {
  if (league === 'nba') {
    return fetchJson<TeamListResponse>('/api/team-explorer/teams')
  }
  const teams = await fetchJson<TeamRowsResponse>('/api/ncaab/teams')
  return {
    teams: teams.teams
      .map((team) => String(team.TeamName ?? team.team_name ?? ''))
      .filter(Boolean)
      .sort(),
  } satisfies TeamListResponse
}

export async function getTeamExplorer(league: League, team: string) {
  if (league === 'nba') {
    return fetchJson<TeamExplorerResponse>(`/api/team-explorer/${team}`)
  }
  return fetchJson<TeamRowsResponse>('/api/ncaab/teams')
}

export function getNcaabSummary() {
  return fetchJson<NcaabSummaryResponse>('/api/ncaab/summary')
}

export function getBracket() {
  return fetchJson<BracketResponse>('/api/ncaab/bracket')
}

export function getNcaabTeams() {
  return fetchJson<TeamRowsResponse>('/api/ncaab/teams')
}

export async function getPaperState(league: League) {
  return league === 'nba'
    ? fetchJson<PaperState>('/api/paper-trader/state')
    : fetchJson<PaperState>('/api/ncaab/paper-trader/state')
}

export async function getPaperCandidates(league: League) {
  return league === 'nba'
    ? fetchJson<PaperCandidatesResponse>('/api/paper-trader/candidates')
    : fetchJson<PaperCandidatesResponse>('/api/ncaab/paper-trader/candidates')
}

export async function tradePaperCandidates(league: League, candidateIds: string[]) {
  const endpoint = league === 'nba' ? '/api/paper-trader/trades' : '/api/ncaab/paper-trader/trades'
  return postJson<PaperTradeActionResult>(endpoint, {
    candidate_ids: candidateIds,
  })
}

export async function getPaperPositions(league: League) {
  if (league === 'nba') {
    const [open, settled] = await Promise.all([
      fetchJson<PaperPositionsResponse>('/api/paper-trader/open-positions'),
      fetchJson<PaperPositionsResponse>('/api/paper-trader/settled-positions'),
    ])
    return {
      open: open.positions ?? [],
      settled: settled.positions ?? [],
    }
  }
  const response = await fetchJson<PaperPositionsResponse>('/api/ncaab/paper-trader/positions')
  return {
    open: response.open ?? [],
    settled: response.settled ?? [],
  }
}

export async function logPaperTrades(league: League) {
  const endpoint = league === 'nba' ? '/api/paper-trader/log-trades' : '/api/ncaab/paper-trader/log-trades'
  const response = await fetch(withQuery(endpoint), { method: 'POST' })
  if (!response.ok) {
    throw new ApiError(`${response.status} ${response.statusText}`, response.status)
  }
  return (await response.json()) as { logged?: number; message?: string }
}

export async function getAutoTradeStatus(league: League) {
  return league === 'nba'
    ? fetchJson<AutoTradeStatus>('/api/paper-trader/auto-trade')
    : fetchJson<AutoTradeStatus>('/api/ncaab/paper-trader/auto-trade')
}

export async function updateAutoTrade(config: AutoTradeConfig) {
  return postJson<AutoTradeStatus>('/api/paper-trader/auto-trade', config)
}

export async function getTracker(league: League) {
  return league === 'nba'
    ? fetchJson<TrackerResponse>('/api/bet-tracker')
    : fetchJson<TrackerResponse>('/api/ncaab/bet-tracker')
}

export async function getAccuracy(league: League) {
  return league === 'nba'
    ? fetchJson<AccuracyResponse>('/api/accuracy')
    : fetchJson<AccuracyResponse>('/api/ncaab/accuracy')
}

export function getSystemHealth() {
  return fetchJson<SystemHealth>('/api/system/health')
}

export function getSystemAlerts() {
  return fetchJson<SystemAlertsResponse>('/api/system/alerts')
}

export async function settleResults() {
  const response = await fetch(withQuery('/api/system/settle-results'), { method: 'POST' })
  if (!response.ok) {
    throw new ApiError(`${response.status} ${response.statusText}`, response.status)
  }
  return (await response.json()) as { success?: boolean; output?: string }
}

export async function startModelUpdate() {
  const response = await fetch(withQuery('/api/system/update-model'), { method: 'POST' })
  if (!response.ok) {
    throw new ApiError(`${response.status} ${response.statusText}`, response.status)
  }
  return (await response.json()) as { started?: boolean; reason?: string }
}

export function getModelUpdateStatus() {
  return fetchJson<{ status?: string; log?: string[]; started_at?: string; finished_at?: string }>(
    '/api/system/update-model/status',
  )
}
