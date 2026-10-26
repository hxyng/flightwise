import { AnimatePresence, motion } from 'framer-motion'
import { Activity, X } from 'lucide-react'
import type { WatchEvent } from '../types'
import { EVENT_ICON, EVENT_TONE } from './Watchlist'

export interface Toast {
  id: number
  event: WatchEvent
}

const LABEL: Record<string, string> = {
  status_change: 'Status update',
  delay_change: 'Delay update',
  gate_change: 'Gate change',
  added: 'Now watching',
  removed: 'Removed',
}

export function Toasts({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  return (
    <div className="pointer-events-none fixed inset-x-3 top-3 z-50 flex flex-col items-end gap-2 sm:inset-x-auto sm:top-auto sm:bottom-4 sm:right-4 sm:w-96">
      <AnimatePresence>
        {toasts.map(({ id, event }) => {
          const Icon = EVENT_ICON[event.type] ?? Activity
          return (
            <motion.div
              key={id}
              layout
              initial={{ opacity: 0, x: 60, scale: 0.9 }}
              animate={{ opacity: 1, x: 0, scale: 1 }}
              exit={{ opacity: 0, x: 60, scale: 0.9 }}
              transition={{ type: 'spring', stiffness: 320, damping: 26 }}
              className="pointer-events-auto glass relative w-full overflow-hidden rounded-xl border-l-4 border-l-flap p-3 pr-9 shadow-2xl"
            >
              <div className="flex items-start gap-3">
                <div className="grid size-9 shrink-0 place-items-center rounded-lg bg-ink-600">
                  <Icon className={`size-5 ${EVENT_TONE[event.type]}`} />
                </div>
                <div className="min-w-0">
                  <div className="text-[0.65rem] font-bold uppercase tracking-[0.2em] text-flap">
                    {LABEL[event.type] ?? event.type} · <span className="font-mono">{event.flight_number}</span>
                  </div>
                  <div className="text-base font-semibold text-white">{event.message}</div>
                </div>
              </div>
              <button onClick={() => onDismiss(id)} className="absolute right-2 top-2 rounded p-1 text-slate-500 hover:text-white" aria-label="Dismiss">
                <X className="size-4" />
              </button>
              <motion.div className="absolute bottom-0 left-0 h-0.5 bg-flap/70" initial={{ width: '100%' }} animate={{ width: 0 }} transition={{ duration: 6, ease: 'linear' }} />
            </motion.div>
          )
        })}
      </AnimatePresence>
    </div>
  )
}
