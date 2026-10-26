import { useEffect, useRef, useState } from 'react'

const SIZES = {
  sm: 'h-6 min-w-[1.05rem] text-[0.8rem] px-[2px]',
  md: 'h-8 min-w-[1.35rem] text-base px-[3px]',
  lg: 'h-11 min-w-[1.8rem] text-2xl px-1',
} as const

/**
 * Departure-board text. Each character sits on its own tile; when the value changes,
 * the changed tiles flip in with a staggered delay.
 */
export function SplitFlap({
  value,
  size = 'md',
  pad = 0,
  className = '',
  tone = 'text-flap',
}: {
  value: string
  size?: keyof typeof SIZES
  pad?: number
  className?: string
  tone?: string
}) {
  const text = value.toUpperCase().padEnd(pad, ' ')
  // First render is static so tiles are never caught blank mid-flip; only later changes flip.
  const prev = useRef<string>(text)
  const [gen, setGen] = useState(0)
  const [changed, setChanged] = useState<boolean[]>(() => Array.from(text, () => false))

  useEffect(() => {
    if (prev.current === text) return
    const old = prev.current
    prev.current = text
    setChanged(Array.from(text, (c, i) => old[i] !== c))
    setGen((g) => g + 1)
  }, [text])

  return (
    <span className={`inline-flex gap-[2px] ${className}`} aria-label={value}>
      {Array.from(text).map((c, i) => (
        <span
          key={`${i}-${changed[i] ? gen : 0}`}
          className={`flap ${SIZES[size]} ${tone} ${changed[i] ? 'flipping' : ''}`}
          style={{ animationDelay: `${i * 45}ms` }}
          aria-hidden
        >
          <span style={{ animationDelay: `${i * 45}ms` }}>{c === ' ' ? ' ' : c}</span>
        </span>
      ))}
    </span>
  )
}
