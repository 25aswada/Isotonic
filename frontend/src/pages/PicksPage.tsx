import { useMemo } from 'react'
import { motion } from 'framer-motion'
import { Filter, SlidersHorizontal } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'

import { LoadingPanel, EmptyState, ErrorState, Button, Pill, Surface } from '../components/ui'
import { getPicks } from '../lib/api'
import { money, pct, pct0, titleCase } from '../lib/format'
import { isLeague, leagueLabels, normalizeLeague } from '../lib/navigation'
import { teamAccent } from '../lib/teamColor'
import { TeamLogo } from '../components/ui'
import { usePersistentState } from '../hooks/usePersistentState'
import type { League, PickRecord } from '../types'

type SortKey = 'edge' | 'kelly' | 'confidence'

interface PickFilters {
  betOnly: boolean
  source: string
  minEdge: number
  sortBy: SortKey
}

function toMaybeNumber(value: unknown) {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function signedPct(value: number | null) {
  if (value == null) return 'No edge'
  return `${value >= 0 ? '+' : ''}${(value * 100).toFixed(1)}%`
}

function pickSortValue(pick: PickRecord, sortBy: SortKey) {
  if (sortBy === 'kelly') return Number(pick.kelly ?? pick.kelly_pct ?? 0)
  if (sortBy === 'confidence') return Number(pick.bet_prob ?? pick.model_prob ?? pick.home_win_prob ?? 0)
  return Number(pick.best_edge ?? pick.edge ?? 0)
}

function PickCard({ pick, featured = false }: { pick: PickRecord; featured?: boolean }) {
  const target = pick.bet_team ?? pick.contract_team ?? 'Pass'
  const source = pick.best_source ?? pick.market_source ?? 'market'
  const story = Array.isArray(pick.game_story) ? pick.game_story : []
  const marketProb = toMaybeNumber(pick.market_prob)
  const awayModel = toMaybeNumber(pick.away_win_prob)
  const homeModel = toMaybeNumber(pick.home_win_prob)
  const awayDisplay = awayModel ?? (marketProb == null ? null : 1 - marketProb)
  const homeDisplay = homeModel ?? marketProb
  const awayKalshi = toMaybeNumber(pick.kalshi_away_prob)
  const homeKalshi = toMaybeNumber(pick.kalshi_home_prob)
  const awayEdgeDelta = awayModel != null && awayKalshi != null ? awayModel - awayKalshi : null
  const homeEdgeDelta = homeModel != null && homeKalshi != null ? homeModel - homeKalshi : null
  const awayModelTone =
    awayDisplay == null || homeDisplay == null ? 'neutral' : awayDisplay === homeDisplay ? 'neutral' : awayDisplay > homeDisplay ? 'good' : 'bad'
  const homeModelTone =
    awayDisplay == null || homeDisplay == null ? 'neutral' : homeDisplay === awayDisplay ? 'neutral' : homeDisplay > awayDisplay ? 'good' : 'bad'
  const awayKalshiTone =
    awayKalshi == null || homeKalshi == null ? 'neutral' : awayKalshi === homeKalshi ? 'neutral' : awayKalshi > homeKalshi ? 'good' : 'bad'
  const homeKalshiTone =
    awayKalshi == null || homeKalshi == null ? 'neutral' : homeKalshi === awayKalshi ? 'neutral' : homeKalshi > awayKalshi ? 'good' : 'bad'
  const awayEdgeTone =
    awayEdgeDelta == null ? 'neutral' : awayEdgeDelta >= 0 ? 'good' : 'bad'
  const homeEdgeTone =
    homeEdgeDelta == null ? 'neutral' : homeEdgeDelta >= 0 ? 'good' : 'bad'

  return (
    <Surface className={`pick-card ${featured ? 'pick-card--feature' : ''}`} tone={pick.bet ? 'accent' : 'default'}>
      <div className="pick-card__header">
        <div>
          <span className="section-kicker">{featured ? 'Featured position' : titleCase(source)}</span>
          <h3>{target}</h3>
          <p className="pick-card__subline">
            {pick.away_team} <span>at</span> {pick.home_team}
          </p>
        </div>
        <Pill tone={pick.bet ? 'good' : 'neutral'}>{pick.bet ? 'Bet' : 'Pass'}</Pill>
      </div>
      <div className="pick-card__teams">
        <div className="pick-card__team">
          <TeamLogo team={pick.away_team as string} size={40} />
          <span style={{ color: teamAccent(pick.away_team as string) }}>{pick.away_team}</span>
          <strong className={`pick-card__prob pick-card__prob--${awayModelTone}`}>{pct0(awayDisplay)}</strong>
          <div className="pick-card__marketline">
            <div className={`pick-card__marketpill pick-card__marketpill--${awayKalshiTone}`}>
              <small>Kalshi</small>
              <span>{pct0(awayKalshi)}</span>
            </div>
            <div className={`pick-card__edgepill pick-card__edgepill--${awayEdgeTone}`}>
              {signedPct(awayEdgeDelta)}
            </div>
          </div>
        </div>
        <div className="pick-card__divider" aria-hidden="true">
          <span>at</span>
        </div>
        <div className="pick-card__team pick-card__team--right">
          <TeamLogo team={pick.home_team as string} size={40} />
          <span style={{ color: teamAccent(pick.home_team as string) }}>{pick.home_team}</span>
          <strong className={`pick-card__prob pick-card__prob--${homeModelTone}`}>{pct0(homeDisplay)}</strong>
          <div className="pick-card__marketline">
            <div className={`pick-card__marketpill pick-card__marketpill--${homeKalshiTone}`}>
              <small>Kalshi</small>
              <span>{pct0(homeKalshi)}</span>
            </div>
            <div className={`pick-card__edgepill pick-card__edgepill--${homeEdgeTone}`}>
              {signedPct(homeEdgeDelta)}
            </div>
          </div>
        </div>
      </div>
      <div className="pick-card__metrics">
        <div className="pick-card__metric">
          <span>Edge</span>
          <strong>{pct(pick.best_edge ?? pick.edge)}</strong>
        </div>
        <div className="pick-card__metric">
          <span>Kelly</span>
          <strong>{pct(pick.kelly ?? pick.kelly_pct)}</strong>
        </div>
        <div className="pick-card__metric">
          <span>Entry</span>
          <strong>{pct0(pick.bet_market ?? pick.market_prob ?? pick.entry_price)}</strong>
        </div>
        <div className="pick-card__metric">
          <span>Stake</span>
          <strong>{money(pick.stake)}</strong>
        </div>
      </div>
      <details className="pick-card__details">
        <summary>Why this position</summary>
        <div className="pick-card__story">
          {story.length ? story.map((line) => <p key={line}>{line}</p>) : <p>No narrative overlay was attached.</p>}
        </div>
      </details>
    </Surface>
  )
}

export default function PicksPage() {
  const params = useParams()
  const league: League = isLeague(params.league) ? params.league : normalizeLeague(params.league)
  const [filters, setFilters] = usePersistentState<PickFilters>(`isotonic:${league}:pick-filters`, {
    betOnly: true,
    source: 'all',
    minEdge: 0.03,
    sortBy: 'edge',
  })

  const picksQuery = useQuery({
    queryKey: ['picks', league, filters.minEdge],
    queryFn: () => getPicks(league, filters.minEdge),
  })

  const sources = useMemo(
    () => Array.from(new Set((picksQuery.data?.picks ?? []).map((pick) => pick.best_source ?? pick.market_source).filter(Boolean))),
    [picksQuery.data?.picks],
  )
  const activeSourceFilter = sources.includes(filters.source) ? filters.source : 'all'

  const filteredPicks = useMemo(() => {
    const picks = picksQuery.data?.picks ?? []
    return picks
      .filter((pick) => !filters.betOnly || Boolean(pick.bet))
      .filter((pick) => activeSourceFilter === 'all' || (pick.best_source ?? pick.market_source) === activeSourceFilter)
      .sort((left, right) => pickSortValue(right, filters.sortBy) - pickSortValue(left, filters.sortBy))
  }, [activeSourceFilter, filters.betOnly, filters.sortBy, picksQuery.data?.picks])

  if (picksQuery.isLoading) return <LoadingPanel label="Curating the picks board" />
  if (picksQuery.isError || !picksQuery.data) {
    return <ErrorState title="Picks unavailable" body="The picks endpoint did not return a usable board." />
  }

  const featured = filteredPicks[0]

  return (
    <div className="page-grid">
      <Surface className="filter-bar">
        <div className="filter-bar__group">
          <div className="filter-bar__label">
            <Filter size={15} />
            <span>Filters</span>
          </div>
          <label className="toggle">
            <input
              checked={filters.betOnly}
              type="checkbox"
              onChange={(event) => setFilters({ ...filters, betOnly: event.target.checked })}
            />
            <span>Bet only</span>
          </label>
          {sources.length > 1 ? (
            <select value={activeSourceFilter} onChange={(event) => setFilters({ ...filters, source: event.target.value })}>
              <option value="all">All sources</option>
              {sources.map((source) => (
                <option key={source} value={source}>
                  {titleCase(source)}
                </option>
              ))}
            </select>
          ) : (
            <Pill tone="accent">Kalshi only</Pill>
          )}
        </div>
        <div className="filter-bar__group filter-bar__group--stretch">
          <div className="filter-bar__label">
            <SlidersHorizontal size={15} />
            <span>Min edge</span>
          </div>
          <input
            max={0.12}
            min={0.01}
            step={0.01}
            type="range"
            value={filters.minEdge}
            onChange={(event) => setFilters({ ...filters, minEdge: Number(event.target.value) })}
          />
          <strong>{pct(filters.minEdge)}</strong>
          <select value={filters.sortBy} onChange={(event) => setFilters({ ...filters, sortBy: event.target.value as SortKey })}>
            <option value="edge">Sort by edge</option>
            <option value="kelly">Sort by Kelly</option>
            <option value="confidence">Sort by confidence</option>
          </select>
        </div>
      </Surface>

      {featured ? (
        <div>
          <PickCard pick={featured} featured />
        </div>
      ) : (
        <EmptyState
          title={`No ${leagueLabels[league]} positions surfaced`}
          body="The current filter stack removed every card on the board. Loosen the edge or source filters."
        />
      )}

      <div className="pick-grid">
        {filteredPicks.slice(featured ? 1 : 0).map((pick, index) => (
          <motion.div
            key={`${pick.trade_id ?? pick.game_id ?? `${pick.away_team}-${pick.home_team}-${index}`}`}
            layout
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.28, delay: Math.min(index * 0.02, 0.16) }}
          >
            <PickCard pick={pick} />
          </motion.div>
        ))}
      </div>

      {!filteredPicks.length ? (
        <Button tone="secondary" disabled>
          No filtered picks
        </Button>
      ) : null}
    </div>
  )
}
