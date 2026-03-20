import { AnimatePresence, LazyMotion, domAnimation, m, useReducedMotion } from 'framer-motion'
import {
  Activity,
  BarChart3,
  Command,
  FlaskConical,
  LayoutGrid,
  MonitorCog,
  PanelLeft,
  Search,
  ShieldCheck,
  WalletCards,
  BadgeDollarSign,
  Blocks,
} from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import type { ComponentType } from 'react'
import { NavLink, Outlet, useLocation, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import { CommandPalette } from '../components/CommandPalette'
import { BrandMark } from '../components/BrandMark'
import { Button, Pill, StatusDot } from '../components/ui'
import { getSystemHealth } from '../lib/api'
import { formatAgeSeconds } from '../lib/format'
import {
  buildLeaguePath,
  getSectionFromPath,
  isLeague,
  leagueLabels,
  normalizeLeague,
  sections,
} from '../lib/navigation'
import { usePersistentState } from '../hooks/usePersistentState'
import type { League, WorkspaceSection } from '../types'

const sectionIcons = {
  overview: LayoutGrid,
  picks: BadgeDollarSign,
  live: Activity,
  'paper-trader': WalletCards,
  combos: Blocks,
  research: FlaskConical,
  history: BarChart3,
} satisfies Record<WorkspaceSection, ComponentType<{ size?: number; className?: string }>>

function resolvePageTitle(pathname: string) {
  if (pathname === '/app/system') {
    return {
      title: 'System',
      description: 'Health, freshness, update controls, and alert visibility.',
    }
  }

  const section = getSectionFromPath(pathname)
  return section
    ? {
        title: sections[section].label,
        description: sections[section].description,
      }
    : {
        title: 'Workspace',
        description: 'Premium command surfaces for every part of the workflow.',
      }
}

export default function WorkspaceShell() {
  const params = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const reduceMotion = useReducedMotion()

  const [storedLeague, setStoredLeague] = usePersistentState<League>('isotonic:league', 'nba')
  const [railCollapsed, setRailCollapsed] = usePersistentState('isotonic:rail-collapsed', false)
  const [paletteOpen, setPaletteOpen] = useState(false)

  const currentLeague = isLeague(params.league) ? params.league : normalizeLeague(storedLeague)
  useEffect(() => {
    if (currentLeague !== storedLeague) setStoredLeague(currentLeague)
  }, [currentLeague, setStoredLeague, storedLeague])

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setPaletteOpen(true)
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  const pageMeta = resolvePageTitle(location.pathname)
  const currentSection = getSectionFromPath(location.pathname) ?? 'overview'

  const systemHealth = useQuery({
    queryKey: ['system-health'],
    queryFn: getSystemHealth,
    staleTime: 30_000,
  })

  const commandItems = useMemo(
    () => [
      ...(
        Object.keys(sections) as WorkspaceSection[]
      ).map((section) => ({
        id: section,
        label: `${leagueLabels[currentLeague]} ${sections[section].label}`,
        subtitle: sections[section].description,
        href: buildLeaguePath(currentLeague, section),
      })),
      {
        id: 'system',
        label: 'System',
        subtitle: 'Health, alerts, and maintenance controls.',
        href: '/app/system',
      },
    ],
    [currentLeague],
  )

  return (
    <LazyMotion features={domAnimation}>
      <div className="app-shell">
        <div className="app-shell__noise" />
        <aside className={`app-rail ${railCollapsed ? 'is-collapsed' : ''}`}>
          <div className="app-rail__top">
            <BrandMark compact={railCollapsed} />
            <button
              className="app-rail__collapse"
              aria-label={railCollapsed ? 'Expand navigation' : 'Collapse navigation'}
              onClick={() => setRailCollapsed((value) => !value)}
            >
              <PanelLeft size={16} />
            </button>
          </div>
          <nav className="app-rail__nav" aria-label="Primary">
            {(Object.keys(sections) as WorkspaceSection[]).map((section) => (
              (() => {
                const Icon = sectionIcons[section]
                return (
                  <NavLink
                    key={section}
                    aria-label={sections[section].label}
                    title={sections[section].label}
                    className={({ isActive }) =>
                      `app-rail__link ${isActive && currentSection === section ? 'is-active' : ''}`
                    }
                    to={buildLeaguePath(currentLeague, section)}
                  >
                    <span className="app-rail__link-icon" aria-hidden="true">
                      <Icon size={18} />
                    </span>
                    <span className="app-rail__link-copy">
                      <span>{sections[section].label}</span>
                      <small>{sections[section].description}</small>
                    </span>
                  </NavLink>
                )
              })()
            ))}
          </nav>
          <div className="app-rail__footer">
            <button
              className="app-rail__utility"
              aria-label="System"
              title="System"
              onClick={() => navigate('/app/system')}
            >
              <MonitorCog size={16} />
              <span>System</span>
            </button>
          </div>
        </aside>

        <div className="app-shell__main">
          <header className="topbar">
            <div className="topbar__copy">
              <span className="topbar__eyebrow">{leagueLabels[currentLeague]} workspace</span>
              <h1>{pageMeta.title}</h1>
              <p>{pageMeta.description}</p>
            </div>
            <div className="topbar__actions">
              <button className="topbar__search" onClick={() => setPaletteOpen(true)}>
                <Search size={16} />
                <span>Search</span>
                <kbd>
                  <Command size={11} />
                  K
                </kbd>
              </button>
              <div className="topbar__status">
                <StatusDot ok={systemHealth.data?.model_loaded} label="NBA model" />
                <StatusDot ok={systemHealth.data?.ncaab_model_loaded} label="NCAA model" />
                <Pill tone={systemHealth.data?.snapshot_stale ? 'danger' : 'accent'}>
                  {formatAgeSeconds(systemHealth.data?.snapshot_age_seconds)}
                </Pill>
              </div>
              <div className="league-switcher" role="tablist" aria-label="League">
                {(['nba', 'ncaab'] as League[]).map((league) => (
                  <button
                    key={league}
                    className={league === currentLeague ? 'is-active' : ''}
                    onClick={() => navigate(buildLeaguePath(league, currentSection))}
                  >
                    {leagueLabels[league]}
                  </button>
                ))}
              </div>
              <Button tone="ghost" onClick={() => navigate('/app/system')}>
                <ShieldCheck size={16} />
                <span>System</span>
              </Button>
            </div>
          </header>

          <AnimatePresence mode="sync" initial={false}>
            <m.div
              key={location.pathname}
              className="workspace-stage"
              initial={reduceMotion ? undefined : { opacity: 0 }}
              animate={reduceMotion ? undefined : { opacity: 1 }}
              exit={reduceMotion ? undefined : { opacity: 0 }}
              transition={{ duration: 0.18 }}
            >
              <Outlet />
            </m.div>
          </AnimatePresence>
        </div>

        <div className="mobile-dock" aria-label="Mobile navigation">
          {(Object.keys(sections) as WorkspaceSection[]).map((section) => (
            <button
              key={section}
              className={currentSection === section ? 'is-active' : ''}
              onClick={() => navigate(buildLeaguePath(currentLeague, section))}
            >
              {sections[section].dockLabel ?? sections[section].label}
            </button>
          ))}
        </div>

        <CommandPalette
          open={paletteOpen}
          onClose={() => setPaletteOpen(false)}
          items={commandItems}
          currentLeague={currentLeague}
          navigate={(href) => navigate(href)}
        />
      </div>
    </LazyMotion>
  )
}
