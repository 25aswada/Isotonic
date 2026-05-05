export type League = 'nba' | 'ncaab'
export type WorkspaceSection =
  | 'overview'
  | 'picks'
  | 'live'
  | 'paper-trader'
  | 'combos'
  | 'research'
  | 'history'

export type MaybeNumber = number | null | undefined

export interface PickRecord {
  trade_id?: string
  game_id?: string | number
  game_date?: string
  tipoff_utc?: string
  home_team?: string
  away_team?: string
  bet?: boolean
  bet_team?: string
  contract_team?: string
  bet_side?: string
  confidence?: string
  best_edge?: number
  edge?: number
  kelly?: number
  kelly_pct?: number
  stake?: number
  model_prob?: number
  bet_prob?: number
  market_prob?: number
  market_home_implied?: number
  best_source?: string
  market_source?: string
  bet_market?: number
  entry_price?: number
  kalshi_home_prob?: number
  kalshi_away_prob?: number
  polymarket_home_prob?: number
  polymarket_away_prob?: number
  home_win_prob?: number
  away_win_prob?: number
  game_story?: string[]
  expected_profit?: number
  [key: string]: unknown
}

export interface PicksResponse {
  date?: string
  games_analyzed?: number
  bets_found?: number
  avg_edge?: number
  odds_sources?: string[]
  available?: boolean
  error?: string
  picks: PickRecord[]
}

export interface LiveGame {
  game_id?: string | number
  game_status?: number
  game_status_text?: string
  tipoff_utc?: string
  seconds_remaining?: number
  period?: number
  period_label?: string
  clock_display?: string
  home_team?: string
  away_team?: string
  home_full_name?: string
  away_full_name?: string
  home_score?: number
  away_score?: number
  home_win_prob?: number
  away_win_prob?: number
  pregame_home_prob?: number
  pregame_away_prob?: number
  live_home_prob?: number
  live_away_prob?: number
  live_home_edge?: number
  live_away_edge?: number
  edge?: number
  kalshi_home_prob?: number
  kalshi_away_prob?: number
  polymarket_home_prob?: number
  polymarket_away_prob?: number
  market_home_live?: number
  market_away_live?: number
  pred_home_score?: number
  pred_away_score?: number
  [key: string]: unknown
}

export interface LivePayload {
  fetched_at?: string
  in_progress: LiveGame[]
  upcoming: LiveGame[]
  final: LiveGame[]
}

export interface ProbSnapshot {
  ts: string
  model_home: number | null
  model_away: number | null
  market_home: number | null
  market_away: number | null
  home_score: number
  away_score: number
  period?: string | number
  clock?: string
}

export interface GameDetailResponse {
  game: LiveGame
  history: ProbSnapshot[]
}

export interface OverviewResponse {
  league: League
  available: boolean
  generated_at?: string
  bets_found?: number
  avg_edge?: number
  live_count: number
  open_positions_count: number
  settled_positions_count?: number
  top_pick: PickRecord | null
  top_picks: PickRecord[]
  live_games: LiveGame[]
  open_positions: PositionRecord[]
  model_trained_at?: string | null
  snapshot_age_seconds?: number | null
  snapshot_stale?: boolean | null
  alerts_24h?: number
  meta?: Record<string, unknown>
}

export interface PositionRecord {
  candidate_id?: string
  trade_id?: string
  placed_at?: string
  settled_at?: string
  game_id?: string | number
  game_date?: string
  tipoff_utc?: string
  market_source?: string
  home_team?: string
  away_team?: string
  bet_side?: string
  contract_team?: string
  model_prob?: number
  market_prob?: number
  quoted_entry_price?: number
  entry_price?: number
  entry_slippage?: number
  current_value?: number
  current_mark_price?: number
  edge?: number
  kelly_pct?: number
  stake?: number
  expected_profit?: number
  cash_after_trade?: number
  break_even_prob?: number
  pnl?: number
  clv?: number
  status?: string
  trade_stage?: string
  auto_placed?: boolean
  placed_by?: string
  win?: number | boolean
  [key: string]: unknown
}

export interface PaperBankroll {
  starting_bankroll: number
  realized_pnl: number
  unrealized_pnl: number
  settled_bankroll: number
  open_risk: number
  available_cash: number
  live_open_value: number
  estimated_equity: number
}

export interface PaperState {
  bankroll: PaperBankroll
  open_count: number
  settled_count: number
}

export interface PaperCandidatesResponse {
  candidates: PaperTraderCandidate[]
}

export interface PaperTraderCandidate extends PositionRecord {
  candidate_id: string
}

export interface ManualTradePreviewResponse {
  trade: PositionRecord
}

export interface ComboLegRecord {
  collection_ticker?: string
  market_ticker?: string
  title?: string
  display?: string
  market_type?: string
  team?: string | null
  team_side?: string | null
  threshold?: number | null
  entry_price?: number
  mark_price?: number
  market_prob?: number
  model_prob?: number
  edge?: number
}

export interface ComboCollectionRecord {
  collection_ticker: string
  title?: string
  description?: string
  functional_description?: string
  home_team?: string
  away_team?: string
  tipoff_utc?: string
  pred_home_score?: number
  pred_away_score?: number
  home_win_prob?: number
  away_win_prob?: number
  best_edge?: number
  legs: ComboLegRecord[]
}

export interface ComboBoardResponse {
  collections: ComboCollectionRecord[]
}

export interface ComboState {
  bankroll: PaperBankroll
  open_count: number
  settled_count: number
}

export interface ComboCandidatesResponse {
  candidates: PaperTraderCandidate[]
}

export interface PaperTradeActionResult {
  logged?: number
  message?: string
  trade_ids?: string[]
}

export interface AutoTradeStatus {
  available: boolean
  enabled?: boolean
  mode?: 'armed' | 'dry-run'
  min_edge?: number
  sources?: string[]
  poll_seconds?: number
  active_hours?: [number, number]
  last_run?: string | null
  next_run?: string | null
  games_checked?: number
  new_bets_placed?: number
  last_error?: string | null
  last_message?: string | null
  is_running?: boolean
  reason?: string | null
}

export interface AutoTradeConfig {
  action: 'arm' | 'pause' | 'run_dry_cycle'
}

export interface PaperPositionsResponse {
  positions?: PositionRecord[]
  open?: PositionRecord[]
  settled?: PositionRecord[]
}

export interface TrackerResponse {
  summary: {
    total_bets?: number
    settled_count?: number
    wins?: number
    losses?: number
    win_rate?: number | null
    flat_roi?: number | null
  }
  cumulative_pnl: Array<{ game_date?: string; cumulative?: number }>
  bets: PositionRecord[]
}

export interface AccuracyMetricSet {
  [key: string]: string | number | boolean | null | undefined
}

export interface CalibrationPoint {
  mean_predicted?: number
  fraction_positive?: number
}

export interface AccuracyResponse {
  error?: string
  metrics?: AccuracyMetricSet
  calibration?: CalibrationPoint[]
  backtest?: Record<
    string,
    {
      cumulative_pnl?: number[]
      roi?: number | null
      bet_count?: number
    }
  >
  feature_importance?: Array<{ feature?: string; importance?: number; gain?: number }>
  recent_predictions?: PickRecord[]
  available?: boolean
}

export interface TeamExplorerResponse {
  team?: string
  error?: string
  current_elo?: number
  record_season?: string
  season_record?: { wins?: number; losses?: number }
  win_pct?: number
  elo_history?: Array<{ game_date?: string; elo?: number }>
  rolling_form?: Array<{ game_date?: string; roll_10_pts?: number; roll_10_opp_pts?: number }>
  seed?: string | number
  net_rtg?: number
  avg_margin?: number
  off_rtg?: number
  def_rtg?: number
  last10_win_pct?: number
  last10_margin?: number
  median_rank?: number
  best_rank?: number
}

export interface MatchupResponse {
  team_a?: string
  team_b?: string
  pred_prob_a?: number
  pred_prob_b?: number
  favorite?: string
  favorite_prob?: number
  confidence_label?: string
  prediction_source?: string
  pred_score_a?: number
  pred_score_b?: number
  narrative?: string
  market_odds?: Record<string, number | null>
  stats_a?: Record<string, number | string | null>
  stats_b?: Record<string, number | string | null>
  form_a?: Array<Record<string, number | string>>
  form_b?: Array<Record<string, number | string>>
  h2h?: Array<Record<string, number | string>>
  h2h_summary?: Record<string, number>
  elo_history_a?: Array<{ game_date?: string; elo?: number }>
  elo_history_b?: Array<{ game_date?: string; elo?: number }>
  team_a_win_prob?: number
  team_b_win_prob?: number
  team_a_win_prob_model?: number
  team_b_win_prob_model?: number
  seed_baseline_prob?: number
  team_a_seed_edge?: number
  team_b_seed_edge?: number
  team_a_availability_summary?: string
  team_b_availability_summary?: string
}

export interface NcaabSummaryResponse {
  available?: boolean
  reason?: string
  metrics?: Record<string, number | string | null>
  meta?: Record<string, unknown>
}

export interface NcaabTeamRecord {
  TeamName?: string
  team_name?: string
  Seed?: string
  seed_num?: number
  region?: string
  elo?: number
  win_pct?: number
  avg_margin?: number
  net_rtg?: number
  off_rtg?: number
  def_rtg?: number
  last10_win_pct?: number
  last10_margin?: number
  [key: string]: unknown
}

export interface AdvancementRow {
  TeamID: number
  TeamName: string
  seed_num: number
  region: string
  'Round of 64': number
  'Round of 32': number
  'Sweet 16': number
  'Elite 8': number
  'Final Four': number
  Championship: number
  [key: string]: unknown
}

export interface BracketResponse {
  available?: boolean
  bracket: Array<Record<string, string | number | null>>
  advancement?: AdvancementRow[]
  results?: Array<Record<string, string | number | null>>
}

export interface TeamListResponse {
  teams: string[]
}

export interface TeamRowsResponse {
  teams: NcaabTeamRecord[]
  available?: boolean
}

export interface SystemHealth {
  model_loaded?: boolean
  ncaab_model_loaded?: boolean
  model_trained_at?: string | null
  latest_snapshot_at?: string | null
  snapshot_age_seconds?: number | null
  snapshot_stale?: boolean | null
  paper_trades_count?: number
  alerts_24h?: number
}

export interface SystemAlert {
  code?: string
  severity?: string
  created_at?: string
  message?: string
}

export interface SystemAlertsResponse {
  alerts: SystemAlert[]
}
