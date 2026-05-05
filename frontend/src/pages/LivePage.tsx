import { useEffect, useMemo, useRef, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { motion } from 'framer-motion'
import { Pin, PinOff, RefreshCcw, TimerReset } from 'lucide-react'
import { useParams, useNavigate } from 'react-router-dom'

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

function byTipoffAsc(left: LiveGame, right: LiveGame) {
  return String(left.tipoff_utc ?? '').localeCompare(String(right.tipoff_utc ?? ''))
}

function comparisonTone(value: number | null | undefined, other: number | null | undefined) {
  if (value == null || other == null) return 'neutral'
  if (value === other) return 'neutral'
  return value > other ? 'good' : 'bad'
}

function AnimatedLiveValue({
  valueKey,
  className,
  children,
}: {
  valueKey: string
  className?: string
  children: ReactNode
}) {
  return (
    <motion.span
      key={valueKey}
      className={className}
      initial={{ opacity: 0.55, y: 6, scale: 0.985, filter: 'blur(3px)' }}
      animate={{ opacity: 1, y: 0, scale: 1, filter: 'blur(0px)' }}
      transition={{ duration: 0.28, ease: 'easeOut' }}
    >
      {children}
    </motion.span>
  )
}

function AnimatedScoreValue({
  numericValue,
  children,
}: {
  numericValue: number
  children: ReactNode
}) {
  const previousValueRef = useRef(numericValue)
  const delta = numericValue - previousValueRef.current

  useEffect(() => {
    previousValueRef.current = numericValue
  }, [numericValue])

  const toneClass =
    delta > 0 ? 'live-score-value--up' : delta < 0 ? 'live-score-value--down' : 'live-score-value--steady'

  return (
    <motion.span
      className={`live-score-value ${toneClass}`}
      initial={{ opacity: 0.6, y: 10, scale: 0.97 }}
      animate={
        delta > 0
          ? {
              opacity: [0.9, 1, 1],
              y: [10, -2, 0],
              scale: [0.97, 1.08, 1],
              color: ['#16c75f', '#31db78', '#ffffff'],
              textShadow: [
                '0 0 0 rgba(22,199,95,0)',
                '0 0 6px rgba(22,199,95,0.12)',
                '0 0 0 rgba(22,199,95,0)',
              ],
            }
          : delta < 0
            ? {
                opacity: [0.9, 1, 1],
                y: [10, -2, 0],
                scale: [0.97, 1.05, 1],
                color: ['#ff4d43', '#ff736b', '#ffffff'],
                textShadow: [
                  '0 0 0 rgba(255,77,67,0)',
                  '0 0 6px rgba(255,77,67,0.1)',
                  '0 0 0 rgba(255,77,67,0)',
                ],
              }
            : {
                opacity: 1,
                y: 0,
                scale: 1,
                color: '#ffffff',
                textShadow: '0 0 0 rgba(255,255,255,0)',
              }
      }
      transition={{ duration: delta === 0 ? 0.2 : 0.7, ease: 'easeOut' }}
    >
      {children}
    </motion.span>
  )
}

function buildGroups(payload: LivePayload, pinned: string[]) {
  const isPinned = (game: LiveGame, index: number) => pinned.includes(gameKey(game, index))
  return {
    inProgress: [...payload.in_progress].sort((left, right) => {
      const leftPinned = isPinned(left, 0)
      const rightPinned = isPinned(right, 0)
      if (leftPinned !== rightPinned) return leftPinned ? -1 : 1
      return 0
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
  onCardClick,
}: {
  game: LiveGame
  pinned: boolean
  onTogglePin: () => void
  onCardClick: () => void
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
  const latestPlay = (game.latest_play as { text?: string; clock?: string; period?: string } | undefined) ?? undefined
  const awayModelTone = comparisonTone(awayProb, homeProb)
  const homeModelTone = comparisonTone(homeProb, awayProb)
  const awayKalshiTone = comparisonTone(awayKalshi, homeKalshi)
  const homeKalshiTone = comparisonTone(homeKalshi, awayKalshi)

  return (
    <Surface className="live-card-modern live-card-modern--clickable" onClick={(e: React.MouseEvent) => {
      // Don't navigate if user clicked on the pin button
      if ((e.target as HTMLElement).closest('.icon-button')) return
      onCardClick()
    }}>
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
          <TeamLogo team={(game.away_full_name ?? game.away_team) as string} size={36} />
          <span style={{ color: teamAccent((game.away_full_name ?? game.away_team) as string) }}>{game.away_team}</span>
          <strong>
            <AnimatedScoreValue
              numericValue={game.away_score ?? 0}
            >
              {game.away_score ?? 0}
            </AnimatedScoreValue>
          </strong>
          <small className={`live-prob live-prob--${awayModelTone}`}>
            <AnimatedLiveValue
              valueKey={`away-prob-${game.game_id}-${awayProb.toFixed(4)}`}
              className={`live-prob live-prob--${awayModelTone}`}
            >
              {pct0(awayProb)}
            </AnimatedLiveValue>
          </small>
        </div>
        <div className="live-card-modern__middle">
          <span>{game.period_label ?? game.game_status_text ?? 'Status'}</span>
          <strong>
            <AnimatedLiveValue valueKey={`clock-${game.game_id}-${game.period_label ?? ''}-${game.clock_display ?? 'na'}`}>
              {game.clock_display ?? '—'}
            </AnimatedLiveValue>
          </strong>
        </div>
        <div className="live-team live-team--right">
          <TeamLogo team={(game.home_full_name ?? game.home_team) as string} size={36} />
          <span style={{ color: teamAccent((game.home_full_name ?? game.home_team) as string) }}>{game.home_team}</span>
          <strong>
            <AnimatedScoreValue
              numericValue={game.home_score ?? 0}
            >
              {game.home_score ?? 0}
            </AnimatedScoreValue>
          </strong>
          <small className={`live-prob live-prob--${homeModelTone}`}>
            <AnimatedLiveValue
              valueKey={`home-prob-${game.game_id}-${homeProb.toFixed(4)}`}
              className={`live-prob live-prob--${homeModelTone}`}
            >
              {pct0(homeProb)}
            </AnimatedLiveValue>
          </small>
        </div>
      </div>

      <div className="live-card-modern__meta">
        {pregameAwayProb != null && (
          <div>
            <span>Pregame model</span>
            <strong className="live-marketline">
              <b className={`live-prob live-prob--${comparisonTone(pregameAwayProb, pregameHomeProb)}`}>
                <AnimatedLiveValue
                  valueKey={`pregame-away-${game.game_id}-${pregameAwayProb.toFixed(4)}`}
                  className={`live-prob live-prob--${comparisonTone(pregameAwayProb, pregameHomeProb)}`}
                >
                  {pct0(pregameAwayProb)}
                </AnimatedLiveValue>
              </b>
              <i>/</i>
              <b className={`live-prob live-prob--${comparisonTone(pregameHomeProb, pregameAwayProb)}`}>
                <AnimatedLiveValue
                  valueKey={`pregame-home-${game.game_id}-${(pregameHomeProb ?? 0).toFixed(4)}`}
                  className={`live-prob live-prob--${comparisonTone(pregameHomeProb, pregameAwayProb)}`}
                >
                  {pct0(pregameHomeProb)}
                </AnimatedLiveValue>
              </b>
            </strong>
          </div>
        )}
        <div>
          <span>Kalshi</span>
          <strong className="live-marketline">
            <b className={`live-prob live-prob--${awayKalshiTone}`}>
              <AnimatedLiveValue
                valueKey={`kalshi-away-${game.game_id}-${awayKalshi ?? 'na'}`}
                className={`live-prob live-prob--${awayKalshiTone}`}
              >
                {pct0(awayKalshi)}
              </AnimatedLiveValue>
            </b>
            <i>/</i>
            <b className={`live-prob live-prob--${homeKalshiTone}`}>
              <AnimatedLiveValue
                valueKey={`kalshi-home-${game.game_id}-${homeKalshi ?? 'na'}`}
                className={`live-prob live-prob--${homeKalshiTone}`}
              >
                {pct0(homeKalshi)}
              </AnimatedLiveValue>
            </b>
          </strong>
        </div>
        <div>
          <span>Pred score</span>
          <strong>
            <AnimatedLiveValue
              valueKey={`pred-score-${game.game_id}-${game.pred_away_score ?? 'na'}-${game.pred_home_score ?? 'na'}`}
              className="live-pred-score-value"
            >
              {game.pred_away_score ?? '—'} - {game.pred_home_score ?? '—'}
            </AnimatedLiveValue>
          </strong>
        </div>
      </div>

      {latestPlay?.text ? (
        <motion.div
          key={`latest-play-${game.game_id}-${latestPlay.text}-${latestPlay.clock ?? 'na'}`}
          className="live-card-modern__play"
          initial={{ opacity: 0.45, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.32, ease: 'easeOut' }}
        >
          <span className="live-card-modern__play-label">
            {latestPlay.period ?? game.period_label ?? 'Live'}
            {latestPlay.clock ? ` · ${latestPlay.clock}` : ''}
          </span>
          <strong>{latestPlay.text}</strong>
        </motion.div>
      ) : null}
    </Surface>
  )
}

export default function LivePage() {
  const params = useParams()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const league: League = isLeague(params.league) ? params.league : normalizeLeague(params.league)
  const [autoRefresh, setAutoRefresh] = usePersistentState(`isotonic:${league}:live-refresh`, true)
  const [pinnedGames, setPinnedGames] = usePersistentState<string[]>(`isotonic:${league}:pinned-games`, [])

  const liveQuery = useQuery({
    queryKey: ['live', league],
    queryFn: () => getLive(league),
    refetchInterval: autoRefresh ? 2_000 : false,
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

  if (liveQuery.isLoading && !liveQuery.data) return <LoadingPanel label="Syncing the live board" />
  if (!liveQuery.data || !groups) {
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
                      onCardClick={() => navigate(`/app/${league}/live/${game.game_id}`)}
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
              {groups.upcoming.map((game, index) => {
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
                    onCardClick={() => navigate(`/app/${league}/live/${game.game_id}`)}
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
              {groups.finals.map((game, index) => {
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
                    onCardClick={() => navigate(`/app/${league}/live/${game.game_id}`)}
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
