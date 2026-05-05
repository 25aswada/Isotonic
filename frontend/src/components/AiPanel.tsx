import { useEffect, useRef, useState } from 'react'
import { Bot, Send, X, Trash2, Loader2 } from 'lucide-react'

interface Message {
  role: 'user' | 'assistant'
  content: string
}

const SYSTEM_PROMPT = `You are Isotonic AI, a sharp sports betting analyst assistant built into the Isotonic prediction platform.
You have expertise in NBA and NCAA basketball analytics, betting markets, player props, injury impacts, and prediction modeling.
Be concise, data-driven, and direct. When discussing probabilities or odds, always provide context.
The platform uses XGBoost with Elo ratings, rolling team stats, and live injury adjustments from the official NBA report.`

interface Props {
  open: boolean
  onClose: () => void
  context?: string
}

export function AiPanel({ open, onClose, context }: Props) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function send() {
    const text = input.trim()
    if (!text || streaming) return

    setInput('')
    setError(null)

    const userMsg: Message = { role: 'user', content: text }
    const nextMessages = [...messages, userMsg]
    setMessages(nextMessages)
    setStreaming(true)

    const systemMessages: Message[] = [
      { role: 'user', content: SYSTEM_PROMPT },
      { role: 'assistant', content: "Understood. I'm Isotonic AI, ready to help with sports analytics and betting insights." },
    ]
    const contextMessages: Message[] = context
      ? [{ role: 'user', content: `Current context: ${context}` }, { role: 'assistant', content: 'Got it, I have that context.' }]
      : []
    const payload = [...systemMessages, ...contextMessages, ...nextMessages]

    abortRef.current = new AbortController()

    try {
      const res = await fetch('http://localhost:11434/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: abortRef.current.signal,
        body: JSON.stringify({ model: 'qwen2.5:32b', messages: payload, stream: true }),
      })

      if (!res.ok) throw new Error(`Ollama error ${res.status}`)
      if (!res.body) throw new Error('No response body')

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let assistantContent = ''

      setMessages(prev => [...prev, { role: 'assistant', content: '' }])

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = decoder.decode(value, { stream: true })
        for (const line of chunk.split('\n')) {
          if (!line.trim()) continue
          try {
            const json = JSON.parse(line)
            assistantContent += json.message?.content ?? ''
            setMessages(prev => {
              const updated = [...prev]
              updated[updated.length - 1] = { role: 'assistant', content: assistantContent }
              return updated
            })
          } catch { /* partial line */ }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return
      const msg = err instanceof Error ? err.message : 'Unknown error'
      setError(`Could not reach Ollama: ${msg}. Make sure Ollama is running on localhost:11434.`)
      setMessages(prev => prev.slice(0, -0).filter((_, i) => i !== prev.length - 1 || prev[prev.length - 1].content !== ''))
    } finally {
      setStreaming(false)
      abortRef.current = null
    }
  }

  function stop() {
    abortRef.current?.abort()
    setStreaming(false)
  }

  function clear() {
    if (streaming) stop()
    setMessages([])
    setError(null)
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  return (
    <div className={`ai-panel ${open ? 'is-open' : ''}`} aria-label="AI Assistant">
      <div className="ai-panel__header">
        <div className="ai-panel__title">
          <Bot size={15} />
          <span>Isotonic AI</span>
          <span className="ai-panel__model">qwen2.5:32b</span>
        </div>
        <div className="ai-panel__header-actions">
          {messages.length > 0 && (
            <button className="ai-panel__icon-btn" onClick={clear} aria-label="Clear chat">
              <Trash2 size={14} />
            </button>
          )}
          <button className="ai-panel__icon-btn" onClick={onClose} aria-label="Close AI panel">
            <X size={15} />
          </button>
        </div>
      </div>

      <div className="ai-panel__messages">
        {messages.length === 0 && (
          <div className="ai-panel__empty">
            <Bot size={28} />
            <p>Ask anything about today's games, model predictions, odds, or injuries.</p>
          </div>
        )}
        {messages.map((msg, i) => (
          <div key={i} className={`ai-panel__msg ai-panel__msg--${msg.role}`}>
            {msg.role === 'assistant' && (
              <span className="ai-panel__msg-label">
                <Bot size={11} /> AI
              </span>
            )}
            <div className="ai-panel__msg-content">
              {msg.content
                ? msg.content
                : streaming && i === messages.length - 1
                ? <Loader2 size={14} className="ai-spin" />
                : null}
            </div>
          </div>
        ))}
        {error && <div className="ai-panel__error">{error}</div>}
        <div ref={bottomRef} />
      </div>

      <div className="ai-panel__input-row">
        <textarea
          ref={inputRef}
          className="ai-panel__input"
          rows={1}
          placeholder="Ask about picks, odds, injuries… (Enter to send)"
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={streaming}
        />
        <button
          className="ai-panel__send"
          onClick={streaming ? stop : send}
          aria-label={streaming ? 'Stop' : 'Send'}
          disabled={!streaming && !input.trim()}
        >
          {streaming ? <Loader2 size={15} className="ai-spin" /> : <Send size={15} />}
        </button>
      </div>
    </div>
  )
}
