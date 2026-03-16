import type { League, WorkspaceSection } from '../types'

export interface SectionMeta {
  label: string
  dockLabel?: string
  description: string
}

export const sections: Record<WorkspaceSection, SectionMeta> = {
  overview: {
    label: 'Overview',
    description: 'A high-signal front page for the current league.',
  },
  picks: {
    label: 'Picks',
    description: 'Featured edges, filters, and decisive bet framing.',
  },
  live: {
    label: 'Live',
    description: 'Real-time board, watchlist, and live edge monitoring.',
  },
  'paper-trader': {
    label: 'Paper Trader',
    dockLabel: 'Paper',
    description: 'Simulated trading, positions, and auto-trade controls.',
  },
  research: {
    label: 'Research',
    description: 'Matchup tools, explorers, and supporting context.',
  },
  history: {
    label: 'History',
    description: 'Performance tracking and model accuracy.',
  },
}

export const leagueLabels: Record<League, string> = {
  nba: 'NBA',
  ncaab: 'NCAA',
}

export const legacyHashMap: Record<string, string> = {
  picks: '/app/nba/picks',
  live: '/app/nba/live',
  matchup: '/app/nba/research?tab=matchup',
  paper: '/app/nba/paper-trader',
  accuracy: '/app/nba/history?tab=accuracy',
  team: '/app/nba/research?tab=teams',
  tracker: '/app/nba/history?tab=tracker',
  system: '/app/system',
  'nc-picks': '/app/ncaab/picks',
  'nc-live': '/app/ncaab/live',
  'nc-matchup': '/app/ncaab/research?tab=matchup',
  'nc-trader': '/app/ncaab/paper-trader',
  'nc-accuracy': '/app/ncaab/history?tab=accuracy',
  'nc-teams': '/app/ncaab/research?tab=teams',
  'nc-tracker': '/app/ncaab/history?tab=tracker',
  'nc-bracket': '/app/ncaab/research?tab=bracket',
}

export function isLeague(value: string | undefined): value is League {
  return value === 'nba' || value === 'ncaab'
}

export function buildLeaguePath(league: League, section: WorkspaceSection) {
  return `/app/${league}/${section}`
}

export function getSectionFromPath(pathname: string): WorkspaceSection | null {
  const match = pathname.match(/\/(overview|picks|live|paper-trader|research|history)$/)
  return (match?.[1] as WorkspaceSection | undefined) ?? null
}

export function normalizeLeague(value: string | null | undefined): League {
  return value === 'ncaab' ? 'ncaab' : 'nba'
}
