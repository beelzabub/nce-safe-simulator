<template>
  <span
    ref="iconEl"
    class="helptip"
    tabindex="0"
    role="note"
    :aria-label="'Help: ' + text"
    @mouseenter="open"
    @mouseleave="close"
    @focus="open"
    @blur="close"
  >
    <span class="helptip-icon">?</span>
    <Teleport to="body">
      <span v-if="show" class="helptip-bubble" :style="bubbleStyle">{{ text }}</span>
    </Teleport>
  </span>
</template>

<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'

defineProps({ text: { type: String, required: true } })

const iconEl = ref(null)
const show   = ref(false)
const rect   = ref(null)

const MAXW = 280, GAP = 6, PAD = 8

function open() {
  if (iconEl.value) rect.value = iconEl.value.getBoundingClientRect()
  show.value = true
}
function close() { show.value = false }

// Teleported to <body> and positioned fixed against the icon, so the dialog's
// scroll/overflow can't crop it. Opens above the icon when there's room, else below.
const bubbleStyle = computed(() => {
  const r = rect.value
  if (!r) return {}
  const left = Math.max(PAD, Math.min(r.left, window.innerWidth - MAXW - PAD))
  const s = { left: left + 'px', maxWidth: MAXW + 'px' }
  if (r.top > 140) s.bottom = (window.innerHeight - r.top + GAP) + 'px'
  else             s.top    = (r.bottom + GAP) + 'px'
  return s
})

function reposition() { if (show.value && iconEl.value) rect.value = iconEl.value.getBoundingClientRect() }
watch(show, on => {
  if (on) {
    window.addEventListener('scroll', reposition, true)
    window.addEventListener('resize', reposition)
  } else {
    window.removeEventListener('scroll', reposition, true)
    window.removeEventListener('resize', reposition)
  }
})
onBeforeUnmount(() => {
  window.removeEventListener('scroll', reposition, true)
  window.removeEventListener('resize', reposition)
})
</script>

<style scoped>
.helptip {
  position: relative;
  display: inline-flex;
  margin-left: 4px;
  cursor: help;
  outline: none;
}
.helptip-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 1px solid var(--border);
  color: var(--text-3);
  font-size: 0.62rem;
  font-weight: 700;
  line-height: 1;
  transition: color 0.12s, border-color 0.12s;
}
.helptip:hover .helptip-icon,
.helptip:focus .helptip-icon { border-color: var(--action); color: var(--action); }

/* Teleported to <body>; position is set inline (fixed). */
.helptip-bubble {
  position: fixed;
  z-index: 1000;
  white-space: pre-line;
  text-align: left;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 7px 9px;
  font-size: 0.72rem;
  font-weight: 400;
  line-height: 1.45;
  color: var(--text-1);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
  pointer-events: none;
}
</style>
