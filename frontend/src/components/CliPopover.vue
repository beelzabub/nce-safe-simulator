<!-- Per-action CLI command popover (issue #140). A small </> icon that, on
     click, shows the equivalent command line in a teleported, interactive bubble
     with a copy button. Teleported to <body> and fixed-positioned (same approach
     as HelpTip) so a scrolling job list can't crop it. Used on job rows that
     launch directly, where there is no dialog to host an inline strip. -->
<template>
  <span ref="iconEl" class="cli-pop" @click.stop>
    <button
      type="button"
      class="cli-pop-icon"
      :class="{ active: show }"
      :title="'Show CLI command'"
      aria-label="Show equivalent CLI command"
      @click.stop="toggle"
    >&lt;/&gt;</button>
    <Teleport to="body">
      <div v-if="show" class="cli-pop-bubble" :style="bubbleStyle" @click.stop>
        <div class="cli-pop-head">
          <span class="cli-pop-title">Equivalent CLI command</span>
          <button
            type="button"
            class="cli-pop-copy"
            :class="{ 'cli-pop-copy--done': copied }"
            @click.stop="copy"
          >{{ copied ? '✓ Copied' : 'Copy' }}</button>
        </div>
        <pre class="cli-pop-body"><code>{{ command }}</code></pre>
      </div>
    </Teleport>
  </span>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({ command: { type: String, required: true } })

const iconEl = ref(null)
const show   = ref(false)
const rect   = ref(null)
const copied = ref(false)
let copiedTimer = null

const MAXW = 420, GAP = 6, PAD = 8

function toggle() {
  if (show.value) { show.value = false; return }
  if (iconEl.value) rect.value = iconEl.value.getBoundingClientRect()
  show.value = true
}
function close() { show.value = false }

// Fixed-position against the icon; open above when there's room, else below.
const bubbleStyle = computed(() => {
  const r = rect.value
  if (!r) return {}
  const left = Math.max(PAD, Math.min(r.left, window.innerWidth - MAXW - PAD))
  const s = { left: left + 'px', maxWidth: MAXW + 'px' }
  if (r.top > 160) s.bottom = (window.innerHeight - r.top + GAP) + 'px'
  else             s.top    = (r.bottom + GAP) + 'px'
  return s
})

async function copy() {
  try {
    await navigator.clipboard.writeText(props.command)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = props.command
    ta.style.position = 'fixed'; ta.style.opacity = '0'
    document.body.appendChild(ta); ta.select()
    try { document.execCommand('copy') } catch { /* ignore */ }
    document.body.removeChild(ta)
  }
  copied.value = true
  clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => { copied.value = false }, 1500)
}

function reposition() { if (show.value && iconEl.value) rect.value = iconEl.value.getBoundingClientRect() }
function onDocClick() { close() }
function onKey(e) { if (e.key === 'Escape') close() }

watch(show, on => {
  if (on) {
    window.addEventListener('scroll', reposition, true)
    window.addEventListener('resize', reposition)
    document.addEventListener('click', onDocClick)
    document.addEventListener('keydown', onKey)
  } else {
    window.removeEventListener('scroll', reposition, true)
    window.removeEventListener('resize', reposition)
    document.removeEventListener('click', onDocClick)
    document.removeEventListener('keydown', onKey)
  }
})
onBeforeUnmount(() => {
  clearTimeout(copiedTimer)
  window.removeEventListener('scroll', reposition, true)
  window.removeEventListener('resize', reposition)
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKey)
})
</script>

<style scoped>
.cli-pop { position: relative; display: inline-flex; }
.cli-pop-icon {
  background: none;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 0 4px;
  height: 16px;
  line-height: 1;
  cursor: pointer;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.6rem;
  font-weight: 700;
  color: var(--text-3);
  transition: color 0.12s, border-color 0.12s;
}
.cli-pop-icon:hover, .cli-pop-icon.active { border-color: var(--action); color: var(--action); }

/* Teleported to <body>; position set inline (fixed). */
.cli-pop-bubble {
  position: fixed;
  z-index: 1000;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
  overflow: hidden;
}
.cli-pop-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.35rem 0.5rem;
}
.cli-pop-title { font-size: 0.72rem; font-weight: 600; color: var(--text-3); }
.cli-pop-copy {
  background: none;
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 0.1rem 0.45rem;
  cursor: pointer;
  font-size: 0.7rem;
  color: var(--text-3);
}
.cli-pop-copy:hover { border-color: var(--action); color: var(--action); }
.cli-pop-copy--done { color: var(--ok, #1a7f37); border-color: var(--ok, #1a7f37); }
.cli-pop-body {
  margin: 0;
  padding: 0.5rem 0.6rem;
  border-top: 1px solid var(--border);
  background: var(--surface-code, #0d1117);
  color: var(--text-code, #e6edf3);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.72rem;
  line-height: 1.45;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
