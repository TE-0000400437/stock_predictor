<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { useRuntimeConfig } from '#app'
import { useChat } from '~/composables/useChat'

const config  = useRuntimeConfig()
const apiBase = config.public.apiBase as string

const model   = ref('claude-sonnet-4-6')
const input   = ref('')
const chatEl  = ref<HTMLElement | null>(null)
const view    = ref<'home' | 'chat'>('home')
const capital = ref<number | null>(null)

const { messages, isLoading, sendMessage } = useChat(apiBase, model)

const send = async (text?: string) => {
  const msg = text ?? input.value
  if (!msg.trim() || isLoading.value) return
  input.value = ''
  view.value = 'chat'
  await sendMessage(msg)
}

const autoResize = (e: Event) => {
  const el = e.target as HTMLTextAreaElement
  el.style.height = 'auto'
  el.style.height = el.scrollHeight + 'px'
}

// 送信後に最下部へスクロール
watch(messages, async () => {
  await nextTick()
  chatEl.value?.scrollTo({ top: chatEl.value.scrollHeight, behavior: 'smooth' })
}, { deep: true })
</script>

<template>
  <div class="h-screen flex flex-col bg-zinc-950 text-zinc-100">

    <!-- ── ヘッダー ── -->
    <header class="shrink-0 bg-zinc-900/95 backdrop-blur border-b border-zinc-800 px-5 py-3 flex items-center justify-between">
      <div class="flex items-center gap-2.5">
        <button
          v-if="view === 'chat'"
          class="mr-1 p-1.5 rounded-lg text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800 transition-colors text-xs flex items-center gap-1"
          @click="view = 'home'"
        >
          ← ホーム
        </button>
        <span class="text-xl">📈</span>
        <div>
          <h1 class="text-sm font-bold leading-tight">短期株価予測 AI</h1>
          <p class="text-zinc-500 text-xs">対話形式で1〜2週間後の有望銘柄を分析</p>
        </div>
      </div>

      <!-- モデル選択 -->
      <select
        v-model="model"
        class="bg-zinc-800 border border-zinc-700 rounded-lg px-2.5 py-1.5 text-xs text-zinc-300 focus:outline-none focus:border-blue-500"
      >
        <option value="claude-haiku-4-5-20251001">⚡ Haiku</option>
        <option value="claude-sonnet-4-6">✨ Sonnet</option>
        <option value="claude-opus-4-6">🎯 Opus</option>
      </select>
    </header>

    <!-- ── メッセージエリア ── -->
    <main
      ref="chatEl"
      class="flex-1 overflow-y-auto px-4 py-6"
    >
      <!-- ウェルカム画面 -->
      <SuggestChips v-if="view === 'home'" :capital="capital" @select="send" @update:capital="capital = $event" />

      <!-- チャット -->
      <div v-else class="max-w-3xl mx-auto space-y-5 pb-4">
        <ChatMessage
          v-for="msg in messages"
          :key="msg.id"
          :message="msg"
          :capital="capital"
        />

        <!-- タイピングインジケーター -->
        <div v-if="isLoading && messages[messages.length - 1]?.role !== 'assistant'" class="flex gap-3">
          <div class="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center text-sm shrink-0">📈</div>
          <div class="bg-zinc-800 rounded-2xl rounded-bl-sm px-4 py-3 flex gap-1 items-center">
            <span v-for="i in 3" :key="i"
              class="w-2 h-2 bg-zinc-500 rounded-full animate-bounce"
              :style="`animation-delay: ${(i-1)*0.15}s`"
            />
          </div>
        </div>
      </div>
    </main>

    <!-- ── 入力バー ── -->
    <footer class="shrink-0 bg-zinc-900/95 backdrop-blur border-t border-zinc-800 px-4 py-3">
      <div class="max-w-3xl mx-auto">
        <div class="flex items-end gap-2 bg-zinc-800 border border-zinc-700 rounded-2xl px-4 py-2.5 focus-within:border-blue-500 transition-colors">
          <textarea
            v-model="input"
            rows="1"
            placeholder="投資スタイルや興味のある分野を教えてください..."
            class="flex-1 bg-transparent resize-none text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none max-h-32"
            :disabled="isLoading"
            @keydown.meta.enter.prevent="send()"
            @input="autoResize"
          />
          <button
            :disabled="isLoading || !input.trim()"
            class="shrink-0 w-8 h-8 rounded-xl flex items-center justify-center transition-all"
            :class="isLoading || !input.trim()
              ? 'bg-zinc-700 text-zinc-500 cursor-not-allowed'
              : 'bg-blue-600 hover:bg-blue-500 text-white active:scale-95'"
            @click="send()"
          >
            <svg v-if="!isLoading" xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 12h14M12 5l7 7-7 7" />
            </svg>
            <span v-else class="w-4 h-4 border-2 border-zinc-400 border-t-transparent rounded-full animate-spin" />
          </button>
        </div>
        <p class="text-center text-xs text-zinc-600 mt-2">
          この分析は情報提供のみです。投資は自己責任でお願いします。
        </p>
      </div>
    </footer>

  </div>
</template>
