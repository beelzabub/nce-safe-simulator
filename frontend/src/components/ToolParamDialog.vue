<template>
  <Teleport to="body">
    <div v-if="tool" class="overlay" @mousedown.self="overlayDown = true" @mouseup.self="overlayDown && $emit('cancel'); overlayDown = false" @mouseleave="overlayDown = false">
      <div class="dialog" role="dialog" :aria-label="formatKey(tool.key)">

        <div class="dialog-header">
          <div class="dialog-title-block">
            <span class="dialog-name">{{ confirming ? 'Confirm: ' : '' }}{{ formatKey(tool.key) }}</span>
            <code class="dialog-key">{{ tool.key }}</code>
          </div>
          <button class="close-btn" @click="$emit('cancel')" title="Cancel">✕</button>
        </div>

        <!-- ── Configure view ── -->
        <template v-if="!confirming">
          <p class="dialog-desc">{{ tool.description }}</p>

          <div v-if="tool.params.length" class="params">
            <template v-for="(param, idx) in tool.params" :key="param.name">
            <div
              v-if="param.section && (idx === 0 || tool.params[idx-1].section !== param.section)"
              class="param-section-label"
            >{{ param.section }}</div>
            <div
              class="param-row"
              :class="{ 'param-dryrun': param.name === 'dry_run' }"
            >
              <!-- group widget → locked display with Edit button -->
              <template v-if="param.widget === 'group'">
                <div class="field-label">
                  {{ param.prompt }}
                  <span class="optional-tag">from config</span>
                </div>
                <div class="group-field">
                  <input
                    type="text"
                    class="field-input group-input"
                    :class="{ 'group-input--locked': groupLocked }"
                    :readonly="groupLocked"
                    v-model="values[param.name]"
                    :title="groupLocked ? 'Click Edit to override' : ''"
                  />
                  <button v-if="groupLocked" class="group-edit-btn" type="button" @click="groupLocked = false">
                    Edit
                  </button>
                  <button v-else class="group-reset-btn" type="button" @click="resetGroup(param)">
                    Reset
                  </button>
                </div>
              </template>

              <!-- bool → toggle -->
              <template v-else-if="param.type === 'bool'">
                <label class="toggle-label">
                  <input type="checkbox" class="toggle-input" v-model="values[param.name]" />
                  <span class="toggle-track"><span class="toggle-thumb" /></span>
                  <span class="toggle-text">{{ param.prompt }}</span>
                </label>
              </template>

              <!-- int / float → number -->
              <template v-else-if="param.type === 'int' || param.type === 'float'">
                <label class="field-label">
                  {{ param.prompt }}
                  <span v-if="!param.optional" class="required-mark">*</span>
                  <span v-else class="optional-tag">optional</span>
                </label>
                <input
                  type="number"
                  class="field-input"
                  :step="param.type === 'float' ? 0.01 : 1"
                  :min="param.type === 'float' ? 0 : undefined"
                  :max="param.type === 'float' ? 1 : undefined"
                  :placeholder="param.optional ? 'leave blank for config default' : String(param.default ?? '')"
                  v-model.number="values[param.name]"
                />
                <span v-if="param.hint" class="field-hint">{{ param.hint }}</span>
              </template>

              <!-- str → text -->
              <template v-else>
                <label class="field-label">
                  {{ param.prompt }}
                  <span v-if="!param.optional" class="required-mark">*</span>
                  <span v-else class="optional-tag">optional</span>
                </label>
                <input
                  type="text"
                  class="field-input"
                  :placeholder="param.optional ? 'leave blank to skip' : (param.default ?? '')"
                  v-model="values[param.name]"
                />
                <span v-if="param.hint" class="field-hint">{{ param.hint }}</span>
              </template>
            </div>
            </template>
          </div>

          <div v-else class="no-params">
            No parameters required — ready to launch.
          </div>

          <ConflictBanner
            v-if="blockers.length"
            :blockers="blockers"
            :group="group"
            class="dialog-conflict"
          />

          <div class="dialog-footer">
            <button class="btn-cancel" @click="$emit('cancel')">Cancel</button>
            <button class="btn-launch" :disabled="!isValid || blockers.length > 0" @click="submit">
              Launch {{ formatKey(tool.key) }}
            </button>
          </div>
        </template>

        <!-- ── Confirmation view ── -->
        <template v-else>
          <p class="dialog-desc confirm-intro">
            Review the settings below, then confirm to start the job.
          </p>

          <div class="confirm-table">
            <div v-for="row in confirmRows" :key="row.label" class="confirm-row">
              <span class="confirm-label">{{ row.label }}</span>
              <span class="confirm-value" :class="row.cls">{{ row.display }}</span>
            </div>
          </div>

          <div class="dialog-footer">
            <button class="btn-cancel" @click="confirming = false">← Back</button>
            <button class="btn-launch btn-launch--confirm" @click="doLaunch">
              Confirm &amp; Launch
            </button>
          </div>
        </template>

      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, watch, computed, onMounted, onBeforeUnmount } from 'vue'
import ConflictBanner from './ConflictBanner.vue'

const props = defineProps({
  tool:     { type: Object, default: null },
  blockers: { type: Array,  default: () => [] },
  group:    { type: String, default: null },
})
const emit = defineEmits(['launch', 'cancel'])

const values      = ref({})
const groupLocked = ref(true)
const overlayDown = ref(false)
const confirming  = ref(false)

// Re-initialise values whenever the tool changes.
watch(() => props.tool, tool => {
  groupLocked.value = true
  confirming.value  = false
  if (!tool) { values.value = {}; return }
  const init = {}
  for (const p of tool.params) {
    init[p.name] = _initValue(p)
  }
  values.value = init
}, { immediate: true })

// Pre-fill logic: optional params with a server-resolved default are pre-filled
// so the dialog shows exactly what the config contains.
function _initValue(p) {
  if (p.widget === 'group')                        return p.default ?? ''
  if (p.type === 'bool')                           return p.default ?? false
  if (p.default !== null && p.default !== undefined) return p.default
  if (p.optional)                                  return null
  return ''
}

function resetGroup(param) {
  values.value[param.name] = param.default ?? ''
  groupLocked.value = true
}

const isValid = computed(() => {
  if (!props.tool) return false
  for (const p of props.tool.params) {
    if (p.optional || p.type === 'bool' || p.widget === 'group') continue
    const v = values.value[p.name]
    if (v === '' || v === null || v === undefined) return false
  }
  return true
})

function formatKey(key) {
  const ACRONYMS = new Set(['roam', 'wsjf', 'bv', 'piid', 'pi'])
  return key.split('-').map(w =>
    ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)
  ).join(' ')
}

// Build the params object that will be sent on launch.
function _buildParams() {
  const params = {}
  for (const p of props.tool.params) {
    const v = values.value[p.name]
    if (p.optional && (v === null || v === '')) continue
    if (p.widget === 'group' && (v === null || v === '')) continue
    params[p.name] = v
  }
  return params
}

// Confirmation summary rows.
const confirmRows = computed(() => {
  if (!props.tool) return []
  const rows = []
  for (const p of props.tool.params) {
    const v = values.value[p.name]
    let display, cls = ''
    if (p.type === 'bool') {
      if (p.name === 'dry_run') {
        display = v ? 'Yes — preview only, no changes' : 'No — will create objects in GitLab'
        cls = v ? 'confirm-value--warn' : 'confirm-value--danger'
      } else {
        display = v ? 'Yes' : 'No'
      }
    } else if (p.type === 'float' && v != null && v <= 1) {
      display = `${Math.round(v * 100)}%`
    } else if (v === null || v === undefined || v === '') {
      display = '— config default'
      cls = 'confirm-value--dim'
    } else {
      display = String(v)
    }
    rows.push({ label: p.prompt, display, cls })
  }
  return rows
})

function onKeydown(e) {
  if (e.key === 'Escape' && props.tool) {
    if (confirming.value) confirming.value = false
    else emit('cancel')
  }
}
onMounted(() => document.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => document.removeEventListener('keydown', onKeydown))

// First click: show confirmation step (if tool.confirm); second click: launch.
function submit() {
  if (!isValid.value) return
  if (props.tool.confirm) { confirming.value = true; return }
  doLaunch()
}

function doLaunch() {
  emit('launch', props.tool, _buildParams())
}
</script>

<style scoped>
/* ── Overlay ── */
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 1rem;
}

/* ── Dialog card ── */
.dialog {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  width: 100%;
  max-width: 520px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.5);
}

/* ── Header ── */
.dialog-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 1rem;
  padding: 1rem 1.25rem 0.5rem;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.dialog-title-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.dialog-name {
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-1);
}
.dialog-key {
  font-size: 0.72rem;
  color: var(--text-3);
  background: var(--surface-alt);
  border-radius: 3px;
  padding: 1px 5px;
  width: fit-content;
}
.close-btn {
  background: transparent;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  font-size: 1rem;
  padding: 2px 4px;
  line-height: 1;
  flex-shrink: 0;
}
.close-btn:hover { color: var(--text-1); }

/* ── Description ── */
.dialog-desc {
  margin: 0;
  padding: 0.6rem 1.25rem;
  font-size: 0.82rem;
  color: var(--text-2);
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

/* ── Params ── */
.params {
  flex: 1;
  overflow-y: auto;
  padding: 0.75rem 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.param-section-label {
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.07em;
  text-transform: uppercase;
  color: var(--text-3);
  padding: 0.35rem 0 0.1rem;
  border-top: 1px solid var(--border);
  margin-top: 0.25rem;
}

.param-row {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

/* Dry run gets a subtle amber tint to signal it's a safety toggle */
.param-dryrun {
  background: color-mix(in srgb, var(--conflict-bg) 40%, transparent);
  border: 1px solid var(--conflict-border);
  border-radius: 5px;
  padding: 0.5rem 0.75rem;
}

/* ── Group widget ── */
.group-field {
  display: flex;
  gap: 0.4rem;
  align-items: center;
}
.group-input {
  flex: 1;
}
.group-input--locked {
  color: var(--text-2);
  background: var(--surface-alt);
  cursor: default;
}
.group-edit-btn,
.group-reset-btn {
  flex-shrink: 0;
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-2);
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 0.78rem;
  white-space: nowrap;
  transition: border-color 0.15s, color 0.15s;
}
.group-edit-btn:hover  { border-color: var(--action); color: var(--action); }
.group-reset-btn:hover { border-color: var(--text-2); color: var(--text-1); }

/* ── Toggle (bool) ── */
.toggle-label {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  cursor: pointer;
  user-select: none;
}
.toggle-input { display: none; }

.toggle-track {
  position: relative;
  width: 36px;
  height: 20px;
  background: var(--border);
  border-radius: 10px;
  flex-shrink: 0;
  transition: background 0.2s;
}
.toggle-input:checked + .toggle-track { background: var(--action); }

.toggle-thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 14px;
  height: 14px;
  background: #fff;
  border-radius: 50%;
  transition: left 0.2s;
}
.toggle-input:checked + .toggle-track .toggle-thumb { left: 19px; }

.toggle-text { font-size: 0.85rem; color: var(--text-1); }

/* ── Text / number fields ── */
.field-label {
  font-size: 0.78rem;
  color: var(--text-2);
  display: flex;
  gap: 0.3rem;
  align-items: center;
}
.required-mark { color: #f87171; font-weight: 700; }
.optional-tag  { color: var(--text-3); font-size: 0.72rem; }
.field-hint    { font-size: 0.72rem; color: var(--text-3); margin-top: 2px; }

.field-input {
  width: 100%;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 5px;
  color: var(--text-1);
  padding: 6px 10px;
  font-size: 0.85rem;
  outline: none;
  transition: border-color 0.15s;
}
.field-input:focus        { border-color: var(--action); }
.field-input::placeholder { color: var(--text-3); }

/* ── No-params message ── */
.no-params {
  padding: 1.25rem;
  color: var(--text-2);
  font-size: 0.85rem;
  text-align: center;
}

/* ── Confirmation view ── */
.confirm-intro {
  border-bottom: none;
  padding-bottom: 0;
}
.confirm-table {
  padding: 0.5rem 1.25rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0;
  overflow-y: auto;
  flex: 1;
}
.confirm-row {
  display: grid;
  grid-template-columns: 11rem 1fr;
  gap: 0.5rem;
  align-items: baseline;
  padding: 0.35rem 0;
  border-bottom: 1px solid var(--border);
  font-size: 0.84rem;
}
.confirm-row:last-child { border-bottom: none; }
.confirm-label {
  color: var(--text-2);
  font-size: 0.78rem;
}
.confirm-value        { color: var(--text-1); font-weight: 500; }
.confirm-value--dim   { color: var(--text-3); font-weight: 400; font-style: italic; }
.confirm-value--warn  { color: #d97706; }
.confirm-value--danger{ color: #ef4444; }

.btn-launch--confirm { background: #16a34a; }
.btn-launch--confirm:hover:not(:disabled) { background: #15803d; }

/* ── Footer ── */
.dialog-conflict { margin: 0 1.25rem 0.5rem; }
.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 0.6rem;
  padding: 0.75rem 1.25rem;
  border-top: 1px solid var(--border);
  flex-shrink: 0;
}
.btn-cancel {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text-2);
  padding: 6px 16px;
  border-radius: 5px;
  cursor: pointer;
  font-size: 0.85rem;
  transition: border-color 0.15s, color 0.15s;
}
.btn-cancel:hover { border-color: var(--text-2); color: var(--text-1); }

.btn-launch {
  background: var(--action);
  border: none;
  color: #fff;
  padding: 6px 18px;
  border-radius: 5px;
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 500;
  transition: background 0.15s;
}
.btn-launch:hover:not(:disabled) { background: var(--action-hover); }
.btn-launch:disabled {
  background: var(--action-off);
  color: var(--action-off-text);
  cursor: not-allowed;
}
</style>
