<!-- Presentational "equivalent CLI command" strip: a monospace command with a
     copy button (issue #140). Shared by the docked CommandBar and by the tool /
     report dialogs so the command is visible *inside* a modal too, not only on
     the bar the overlay covers (issue #185). Pure display — the caller owns the
     command string and any docking chrome (border, background). -->
<template>
  <div class="cmd-strip" :class="{ 'cmd-strip--empty': !command }">
    <span class="cmd-icon">&lt;/&gt;</span>
    <code v-if="command" class="cmd-text">{{ command }}</code>
    <span v-else class="cmd-hint">{{ emptyHint }}</span>
    <button
      v-if="command"
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

const props = defineProps({
  command:   { type: String, default: '' },
  emptyHint: { type: String, default: 'Hover or configure an operation to see its CLI command' },
})

const copied = ref(false)
let copiedTimer = null

async function copy() {
  const text = props.command
  if (!text) return
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
.cmd-strip {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.4rem 0.75rem;
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

@media (pointer: coarse) {
  .cmd-copy { padding: 0.4rem 0.8rem; }
}
</style>
