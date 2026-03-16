export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`brandmark ${compact ? 'brandmark--compact' : ''}`}>
      <div className="brandmark__glyph" aria-hidden="true">
        <svg viewBox="0 0 72 72" role="presentation">
          <defs>
            <linearGradient id="brandGradient" x1="8" x2="64" y1="12" y2="60" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stopColor="#f2f5ff" />
              <stop offset="45%" stopColor="#8fb1ff" />
              <stop offset="100%" stopColor="#5f7cff" />
            </linearGradient>
          </defs>
          <rect x="6" y="6" width="60" height="60" rx="18" fill="rgba(255,255,255,0.04)" />
          <path
            d="M18 47.5C26.2 47.5 26.6 24.5 36 24.5C45.4 24.5 45.8 47.5 54 47.5"
            fill="none"
            stroke="url(#brandGradient)"
            strokeLinecap="round"
            strokeWidth="5.5"
          />
          <path
            d="M18 36C26.2 36 26.6 13 36 13C45.4 13 45.8 36 54 36"
            fill="none"
            opacity="0.55"
            stroke="url(#brandGradient)"
            strokeLinecap="round"
            strokeWidth="3"
          />
        </svg>
      </div>
      <div className="brandmark__copy">
        <span className="brandmark__eyebrow">Prediction Workspace</span>
        <strong>Isotonic</strong>
      </div>
    </div>
  )
}
