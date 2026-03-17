import { motion, useReducedMotion } from 'framer-motion'
import { ArrowRight, Dot, Sparkles } from 'lucide-react'
import { useEffect } from 'react'
import { useQueries } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'

import { getOverview, getSystemHealth } from '../lib/api'
import { formatAgeSeconds, pct } from '../lib/format'
import { legacyHashMap, leagueLabels } from '../lib/navigation'
import { Pill, Surface, TeamLogo } from '../components/ui'
import { BrandMark } from '../components/BrandMark'

export default function LandingPage() {
  const navigate = useNavigate()
  const reduceMotion = useReducedMotion()

  useEffect(() => {
    const hash = window.location.hash.replace('#', '')
    if (hash && legacyHashMap[hash]) {
      navigate(legacyHashMap[hash], { replace: true })
    }
  }, [navigate])

  const [nbaOverview, ncaabOverview, systemHealth] = useQueries({
    queries: [
      { queryKey: ['overview', 'nba'], queryFn: () => getOverview('nba') },
      { queryKey: ['overview', 'ncaab'], queryFn: () => getOverview('ncaab') },
      { queryKey: ['system-health'], queryFn: getSystemHealth },
    ],
  })

  const leagues = [
    { key: 'nba' as const, data: nbaOverview.data },
    { key: 'ncaab' as const, data: ncaabOverview.data },
  ]

  return (
    <main className="landing">
      <div className="landing__noise" />
      <div className="landing__gradient landing__gradient--primary" />
      <div className="landing__gradient landing__gradient--secondary" />

      <motion.section
        className="landing__hero"
        initial={reduceMotion ? undefined : { opacity: 0, y: 24 }}
        animate={reduceMotion ? undefined : { opacity: 1, y: 0 }}
        transition={{ duration: 0.8, ease: [0.16, 1, 0.3, 1] }}
      >
        <BrandMark />
        <div className="landing__eyebrow">
          <Sparkles size={14} />
          <span>Premium model workspace</span>
        </div>
        <h1>One command center for every edge worth acting on.</h1>
        <p>
          Isotonic turns live markets, model conviction, matchup context, and paper-trading history into a focused
          pro workflow instead of a homemade dashboard.
        </p>
        <div className="landing__actions">
          <Link className="landing__cta" to="/app/nba/overview">
            Enter Workspace
            <ArrowRight size={16} />
          </Link>
          <Link className="landing__secondary" to="/app/ncaab/overview">
            Open NCAA Desk
          </Link>
        </div>
      </motion.section>

      <section className="landing__strip">
        <Surface className="landing__proof">
          <div>
            <span className="landing__proof-label">System status</span>
            <strong>{systemHealth.data?.model_loaded ? 'NBA model loaded' : 'Waiting on model'}</strong>
          </div>
          <div>
            <span className="landing__proof-label">Snapshot age</span>
            <strong>{formatAgeSeconds(systemHealth.data?.snapshot_age_seconds)}</strong>
          </div>
          <div>
            <span className="landing__proof-label">Alerts</span>
            <strong>{systemHealth.data?.alerts_24h ?? 0} in the last 24h</strong>
          </div>
        </Surface>
      </section>

      <section className="landing__league-grid">
        {leagues.map(({ key, data }) => (
          <Surface key={key} className="landing__league-card">
            <div className="landing__league-header">
              <div>
                <span className="landing__proof-label">{leagueLabels[key]}</span>
                <div className="landing__league-title">
                  {data?.top_pick?.bet_team ? <TeamLogo team={data.top_pick.bet_team as string} size={22} /> : null}
                  <h2>{data?.top_pick?.bet_team ?? 'Board ready'}</h2>
                </div>
              </div>
              <Pill tone="accent">{data?.live_count ?? 0} live</Pill>
            </div>
            <p>
              {data?.top_pick
                ? `${data.top_pick.away_team} at ${data.top_pick.home_team} · best edge ${pct(
                    data.top_pick.best_edge ?? data.top_pick.edge,
                  )}`
                : 'No featured edge is active right now, but the desk is still online.'}
            </p>
            <div className="landing__league-metrics">
              <span>
                {data?.bets_found ?? 0}
                <small>bets</small>
              </span>
              <Dot />
              <span>
                {pct(data?.avg_edge)}
                <small>avg edge</small>
              </span>
              <Dot />
              <span>
                {data?.open_positions_count ?? 0}
                <small>open</small>
              </span>
            </div>
            <Link className="landing__inline-link" to={`/app/${key}/overview`}>
              Open {leagueLabels[key]}
              <ArrowRight size={14} />
            </Link>
          </Surface>
        ))}
      </section>
    </main>
  )
}
