import { ref, type Ref } from 'vue'
import type { StockResult, TickerStatus } from './useAnalysis'

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  // 分析データ（AI メッセージに付随）
  analysis?: {
    tickers: string[]
    progress: Record<string, TickerStatus>
    results: StockResult[]
    done: boolean
  }
}

export const useChat = (apiBase: string, model: Ref<string>) => {
  const messages   = ref<ChatMessage[]>([])
  const isLoading  = ref(false)
  const controller = ref<AbortController | null>(null)

  const sendMessage = async (userText: string) => {
    if (isLoading.value || !userText.trim()) return

    // ユーザーメッセージを追加
    messages.value.push({
      id:      crypto.randomUUID(),
      role:    'user',
      content: userText.trim(),
    })

    // AI メッセージのプレースホルダー
    const aiMsg: ChatMessage = {
      id:      crypto.randomUUID(),
      role:    'assistant',
      content: '',
    }
    messages.value.push(aiMsg)
    isLoading.value = true

    try {
      const res = await fetch(`${apiBase}/chat`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: model.value,
          messages: messages.value
            .filter(m => m.id !== aiMsg.id)
            .map(m => ({ role: m.role, content: m.content })),
        }),
      })

      const reader  = res.body!.getReader()
      const decoder = new TextDecoder()
      let   buf     = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw) continue

          let ev: Record<string, unknown>
          try { ev = JSON.parse(raw) } catch { continue }

          // テキストをストリーミング追記
          if (ev.type === 'text') {
            const idx = messages.value.findIndex(m => m.id === aiMsg.id)
            if (idx !== -1) {
              messages.value[idx] = {
                ...messages.value[idx],
                content: messages.value[idx].content + (ev.content as string),
              }
            }
          }

          // 銘柄推薦 → analysis オブジェクトを初期化
          if (ev.type === 'recommend') {
            const tickers = ev.tickers as string[]
            const idx = messages.value.findIndex(m => m.id === aiMsg.id)
            if (idx !== -1) {
              messages.value[idx] = {
                ...messages.value[idx],
                analysis: {
                  tickers,
                  progress: Object.fromEntries(tickers.map(t => [t, 'waiting' as TickerStatus])),
                  results: [],
                  done: false,
                },
              }
            }
          }

          // 分析進捗
          if (ev.type === 'analysis_progress') {
            const ticker = ev.ticker as string
            const idx = messages.value.findIndex(m => m.id === aiMsg.id)
            if (idx !== -1 && messages.value[idx].analysis) {
              messages.value[idx] = {
                ...messages.value[idx],
                analysis: {
                  ...messages.value[idx].analysis!,
                  progress: {
                    ...messages.value[idx].analysis!.progress,
                    [ticker]: 'analyzing',
                  },
                },
              }
            }
          }

          // 分析結果
          if (ev.type === 'analysis_result') {
            const ticker = ev.ticker as string
            const data   = ev.data as StockResult
            const idx = messages.value.findIndex(m => m.id === aiMsg.id)
            if (idx !== -1 && messages.value[idx].analysis) {
              const prev = messages.value[idx].analysis!
              messages.value[idx] = {
                ...messages.value[idx],
                analysis: {
                  ...prev,
                  progress: { ...prev.progress, [ticker]: 'done' },
                  results:  [...prev.results, data],
                },
              }
            }
          }

          // 分析完了
          if (ev.type === 'analysis_done') {
            const idx = messages.value.findIndex(m => m.id === aiMsg.id)
            if (idx !== -1 && messages.value[idx].analysis) {
              messages.value[idx] = {
                ...messages.value[idx],
                analysis: { ...messages.value[idx].analysis!, done: true },
              }
            }
          }

          if (ev.type === 'done') {
            isLoading.value = false
          }
        }
      }
    } catch (e) {
      const idx = messages.value.findIndex(m => m.id === aiMsg.id)
      if (idx !== -1) {
        messages.value[idx] = {
          ...messages.value[idx],
          content: messages.value[idx].content || 'エラーが発生しました。',
        }
      }
    } finally {
      isLoading.value = false
    }
  }

  return { messages, isLoading, sendMessage }
}
