<!-- Bottom-docked "equivalent CLI command" bar (issue #140). Shows the command
     for whatever operation the user is currently looking at — a hovered job row,
     an open tool dialog (live as params change), or the report picker — with a
     copy button. One persistent surface for every operation, replacing the
     per-widget previews. The authoritative command for a *launched* run is
     echoed into that run's output by the server. -->
<template>
  <div class="cmd-bar" :class="{ 'cmd-bar--empty': !previewCommand }">
    <span class="cmd-icon">&lt;/&gt;</span>
    <code v-if="previewCommand" class="cmd-text">{{ previewCommand }}</code>
    <span v-else class="cmd-hint">Hover or configure an operation to see its CLI command</span>
    <button
      v-if="previewCommand"
      type="button"
      class="cmd-copy"
      :class="{ 'cmd-copy--done': copied }"
      :title="copied ? 'Copied to clipboard' : 'Copy command'"
      @click="copy"
    >{{ copied ? '✓ Copied' : 'Copy' }}</button>
  </div>
</template>

<script setup>
import { ref, onBeforeUnmount } from 'vue'
import { useCommandPreview } from '../composables/useCommandPreview.js'

const { previewCommand } = useCommandPreview()

const copied = ref(false)
let copiedTimer = null

async function copy() {
  const text = previewCommand.value
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    try { document.execCommand('copy') } catch { /* ignore */ }
    document.body.removeChild(ta)
  }
  copied.value = true
  clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => { copied.value = false }, 1500)
}

onBeforeUnmount(() => clearTimeout(copiedTimer))
</script>

<style scoped>
.cmd-bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.4rem 0.75rem;
  border-top: 1px solid var(--border);
  background: var(--surface);
  min-height: 2.1rem;
}
.cmd-icon {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-weight: 700;
  font-size: 0.8rem;
  color: var(--action);
  flex-shrink: 0;
}
.cmd-text {
  flex: 1;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.78rem;
  color: var(--text-1);
  white-space: pre-wrap;
  word-break: break-all;
  overflow-x: auto;
}
.cmd-hint {
  flex: 1;
  font-size: 0.76rem;
  font-style: italic;
  color: var(--text-3);
}
.cmd-copy {
  flex-shrink: 0;
  background: none;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 0.15rem 0.55rem;
  cursor: pointer;
  font-size: 0.72rem;
  color: var(--text-2);
}
.cmd-copy:hover { background: var(--border); color: var(--text-1); }
.cmd-copy--done { color: var(--ok); border-color: var(--ok); }
</style>
