<template>
  <div v-if="blockers.length" class="conflict-banner" role="alert">
    <span class="conflict-line">
      <strong>Can't launch</strong> —
      <span v-for="(key, i) in blockers" :key="key">
        <code>{{ key }}</code><span v-if="i < blockers.length - 1">, </span>
      </span>
      {{ blockers.length === 1 ? 'is' : 'are' }} already running.
    </span>
    <span class="conflict-reason">
      {{ groupLabel ? `These tools both write to the ${groupLabel} group` : 'These tools share a write group' }}
      and can't run at the same time.
    </span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  blockers: { type: Array, default: () => [] },
  group:    { type: String, default: null },
})

const ACRONYMS = new Set(['roam', 'wsjf', 'bv', 'piid', 'pi'])
const groupLabel = computed(() => {
  if (!props.group) return null
  return props.group.split('-').map(w =>
    ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)
  ).join(' ')
})
</script>

<style scoped>
.conflict-banner {
  background: var(--conflict-bg);
  border: 1px solid var(--conflict-border);
  border-radius: 4px;
  padding: 8px 12px;
  color: var(--conflict-text);
  font-size: 0.82rem;
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}
.conflict-reason {
  font-size: 0.78rem;
  opacity: 0.85;
}
code {
  background: var(--conflict-code-bg);
  border-radius: 3px;
  padding: 1px 4px;
  font-size: 0.85em;
}
</style>
