import siteLogo from '../assets/site-logo.png'

export function BrandMark({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`brandmark ${compact ? 'brandmark--compact' : ''}`}>
      <div className="brandmark__glyph" aria-hidden="true">
        <img src={siteLogo} alt="" role="presentation" />
      </div>
      <div className="brandmark__copy">
        <strong>Isotonic</strong>
      </div>
    </div>
  )
}
