<template>
  <div v-if="blockers.length" class="conflict-banner" role="alert">
    <strong>Conflict</strong> — blocked by:
    <span v-for="(key, i) in blockers" :key="key">
      <code>{{ key }}</code><span v-if="i < blockers.length - 1">, </span>
    </span>
  </div>
</template>

<script setup>
defineProps({
  blockers: { type: Array, default: () => [] },
})
</script>

<style scoped>
.conflict-banner {
  background: var(--conflict-bg);
  border: 1px solid var(--conflict-border);
  border-radius: 4px;
  padding: 6px 10px;
  color: var(--conflict-text);
  font-size: 0.82rem;
  margin-bottom: 0.4rem;
}
code {
  background: var(--conflict-code-bg);
  border-radius: 3px;
  padding: 1px 4px;
  font-size: 0.8em;
}
</style>
