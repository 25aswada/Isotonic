import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'

import { Button, ErrorState, LoadingPanel, MetricCard, Pill, Surface } from '../components/ui'
import { getModelUpdateStatus, getSystemAlerts, getSystemHealth, settleResults, startModelUpdate } from '../lib/api'
import { formatAgeSeconds, formatDateTime } from '../lib/format'

export default function SystemPage() {
  const [message, setMessage] = useState('')

  const health = useQuery({
    queryKey: ['system-health'],
    queryFn: getSystemHealth,
  })
  const alerts = useQuery({
    queryKey: ['system-alerts'],
    queryFn: getSystemAlerts,
  })
  const updateStatus = useQuery({
    queryKey: ['system-update-status'],
    queryFn: getModelUpdateStatus,
    refetchInterval: (query) => (query.state.data?.status === 'running' ? 3_000 : false),
  })

  const settleMutation = useMutation({
    mutationFn: settleResults,
    onSuccess: (data) => setMessage(data.output ?? (data.success ? 'Settlement finished.' : 'Settlement failed.')),
    onError: () => setMessage('Settlement failed.'),
  })

  const updateMutation = useMutation({
    mutationFn: startModelUpdate,
    onSuccess: (data) => setMessage(data.started ? 'Model update started.' : data.reason ?? 'Update already running.'),
    onError: () => setMessage('Model update failed to start.'),
  })

  if (health.isLoading || alerts.isLoading || updateStatus.isLoading) return <LoadingPanel label="Loading system controls" />
  if (health.isError || alerts.isError || updateStatus.isError || !health.data || !alerts.data || !updateStatus.data) {
    return <ErrorState title="System controls unavailable" body="One or more system endpoints failed." />
  }

  return (
    <div className="page-grid">
      <div className="metric-grid">
        <MetricCard label="NBA model" value={health.data.model_loaded ? 'Loaded' : 'Unavailable'} />
        <MetricCard label="NCAA model" value={health.data.ncaab_model_loaded ? 'Loaded' : 'Unavailable'} />
        <MetricCard label="Snapshot age" value={formatAgeSeconds(health.data.snapshot_age_seconds)} />
        <MetricCard label="Alerts (24h)" value={health.data.alerts_24h ?? 0} />
      </div>

      <Surface className="filter-bar">
        <div className="filter-bar__group">
          <Button tone="secondary" disabled={settleMutation.isPending} onClick={() => settleMutation.mutate()}>
            {settleMutation.isPending ? 'Settling…' : 'Settle results'}
          </Button>
          <Button tone="primary" disabled={updateMutation.isPending} onClick={() => updateMutation.mutate()}>
            {updateMutation.isPending ? 'Starting…' : 'Update model'}
          </Button>
          <Pill tone={updateStatus.data.status === 'running' ? 'accent' : 'neutral'}>
            {updateStatus.data.status ?? 'idle'}
          </Pill>
        </div>
        {message ? <Pill tone="accent">{message}</Pill> : null}
      </Surface>

      <div className="content-grid">
        <Surface className="stack-panel">
          <div className="stack-panel__header">
            <div>
              <span className="section-kicker">Health</span>
              <h3>Current state</h3>
            </div>
          </div>
          <div className="status-list">
            <div className="status-list__row">
              <span>Model trained</span>
              <strong>{formatDateTime(health.data.model_trained_at)}</strong>
            </div>
            <div className="status-list__row">
              <span>Latest snapshot</span>
              <strong>{formatDateTime(health.data.latest_snapshot_at)}</strong>
            </div>
            <div className="status-list__row">
              <span>Paper trades</span>
              <strong>{health.data.paper_trades_count ?? 0}</strong>
            </div>
          </div>
        </Surface>

        <Surface className="stack-panel">
          <div className="stack-panel__header">
            <div>
              <span className="section-kicker">Update log</span>
              <h3>Background job</h3>
            </div>
          </div>
          <pre className="log-panel">{(updateStatus.data.log ?? []).join('\n') || 'No update log yet.'}</pre>
        </Surface>
      </div>

      <Surface className="stack-panel">
        <div className="stack-panel__header">
          <div>
            <span className="section-kicker">Recent alerts</span>
            <h3>Ops visibility</h3>
          </div>
          <Pill>{alerts.data.alerts.length}</Pill>
        </div>
        <div className="stack-panel__body">
          {alerts.data.alerts.map((alert, index) => (
            <div className="preview-row" key={`${alert.code ?? index}`}>
              <div className="preview-row__title">
                <strong>{alert.code ?? 'Alert'}</strong>
                <span>{alert.message ?? 'No alert message provided.'}</span>
              </div>
              <div className="preview-row__meta">
                <span>{alert.severity ?? 'info'}</span>
                <span>{formatDateTime(alert.created_at)}</span>
              </div>
            </div>
          ))}
        </div>
      </Surface>
    </div>
  )
}
