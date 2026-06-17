<template>
  <div class="overlay" @click.self="$emit('close')">
    <div class="dialog">

      <div class="dialog-header">
        <span class="dialog-title">Run Reports</span>
        <button class="dialog-close" @click="$emit('close')">×</button>
      </div>

      <!-- Data source -->
      <div class="data-source-row">
        <label class="check-label">
          <input type="checkbox" v-model="useLast" />
          Use last available data snapshot
        </label>
        <span class="data-source-hint">Skip API fetch — re-render from the most recent data/ directory</span>
      </div>

      <!-- Format selection -->
      <div class="section-label">Output formats</div>
      <div class="format-row">
        <label
          v-for="f in ALL_FORMATS"
          :key="f"
          class="check-label"
          :class="{ 'check-label--disabled': !allSelected && f !== 'markdown' }"
          :title="!allSelected && f !== 'markdown' ? 'Requires all reports selected — site build is project-wide' : ''"
        >
          <input
            type="checkbox"
            :value="f"
            v-model="selectedFormats"
            :disabled="!allSelected && f !== 'markdown'"
          />
          {{ f }}
        </label>
      </div>

      <!-- Report list -->
      <div class="section-label">
        Reports
        <label class="check-label all-toggle">
          <input type="checkbox" :checked="allSelected" @change="toggleAll" />
          All
        </label>
      </div>
      <div class="report-list">
        <label v-for="r in reports" :key="r.key" class="check-label report-row">
          <input type="checkbox" :value="r.key" v-model="selectedKeys" />
          <span class="report-key">{{ r.key }}</span>
          <span class="report-desc">{{ r.description }}</span>
        </label>
      </div>

      <div class="dialog-footer">
        <button class="btn-cancel" @click="$emit('close')">Cancel</button>
        <button
          class="btn-launch"
          :disabled="!canLaunch"
          @click="launch"
        >
          Launch {{ selectedKeys.length }} report{{ selectedKeys.length !== 1 ? 's' : '' }}
        </button>
      </div>

    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { loadStored, saveStored } from '../composables/useLocalStorage.js'

const props = defineProps({
  reports: { type: Array, required: true },
})
const emit = defineEmits(['launch', 'close'])

const ALL_FORMATS = ['markdown', 'plotly', 'interactive']
const STORAGE_KEY = 'nce-report-picker'

function _loadState() {
  const saved = loadStored(STORAGE_KEY, {})
  const validKeys = new Set(props.reports.map(r => r.key))
  return {
    formats: Array.isArray(saved.formats)
      ? saved.formats.filter(f => ALL_FORMATS.includes(f))
      : [...ALL_FORMATS],
    keys: Array.isArray(saved.keys)
      ? saved.keys.filter(k => validKeys.has(k))
      : props.reports.map(r => r.key),
    useLast: saved.useLast ?? false,
  }
}

const _init          = _loadState()
const selectedFormats = ref(_init.formats)
const selectedKeys    = ref(_init.keys)
const useLast         = ref(_init.useLast)

watch([selectedFormats, selectedKeys, useLast], () => {
  saveStored(STORAGE_KEY, {
    formats: selectedFormats.value,
    keys:    selectedKeys.value,
    useLast: useLast.value,
  })
}, { deep: true })

const allSelected = computed(() => selectedKeys.value.length === props.reports.length)
const canLaunch   = computed(() => selectedKeys.value.length > 0 && selectedFormats.value.length > 0)

// Drop site-build formats when not all reports are selected
watch(allSelected, (all) => {
  if (!all) {
    selectedFormats.value = selectedFormats.value.filter(f => f === 'markdown')
  }
})

function toggleAll() {
  selectedKeys.value = allSelected.value ? [] : props.reports.map(r => r.key)
}

function onKeydown(e) {
  if (e.key === 'Escape') emit('close')
}
onMounted(() => document.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))

function launch() {
  const selected = props.reports.filter(r => selectedKeys.value.includes(r.key))
  emit('launch', selected, selectedFormats.value, useLast.value)
}
</script>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.dialog {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  width: 520px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

/* ── Header ── */
.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.85rem 1rem 0.75rem;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.dialog-title { font-size: 0.95rem; font-weight: 600; color: var(--text-1); }
.dialog-close {
  background: none; border: none;
  color: var(--text-3); cursor: pointer; font-size: 1.1rem; line-height: 1;
}
.dialog-close:hover { color: var(--text-1); }

/* ── Sections ── */
.section-label {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.65rem 1rem 0.3rem;
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-3);
  flex-shrink: 0;
}
.all-toggle {
  font-size: 0.8rem;
  font-weight: 400;
  text-transform: none;
  letter-spacing: 0;
  color: var(--text-2);
}

/* ── Data source ── */
.data-source-row {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
  padding: 0.55rem 1rem 0.6rem;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.data-source-hint {
  font-size: 0.75rem;
  color: var(--text-3);
  padding-left: 1.4rem;
}

/* ── Format row ── */
.format-row {
  display: flex;
  gap: 1.25rem;
  padding: 0.3rem 1rem 0.65rem;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

/* ── Report list ── */
.report-list {
  flex: 1;
  overflow-y: auto;
  padding: 0.3rem 0.5rem 0.5rem;
}

/* ── Shared label ── */
.check-label {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  cursor: pointer;
  color: var(--text-1);
  font-size: 0.85rem;
}
.check-label input[type="checkbox"] { cursor: pointer; flex-shrink: 0; }
.check-label--disabled { opacity: 0.38; cursor: not-allowed; }
.check-label--disabled input { cursor: not-allowed; }

.report-row {
  padding: 0.35rem 0.5rem;
  border-radius: 4px;
}
.report-row:hover { background: var(--surface-alt); }
.report-key  { font-family: monospace; font-size: 0.82rem; white-space: nowrap; }
.report-desc { color: var(--text-2); font-size: 0.78rem; }

/* ── Footer ── */
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.6rem;
  padding: 0.75rem 1rem;
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}
.btn-cancel {
  padding: 6px 16px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--text-2);
  cursor: pointer;
  font-size: 0.85rem;
  transition: border-color 0.15s, color 0.15s;
}
.btn-cancel:hover { border-color: var(--text-2); color: var(--text-1); }
.btn-launch {
  padding: 6px 16px;
  background: var(--action);
  border: none;
  border-radius: 5px;
  color: #fff;
  cursor: pointer;
  font-size: 0.85rem;
  transition: background 0.15s;
}
.btn-launch:disabled { background: var(--action-off); color: var(--action-off-text); cursor: not-allowed; }
.btn-launch:not(:disabled):hover { background: var(--action-hover); }
</style>
