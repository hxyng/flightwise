import { useEffect, useRef, useState } from "react"

/** Smoothly tween a number toward its target. */
function useTween(target: number, ms = 1200) {
  const [v, setV] = useState(target)
  const from = useRef(target)
  const cur = useRef(target)
  useEffect(() => {
    from.current = cur.current
    const start = performance.now()
    let raf = 0
    const step = (t: number) => {
      const k = Math.min(1, (t - start) / ms)
      const e = 1 - Math.pow(1 - k, 3)
      cur.current = from.current + (target - from.current) * e
      setV(cur.current)
      if (k < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  }, [target, ms])
  return v
}

// Quadratic Bezier, a "great-circle-ish" arc
const P0 = { x: 18, y: 78 }
const P1 = { x: 160, y: -18 }
const P2 = { x: 302, y: 78 }

function at(t: number) {
  const u = 1 - t
  return {
    x: u * u * P0.x + 2 * u * t * P1.x + t * t * P2.x,
    y: u * u * P0.y + 2 * u * t * P1.y + t * t * P2.y,
  }
}
function tangentDeg(t: number) {
  const dx = 2 * (1 - t) * (P1.x - P0.x) + 2 * t * (P2.x - P1.x)
  const dy = 2 * (1 - t) * (P1.y - P0.y) + 2 * t * (P2.y - P1.y)
  return (Math.atan2(dy, dx) * 180) / Math.PI
}

export function RouteArc({ progress, origin, destination, tone = '#30d158' }: { progress: number; origin: string; destination: string; tone?: string }) {
  const p = useTween(Math.max(0, Math.min(1, progress)))
  const pos = at(p)
  const ang = tangentDeg(p)
  const d = `M ${P0.x} ${P0.y} Q ${P1.x} ${P1.y} ${P2.x} ${P2.y}`
  return (
    <svg viewBox="0 0 320 96" className="w-full h-auto overflow-visible" role="img" aria-label={`${origin} to ${destination}, ${Math.round(progress * 100)}% complete`}>
      <path d={d} fill="none" stroke="rgba(255,255,255,0.22)" strokeWidth="1.5" strokeDasharray="3 5" />
      <path d={d} fill="none" stroke={tone} strokeWidth="2.5" pathLength={1} strokeDasharray={`${p} 1`} strokeLinecap="round" />
      <circle cx={P0.x} cy={P0.y} r="4.5" fill="#272729" stroke={tone} strokeWidth="2" />
      <circle cx={P2.x} cy={P2.y} r="4.5" fill={p >= 1 ? tone : '#272729'} stroke={tone} strokeWidth="2" />
      <g transform={`translate(${pos.x} ${pos.y}) rotate(${ang})`}>
        {/* plane silhouette pointing +x */}
        <path d="M 9 0 L 2 -1.6 L -2 -8 L -4.5 -8 L -2.2 -1.6 L -7 -1.4 L -9 -4 L -10.5 -4 L -9.2 0 L -10.5 4 L -9 4 L -7 1.4 L -2.2 1.6 L -4.5 8 L -2 8 L 2 1.6 Z" fill="#fff" />
      </g>
    </svg>
  )
}
