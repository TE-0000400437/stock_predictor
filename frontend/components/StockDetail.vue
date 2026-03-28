<script setup lang="ts">
import type { StockResult } from '~/composables/useAnalysis'
import { ref } from 'vue'

defineProps<{ result: StockResult; rank: number }>()

const medals = ['🥇', '🥈', '🥉']
const agentIcons: Record<string, string> = {
  technical:  '📊',
  momentum:   '⚡',
  sentiment:  '📰',
  pattern:    '🕯️',
}
const agentColors: Record<string, string> = {
  technical:  'border-blue-700/50 bg-blue-900/20',
  momentum:   'border-amber-700/50 bg-amber-900/20',
  sentiment:  'border-emerald-700/50 bg-emerald-900/20',
  pattern:    'border-violet-700/50 bg-violet-900/20',
}
const agentTextColors: Record<string, string> = {
  technical:  'text-blue-400',
  momentum:   'text-amber-400',
  sentiment:  'text-emerald-400',
  pattern:    'text-violet-400',
}

const scoreColor = (s: number) => {
  if (s >= 70) return 'text-emerald-400'
  if (s >= 45) return 'text-amber-400'
  return 'text-red-400'
}

const scoreBg = (s: number) => {
  if (s >= 70) return 'bg-emerald-900/30 border-emerald-700/40'
  if (s >= 45) return 'bg-amber-900/30 border-amber-700/40'
  return 'bg-red-900/30 border-red-700/40'
}

const expanded = ref<Record<string, boolean>>({})
const toggle = (key: string) => { expanded.value[key] = !expanded.value[key] }
</script>

<template>
  <div class="rounded-xl bg-zinc-900 border border-zinc-800 overflow-hidden">
    <!-- ヘッダー -->
    <div class="px-5 py-4 border-b border-zinc-800 flex items-center justify-between flex-wrap gap-3">
      <div class="flex items-center gap-3">
        <span class="text-xl">{{ medals[rank] ?? `#${rank + 1}` }}</span>
        <span class="font-mono font-bold text-blue-400 text-lg">{{ result.ticker }}</span>
        <span class="text-zinc-300 text-sm font-medium">{{ result.company_name }}</span>
        <span class="text-zinc-500 text-xs bg-zinc-800 px-2 py-0.5 rounded">{{ result.sector }}</span>
      </div>
      <div class="flex items-center gap-3">
        <span :class="['text-3xl font-black', scoreColor(result.final_score)]">
          {{ result.final_score.toFixed(1) }}
        </span>
        <RecBadge :rec="result.recommendation" />
        <span class="font-mono text-zinc-400 text-sm">
          {{ result.currency === 'JPY' ? '¥' : '$' }}{{ result.currency === 'JPY' ? result.current_price.toLocaleString('ja-JP') : result.current_price.toFixed(2) }}
        </span>
      </div>
    </div>

    <div class="p-5 space-y-5">
      <!-- オーケストレーターサマリー -->
      <div v-if="result.summary" class="bg-zinc-800/50 rounded-lg p-4 border border-zinc-700/50">
        <p class="text-xs text-zinc-500 font-semibold uppercase tracking-wide mb-2">🧠 総合判断</p>
        <p class="text-zinc-200 text-sm leading-relaxed">{{ result.summary }}</p>
      </div>

      <!-- エージェント詳細 -->
      <div class="space-y-3">
        <p class="text-xs text-zinc-500 font-semibold uppercase tracking-wide">エージェント別分析</p>

        <div
          v-for="agent in result.agent_results"
          :key="agent.key"
          :class="['rounded-lg border overflow-hidden', agentColors[agent.key] ?? 'border-zinc-700/50 bg-zinc-800/30']"
        >
          <!-- エージェントヘッダー（クリックで展開） -->
          <button
            class="w-full px-4 py-3 flex items-center justify-between gap-3 hover:bg-white/5 transition-colors"
            @click="toggle(agent.key)"
          >
            <div class="flex items-center gap-2.5">
              <span>{{ agentIcons[agent.key] ?? '🤖' }}</span>
              <span :class="['text-sm font-semibold', agentTextColors[agent.key] ?? 'text-zinc-300']">
                {{ agent.name }}
              </span>
              <span class="text-xs text-zinc-500">信頼度: {{ agent.confidence }}</span>
            </div>
            <div class="flex items-center gap-3">
              <div :class="['px-2.5 py-1 rounded-lg border text-sm font-black', scoreBg(agent.score), scoreColor(agent.score)]">
                {{ agent.score.toFixed(0) }}<span class="text-xs font-normal opacity-60">/100</span>
              </div>
              <span class="text-zinc-500 text-xs">{{ expanded[agent.key] ? '▲' : '▼' }}</span>
            </div>
          </button>

          <!-- 展開コンテンツ -->
          <div v-if="expanded[agent.key]" class="px-4 pb-4 space-y-3 border-t border-white/5">
            <!-- 詳細分析 -->
            <div class="pt-3">
              <p class="text-xs text-zinc-500 font-semibold mb-1.5">分析詳細</p>
              <p class="text-zinc-300 text-sm leading-relaxed">{{ agent.reasoning }}</p>
            </div>

            <!-- シグナル -->
            <div v-if="agent.signals.length">
              <p class="text-xs text-zinc-500 font-semibold mb-1.5">主要シグナル</p>
              <ul class="space-y-1.5">
                <li
                  v-for="(sig, si) in agent.signals"
                  :key="si"
                  class="flex gap-2 text-sm leading-snug"
                >
                  <span :class="['shrink-0 mt-0.5', agentTextColors[agent.key] ?? 'text-blue-400']">▸</span>
                  <span class="text-zinc-300">{{ sig }}</span>
                </li>
              </ul>
            </div>
          </div>

          <!-- 折りたたみ時はシグナルのみ表示 -->
          <div v-else class="px-4 pb-3 flex flex-wrap gap-1.5">
            <span
              v-for="(sig, si) in agent.signals.slice(0, 2)"
              :key="si"
              class="text-xs text-zinc-400 bg-zinc-800/60 rounded px-2 py-1"
            >
              {{ sig }}
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
