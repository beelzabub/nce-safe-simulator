<template>
  <div ref="el" class="log-pane" @scroll.passive="onScroll">
    <div v-if="lines.length === 0" class="log-empty">Waiting for output…</div>
    <pre v-for="(line, i) in lines" :key="i" class="log-line">{{ line }}</pre>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'

const props = defineProps({
  lines: { type: Array, required: true },
})

const el = ref(null)
let pinned = true

function onScroll() {
  const div = el.value
  if (!div) return
  pinned = div.scrollHeight - div.scrollTop - div.clientHeight < 8
}

watch(() => props.lines.length, async () => {
  if (!pinned) return
  await nextTick()
  const div = el.value
  if (div) div.scrollTop = div.scrollHeight
})
</script>

<style scoped>
.log-pane {
  height: 100%;
  overflow-y: auto;
  background: var(--bg, #0d1117);
  padding: 0.75rem 1rem;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 0.8rem;
  color: var(--text-1, #e6edf3);
}
.log-empty {
  color: var(--text-3, #6e7681);
  font-style: italic;
}
.log-line {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.5;
}
</style>
