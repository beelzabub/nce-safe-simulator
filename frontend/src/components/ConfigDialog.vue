<template>
  <div class="overlay" @click.self="$emit('close')">
    <div class="dialog">

      <div class="dialog-header">
        <span class="dialog-title">Config</span>
        <button class="dialog-close" @click="$emit('close')" aria-label="Close">×</button>
      </div>

      <!-- Loading / error states -->
      <div v-if="loading" class="state-msg">Loading…</div>
      <div v-else-if="loadError" class="state-msg state-error">{{ loadError }}</div>

      <template v-else>
        <!-- Tab bar -->
        <div class="tab-bar">
          <button
            v-for="t in TABS"
            :key="t.key"
            class="tab-btn"
            :class="{ active: activeTab === t.key }"
            @click="activeTab = t.key"
          >{{ t.label }}</button>
        </div>

        <div class="dialog-body">

          <!-- ── Connection ── -->
          <div v-if="activeTab === 'connection'" class="section">
            <label class="field">
              <span class="field-label">GitLab URL</span>
              <input v-model="form.url" class="field-input" type="url" spellcheck="false" />
            </label>
            <label class="field">
              <span class="field-label">Private Token</span>
              <div class="token-wrap">
                <input
                  v-model="form.private_token"
                  class="field-input"
                  :type="showToken ? 'text' : 'password'"
                  spellcheck="false"
                  autocomplete="off"
                />
                <button class="token-toggle" @click.prevent="showToken = !showToken" type="button">
                  {{ showToken ? 'Hide' : 'Show' }}
                </button>
              </div>
            </label>
            <label class="field">
              <span class="field-label">Parent Group</span>
              <input v-model="form.parent_group" class="field-input" spellcheck="false" />
            </label>
            <label class="field">
              <span class="field-label">GitLab Namespace</span>
              <input v-model="form.gitlab_namespace" class="field-input" spellcheck="false" />
            </label>
            <label class="field field--row">
              <span class="field-label">SSL Verify</span>
              <input v-model="form.ssl_verify" type="checkbox" class="field-check" />
            </label>
            <label class="field">
              <span class="field-label">API Timeout (s)</span>
              <input v-model.number="form.api_timeout" class="field-input field-input--sm" type="number" min="10" />
            </label>
            <label class="field">
              <span class="field-label">Delete Workers</span>
              <input v-model.number="form.delete_workers" class="field-input field-input--sm" type="number" min="1" max="20" />
            </label>
          </div>

          <!-- ── Labels ── -->
          <div v-if="activeTab === 'labels'" class="section section--two-col">
            <label class="field" v-for="f in LABEL_FIELDS" :key="f.key">
              <span class="field-label">{{ f.label }}</span>
              <textarea v-model="form[f.key]" class="field-textarea" rows="4" spellcheck="false" />
            </label>
            <label class="field">
              <span class="field-label">WSJF Urgency Labels</span>
              <textarea v-model="form.wsjf_urgency" class="field-textarea" rows="4" spellcheck="false" />
            </label>
            <label class="field">
              <span class="field-label">WSJF Risk Labels</span>
              <textarea v-model="form.wsjf_risk" class="field-textarea" rows="4" spellcheck="false" />
            </label>
          </div>

          <!-- ── Weights ── -->
          <div v-if="activeTab === 'weights'" class="section">
            <label class="field">
              <span class="field-label">Fibonacci Weights <span class="field-hint">(one per line)</span></span>
              <textarea v-model="form.fibonacci_weights" class="field-textarea" rows="4" spellcheck="false" />
            </label>
            <div class="subsection-label">Epic Type Planned Weights <span class="field-hint">(one per line)</span></div>
            <label class="field" v-for="t in epicWeightTypes" :key="t">
              <span class="field-label">{{ t }}</span>
              <textarea v-model="form.epic_weights[t]" class="field-textarea" rows="3" spellcheck="false" />
            </label>
            <template v-if="form.bv_name !== undefined">
              <div class="subsection-label">Business Value Field</div>
              <label class="field">
                <span class="field-label">Field Name</span>
                <input v-model="form.bv_name" class="field-input" spellcheck="false" />
              </label>
              <label class="field">
                <span class="field-label">Select Options <span class="field-hint">(one per line)</span></span>
                <textarea v-model="form.bv_options" class="field-textarea" rows="4" spellcheck="false" />
              </label>
            </template>
          </div>

          <!-- ── Defaults ── -->
          <div v-if="activeTab === 'defaults'" class="section">
            <label class="field">
              <span class="field-label">Bootstrap Defaults <span class="field-hint">(JSON)</span></span>
              <textarea v-model="form.defaults_bootstrap" class="field-textarea field-textarea--mono" rows="14" spellcheck="false" />
              <span v-if="bootstrapJsonError" class="field-error">{{ bootstrapJsonError }}</span>
            </label>
            <label class="field">
              <span class="field-label">Tool Defaults <span class="field-hint">(JSON)</span></span>
              <textarea v-model="form.defaults_tools" class="field-textarea field-textarea--mono" rows="10" spellcheck="false" />
              <span v-if="toolsJsonError" class="field-error">{{ toolsJsonError }}</span>
            </label>
          </div>

        </div><!-- end dialog-body -->

        <!-- Footer -->
        <div class="dialog-footer">
          <span v-if="saveError"   class="footer-msg footer-msg--error">{{ saveError }}</span>
          <span v-if="saveSuccess" class="footer-msg footer-msg--ok">Saved.</span>
          <button class="btn-cancel" @click="$emit('close')">Cancel</button>
          <button class="btn-save" :disabled="saving || hasJsonErrors" @click="save">
            {{ saving ? 'Saving…' : 'Save' }}
          </button>
        </div>
      </template>

    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { getFullConfig, saveConfig } from '../api.js'

const emit = defineEmits(['close'])

const TABS = [
  { key: 'connection', label: 'Connection' },
  { key: 'labels',     label: 'Labels'     },
  { key: 'weights',    label: 'Weights'    },
  { key: 'defaults',   label: 'Defaults'   },
]

const LABEL_FIELDS = [
  { key: 'project_labels',   label: 'Project Labels'    },
  { key: 'piid_labels',      label: 'PIID Labels'       },
  { key: 'epic_type_labels', label: 'Epic Type Labels'  },
  { key: 'risk_labels',      label: 'Risk Labels'       },
  { key: 'roam_labels',      label: 'ROAM Labels'       },
  { key: 'work_type_labels', label: 'Work Type Labels'  },
  { key: 'lifecycle_labels', label: 'Lifecycle Labels'  },
]

const activeTab  = ref('connection')
const loading    = ref(true)
const loadError  = ref(null)
const saving     = ref(false)
const saveError  = ref(null)
const saveSuccess= ref(false)
const showToken  = ref(false)

// Raw config kept around so unknown fields are preserved on save
let rawConfig = {}

const form = reactive({
  // Connection
  url:              '',
  private_token:    '',
  parent_group:     '',
  gitlab_namespace: '',
  ssl_verify:       true,
  api_timeout:      300,
  delete_workers:   5,
  // Labels (one per line in textarea)
  project_labels:   '',
  piid_labels:      '',
  epic_type_labels: '',
  risk_labels:      '',
  roam_labels:      '',
  work_type_labels: '',
  lifecycle_labels: '',
  wsjf_urgency:     '',
  wsjf_risk:        '',
  // Weights
  fibonacci_weights: '',
  epic_weights:      {},
  bv_name:           undefined,
  bv_options:        '',
  // Defaults (JSON strings)
  defaults_bootstrap: '',
  defaults_tools:     '',
})

const epicWeightTypes = computed(() => Object.keys(form.epic_weights))

// ── JSON validation ────────────────────────────────────────────────────────

const bootstrapJsonError = computed(() => {
  try { JSON.parse(form.defaults_bootstrap); return null }
  catch (e) { return `Invalid JSON: ${e.message}` }
})
const toolsJsonError = computed(() => {
  try { JSON.parse(form.defaults_tools); return null }
  catch (e) { return `Invalid JSON: ${e.message}` }
})
const hasJsonErrors = computed(() => !!(bootstrapJsonError.value || toolsJsonError.value))

// ── Load / populate ────────────────────────────────────────────────────────

function arrToLines(arr) {
  return Array.isArray(arr) ? arr.join('\n') : ''
}

function populateForm(cfg) {
  rawConfig = cfg

  form.url              = cfg.url              ?? ''
  form.private_token    = cfg.private_token    ?? ''
  form.parent_group     = cfg.parent_group     ?? ''
  form.gitlab_namespace = cfg.gitlab_namespace ?? ''
  form.ssl_verify       = cfg.ssl_verify       ?? true
  form.api_timeout      = cfg.api_timeout      ?? 300
  form.delete_workers   = cfg.delete_workers   ?? 5

  for (const f of LABEL_FIELDS) {
    form[f.key] = arrToLines(cfg[f.key])
  }
  form.wsjf_urgency = arrToLines(cfg.wsjf_labels?.urgency)
  form.wsjf_risk    = arrToLines(cfg.wsjf_labels?.risk)

  form.fibonacci_weights = arrToLines(cfg.fibonacci_weights)
  form.epic_weights = {}
  for (const [type, vals] of Object.entries(cfg.epic_type_planned_weights ?? {})) {
    form.epic_weights[type] = arrToLines(vals)
  }

  if (cfg.business_value_field) {
    form.bv_name    = cfg.business_value_field.name ?? ''
    form.bv_options = arrToLines(cfg.business_value_field.select_options)
  } else {
    form.bv_name = undefined
  }

  form.defaults_bootstrap = JSON.stringify(cfg.defaults?.bootstrap ?? {}, null, 2)
  form.defaults_tools     = JSON.stringify(cfg.defaults?.tools     ?? {}, null, 2)
}

onMounted(async () => {
  try {
    const cfg = await getFullConfig()
    populateForm(cfg)
  } catch (e) {
    loadError.value = e.message
  } finally {
    loading.value = false
  }
  document.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
})

function onKeydown(e) {
  if (e.key === 'Escape') emit('close')
}

// ── Save ───────────────────────────────────────────────────────────────────

function linesToArr(str) {
  return str.split('\n').map(s => s.trim()).filter(Boolean)
}

function linesToNums(str) {
  return str.split('\n').map(s => Number(s.trim())).filter(n => !isNaN(n) && s.trim() !== '')
}

function buildConfig() {
  const cfg = { ...rawConfig }

  // Connection
  cfg.url              = form.url.trim()
  cfg.private_token    = form.private_token.trim()
  cfg.parent_group     = form.parent_group.trim()
  cfg.gitlab_namespace = form.gitlab_namespace.trim()
  cfg.ssl_verify       = form.ssl_verify
  cfg.api_timeout      = Number(form.api_timeout)
  cfg.delete_workers   = Number(form.delete_workers)

  // Labels
  for (const f of LABEL_FIELDS) {
    cfg[f.key] = linesToArr(form[f.key])
  }
  cfg.wsjf_labels = {
    ...(rawConfig.wsjf_labels ?? {}),
    urgency: linesToArr(form.wsjf_urgency),
    risk:    linesToArr(form.wsjf_risk),
  }

  // Weights
  cfg.fibonacci_weights = linesToNums(form.fibonacci_weights)
  cfg.epic_type_planned_weights = {}
  for (const [type, val] of Object.entries(form.epic_weights)) {
    cfg.epic_type_planned_weights[type] = linesToNums(val)
  }
  if (form.bv_name !== undefined) {
    cfg.business_value_field = {
      ...(rawConfig.business_value_field ?? {}),
      name:           form.bv_name.trim(),
      select_options: linesToArr(form.bv_options),
    }
  }

  // Defaults
  cfg.defaults = {
    ...(rawConfig.defaults ?? {}),
    bootstrap: JSON.parse(form.defaults_bootstrap),
    tools:     JSON.parse(form.defaults_tools),
  }

  return cfg
}

async function save() {
  if (hasJsonErrors.value) return
  saving.value     = true
  saveError.value  = null
  saveSuccess.value = false
  try {
    await saveConfig(buildConfig())
    saveSuccess.value = true
    setTimeout(() => { saveSuccess.value = false }, 3000)
  } catch (e) {
    saveError.value = e.message
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}

.dialog {
  background: var(--surface, #161b22);
  border: 1px solid var(--border, #30363d);
  border-radius: 8px;
  width: 680px;
  max-width: 95vw;
  max-height: 88vh;
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
  border-bottom: 1px solid var(--border, #30363d);
  flex-shrink: 0;
}
.dialog-title { font-size: 0.95rem; font-weight: 600; color: var(--text-1, #e6edf3); }
.dialog-close {
  background: none; border: none;
  color: var(--text-3, #6e7681); cursor: pointer; font-size: 1.1rem; line-height: 1;
}
.dialog-close:hover { color: var(--text-1, #e6edf3); }

/* ── Tabs ── */
.tab-bar {
  display: flex;
  border-bottom: 1px solid var(--border, #30363d);
  flex-shrink: 0;
}
.tab-btn {
  flex: 1;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-3, #6e7681);
  cursor: pointer;
  font-size: 0.8rem;
  font-weight: 500;
  padding: 0.55rem 0.5rem;
  transition: color 0.15s, border-color 0.15s;
}
.tab-btn:hover { color: var(--text-1, #e6edf3); }
.tab-btn.active {
  color: var(--text-1, #e6edf3);
  border-bottom-color: var(--action, #2563eb);
}

/* ── Scrollable body ── */
.dialog-body {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
}

/* ── Sections ── */
.section {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.section--two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

.subsection-label {
  font-size: 0.72rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-3, #6e7681);
  margin-top: 0.25rem;
}

/* ── Fields ── */
.field {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}
.field--row {
  flex-direction: row;
  align-items: center;
  gap: 0.6rem;
}

.field-label {
  font-size: 0.78rem;
  font-weight: 500;
  color: var(--text-2, #8b949e);
}
.field-hint {
  font-weight: 400;
  color: var(--text-3, #6e7681);
  font-size: 0.72rem;
}

.field-input {
  background: var(--bg, #0d1117);
  border: 1px solid var(--border, #30363d);
  border-radius: 5px;
  color: var(--text-1, #e6edf3);
  padding: 6px 9px;
  font-size: 0.85rem;
  outline: none;
  transition: border-color 0.15s;
}
.field-input:focus { border-color: var(--action, #2563eb); }
.field-input--sm   { max-width: 120px; }

.field-check { width: 15px; height: 15px; cursor: pointer; }

.token-wrap {
  display: flex;
  gap: 0.4rem;
}
.token-wrap .field-input { flex: 1; font-family: ui-monospace, monospace; font-size: 0.8rem; }
.token-toggle {
  background: none;
  border: 1px solid var(--border, #30363d);
  border-radius: 5px;
  color: var(--text-2, #8b949e);
  cursor: pointer;
  font-size: 0.75rem;
  padding: 0 10px;
  white-space: nowrap;
  transition: border-color 0.15s, color 0.15s;
}
.token-toggle:hover { border-color: var(--text-2); color: var(--text-1); }

.field-textarea {
  background: var(--bg, #0d1117);
  border: 1px solid var(--border, #30363d);
  border-radius: 5px;
  color: var(--text-1, #e6edf3);
  padding: 6px 9px;
  font-size: 0.82rem;
  outline: none;
  resize: vertical;
  transition: border-color 0.15s;
  min-height: 70px;
}
.field-textarea:focus        { border-color: var(--action, #2563eb); }
.field-textarea--mono        { font-family: ui-monospace, monospace; font-size: 0.78rem; }

.field-error {
  font-size: 0.75rem;
  color: #f85149;
}

/* ── Footer ── */
.dialog-footer {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.75rem 1rem;
  border-top: 1px solid var(--border, #30363d);
  flex-shrink: 0;
}
.footer-msg { font-size: 0.82rem; flex: 1; }
.footer-msg--ok    { color: #3fb950; }
.footer-msg--error { color: #f85149; }

.btn-cancel {
  margin-left: auto;
  padding: 6px 16px;
  background: none;
  border: 1px solid var(--border, #30363d);
  border-radius: 5px;
  color: var(--text-2, #8b949e);
  cursor: pointer;
  font-size: 0.85rem;
  transition: border-color 0.15s, color 0.15s;
}
.btn-cancel:hover { border-color: var(--text-2); color: var(--text-1); }

.btn-save {
  padding: 6px 16px;
  background: var(--action, #2563eb);
  border: none;
  border-radius: 5px;
  color: #fff;
  cursor: pointer;
  font-size: 0.85rem;
  font-weight: 500;
  transition: background 0.15s;
}
.btn-save:disabled { background: #1e3a8a; color: #60a5fa; cursor: not-allowed; }
.btn-save:not(:disabled):hover { background: #1d4ed8; }

/* ── State messages ── */
.state-msg {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-2, #8b949e);
  font-size: 0.9rem;
  padding: 2rem;
}
.state-error { color: #f85149; }
</style>
