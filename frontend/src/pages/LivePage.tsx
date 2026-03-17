import { useEffect, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Pin, PinOff, RefreshCcw, TimerReset } from 'lucide-react'
import { useParams } from 'react-router-dom'

import { Button, EmptyState, ErrorState, LoadingPanel, Pill, Surface } from '../components/ui'
import { getLive } from '../lib/api'
import { formatAgeSeconds, pct, pct0 } from '../lib/format'
import { isLeague, leagueLabels, normalizeLeague } from '../lib/navigation'
import { teamAccent } from '../lib/teamColor'
import { TeamLogo } from '../components/ui'
import { usePersistentState } from '../hooks/usePersistentState'
import type { League, LiveGame, LivePayload } from '../types'

function gameKey(game: LiveGame, fallback: number) {
  return String(game.game_id ?? `${game.away_team}-${game.home_team}-${fallback}`)
}

function magnitude(game: LiveGame) {
  const liveEdge = Math.abs(Number(game.live_home_edge ?? game.live_away_edge ?? game.edge ?? 0))
  return Number.isFinite(liveEdge) ? liveEdge : 0
}

function byTipoffAsc(left: LiveGame, right: LiveGame) {
  return String(left.tipoff_utc ?? '').localeCompare(String(right.tipoff_utc ?? ''))
}

function comparisonTone(value: number | null | undefined, other: number | null | undefined) {
  if (value == null || other == null) return 'neutral'
  if (value === other) return 'neutral'
  return value > other ? 'good' : 'bad'
}

function buildGroups(payload: LivePayload, pinned: string[]) {
  const isPinned = (game: LiveGame, index: number) => pinned.includes(gameKey(game, index))
  return {
    inProgress: [...payload.in_progress].sort((left, right) => {
      const leftPinned = isPinned(left, 0)
      const rightPinned = isPinned(right, 0)
      if (leftPinned !== rightPinned) return leftPinned ? -1 : 1
      return magnitude(right) - magnitude(left)
    }),
    upcoming: [...payload.upcoming].sort((left, right) => {
      const leftPinned = isPinned(left, 0)
      const rightPinned = isPinned(right, 0)
      if (leftPinned !== rightPinned) return leftPinned ? -1 : 1
      return byTipoffAsc(left, right)
    }),
    finals: [...payload.final].sort((left, right) => byTipoffAsc(right, left)),
  }
}

function LiveCard({
  game,
  pinned,
  onTogglePin,
}: {
  game: LiveGame
  pinned: boolean
  onTogglePin: () => void
}) {
  const pregameHomeProb = game.pregame_home_prob == null ? null : Number(game.pregame_home_prob)
  const pregameAwayProb = game.pregame_away_prob != null
    ? Number(game.pregame_away_prob)
    : pregameHomeProb != null ? 1 - pregameHomeProb : null
  const homeProb = Number(game.live_home_prob ?? game.pregame_home_prob ?? game.home_win_prob ?? 0.5)
  const awayProb = Number(game.live_away_prob ?? game.pregame_away_prob ?? game.away_win_prob ?? 0.5)
  const edgeValue = Number(game.live_home_edge ?? game.live_away_edge ?? game.edge ?? 0)
  const awayKalshi = game.kalshi_away_prob == null ? null : Number(game.kalshi_away_prob)
  const homeKalshi = game.kalshi_home_prob == null ? null : Number(game.kalshi_home_prob)
  const awayModelTone = comparisonTone(awayProb, homeProb)
  const homeModelTone = comparisonTone(homeProb, awayProb)
  const awayKalshiTone = comparisonTone(awayKalshi, homeKalshi)
  const homeKalshiTone = comparisonTone(homeKalshi, awayKalshi)

  return (
    <Surface className="live-card-modern">
      <div className="live-card-modern__top">
        <div>
          <span className="section-kicker">{game.game_status_text ?? game.period_label ?? 'Live board'}</span>
          <h3>
            {game.away_team} @ {game.home_team}
          </h3>
        </div>
        <div className="live-card-modern__actions">
          <Pill tone={edgeValue > 0.03 ? 'good' : 'neutral'}>{pct(Math.abs(edgeValue))} edge</Pill>
          <button className="icon-button" onClick={onTogglePin}>
            {pinned ? <PinOff size={15} /> : <Pin size={15} />}
          </button>
        </div>
      </div>

      <div className="live-card-modern__scoreboard">
        <div className="live-team">
          <TeamLogo team={game.away_team as string} size={36} />
          <span style={{ color: teamAccent((game.away_full_name ?? game.away_team) as string) }}>{game.away_team}</span>
          <strong>{game.away_score ?? 0}</strong>
          <small className={`live-prob live-prob--${awayModelTone}`}>{pct0(awayProb)}</small>
        </div>
        <div className="live-card-modern__middle">
          <span>{game.period_label ?? game.game_status_text ?? 'Status'}</span>
          <strong>{game.clock_display ?? '—'}</strong>
        </div>
        <div className="live-team live-team--right">
          <TeamLogo team={game.home_team as string} size={36} />
          <span style={{ color: teamAccent((game.home_full_name ?? game.home_team) as string) }}>{game.home_team}</span>
          <strong>{game.home_score ?? 0}</strong>
          <small className={`live-prob live-prob--${homeModelTone}`}>{pct0(homeProb)}</small>
        </div>
      </div>

      <div className="live-card-modern__meta">
        {pregameAwayProb != null && (
          <div>
            <span>Pregame model</span>
            <strong className="live-marketline">
              <b className={`live-prob live-prob--${comparisonTone(pregameAwayProb, pregameHomeProb)}`}>{pct0(pregameAwayProb)}</b>
              <i>/</i>
              <b className={`live-prob live-prob--${comparisonTone(pregameHomeProb, pregameAwayProb)}`}>{pct0(pregameHomeProb)}</b>
            </strong>
          </div>
        )}
        <div>
          <span>Kalshi</span>
          <strong className="live-marketline">
            <b className={`live-prob live-prob--${awayKalshiTone}`}>{pct0(awayKalshi)}</b>
            <i>/</i>
            <b className={`live-prob live-prob--${homeKalshiTone}`}>{pct0(homeKalshi)}</b>
          </strong>
        </div>
        <div>
          <span>Pred score</span>
          <strong>
            {game.pred_away_score ?? '—'} - {game.pred_home_score ?? '—'}
          </strong>
        </div>
      </div>
    </Surface>
  )
}

export default function LivePage() {
  const params = useParams()
  const queryClient = useQueryClient()
  const league: League = isLeague(params.league) ? params.league : normalizeLeague(params.league)
  const [autoRefresh, setAutoRefresh] = usePersistentState(`isotonic:${league}:live-refresh`, true)
  const [pinnedGames, setPinnedGames] = usePersistentState<string[]>(`isotonic:${league}:pinned-games`, [])

  const liveQuery = useQuery({
    queryKey: ['live', league],
    queryFn: () => getLive(league),
    refetchInterval: autoRefresh ? 5_000 : false,
  })

  useEffect(() => {
    if (league !== 'nba' || !autoRefresh) return

    const source = new EventSource('/api/live/stream')
    source.addEventListener('games', (event) => {
      try {
        queryClient.setQueryData(['live', 'nba'], JSON.parse((event as MessageEvent).data) as LivePayload)
      } catch {
        // Ignore malformed stream payloads.
      }
    })
    return () => source.close()
  }, [autoRefresh, league, queryClient])

  const groups = useMemo(() => {
    if (!liveQuery.data) return null
    return buildGroups(liveQuery.data, pinnedGames)
  }, [liveQuery.data, pinnedGames])

  if (liveQuery.isLoading) return <LoadingPanel label="Syncing the live board" />
  if (liveQuery.isError || !liveQuery.data || !groups) {
    return <ErrorState title="Live board unavailable" body="The live endpoint did not return a usable payload." />
  }

  const totalGames = groups.inProgress.length + groups.upcoming.length + groups.finals.length

  if (!totalGames) {
    return (
      <EmptyState
        title={`No ${leagueLabels[league]} games right now`}
        body="The command center is online, but there are no games active or scheduled in the current payload."
      />
    )
  }

  return (
    <div className="page-grid">
      <Surface className="filter-bar">
        <div className="filter-bar__group">
          <div className="filter-bar__label">
            <TimerReset size={15} />
            <span>Freshness</span>
          </div>
          <strong>{formatAgeSeconds(new Date().valueOf() / 1000 - new Date(liveQuery.data.fetched_at ?? Date.now()).valueOf() / 1000)}</strong>
          <Pill tone={autoRefresh ? 'accent' : 'neutral'}>{autoRefresh ? 'Auto refresh on' : 'Auto refresh off'}</Pill>
        </div>
        <div className="filter-bar__group">
          <Button tone="secondary" onClick={() => liveQuery.refetch()}>
            <RefreshCcw size={15} />
            Refresh
          </Button>
          <Button tone="ghost" onClick={() => setAutoRefresh((value) => !value)}>
            {autoRefresh ? 'Pause refresh' : 'Resume refresh'}
          </Button>
        </div>
      </Surface>

      <div className="live-sections">
        {groups.inProgress.length ? (
          <div className="live-group">
            <div className="live-group__header">
              <span>In progress</span>
              <strong>{groups.inProgress.length}</strong>
            </div>
            <div className="live-board live-board--auto">
              {groups.inProgress.map((game, index) => {
                const key = gameKey(game, index)
                return (
                  <motion.div key={key} layout>
                    <LiveCard
                      game={game}
                      pinned={pinnedGames.includes(key)}
                      onTogglePin={() =>
                        setPinnedGames((games) =>
                          games.includes(key) ? games.filter((entry) => entry !== key) : [...games, key],
                        )
                      }
                    />
                  </motion.div>
                )
              })}
            </div>
          </div>
        ) : null}

        {groups.upcoming.length ? (
          <div className="live-group">
            <div className="live-group__header">
              <span>Upcoming</span>
              <strong>{groups.upcoming.length}</strong>
            </div>
            <div className="live-board live-board--auto">
              {groups.upcoming.slice(0, 8).map((game, index) => {
                const key = gameKey(game, index)
                return (
                  <LiveCard
                    key={key}
                    game={game}
                    pinned={pinnedGames.includes(key)}
                    onTogglePin={() =>
                      setPinnedGames((games) =>
                        games.includes(key) ? games.filter((entry) => entry !== key) : [...games, key],
                      )
                    }
                  />
                )
              })}
            </div>
          </div>
        ) : null}

        {groups.finals.length ? (
          <div className="live-group">
            <div className="live-group__header">
              <span>Final</span>
              <strong>{groups.finals.length}</strong>
            </div>
            <div className="live-board live-board--auto">
              {groups.finals.slice(0, 6).map((game, index) => {
                const key = gameKey(game, index)
                return (
                  <LiveCard
                    key={key}
                    game={game}
                    pinned={pinnedGames.includes(key)}
                    onTogglePin={() =>
                      setPinnedGames((games) =>
                        games.includes(key) ? games.filter((entry) => entry !== key) : [...games, key],
                      )
                    }
                  />
                )
              })}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  )
}
