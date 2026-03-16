import { useQuery } from '@tanstack/react-query'
import { ArrowUpRight, Clock3, Radar, ShieldAlert } from 'lucide-react'
import { useParams } from 'react-router-dom'

import { MetricCard, EmptyState, ErrorState, LoadingPanel, Pill, Surface } from '../components/ui'
import { getOverview } from '../lib/api'
import { formatAgeSeconds, formatDateTime, moneySigned, pct } from '../lib/format'
import { isLeague, leagueLabels, normalizeLeague } from '../lib/navigation'
import { teamAccent } from '../lib/teamColor'
import type { League, LiveGame, PickRecord, PositionRecord } from '../types'

function pickHeadline(pick: PickRecord | null) {
  if (!pick) return 'No featured position on deck.'
  const target = pick.bet_team ?? pick.contract_team ?? 'Current edge'
  return `${target} is the clearest edge on the board.`
}

function pickSubline(pick: PickRecord | null) {
  if (!pick) return 'The workspace is still online and tracking markets in the background.'
  return `${pick.away_team} at ${pick.home_team} · ${pct(pick.best_edge ?? pick.edge)} edge · ${
    pick.best_source ?? pick.market_source ?? 'market'
  }`
}

function PositionPreview({ position }: { position: PositionRecord }) {
  return (
    <div className="preview-row">
      <div className="preview-row__title">
        <strong>{position.contract_team ?? position.bet_side ?? 'Open position'}</strong>
        <span>
          {position.away_team} @ {position.home_team}
        </span>
      </div>
      <div className="preview-row__meta">
        <span>{pct(position.entry_price ?? position.market_prob, 0)} entry</span>
        <span className={(position.pnl ?? 0) >= 0 ? 'is-good' : 'is-bad'}>{moneySigned(position.pnl)}</span>
      </div>
    </div>
  )
}

function LivePreview({ game }: { game: LiveGame }) {
  return (
    <div className="preview-row">
      <div className="preview-row__teams">
        <strong style={{ color: teamAccent((game.away_full_name ?? game.away_team) as string) }}>{game.away_team}</strong>
        <span>@</span>
        <strong style={{ color: teamAccent((game.home_full_name ?? game.home_team) as string) }}>{game.home_team}</strong>
      </div>
      <div className="preview-row__meta">
        <span>{pct(game.live_home_edge ?? game.live_away_edge ?? game.edge)}</span>
        <span>{game.game_status_text ?? game.period_label ?? 'Live'}</span>
      </div>
    </div>
  )
}

export default function OverviewPage() {
  const params = useParams()
  const league: League = isLeague(params.league) ? params.league : normalizeLeague(params.league)

  const overview = useQuery({
    queryKey: ['overview', league],
    queryFn: () => getOverview(league),
  })

  if (overview.isLoading) return <LoadingPanel label="Building the overview desk" />
  if (overview.isError || !overview.data) {
    return <ErrorState title="Overview unavailable" body="The summary layer could not be loaded from the API." />
  }

  const data = overview.data

  if (!data.available) {
    return (
      <EmptyState
        title={`${leagueLabels[league]} overview unavailable`}
        body="The underlying dataset or model output is missing, so the desk cannot assemble a proper summary yet."
      />
    )
  }

  return (
    <div className="page-grid">
      <Surface className="hero-panel hero-panel--feature" tone="accent">
        <div className="hero-panel__copy">
          <span className="hero-panel__eyebrow">{leagueLabels[league]} featured signal</span>
          <h2>{pickHeadline(data.top_pick)}</h2>
          <p>{pickSubline(data.top_pick)}</p>
          {data.top_pick ? (
            <div className="hero-panel__chips">
              <Pill tone="accent">{pct(data.top_pick.bet_prob ?? data.top_pick.model_prob, 0)} model</Pill>
              <Pill>{pct(data.top_pick.bet_market ?? data.top_pick.market_prob, 0)} market</Pill>
              <Pill tone="good">{pct(data.top_pick.best_edge ?? data.top_pick.edge)}</Pill>
            </div>
          ) : null}
        </div>
        {data.top_pick ? (
          <div className="hero-matchup">
            <div className="hero-matchup__team">
              <span>{data.top_pick.away_team}</span>
              <strong style={{ color: teamAccent(data.top_pick.away_team as string) }}>
                {pct(data.top_pick.away_win_prob, 0)}
              </strong>
            </div>
            <div className="hero-matchup__divider">at</div>
            <div className="hero-matchup__team">
              <span>{data.top_pick.home_team}</span>
              <strong style={{ color: teamAccent(data.top_pick.home_team as string) }}>
                {pct(data.top_pick.home_win_prob, 0)}
              </strong>
            </div>
          </div>
        ) : (
          <div className="hero-panel__ghost">Monitoring board conditions and waiting for a better setup.</div>
        )}
      </Surface>

      <div className="metric-grid">
        <MetricCard
          label="Live board"
          value={data.live_count}
          hint={`${data.live_games.length} surfaced in the desk`}
          accent="good"
        />
        <MetricCard
          label="Open positions"
          value={data.open_positions_count}
          hint={`${data.settled_positions_count ?? 0} settled this cycle`}
        />
        <MetricCard
          label="Snapshot age"
          value={formatAgeSeconds(data.snapshot_age_seconds)}
          hint={data.snapshot_stale ? 'Market snapshots are stale' : 'Fresh enough for normal operation'}
          accent={data.snapshot_stale ? 'warn' : 'default'}
        />
        <MetricCard label="Alerts" value={data.alerts_24h ?? 0} hint="Issues seen in the last 24 hours" />
      </div>

      <div className="content-grid content-grid--overview">
        <Surface className="stack-panel">
          <div className="stack-panel__header">
            <div>
              <span className="section-kicker">Live watchlist</span>
              <h3>What needs attention now</h3>
            </div>
            <Radar size={16} />
          </div>
          {data.live_games.length ? (
            <div className="stack-panel__body">
              {data.live_games.slice(0, 5).map((game, index) => (
                <LivePreview key={`${String(game.game_id ?? index)}`} game={game} />
              ))}
            </div>
          ) : (
            <EmptyState title="No live games" body="The board is quiet right now, but the desk is still warm." />
          )}
        </Surface>

        <Surface className="stack-panel">
          <div className="stack-panel__header">
            <div>
              <span className="section-kicker">Active exposure</span>
              <h3>Open positions</h3>
            </div>
            <ArrowUpRight size={16} />
          </div>
          {data.open_positions.length ? (
            <div className="stack-panel__body">
              {data.open_positions.slice(0, 5).map((position, index) => (
                <PositionPreview key={`${position.trade_id ?? index}`} position={position} />
              ))}
            </div>
          ) : (
            <EmptyState title="No open positions" body="Paper capital is flat until the next trade is logged." />
          )}
        </Surface>
      </div>

      <div className="content-grid content-grid--overview">
        <Surface className="stack-panel">
          <div className="stack-panel__header">
            <div>
              <span className="section-kicker">Top picks</span>
              <h3>Secondary opportunities</h3>
            </div>
            <Clock3 size={16} />
          </div>
          {data.top_picks.length ? (
            <div className="stack-panel__body">
              {data.top_picks.slice(0, 4).map((pick, index) => (
                <div className="preview-row" key={`${pick.trade_id ?? pick.game_id ?? index}`}>
                  <div className="preview-row__title">
                    <strong>{pick.bet_team ?? pick.contract_team ?? 'Watch'}</strong>
                    <span>
                      {pick.away_team} @ {pick.home_team}
                    </span>
                  </div>
                  <div className="preview-row__meta">
                    <span>{pct(pick.best_edge ?? pick.edge)}</span>
                    <span>{pick.best_source ?? pick.market_source ?? 'market'}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title="No backup edges" body="Only the lead card is worth surfacing right now." />
          )}
        </Surface>

        <Surface className="stack-panel">
          <div className="stack-panel__header">
            <div>
              <span className="section-kicker">Freshness</span>
              <h3>Operational confidence</h3>
            </div>
            <ShieldAlert size={16} />
          </div>
          <div className="status-list">
            <div className="status-list__row">
              <span>Model trained</span>
              <strong>{formatDateTime(data.model_trained_at)}</strong>
            </div>
            <div className="status-list__row">
              <span>Snapshot age</span>
              <strong>{formatAgeSeconds(data.snapshot_age_seconds)}</strong>
            </div>
            <div className="status-list__row">
              <span>Alerts</span>
              <strong>{data.alerts_24h ?? 0}</strong>
            </div>
            <div className="status-list__row">
              <span>Generated</span>
              <strong>{formatDateTime(data.generated_at)}</strong>
            </div>
          </div>
        </Surface>
      </div>
    </div>
  )
}
