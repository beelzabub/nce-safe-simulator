<!-- In-app markdown report viewer (issue #167). Renders the server-side
     HTML fragment for a wiki page (same python-markdown renderer as the
     standalone /api/runs/.../wiki/{slug} route) styled with the app theme.
     The fragment is same-origin server-generated report output — the server
     is the trust boundary, exactly as with the standalone HTML view. -->
<template>
  <div class="md-view">
    <div class="md-header">
      <span class="md-title">{{ title }}</span>
      <span class="md-run">{{ runLabel }}</span>
      <a v-if="page" class="md-ext" :href="`/api/runs/${page.date}/${page.time}/wiki/${page.slug}`"
         target="_blank" rel="noopener" title="Open standalone page">↗</a>
    </div>

    <div v-if="state === 'loading'" class="md-empty">Loading…</div>
    <div v-else-if="state === 'error'" class="md-empty">
      Couldn't load this page — the snapshot may have been cleared.
    </div>
    <div v-else class="md-body" v-html="html" />
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useMainView } from '../composables/useMainView.js'

const { reportPage } = useMainView()

const page  = computed(() => reportPage.value)
const html  = ref('')
const title = ref('')
const state = ref('loading')

const runLabel = computed(() => {
  if (!page.value) return ''
  const { date: d, time: t } = page.value
  return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)} ${t.slice(0, 2)}:${t.slice(2, 4)}`
})

watch(page, async (p) => {
  if (!p) return
  state.value = 'loading'
  title.value = p.title || ''
  html.value  = ''
  try {
    const r = await fetch(`/api/runs/${p.date}/${p.time}/wiki/${p.slug}.json`)
    if (!r.ok) throw new Error(String(r.status))
    const body = await r.json()
    title.value = body.title
    html.value  = body.html
    state.value = 'ready'
  } catch {
    state.value = 'error'
  }
}, { immediate: true })
</script>

<style scoped>
.md-view {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.md-header {
  flex-shrink: 0;
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
  padding: 0.65rem 1.25rem;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.md-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.md-run {
  font-size: 0.75rem;
  color: var(--text-3);
  flex-shrink: 0;
}
.md-ext {
  margin-left: auto;
  color: var(--text-3);
  text-decoration: none;
  font-size: 0.9rem;
}
.md-ext:hover { color: var(--text-1); }

.md-empty {
  padding: 2.5rem 1.5rem;
  text-align: center;
  color: var(--text-3);
  font-size: 0.85rem;
}

/* ── Rendered markdown ── */
.md-body {
  flex: 1;
  overflow-y: auto;
  padding: 1.25rem 1.5rem 3rem;
  font-size: 0.88rem;
  line-height: 1.6;
  color: var(--text-2);
}
.md-body :deep(h1),
.md-body :deep(h2),
.md-body :deep(h3),
.md-body :deep(h4) {
  color: var(--text-1);
  line-height: 1.25;
  margin: 1.4em 0 0.5em;
}
.md-body :deep(h1) { font-size: 1.35rem; margin-top: 0.2em; }
.md-body :deep(h2) { font-size: 1.1rem; border-bottom: 1px solid var(--border); padding-bottom: 0.25em; }
.md-body :deep(h3) { font-size: 0.95rem; }
.md-body :deep(a)  { color: var(--action); text-decoration: none; }
.md-body :deep(a:hover) { text-decoration: underline; }
.md-body :deep(code) {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.82em;
  background: var(--surface-code);
  color: var(--text-code);
  border-radius: 3px;
  padding: 0.1em 0.35em;
}
.md-body :deep(pre) {
  background: var(--surface-code);
  border-radius: 6px;
  padding: 0.75rem 1rem;
  overflow-x: auto;
}
.md-body :deep(pre code) { background: none; padding: 0; }
.md-body :deep(table) {
  border-collapse: collapse;
  margin: 0.75rem 0;
  display: block;
  overflow-x: auto;      /* wide report tables scroll inside themselves */
  max-width: 100%;
  font-variant-numeric: tabular-nums;
}
.md-body :deep(th),
.md-body :deep(td) {
  border: 1px solid var(--border);
  padding: 0.35rem 0.65rem;
  text-align: left;
  white-space: nowrap;
}
.md-body :deep(th) {
  background: var(--surface-alt);
  color: var(--text-1);
  font-weight: 600;
}
.md-body :deep(blockquote) {
  border-left: 3px solid var(--border);
  margin: 0.75rem 0;
  padding: 0.1rem 1rem;
  color: var(--text-3);
}
.md-body :deep(hr) { border: none; border-top: 1px solid var(--border); }
.md-body :deep(details) {
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.5rem 0.75rem;
  margin: 0.5rem 0;
}
</style>
