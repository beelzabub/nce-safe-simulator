<template>
  <div ref="el" class="log-pane" @scroll.passive="onScroll">
    <div v-if="lines.length === 0" class="log-empty">Waiting for output…</div>
    <pre v-else class="log-content"><template v-for="(line, i) in lines" :key="i"><template v-for="part in parseLine(line)" :key="part.value"><a v-if="part.type === 'url'" :href="part.value" target="_blank" rel="noopener" class="log-link">{{ part.value }}</a><span v-else-if="part.type === 'hint'" class="log-hint">{{ part.value }}</span><span v-else>{{ part.value }}</span></template>{{ i < lines.length - 1 ? '\n' : '' }}</template></pre>
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

const URL_RE = /https?:\/\/\S+/g

const LINE_HINTS = [
  {
    pattern: /429|Too many requests/i,
    hint: ' — GitLab rate limit; retrying automatically (up to 5×, ~30 s backoff)',
  },
]

function parseLine(line) {
  const parts = []
  let last = 0
  URL_RE.lastIndex = 0
  let m
  while ((m = URL_RE.exec(line)) !== null) {
    if (m.index > last) parts.push({ type: 'text', value: line.slice(last, m.index) })
    parts.push({ type: 'url', value: m[0] })
    last = m.index + m[0].length
  }
  if (last < line.length) parts.push({ type: 'text', value: line.slice(last) })
  if (!parts.length) parts.push({ type: 'text', value: line })

  for (const { pattern, hint } of LINE_HINTS) {
    if (pattern.test(line)) {
      parts.push({ type: 'hint', value: hint })
      break
    }
  }
  return parts
}
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
.log-content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.5;
}
.log-link {
  color: var(--action, #2563eb);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.log-link:hover {
  color: var(--action-hover, #3b82f6);
}
.log-hint {
  color: var(--text-3, #6e7681);
  font-style: italic;
}
</style>
