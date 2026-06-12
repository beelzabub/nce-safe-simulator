<template>
  <div class="overlay" @click.self="$emit('close')">
    <div class="dialog">

      <div class="dialog-header">
        <span class="dialog-title">Run Reports</span>
        <button class="dialog-close" @click="$emit('close')">×</button>
      </div>

      <!-- Format selection -->
      <div class="section-label">Output formats</div>
      <div class="format-row">
        <label v-for="f in ALL_FORMATS" :key="f" class="check-label">
          <input type="checkbox" :value="f" v-model="selectedFormats" />
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
import { ref, computed } from 'vue'

const props = defineProps({
  reports: { type: Array, required: true },
})
const emit = defineEmits(['launch', 'close'])

const ALL_FORMATS = ['markdown', 'plotly', 'interactive']

const selectedFormats = ref([...ALL_FORMATS])
const selectedKeys    = ref(props.reports.map(r => r.key))

const allSelected = computed(() => selectedKeys.value.length === props.reports.length)
const canLaunch   = computed(() => selectedKeys.value.length > 0 && selectedFormats.value.length > 0)

function toggleAll() {
  selectedKeys.value = allSelected.value ? [] : props.reports.map(r => r.key)
}

function launch() {
  const selected = props.reports.filter(r => selectedKeys.value.includes(r.key))
  emit('launch', selected, selectedFormats.value)
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
  background: #161b22;
  border: 1px solid #30363d;
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
  border-bottom: 1px solid #30363d;
  flex-shrink: 0;
}
.dialog-title { font-size: 0.95rem; font-weight: 600; color: #e6edf3; }
.dialog-close {
  background: none; border: none;
  color: #6e7681; cursor: pointer; font-size: 1.1rem; line-height: 1;
}
.dialog-close:hover { color: #e6edf3; }

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
  color: #6e7681;
  flex-shrink: 0;
}
.all-toggle {
  font-size: 0.8rem;
  font-weight: 400;
  text-transform: none;
  letter-spacing: 0;
  color: #8b949e;
}

/* ── Format row ── */
.format-row {
  display: flex;
  gap: 1.25rem;
  padding: 0.3rem 1rem 0.65rem;
  border-bottom: 1px solid #30363d;
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
  color: #e6edf3;
  font-size: 0.85rem;
}
.check-label input[type="checkbox"] { cursor: pointer; flex-shrink: 0; }

.report-row {
  padding: 0.35rem 0.5rem;
  border-radius: 4px;
}
.report-row:hover { background: #1c2128; }
.report-key  { font-family: monospace; font-size: 0.82rem; white-space: nowrap; }
.report-desc { color: #8b949e; font-size: 0.78rem; }

/* ── Footer ── */
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.6rem;
  padding: 0.75rem 1rem;
  border-top: 1px solid #30363d;
  flex-shrink: 0;
}
.btn-cancel {
  padding: 6px 16px;
  background: none;
  border: 1px solid #30363d;
  border-radius: 5px;
  color: #8b949e;
  cursor: pointer;
  font-size: 0.85rem;
}
.btn-cancel:hover { border-color: #6e7681; color: #e6edf3; }
.btn-launch {
  padding: 6px 16px;
  background: #2563eb;
  border: none;
  border-radius: 5px;
  color: #fff;
  cursor: pointer;
  font-size: 0.85rem;
}
.btn-launch:disabled { background: #1e3a8a; color: #60a5fa; cursor: not-allowed; }
.btn-launch:not(:disabled):hover { background: #1d4ed8; }
</style>
