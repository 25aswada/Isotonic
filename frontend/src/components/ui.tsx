import type { HTMLAttributes, ReactNode } from 'react'
import clsx from 'clsx'
import { AlertTriangle, ArrowRight, CheckCircle2, LoaderCircle, X } from 'lucide-react'

import { pct } from '../lib/format'

export function Surface({
  children,
  className,
  tone = 'default',
  ...props
}: HTMLAttributes<HTMLDivElement> & {
  children: ReactNode
  tone?: 'default' | 'accent' | 'warning'
}) {
  return (
    <div className={clsx('surface', `surface--${tone}`, className)} {...props}>
      {children}
    </div>
  )
}

export function Button({
  children,
  className,
  tone = 'primary',
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & {
  children: ReactNode
  tone?: 'primary' | 'secondary' | 'ghost'
}) {
  return (
    <button className={clsx('button', `button--${tone}`, className)} {...props}>
      {children}
    </button>
  )
}

export function MetricCard({
  label,
  value,
  hint,
  accent = 'default',
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  accent?: 'default' | 'good' | 'warn'
}) {
  return (
    <Surface className={clsx('metric-card', `metric-card--${accent}`)}>
      <span className="metric-card__label">{label}</span>
      <strong className="metric-card__value">{value}</strong>
      {hint ? <span className="metric-card__hint">{hint}</span> : null}
    </Surface>
  )
}

export function Pill({
  children,
  tone = 'neutral',
}: {
  children: ReactNode
  tone?: 'neutral' | 'good' | 'danger' | 'accent'
}) {
  return <span className={clsx('pill', `pill--${tone}`)}>{children}</span>
}

export function StatusDot({
  ok,
  label,
}: {
  ok: boolean | null | undefined
  label: string
}) {
  return (
    <span className="status-dot">
      <span className={clsx('status-dot__light', ok ? 'is-ok' : 'is-bad')} />
      <span>{label}</span>
    </span>
  )
}

export function PageIntro({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string
  title: string
  description: string
  actions?: ReactNode
}) {
  return (
    <div className="page-intro">
      <div>
        <span className="page-intro__eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions ? <div className="page-intro__actions">{actions}</div> : null}
    </div>
  )
}

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string
  body: string
  action?: ReactNode
}) {
  return (
    <Surface className="empty-state">
      <div className="empty-state__icon">
        <ArrowRight size={18} />
      </div>
      <div className="empty-state__copy">
        <strong>{title}</strong>
        <p>{body}</p>
      </div>
      {action}
    </Surface>
  )
}

export function ErrorState({ title, body }: { title: string; body: string }) {
  return (
    <Surface className="empty-state" tone="warning">
      <div className="empty-state__icon">
        <AlertTriangle size={18} />
      </div>
      <div className="empty-state__copy">
        <strong>{title}</strong>
        <p>{body}</p>
      </div>
    </Surface>
  )
}

export function LoadingPanel({ label = 'Pulling signals' }: { label?: string }) {
  return (
    <Surface className="loading-panel">
      <LoaderCircle className="loading-panel__icon" size={18} />
      <div>
        <strong>{label}</strong>
        <p>Fetching the current board and shaping the workspace.</p>
      </div>
    </Surface>
  )
}

export function ConfirmationOverlay({
  open,
  title,
  body,
  details,
  onClose,
}: {
  open: boolean
  title: string
  body: string
  details?: ReactNode
  onClose: () => void
}) {
  if (!open) return null

  return (
    <div className="confirmation-overlay" role="dialog" aria-modal="true" aria-label={title}>
      <div className="confirmation-overlay__backdrop" onClick={onClose} />
      <div className="confirmation-overlay__card">
        <button className="confirmation-overlay__close" onClick={onClose} aria-label="Close confirmation">
          <X size={16} />
        </button>
        <div className="confirmation-overlay__burst" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <div className="confirmation-overlay__icon">
          <CheckCircle2 size={28} />
        </div>
        <div className="confirmation-overlay__copy">
          <span className="section-kicker">Trade confirmed</span>
          <h3>{title}</h3>
          <p>{body}</p>
        </div>
        {details ? <div className="confirmation-overlay__details">{details}</div> : null}
        <Button onClick={onClose}>Back to board</Button>
      </div>
    </div>
  )
}

export function SkeletonBlock({
  height = 120,
  className,
}: {
  height?: number
  className?: string
}) {
  return <div className={clsx('skeleton-block', className)} style={{ height }} />
}

export function StatRow({
  label,
  left,
  right,
  higherIsBetter = true,
}: {
  label: string
  left: number | null | undefined
  right: number | null | undefined
  higherIsBetter?: boolean
}) {
  const leftValue = left ?? 0
  const rightValue = right ?? 0
  const total = Math.abs(leftValue) + Math.abs(rightValue) || 1
  const leftPct = (Math.abs(leftValue) / total) * 100
  const rightPct = 100 - leftPct
  const leftWins = higherIsBetter ? leftValue >= rightValue : leftValue <= rightValue

  return (
    <div className="stat-row">
      <span className={clsx('stat-row__value', leftWins ? 'is-good' : 'is-bad')}>{pct(left, 0)}</span>
      <div className="stat-row__bar">
        <span>{label}</span>
        <div className="stat-row__track">
          <i
            className={clsx('stat-row__fill', leftWins ? 'is-good' : 'is-bad')}
            style={{ width: `${leftPct}%` }}
          />
          <i
            className={clsx('stat-row__fill stat-row__fill--right', leftWins ? 'is-bad' : 'is-good')}
            style={{ width: `${rightPct}%` }}
          />
        </div>
      </div>
      <span className={clsx('stat-row__value', leftWins ? 'is-bad' : 'is-good')}>{pct(right, 0)}</span>
    </div>
  )
}

// ── TeamLogo ──────────────────────────────────────────────────────────────────
import { teamLogoUrl } from '../lib/teamColor'

export function TeamLogo({
  team,
  size = 40,
  className,
}: {
  team?: string | null
  size?: number
  className?: string
}) {
  const url = teamLogoUrl(team)
  if (!url) return null
  return (
    <img
      src={url}
      alt={team ?? ''}
      width={size}
      height={size}
      className={clsx('team-logo', className)}
      onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
    />
  )
}
