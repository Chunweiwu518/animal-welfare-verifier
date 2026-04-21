interface StanceBarProps {
  supporting: number
  opposing: number
  neutral: number
  compact?: boolean
}

export function StanceBar({ supporting, opposing, neutral, compact }: StanceBarProps) {
  const total = supporting + opposing + neutral
  if (total === 0) {
    return <div className={`stance-bar stance-bar-empty${compact ? ' compact' : ''}`}>尚無</div>
  }
  const sPct = Math.round((supporting / total) * 100)
  const oPct = Math.round((opposing / total) * 100)
  const nPct = Math.max(0, 100 - sPct - oPct)

  return (
    <div className={`stance-bar${compact ? ' compact' : ''}`}>
      <div className="stance-bar-track" role="img" aria-label={`正面 ${supporting} 負面 ${opposing} 中性 ${neutral}`}>
        {supporting > 0 && (
          <span className="stance-seg stance-seg-support" style={{ width: `${sPct}%` }} />
        )}
        {opposing > 0 && (
          <span className="stance-seg stance-seg-oppose" style={{ width: `${oPct}%` }} />
        )}
        {neutral > 0 && (
          <span className="stance-seg stance-seg-neutral" style={{ width: `${nPct}%` }} />
        )}
      </div>
      {!compact ? (
        <div className="stance-bar-legend">
          <span className="stance-chip stance-chip-support">👍 {supporting}</span>
          <span className="stance-chip stance-chip-oppose">👎 {opposing}</span>
          <span className="stance-chip stance-chip-neutral">— {neutral}</span>
        </div>
      ) : null}
    </div>
  )
}
