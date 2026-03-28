<script setup lang="ts">
import type { TickerStatus } from '~/composables/useAnalysis'

defineProps<{
  ticker: string
  status: TickerStatus
  score?: number
}>()
</script>

<template>
  <div
    :class="[
      'flex items-center gap-2 px-3 py-1.5 rounded-full text-sm border transition-colors duration-300',
      status === 'waiting'   && 'bg-zinc-800 border-zinc-700 text-zinc-400',
      status === 'analyzing' && 'bg-blue-950 border-blue-600 text-blue-300',
      status === 'done'      && 'bg-emerald-950 border-emerald-700 text-emerald-300',
      status === 'error'     && 'bg-red-950 border-red-700 text-red-400',
    ]"
  >
    <!-- アイコン -->
    <span v-if="status === 'analyzing'" class="flex h-3 w-3 relative">
      <span class="animate-ping absolute h-full w-full rounded-full bg-blue-400 opacity-75" />
      <span class="relative rounded-full h-3 w-3 bg-blue-500" />
    </span>
    <span v-else-if="status === 'done'"  class="text-emerald-400">✓</span>
    <span v-else-if="status === 'error'" class="text-red-400">✗</span>
    <span v-else class="h-3 w-3 rounded-full bg-zinc-600" />

    <span class="font-mono font-bold">{{ ticker }}</span>

    <span v-if="status === 'analyzing'" class="text-xs text-blue-400">分析中</span>
    <span v-else-if="status === 'done' && score !== undefined" class="text-xs font-bold">
      {{ score.toFixed(0) }}点
    </span>
    <span v-else-if="status === 'waiting'" class="text-xs">待機中</span>
    <span v-else-if="status === 'error'"   class="text-xs">エラー</span>
  </div>
</template>
