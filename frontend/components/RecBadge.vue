<script setup lang="ts">
const props = defineProps<{ rec: string }>()

const cls = computed(() => {
  if (['強い買い', '買い'].includes(props.rec))   return 'bg-emerald-900/60 text-emerald-400 ring-1 ring-emerald-700'
  if (props.rec === '中立')                        return 'bg-amber-900/60 text-amber-400 ring-1 ring-amber-700'
  return 'bg-red-900/60 text-red-400 ring-1 ring-red-700'
})
</script>

<template>
  <span :class="['inline-block rounded-full px-3 py-0.5 text-xs font-bold', cls]">
    {{ rec }}
  </span>
</template>
