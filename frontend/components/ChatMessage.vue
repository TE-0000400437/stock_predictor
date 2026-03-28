<script setup lang="ts">
import type { ChatMessage } from '~/composables/useChat'

defineProps<{ message: ChatMessage; capital?: number | null }>()

// JSON ブロックを除いた表示テキスト
const displayText = (content: string) =>
  content.replace(/\{"tickers":\s*\[[^\]]*\]\}/g, '').trim()
</script>

<template>
  <div
    :class="[
      'flex gap-3',
      message.role === 'user' ? 'justify-end' : 'justify-start',
    ]"
  >
    <!-- AI アイコン -->
    <div
      v-if="message.role === 'assistant'"
      class="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-sm shrink-0 mt-0.5"
    >
      📈
    </div>

    <!-- バブル -->
    <div
      :class="[
        'max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed',
        message.role === 'user'
          ? 'bg-blue-600 text-white rounded-br-sm'
          : 'bg-zinc-800 text-zinc-100 rounded-bl-sm',
      ]"
    >
      <!-- テキスト -->
      <p class="whitespace-pre-wrap">{{ displayText(message.content) }}</p>

      <!-- 分析セクション -->
      <template v-if="message.analysis">
        <!-- 進捗ピル -->
        <div class="mt-3 pt-3 border-t border-zinc-700/50 space-y-2">
          <p class="text-xs text-zinc-400 font-semibold">📊 分析中の銘柄</p>
          <div class="flex flex-wrap gap-1.5">
            <TickerPill
              v-for="ticker in message.analysis.tickers"
              :key="ticker"
              :ticker="ticker"
              :status="message.analysis.progress[ticker] ?? 'waiting'"
              :score="message.analysis.results.find(r => r.ticker === ticker)?.final_score"
            />
          </div>
        </div>

        <!-- 分析結果テーブル -->
        <div v-if="message.analysis.results.length" class="mt-4">
          <RankingTable
            :results="[...message.analysis.results].sort((a, b) => b.final_score - a.final_score)"
            :analysis-time="message.analysis.done ? new Date().toLocaleString('ja-JP') : ''"
          />
        </div>

        <!-- 分散投資プラン（完了後） -->
        <div v-if="message.analysis.done && message.analysis.results.length" class="mt-4">
          <AllocationTable
            :results="[...message.analysis.results].sort((a, b) => b.final_score - a.final_score)"
            :initial-capital="capital ?? null"
          />
        </div>

        <!-- 詳細カード（完了後） -->
        <template v-if="message.analysis.done && message.analysis.results.length">
          <div class="mt-4 space-y-3">
            <p class="text-xs text-zinc-400 font-semibold">🏆 銘柄詳細 <span class="text-zinc-600 font-normal">（各エージェントをクリックで分析を展開）</span></p>
            <StockDetail
              v-for="(result, i) in [...message.analysis.results]
                .sort((a, b) => b.final_score - a.final_score)"
              :key="result.ticker"
              :result="result"
              :rank="i"
            />
          </div>
        </template>
      </template>

      <!-- ローディングドット -->
      <span v-if="message.role === 'assistant' && !message.content" class="flex gap-1 py-1">
        <span v-for="i in 3" :key="i"
          class="w-2 h-2 bg-zinc-500 rounded-full animate-bounce"
          :style="`animation-delay: ${(i - 1) * 0.15}s`"
        />
      </span>
    </div>

    <!-- ユーザーアイコン -->
    <div
      v-if="message.role === 'user'"
      class="w-8 h-8 rounded-full bg-zinc-700 flex items-center justify-center text-sm shrink-0 mt-0.5"
    >
      👤
    </div>
  </div>
</template>
