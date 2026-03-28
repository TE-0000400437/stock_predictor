<script setup lang="ts">
const props = defineProps<{ score: number; size?: 'sm' | 'md' }>()

const cls = computed(() => {
  if (props.score >= 70) return 'bg-emerald-900/60 text-emerald-400 ring-1 ring-emerald-700'
  if (props.score >= 45) return 'bg-amber-900/60 text-amber-400 ring-1 ring-amber-700'
  return 'bg-red-900/60 text-red-400 ring-1 ring-red-700'
})
const sz = computed(() =>
  props.size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-0.5 text-sm'
)
</script>

<template>
  <span :class="['inline-block rounded font-bold tabular-nums', cls, sz]">
    {{ score.toFixed(1) }}
  </span>
</template>
