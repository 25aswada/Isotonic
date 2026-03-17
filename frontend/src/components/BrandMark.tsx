import { useId } from 'react'

export function BrandMark({ compact = false }: { compact?: boolean }) {
  const fillId = useId()
  const glowId = useId()
  const maskId = useId()

  return (
    <div className={`brandmark ${compact ? 'brandmark--compact' : ''}`}>
      <div className="brandmark__glyph" aria-hidden="true">
        <svg viewBox="0 0 64 64" role="presentation">
          <defs>
            <linearGradient id={fillId} x1="12" x2="52" y1="10" y2="54" gradientUnits="userSpaceOnUse">
              <stop offset="0%" stopColor="#ffffff" />
              <stop offset="55%" stopColor="#f2f3f7" />
              <stop offset="100%" stopColor="#d5d8e0" />
            </linearGradient>
            <filter id={glowId} x="-45%" y="-45%" width="190%" height="190%">
              <feGaussianBlur stdDeviation="4.8" result="blur" />
              <feColorMatrix
                in="blur"
                type="matrix"
                values="1 0 0 0 0.95 0 1 0 0 0.95 0 0 1 0 0.99 0 0 0 0.20 0"
              />
            </filter>
            <mask id={maskId} maskUnits="userSpaceOnUse" x="0" y="0" width="64" height="64">
              <rect width="64" height="64" fill="black" />
              <rect x="7" y="23" width="50" height="18" rx="9" fill="white" />
              <rect x="23" y="7" width="18" height="50" rx="9" fill="white" />
              <rect x="31" y="5" width="2" height="54" rx="1" fill="black" />
            </mask>
          </defs>
          <g filter={`url(#${glowId})`} opacity="0.58">
            <rect x="4" y="4" width="56" height="56" fill="#ffffff" mask={`url(#${maskId})`} />
          </g>
          <rect x="4" y="4" width="56" height="56" fill={`url(#${fillId})`} mask={`url(#${maskId})`} />
        </svg>
      </div>
      <div className="brandmark__copy">
        <strong>Isotonic</strong>
      </div>
    </div>
  )
}
