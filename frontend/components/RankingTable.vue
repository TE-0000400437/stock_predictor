<script setup lang="ts">
import type { StockResult } from '~/composables/useAnalysis'

defineProps<{
  results: StockResult[]
  analysisTime: string
}>()

const medals = ['🥇', '🥈', '🥉']
</script>

<template>
  <div class="rounded-xl bg-zinc-950 border border-zinc-700 overflow-hidden w-full">
    <!-- ヘッダー -->
    <div class="px-5 py-3 border-b border-zinc-800 flex items-center justify-between">
      <span class="text-sm font-semibold text-zinc-300">📊 短期株価予測ランキング</span>
      <span v-if="analysisTime" class="text-xs text-zinc-500">{{ analysisTime }}</span>
    </div>

    <!-- テーブル -->
    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-zinc-800">
            <th class="px-4 py-2.5 text-left text-xs font-semibold text-zinc-500 uppercase tracking-wider w-12">順位</th>
            <th class="px-4 py-2.5 text-left text-xs font-semibold text-zinc-500 uppercase tracking-wider">銘柄</th>
            <th class="px-4 py-2.5 text-left text-xs font-semibold text-zinc-500 uppercase tracking-wider">企業名</th>
            <th class="px-4 py-2.5 text-right text-xs font-semibold text-zinc-500 uppercase tracking-wider">株価</th>
            <th class="px-4 py-2.5 text-center text-xs font-semibold text-zinc-500 uppercase tracking-wider">スコア</th>
            <th class="px-4 py-2.5 text-center text-xs font-semibold text-zinc-500 uppercase tracking-wider">推奨</th>
            <th class="px-4 py-2.5 text-center text-xs font-semibold text-zinc-500 uppercase tracking-wider">テクニカル</th>
            <th class="px-4 py-2.5 text-center text-xs font-semibold text-zinc-500 uppercase tracking-wider">モメンタム</th>
            <th class="px-4 py-2.5 text-center text-xs font-semibold text-zinc-500 uppercase tracking-wider">センチメント</th>
            <th class="px-4 py-2.5 text-center text-xs font-semibold text-zinc-500 uppercase tracking-wider">パターン</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(r, i) in results"
            :key="r.ticker"
            class="border-b border-zinc-800/50 hover:bg-zinc-800/40 transition-colors"
          >
            <td class="px-4 py-3 text-center text-base">
              {{ medals[i] ?? `#${i + 1}` }}
            </td>
            <td class="px-4 py-3">
              <span class="font-mono font-bold text-blue-400">{{ r.ticker }}</span>
            </td>
            <td class="px-4 py-3 text-zinc-400 text-xs max-w-[160px] truncate">{{ r.company_name }}</td>
            <td class="px-4 py-3 text-right font-mono text-zinc-300">
              {{ r.currency === 'JPY' ? '¥' : '$' }}{{ r.currency === 'JPY' ? r.current_price.toLocaleString('ja-JP') : r.current_price.toFixed(2) }}
            </td>
            <td class="px-4 py-3 text-center">
              <ScoreBadge :score="r.final_score" />
            </td>
            <td class="px-4 py-3 text-center">
              <RecBadge :rec="r.recommendation" />
            </td>
            <td class="px-4 py-3 text-center">
              <ScoreBadge size="sm" :score="r.agent_results.find(a => a.key === 'technical')?.score ?? 50" />
            </td>
            <td class="px-4 py-3 text-center">
              <ScoreBadge size="sm" :score="r.agent_results.find(a => a.key === 'momentum')?.score ?? 50" />
            </td>
            <td class="px-4 py-3 text-center">
              <ScoreBadge size="sm" :score="r.agent_results.find(a => a.key === 'sentiment')?.score ?? 50" />
            </td>
            <td class="px-4 py-3 text-center">
              <ScoreBadge size="sm" :score="r.agent_results.find(a => a.key === 'pattern')?.score ?? 50" />
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
