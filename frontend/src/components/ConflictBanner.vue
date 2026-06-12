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
  background: #fef9c3;
  border: 1px solid #ca8a04;
  border-radius: 4px;
  padding: 8px 12px;
  color: #713f12;
  font-size: 0.9rem;
}
code {
  background: #fde68a;
  border-radius: 3px;
  padding: 1px 4px;
  font-size: 0.85em;
}
</style>
