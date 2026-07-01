<!-- Inline "equivalent CLI command" strip with a copy button (issue #140).
     Given a command string, renders a collapsible monospace box that updates
     live as the caller's command prop changes, plus a one-click copy. Used in
     the tool dialog, the report picker, and (collapsed) per-action popovers. -->
<template>
  <div v-if="command" class="cli-preview" :class="{ 'cli-preview--open': open }">
    <div class="cli-head">
      <button type="button" class="cli-toggle" @click="open = !open" :aria-expanded="open">
        <span class="cli-caret" :class="{ 'cli-caret--open': open }">▸</span>
        <span class="cli-icon">&lt;/&gt;</span>
        {{ label }}
      </button>
      <button
        type="button"
        class="cli-copy"
        :class="{ 'cli-copy--done': copied }"
        :title="copied ? 'Copied to clipboard' : 'Copy command'"
        @click="copy"
      >
        {{ copied ? '✓ Copied' : 'Copy' }}
      </button>
    </div>
    <pre v-show="open" class="cli-body"><code>{{ command }}</code></pre>
  </div>
</template>

<script setup>
import { ref, onBeforeUnmount } from 'vue'

const props = defineProps({
  command: { type: String, default: '' },
  label:   { type: String, default: 'Equivalent CLI command' },
  // start expanded (dialogs) or collapsed (dense per-action popovers)
  defaultOpen: { type: Boolean, default: true },
})

const open = ref(props.defaultOpen)
const copied = ref(false)
let copiedTimer = null

async function copy() {
  const text = props.command
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // Fallback for non-secure contexts / older browsers.
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
.cli-preview {
  border: 1px solid var(--border, #d0d5dd);
  border-radius: 6px;
  background: var(--surface-2, #f6f8fa);
  margin: 0.5rem 0;
  overflow: hidden;
}
.cli-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.35rem 0.5rem;
}
.cli-toggle {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-muted, #475467);
}
.cli-caret {
  display: inline-block;
  transition: transform 0.12s ease;
  font-size: 0.7rem;
}
.cli-caret--open { transform: rotate(90deg); }
.cli-icon {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: var(--action, #1f6feb);
  font-weight: 700;
}
.cli-copy {
  background: none;
  border: 1px solid var(--border, #d0d5dd);
  border-radius: 4px;
  padding: 0.15rem 0.5rem;
  cursor: pointer;
  font-size: 0.72rem;
  color: var(--text-muted, #475467);
}
.cli-copy:hover { background: var(--surface-hover, #eaeef2); }
.cli-copy--done { color: var(--ok, #1a7f37); border-color: var(--ok, #1a7f37); }
.cli-body {
  margin: 0;
  padding: 0.5rem 0.6rem;
  border-top: 1px solid var(--border, #d0d5dd);
  background: var(--surface-code, #0d1117);
  color: var(--text-code, #e6edf3);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.74rem;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-all;
  overflow-x: auto;
}
</style>
