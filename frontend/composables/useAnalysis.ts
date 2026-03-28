import { ref, computed } from 'vue'

export interface AgentResult {
  name: string
  key: string
  score: number
  confidence: string
  reasoning: string
  signals: string[]
}

export interface StockResult {
  ticker: string
  company_name: string
  current_price: number
  currency: string
  sector: string
  final_score: number
  recommendation: string
  summary: string
  error: string | null
  agent_results: AgentResult[]
}

export type TickerStatus = 'waiting' | 'analyzing' | 'done' | 'error'

export const useAnalysis = () => {
  const results       = ref<StockResult[]>([])
  const tickerStatus  = ref<Record<string, TickerStatus>>({})
  const isAnalyzing   = ref(false)
  const analysisTime  = ref<string>('')

  const sortedResults = computed(() =>
    [...results.value].sort((a, b) => b.final_score - a.final_score)
  )

  const analyze = (tickers: string, model: string, apiBase: string) => {
    const tickerList = tickers
      .split(',').map(t => t.trim().toUpperCase()).filter(Boolean)

    if (!tickerList.length) return

    results.value      = []
    isAnalyzing.value  = true
    analysisTime.value = ''
    tickerStatus.value = Object.fromEntries(tickerList.map(t => [t, 'waiting' as TickerStatus]))

    const url = `${apiBase}/analyze?tickers=${encodeURIComponent(tickers)}&model=${encodeURIComponent(model)}`
    const es  = new EventSource(url)

    es.onmessage = (event) => {
      const data = JSON.parse(event.data)

      if (data.type === 'progress' && data.status === 'analyzing') {
        tickerStatus.value = { ...tickerStatus.value, [data.ticker]: 'analyzing' }
      }

      if (data.type === 'result') {
        const r = data.data as StockResult
        tickerStatus.value = {
          ...tickerStatus.value,
          [r.ticker]: r.error ? 'error' : 'done',
        }
        if (!r.error) {
          results.value = [...results.value, r]
        }
      }

      if (data.type === 'done') {
        es.close()
        isAnalyzing.value  = false
        analysisTime.value = new Date().toLocaleString('ja-JP')
      }
    }

    es.onerror = () => {
      es.close()
      isAnalyzing.value = false
    }
  }

  return { results, sortedResults, tickerStatus, isAnalyzing, analysisTime, analyze }
}
