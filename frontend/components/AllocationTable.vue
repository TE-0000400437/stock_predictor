<script setup lang="ts">
import type { StockResult } from '~/composables/useAnalysis'
import { ref, computed } from 'vue'

const props = defineProps<{ results: StockResult[]; initialCapital?: number | null }>()

const capital = ref<number | null>(props.initialCapital ?? null)

// スコア >= 50 の銘柄のみ投資対象（中立以上）
const investable = computed(() =>
  [...props.results]
    .filter(r => r.final_score >= 50)
    .sort((a, b) => b.final_score - a.final_score)
)

const excluded = computed(() =>
  props.results.filter(r => r.final_score < 50)
)

// 重み = (score - 45)^1.5  差を増幅してスコア差を配分に反映
const weight = (score: number) => Math.pow(Math.max(0, score - 45), 1.5)

const totalWeight = computed(() =>
  investable.value.reduce((s, r) => s + weight(r.final_score), 0)
)

// 最大1銘柄40%キャップ（分散投資のため）
const rawAlloc = computed(() =>
  investable.value.map(r => ({
    ...r,
    raw: totalWeight.value > 0 ? weight(r.final_score) / totalWeight.value : 0,
  }))
)

const allocations = computed(() => {
  if (!rawAlloc.value.length) return []
  // 40%キャップを適用して再正規化
  let items = rawAlloc.value.map(r => ({ ...r, pct: Math.min(r.raw, 0.40) }))
  const total = items.reduce((s, r) => s + r.pct, 0)
  items = items.map(r => ({ ...r, pct: r.pct / total }))
  return items
})

const formatPrice = (r: StockResult) => {
  const sym = r.currency === 'JPY' ? '¥' : '$'
  return r.currency === 'JPY'
    ? `${sym}${r.current_price.toLocaleString('ja-JP')}`
    : `${sym}${r.current_price.toFixed(2)}`
}

const formatAmount = (pct: number) => {
  if (!capital.value) return null
  const amt = capital.value * pct
  return amt >= 1000000
    ? `${(amt / 10000).toFixed(0)}万円`
    : `${Math.round(amt).toLocaleString('ja-JP')}円`
}

const recColor: Record<string, string> = {
  '強い買い': 'text-emerald-400',
  '買い':     'text-green-400',
  '中立':     'text-amber-400',
  '売り':     'text-red-400',
  '強い売り': 'text-red-500',
}

const barColor = (score: number) => {
  if (score >= 75) return 'bg-emerald-500'
  if (score >= 62) return 'bg-green-500'
  return 'bg-amber-500'
}
</script>

<template>
  <div class="rounded-xl bg-zinc-950 border border-zinc-700 overflow-hidden w-full">
    <!-- ヘッダー -->
    <div class="px-5 py-4 border-b border-zinc-800">
      <span class="text-sm font-semibold text-zinc-300">💼 分散投資プラン</span>
      <p class="text-xs text-zinc-500 mt-0.5">
        スコアに比例した配分 · 1銘柄40%上限
        <span v-if="!capital" class="text-zinc-600"> · 投資資金はホーム画面で入力できます</span>
      </p>
    </div>

    <!-- 投資対象なし -->
    <div v-if="!investable.length" class="px-5 py-6 text-center text-zinc-500 text-sm">
      スコア50以上の銘柄がないため、投資推奨なし（キャッシュ保持を推奨）
    </div>

    <template v-else>
      <!-- 配分テーブル -->
      <div class="overflow-x-auto">
        <table class="w-full text-sm">
          <thead>
            <tr class="border-b border-zinc-800">
              <th class="px-4 py-2.5 text-left text-xs font-semibold text-zinc-500 uppercase tracking-wider">銘柄</th>
              <th class="px-4 py-2.5 text-center text-xs font-semibold text-zinc-500 uppercase tracking-wider">スコア</th>
              <th class="px-4 py-2.5 text-center text-xs font-semibold text-zinc-500 uppercase tracking-wider">推奨</th>
              <th class="px-4 py-2.5 text-left text-xs font-semibold text-zinc-500 uppercase tracking-wider">配分</th>
              <th v-if="capital" class="px-4 py-2.5 text-right text-xs font-semibold text-zinc-500 uppercase tracking-wider">投資額</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in allocations"
              :key="item.ticker"
              class="border-b border-zinc-800/50 hover:bg-zinc-800/30 transition-colors"
            >
              <td class="px-4 py-3">
                <div class="font-mono font-bold text-blue-400">{{ item.ticker }}</div>
                <div class="text-zinc-500 text-xs truncate max-w-[140px]">{{ item.company_name }}</div>
                <div class="text-zinc-600 text-xs">{{ formatPrice(item) }}</div>
              </td>
              <td class="px-4 py-3 text-center">
                <span :class="['text-lg font-black', item.final_score >= 70 ? 'text-emerald-400' : item.final_score >= 55 ? 'text-amber-400' : 'text-zinc-300']">
                  {{ item.final_score.toFixed(0) }}
                </span>
              </td>
              <td class="px-4 py-3 text-center">
                <span :class="['text-xs font-semibold', recColor[item.recommendation] ?? 'text-zinc-400']">
                  {{ item.recommendation }}
                </span>
              </td>
              <td class="px-4 py-3 min-w-[140px]">
                <div class="flex items-center gap-2">
                  <div class="flex-1 bg-zinc-800 rounded-full h-2">
                    <div
                      :class="['h-2 rounded-full transition-all', barColor(item.final_score)]"
                      :style="`width: ${(item.pct * 100).toFixed(1)}%`"
                    />
                  </div>
                  <span class="text-xs text-zinc-300 font-mono w-10 text-right">
                    {{ (item.pct * 100).toFixed(1) }}%
                  </span>
                </div>
              </td>
              <td v-if="capital" class="px-4 py-3 text-right font-mono text-zinc-200 text-sm font-semibold">
                {{ formatAmount(item.pct) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- フッター：除外銘柄 & 合計 -->
      <div class="px-5 py-3 border-t border-zinc-800 space-y-2">
        <!-- 合計 -->
        <div v-if="capital" class="flex justify-between text-xs">
          <span class="text-zinc-500">合計投資額</span>
          <span class="text-zinc-200 font-mono font-semibold">
            {{ capital.toLocaleString('ja-JP') }}円
          </span>
        </div>

        <!-- 除外銘柄 -->
        <div v-if="excluded.length" class="flex flex-wrap items-center gap-2">
          <span class="text-xs text-zinc-600">投資対象外（スコア50未満）:</span>
          <span
            v-for="r in excluded"
            :key="r.ticker"
            class="text-xs text-zinc-600 bg-zinc-800/50 px-2 py-0.5 rounded font-mono"
          >
            {{ r.ticker }} {{ r.final_score.toFixed(0) }}pt
          </span>
        </div>

        <!-- 注意事項 -->
        <p class="text-xs text-zinc-600">
          ※ スコア差を1.5乗で増幅した重み付け配分。1銘柄の上限は40%。投資は自己責任でお願いします。
        </p>
      </div>
    </template>
  </div>
</template>
