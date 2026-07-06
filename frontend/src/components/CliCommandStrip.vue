<!-- Presentational "equivalent CLI command" strip: a monospace command with a
     copy button (issue #140). Shared by the docked CommandBar and by the tool /
     report dialogs so the command is visible *inside* a modal too, not only on
     the bar the overlay covers (issue #185). Pure display — the caller owns the
     command string and any docking chrome (border, background). -->
<template>
  <div class="cmd-strip" :class="{ 'cmd-strip--empty': !command, 'cmd-strip--expanded': expanded }">
    <span class="cmd-icon">&lt;/&gt;</span>
    <code
      v-if="command"
      ref="textEl"
      class="cmd-text"
      :class="{ 'cmd-text--expanded': expanded }"
    >{{ command }}</code>
    <span v-else class="cmd-hint">{{ emptyHint }}</span>
    <!-- Long commands stay one line by default so they don't distort the
         layout (or a presentation); the toggle reveals the full text on
         demand. Only shown when the command actually overflows (issue #187).
         When expanded the actions ride in a compact top row so the wrapped
         command uses the full width instead of a squeezed column. -->
    <div v-if="command" class="cmd-actions">
      <button
        v-if="expanded || overflowing"
        type="button"
        class="cmd-expand"
        :class="{ 'cmd-expand--open': expanded }"
        :aria-expanded="expanded ? 'true' : 'false'"
        :title="expanded ? 'Collapse command' : 'Show full command'"
        @click="expanded = !expanded"
      >▾</button>
      <button
        type="button"
        class="cmd-copy"
        :class="{ 'cmd-copy--done': copied }"
        :title="copied ? 'Copied to clipboard' : 'Copy command'"
        @click="copy"
      >{{ copied ? '✓ Copied' : 'Copy' }}</button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  command:   { type: String, default: '' },
  emptyHint: { type: String, default: 'Hover or configure an operation to see its CLI command' },
})

const copied = ref(false)
let copiedTimer = null

// Collapsed by default; expand reveals the full, wrapped command. `overflowing`
// gates the toggle so short commands that already fit show no chrome.
const textEl = ref(null)
const expanded = ref(false)
const overflowing = ref(false)

function measure() {
  const el = textEl.value
  if (!el || expanded.value) return   // only meaningful in the collapsed single-line state
  overflowing.value = el.scrollWidth - el.clientWidth > 1
}

// A new command starts collapsed; re-measure once Vue has painted it.
watch(() => props.command, async () => {
  expanded.value = false
  await nextTick()
  measure()
})

onMounted(async () => {
  await nextTick()
  measure()
  window.addEventListener('resize', measure)
})

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

onBeforeUnmount(() => {
  clearTimeout(copiedTimer)
  window.removeEventListener('resize', measure)
})
</script>

<style scoped>
.cmd-strip {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.4rem 0.75rem;
  min-height: 2.1rem;
}
/* When expanded, the command drops to its own full-width row while the actions
   sit in a compact top row — so the buttons cost one row of height, not a whole
   column of width. */
.cmd-strip--expanded {
  align-items: flex-start;
  flex-wrap: wrap;
}
.cmd-strip--expanded .cmd-icon    { display: none; }
.cmd-strip--expanded .cmd-actions { order: 1; margin-left: auto; }
.cmd-strip--expanded .cmd-text    { order: 2; flex-basis: 100%; }
.cmd-icon {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-weight: 700;
  font-size: 0.8rem;
  color: var(--action);
  flex-shrink: 0;
}
.cmd-text {
  flex: 1;
  min-width: 0;               /* let the flex child shrink so the ellipsis engages */
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.78rem;
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cmd-text--expanded {
  white-space: pre-wrap;
  word-break: break-all;
  overflow-y: auto;
  max-height: 40vh;
}
.cmd-hint {
  flex: 1;
  font-size: 0.76rem;
  font-style: italic;
  color: var(--text-3);
}
.cmd-actions {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 0.6rem;
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

.cmd-expand {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.6rem;
  height: 1.6rem;
  background: none;
  border: 1px solid var(--border);
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.7rem;
  line-height: 1;
  color: var(--text-2);
  transition: transform 0.15s ease, background 0.15s ease, color 0.15s ease;
}
.cmd-expand:hover { background: var(--border); color: var(--text-1); }
.cmd-expand--open { transform: rotate(180deg); }

@media (pointer: coarse) {
  .cmd-copy { padding: 0.4rem 0.8rem; }
  .cmd-expand { width: 2rem; height: 2rem; }
}
</style>
