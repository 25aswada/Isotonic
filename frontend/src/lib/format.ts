import type { MaybeNumber } from '../types'

export function pct(value: MaybeNumber, digits = 1) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `${(Number(value) * 100).toFixed(digits)}%`
}

export function pct0(value: MaybeNumber) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `${(Number(value) * 100).toFixed(0)}%`
}

export function num(value: MaybeNumber, digits = 1) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return Number(value).toFixed(digits)
}

export function integer(value: MaybeNumber) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `${Math.round(Number(value))}`
}

export function money(value: MaybeNumber) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `$${Math.abs(Number(value)).toFixed(2)}`
}

export function moneySigned(value: MaybeNumber) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const n = Number(value)
  return `${n >= 0 ? '+' : '-'}$${Math.abs(n).toFixed(2)}`
}

export function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return value.slice(0, 10)
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
  }).format(date)
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) return value
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(date)
}

export function formatAgeSeconds(value: MaybeNumber) {
  if (value == null || Number.isNaN(Number(value))) return 'Unknown'
  const seconds = Number(value)
  if (seconds < 60) return `${Math.round(seconds)}s ago`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`
  return `${(seconds / 3600).toFixed(1)}h ago`
}

export function titleCase(value: string | null | undefined) {
  if (!value) return ''
  return value
    .replace(/[_-]/g, ' ')
    .replace(/\b\w/g, (character) => character.toUpperCase())
}

export function truthyString(value: unknown) {
  return typeof value === 'string' && value.trim().length > 0
}

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

export function sparklinePath(values: number[], width = 260, height = 88, padding = 10) {
  if (!values.length) return ''
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  return values
    .map((value, index) => {
      const x = padding + (index / Math.max(values.length - 1, 1)) * (width - padding * 2)
      const y = height - padding - ((value - min) / range) * (height - padding * 2)
      return `${index === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')
}
