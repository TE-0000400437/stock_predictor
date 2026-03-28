<script setup lang="ts">
defineEmits<{ select: [text: string]; 'update:capital': [value: number | null] }>()
defineProps<{ capital: number | null }>()

const formatCapital = (e: Event) => {
  const el = e.target as HTMLInputElement
  const raw = parseFloat(el.value.replace(/,/g, ''))
  return isNaN(raw) || raw <= 0 ? null : raw
}

const agents = [
  {
    icon: '📊',
    name: 'テクニカル分析',
    weight: 40,
    color: 'blue',
    desc: 'EMA・RSI・MACD・ストキャスティクス・ボリンジャーバンドで短期トレンドを判定',
    tags: ['EMA5/10/20', 'RSI(14)', 'MACD', 'Stochastic', 'BB'],
  },
  {
    icon: '⚡',
    name: 'モメンタム分析',
    weight: 25,
    color: 'amber',
    desc: '価格モメンタム・出来高トレンド・OBV・ATRで勢いと方向性を評価',
    tags: ['Price Momentum', 'Volume Trend', 'OBV', 'ATR'],
  },
  {
    icon: '📰',
    name: 'センチメント分析',
    weight: 20,
    color: 'emerald',
    desc: 'アナリスト評価・目標株価・ニュース・空売り状況で市場心理を把握',
    tags: ['Analyst Rating', '目標株価', 'News', 'Short Interest'],
  },
  {
    icon: '🕯️',
    name: 'パターン分析',
    weight: 15,
    color: 'violet',
    desc: 'ローソク足・サポート/レジスタンス・ブレイクアウトで重要レベルを特定',
    tags: ['Candlestick', 'Support/Resistance', 'Breakout'],
  },
]

const colorMap: Record<string, string> = {
  blue:    'bg-blue-900/40 border-blue-700/50 text-blue-300',
  amber:   'bg-amber-900/40 border-amber-700/50 text-amber-300',
  emerald: 'bg-emerald-900/40 border-emerald-700/50 text-emerald-300',
  violet:  'bg-violet-900/40 border-violet-700/50 text-violet-300',
}
const tagColor: Record<string, string> = {
  blue:    'bg-blue-900/60 text-blue-400',
  amber:   'bg-amber-900/60 text-amber-400',
  emerald: 'bg-emerald-900/60 text-emerald-400',
  violet:  'bg-violet-900/60 text-violet-400',
}

const suggestions = [
  { icon: '🚀', text: 'AI・テクノロジー関連の成長株を教えて' },
  { icon: '💎', text: 'リスクが低めで安定した銘柄を提案して' },
  { icon: '⚡', text: '今注目されている急上昇銘柄は？' },
  { icon: '🌏', text: 'グローバルなトレンドに乗れる銘柄を教えて' },
]
</script>

<template>
  <div class="max-w-3xl mx-auto py-8 px-2 space-y-10">

    <!-- ── タイトル ── -->
    <div class="text-center space-y-2">
      <div class="text-5xl">📈</div>
      <h2 class="text-2xl font-bold text-zinc-100">短期株価予測 AI</h2>
      <p class="text-zinc-400 text-sm">対話形式で投資スタイルに合った銘柄を提案・分析します</p>
    </div>

    <!-- ── エージェント構成 ── -->
    <div class="space-y-4">
      <h3 class="text-xs font-semibold text-zinc-500 uppercase tracking-widest text-center">
        裏側で動く AI エージェント構成
      </h3>

      <!-- 4エージェント -->
      <div class="grid grid-cols-2 gap-3">
        <div
          v-for="agent in agents"
          :key="agent.name"
          :class="['rounded-xl border p-4 space-y-2', colorMap[agent.color]]"
        >
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="text-lg">{{ agent.icon }}</span>
              <span class="font-semibold text-sm">{{ agent.name }}</span>
            </div>
            <span class="text-xs font-bold opacity-80">{{ agent.weight }}%</span>
          </div>
          <p class="text-xs opacity-70 leading-relaxed">{{ agent.desc }}</p>
          <div class="flex flex-wrap gap-1 pt-1">
            <span
              v-for="tag in agent.tags"
              :key="tag"
              :class="['text-xs px-2 py-0.5 rounded-full font-mono', tagColor[agent.color]]"
            >{{ tag }}</span>
          </div>
        </div>
      </div>

      <!-- オーケストレーター -->
      <div class="flex items-center gap-2 justify-center text-zinc-600 text-xs">
        <div class="flex gap-6">
          <span v-for="a in agents" :key="a.name" class="flex flex-col items-center gap-0.5">
            <span>{{ a.icon }}</span>
            <svg class="w-px h-4 text-zinc-700" viewBox="0 0 1 16"><line x1="0" y1="0" x2="0" y2="16" stroke="currentColor"/></svg>
          </span>
        </div>
      </div>
      <div class="relative rounded-xl bg-gradient-to-r from-blue-900/30 via-zinc-800 to-violet-900/30 border border-zinc-700 p-4 text-center">
        <div class="flex items-center justify-center gap-2 mb-1">
          <span class="text-xl">🧠</span>
          <span class="font-bold text-sm text-zinc-100">オーケストレーター</span>
        </div>
        <p class="text-xs text-zinc-400">4エージェントの結果を統合し、信頼度・相関性を考慮して最終スコアと推奨を生成</p>
        <div class="mt-2 flex justify-center gap-2 text-xs text-zinc-500">
          <span class="bg-zinc-800 rounded px-2 py-0.5">総合スコア 0〜100</span>
          <span class="bg-zinc-800 rounded px-2 py-0.5">強い買い / 買い / 中立 / 売り / 強い売り</span>
        </div>
      </div>
    </div>

    <!-- ── 資本金入力 ── -->
    <div class="space-y-3">
      <h3 class="text-xs font-semibold text-zinc-500 uppercase tracking-widest text-center">
        投資資金（任意）
      </h3>
      <div class="max-w-sm mx-auto">
        <div class="flex items-center gap-2 bg-zinc-800 border border-zinc-700 rounded-xl px-4 py-3 focus-within:border-blue-500 transition-colors">
          <span class="text-zinc-400 text-sm shrink-0">¥</span>
          <input
            type="text"
            placeholder="例: 1000000"
            :value="capital ?? ''"
            class="flex-1 bg-transparent text-sm text-zinc-100 placeholder-zinc-600 focus:outline-none"
            @change="$emit('update:capital', formatCapital($event))"
          />
          <span class="text-zinc-500 text-xs shrink-0">円</span>
        </div>
        <p class="text-xs text-zinc-600 text-center mt-1.5">入力すると分析後に分散投資プランを提案します</p>
      </div>
    </div>

    <!-- ── サジェスト ── -->
    <div class="space-y-3">
      <h3 class="text-xs font-semibold text-zinc-500 uppercase tracking-widest text-center">
        話しかけてみる
      </h3>
      <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <button
          v-for="s in suggestions"
          :key="s.text"
          class="flex items-center gap-3 text-left px-4 py-3 rounded-xl bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 hover:border-zinc-500 transition-all text-sm text-zinc-200 group"
          @click="$emit('select', s.text)"
        >
          <span class="text-xl shrink-0">{{ s.icon }}</span>
          <span class="group-hover:text-white transition-colors">{{ s.text }}</span>
        </button>
      </div>
    </div>

  </div>
</template>
