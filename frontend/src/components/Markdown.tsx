import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useEffect, useState } from 'react'

export function Markdown({ text }: { text: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer" />,
      }}
    >
      {text}
    </ReactMarkdown>
  )
}

/** Reveals markdown progressively (about 1.2s regardless of length), for the final agent reply. */
export function TypedMarkdown({ text, animate = true }: { text: string; animate?: boolean }) {
  const [n, setN] = useState(animate ? 0 : text.length)
  useEffect(() => {
    if (!animate) return
    const step = Math.max(2, Math.ceil(text.length / 60))
    const t = setInterval(() => {
      setN((v) => {
        if (v >= text.length) {
          clearInterval(t)
          return v
        }
        return Math.min(text.length, v + step)
      })
    }, 20)
    return () => clearInterval(t)
  }, [text, animate])
  const done = n >= text.length
  return (
    <div className={`md ${done ? '' : 'caret'}`}>
      <Markdown text={text.slice(0, n)} />
    </div>
  )
}
