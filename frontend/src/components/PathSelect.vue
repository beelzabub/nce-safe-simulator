<template>
  <div class="path-select" ref="rootEl">
    <input
      ref="inputEl"
      type="text"
      class="field-input"
      :class="{ 'path-select__input--locked': disabled }"
      :value="modelValue"
      :placeholder="placeholder"
      :readonly="disabled"
      :title="title"
      autocomplete="off"
      role="combobox"
      :aria-expanded="open"
      @input="onInput"
      @focus="onFocus"
      @keydown="onKeydown"
    />

    <div v-if="open && !disabled" class="ps-panel">
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
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'

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
const open     = ref(false)
const activeIdx = ref(0)

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

function onInput(e) {
  emit('update:modelValue', e.target.value)
  activeIdx.value = 0
  open.value = true
}

function onFocus() {
  if (!props.disabled) open.value = true
}

function choose(opt) {
  emit('update:modelValue', opt.path)
  open.value = false
}

function onKeydown(e) {
  if (props.disabled) return
  if (e.key === 'ArrowDown') {
    if (!open.value) { open.value = true; return }
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
  if (open.value && rootEl.value && !rootEl.value.contains(e.target)) open.value = false
}
onMounted(() => document.addEventListener('mousedown', onDocMousedown))
onBeforeUnmount(() => document.removeEventListener('mousedown', onDocMousedown))
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

.ps-panel {
  position: absolute;
  top: calc(100% + 3px);
  left: 0;
  right: 0;
  z-index: 20;
  max-height: 240px;
  overflow-y: auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.45);
  padding: 3px;
}

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
