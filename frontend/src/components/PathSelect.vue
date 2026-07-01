<template>
  <div class="path-select" ref="rootEl">
    <input
      ref="inputEl"
      type="text"
      class="field-input ps-input"
      :class="{ 'path-select__input--locked': disabled }"
      :value="modelValue"
      :placeholder="placeholder"
      :readonly="disabled"
      :title="title"
      autocomplete="off"
      role="combobox"
      aria-haspopup="listbox"
      :aria-expanded="open"
      @input="onInput"
      @focus="onFocus"
      @click="onFocus"
      @keydown="onKeydown"
    />
    <button
      v-if="!disabled"
      type="button"
      class="ps-caret"
      :class="{ 'ps-caret--open': open }"
      tabindex="-1"
      aria-label="Toggle options"
      @mousedown.prevent="toggle"
    >
      <svg viewBox="0 0 12 8" width="12" height="8" aria-hidden="true">
        <path d="M1 1.5 6 6.5 11 1.5" fill="none" stroke="currentColor"
              stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>

    <Teleport to="body">
      <div
        v-if="open && !disabled"
        ref="panelEl"
        class="ps-panel"
        :class="{ 'ps-panel--up': dropUp }"
        :style="panelStyle"
      >
        <div v-if="loading" class="ps-msg">Loading…</div>
        <template v-else>
          <button
            v-for="(opt, i) in filtered"
            :key="opt.path"
            type="button"
            class="ps-option"
            :class="{ 'ps-option--active': i === activeIdx }"
            @mousedown.prevent="choose(opt)"
            @mouseenter="activeIdx = i"
          >
            <span class="ps-name">{{ opt.name }}</span>
            <span class="ps-path" :title="opt.path">{{ collapse(opt.path) }}</span>
          </button>
          <div v-if="!filtered.length" class="ps-msg ps-msg--free">
            No match — <code>{{ modelValue || '(blank)' }}</code> will be used as typed.
          </div>
        </template>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  modelValue:  { type: String,  default: '' },
  options:     { type: Array,   default: () => [] },   // [{ path, name }]
  loading:     { type: Boolean, default: false },
  disabled:    { type: Boolean, default: false },
  placeholder: { type: String,  default: '' },
  title:       { type: String,  default: '' },
})
const emit = defineEmits(['update:modelValue'])

const rootEl   = ref(null)
const inputEl  = ref(null)
const panelEl  = ref(null)
const open     = ref(false)
const activeIdx = ref(0)
const dropUp   = ref(false)   // flip the panel above the field when room is tight
const panelMax = ref(240)     // cap to the available space so it never overflows
const inputRect = ref(null)   // field position, snapshotted for the teleported panel

// The current field text matches an exact option path → the user has a
// selection and isn't actively filtering, so show the whole list. Otherwise
// filter by the typed text against both the human name and the full path.
const filtered = computed(() => {
  const q = (props.modelValue || '').trim().toLowerCase()
  if (!q) return props.options
  if (props.options.some(o => o.path.toLowerCase() === q)) return props.options
  return props.options.filter(
    o => o.name.toLowerCase().includes(q) || o.path.toLowerCase().includes(q)
  )
})

// Longest common ancestor across all option paths (never strips a leaf). Used
// to collapse the shared namespace/root prefix into an ellipsis so long paths
// stay readable.
const commonPrefix = computed(() => {
  const paths = props.options.map(o => o.path.split('/'))
  if (!paths.length) return []
  let prefix = paths[0].slice(0, -1)
  for (const segs of paths) {
    let i = 0
    while (i < prefix.length && i < segs.length - 1 && segs[i] === prefix[i]) i++
    prefix = prefix.slice(0, i)
  }
  return prefix
})

function collapse(path) {
  const segs = path.split('/')
  const p = commonPrefix.value
  if (p.length && segs.length > p.length) return '…/' + segs.slice(p.length).join('/')
  return path
}

// Choose whether the panel drops down or flips up, based on the room between
// the field and the viewport edges, and cap its height to fit — mirrors the
// friendly auto-placement the native datalist used to do.
function positionPanel() {
  const el = inputEl.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  inputRect.value = rect
  const below = window.innerHeight - rect.bottom
  const above = rect.top
  const want  = 240
  if (below < want && above > below) {
    dropUp.value = true
    panelMax.value = Math.max(120, Math.min(want, above - 12))
  } else {
    dropUp.value = false
    panelMax.value = Math.max(120, Math.min(want, below - 12))
  }
}

// The panel is teleported to <body> (so no dialog/overflow clipping) and
// positioned as fixed against the field's viewport rect.
const panelStyle = computed(() => {
  const r = inputRect.value
  if (!r) return {}
  const s = { left: r.left + 'px', width: r.width + 'px', maxHeight: panelMax.value + 'px' }
  if (dropUp.value) s.bottom = (window.innerHeight - r.top + 3) + 'px'
  else s.top = (r.bottom + 3) + 'px'
  return s
})

function openPanel() {
  if (props.disabled) return
  positionPanel()
  open.value = true
}

function onInput(e) {
  emit('update:modelValue', e.target.value)
  activeIdx.value = 0
  openPanel()
}

function onFocus() {
  openPanel()
}

function toggle() {
  if (props.disabled) return
  if (open.value) { open.value = false; return }
  openPanel()
  inputEl.value?.focus()
}

function choose(opt) {
  emit('update:modelValue', opt.path)
  open.value = false
}

function onKeydown(e) {
  if (props.disabled) return
  if (e.key === 'ArrowDown') {
    if (!open.value) { openPanel(); return }
    e.preventDefault()
    activeIdx.value = Math.min(activeIdx.value + 1, filtered.value.length - 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    activeIdx.value = Math.max(activeIdx.value - 1, 0)
  } else if (e.key === 'Enter') {
    if (open.value && filtered.value[activeIdx.value]) {
      e.preventDefault()
      choose(filtered.value[activeIdx.value])
    }
  } else if (e.key === 'Escape') {
    if (open.value) { e.stopPropagation(); open.value = false }
  }
}

function onDocMousedown(e) {
  if (!open.value) return
  const inRoot  = rootEl.value?.contains(e.target)
  const inPanel = panelEl.value?.contains(e.target)   // teleported → outside rootEl
  if (!inRoot && !inPanel) open.value = false
}

// Keep the teleported panel glued to the field while the dialog / list scrolls.
function reposition() { if (open.value) positionPanel() }

watch(open, isOpen => {
  if (isOpen) {
    nextTick(() => {
      window.addEventListener('scroll', reposition, true)
      window.addEventListener('resize', reposition)
    })
  } else {
    window.removeEventListener('scroll', reposition, true)
    window.removeEventListener('resize', reposition)
  }
})

onMounted(() => document.addEventListener('mousedown', onDocMousedown))
onBeforeUnmount(() => {
  document.removeEventListener('mousedown', onDocMousedown)
  window.removeEventListener('scroll', reposition, true)
  window.removeEventListener('resize', reposition)
})
</script>

<style scoped>
.path-select {
  position: relative;
  width: 100%;
}
.path-select__input--locked {
  color: var(--text-2);
  background: var(--surface-alt);
  cursor: default;
}
.ps-input {
  padding-right: 28px;   /* room for the caret */
  cursor: pointer;
}
.ps-input:read-only { cursor: default; }

.ps-caret {
  position: absolute;
  top: 1px;
  bottom: 1px;
  right: 1px;
  width: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: none;
  border-left: 1px solid var(--border);
  color: var(--text-2);
  cursor: pointer;
  transition: color 0.15s;
}
.ps-caret svg { transition: transform 0.15s; }
.ps-caret:hover { color: var(--action); }
.ps-caret--open svg { transform: rotate(180deg); }

.ps-panel {
  position: fixed;          /* teleported to <body>; left/width/top|bottom set inline */
  z-index: 1000;            /* above the dialog overlay (z-index: 100) */
  overflow-y: auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.45);
  padding: 3px;
}
.ps-panel--up { box-shadow: 0 -10px 28px rgba(0, 0, 0, 0.45); }

.ps-option {
  display: flex;
  flex-direction: column;
  gap: 1px;
  width: 100%;
  text-align: left;
  background: transparent;
  border: none;
  border-radius: 4px;
  padding: 5px 8px;
  cursor: pointer;
}
.ps-option--active { background: var(--surface-alt); }

.ps-name {
  font-size: 0.83rem;
  font-weight: 600;
  color: var(--text-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ps-path {
  font-size: 0.72rem;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.ps-msg {
  padding: 7px 9px;
  font-size: 0.75rem;
  color: var(--text-3);
}
.ps-msg--free code {
  color: var(--text-2);
  background: var(--surface-alt);
  border-radius: 3px;
  padding: 0 3px;
}
</style>
