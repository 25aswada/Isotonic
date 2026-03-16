import { Suspense } from 'react'
import type { ReactElement } from 'react'
import { Navigate, createBrowserRouter } from 'react-router-dom'

import LandingPage from './pages/LandingPage'
import WorkspaceShell from './pages/WorkspaceShell'
import OverviewPage from './pages/OverviewPage'
import PicksPage from './pages/PicksPage'
import LivePage from './pages/LivePage'
import PaperTraderPage from './pages/PaperTraderPage'
import ResearchPage from './pages/ResearchPage'
import SystemPage from './pages/SystemPage'
import HistoryPage from './pages/HistoryPage'

function RouteFallback() {
  return (
    <div className="route-loader">
      <div className="route-loader__pulse" />
      <div className="route-loader__copy">
        <span>Loading workspace</span>
        <strong>Composing surfaces and signals.</strong>
      </div>
    </div>
  )
}

function wrap(element: ReactElement) {
  return <Suspense fallback={<RouteFallback />}>{element}</Suspense>
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: wrap(<LandingPage />),
  },
  {
    path: '/app',
    element: wrap(<WorkspaceShell />),
    children: [
      {
        index: true,
        element: <Navigate to="/app/nba/overview" replace />,
      },
      {
        path: 'system',
        element: wrap(<SystemPage />),
      },
      {
        path: ':league',
        children: [
          {
            index: true,
            element: <Navigate to="overview" replace />,
          },
          { path: 'overview', element: wrap(<OverviewPage />) },
          { path: 'picks', element: wrap(<PicksPage />) },
          { path: 'live', element: wrap(<LivePage />) },
          { path: 'paper-trader', element: wrap(<PaperTraderPage />) },
          { path: 'research', element: wrap(<ResearchPage />) },
          { path: 'history', element: wrap(<HistoryPage />) },
        ],
      },
    ],
  },
  {
    path: '*',
    element: <Navigate to="/" replace />,
  },
])
