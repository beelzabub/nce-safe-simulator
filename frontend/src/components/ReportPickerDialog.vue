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

      <!-- Deploy Options (epic #134, issue #215) — live per-target status, with
           an explicit pre-flight before any ECS/EKS launch. -->
      <div class="section-label">
        Deploy Options
        <span v-if="deployLoading" class="deploy-loading">checking…</span>
      </div>
      <div class="deploy-list">
        <div v-for="t in DEPLOY_TARGETS" :key="t.key" class="deploy-row">

          <!-- Already deployed → show URL + Destroy instead of a checkbox -->
          <template v-if="statusFor(t.key).state === 'deployed'">
            <span class="deploy-name">{{ t.label }}</span>
            <span class="deploy-badge deploy-badge--ok">deployed</span>
            <a
              v-if="statusFor(t.key).url"
              :href="statusFor(t.key).url"
              target="_blank"
              rel="noopener"
              class="deploy-url"
              :title="statusFor(t.key).url"
            >{{ shortUrl(statusFor(t.key).url) }}</a>
            <button class="deploy-destroy" @click="requestDeploy(t.key, 'destroy')">Destroy</button>
          </template>

          <!-- Deploy/destroy in flight (running job or CloudFormation busy) -->
          <template v-else-if="inFlight(t.key)">
            <span class="deploy-name">{{ t.label }}</span>
            <span class="deploy-badge deploy-badge--busy">● {{ inFlightLabel(t.key) }}</span>
            <span class="deploy-logline">{{ lastLogLine(t.key) }}</span>
          </template>

          <!-- Selectable → checkbox + current status -->
          <template v-else>
            <label class="check-label deploy-check">
              <input type="checkbox" :value="t.key" v-model="deployTargets" />
              {{ t.label }}
            </label>
            <span class="deploy-badge" :class="badgeClass(t.key)">{{ stateLabel(t.key) }}</span>
          </template>

        </div>

        <div v-if="selectableChecked.length" class="deploy-actions">
          <button class="btn-deploy" @click="startDeploy">
            Deploy {{ selectableChecked.length }} target{{ selectableChecked.length !== 1 ? 's' : '' }}…
          </button>
        </div>
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

      <!-- Equivalent CLI command(s) for the current selection — pinned inside
           the dialog so it stays visible while the modal covers the docked bar
           (issue #185). -->
      <CliCommandStrip
        class="dialog-cmd"
        :command="cliCommand"
        empty-hint="Select at least one report to see its CLI command"
      />

    </div>
  </div>

  <!-- Pre-flight confirmation for a deploy/destroy (issue #215). -->
  <DeployPreflightDialog
    v-if="preflight"
    :target="preflight.target"
    :action="preflight.action"
    @confirm="confirmDeploy"
    @cancel="cancelDeploy"
  />
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { loadStored, saveStored } from '../composables/useLocalStorage.js'
import { buildReportCommand } from '../composables/useCliCommand.js'
import { useCommandPreview } from '../composables/useCommandPreview.js'
import { useDeployStatus } from '../composables/useDeployStatus.js'
import { useDurableJobs } from '../composables/useDurableJobs.js'
import CliCommandStrip from './CliCommandStrip.vue'
import DeployPreflightDialog from './DeployPreflightDialog.vue'

const props = defineProps({
  reports: { type: Array, required: true },
})
const emit = defineEmits(['launch', 'close'])

const ALL_FORMATS = ['markdown', 'plotly', 'interactive']
const DEPLOY_TARGETS = [
  { key: 's3',  label: 'S3' },
  { key: 'ecs', label: 'ECS' },
  { key: 'eks', label: 'EKS' },
]
const DEPLOY_KEYS = new Set(DEPLOY_TARGETS.map(t => t.key))
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
    deployTargets: Array.isArray(saved.deployTargets)
      ? saved.deployTargets.filter(k => DEPLOY_KEYS.has(k))
      : [],
  }
}

const _init          = _loadState()
const selectedFormats = ref(_init.formats)
const selectedKeys    = ref(_init.keys)
const useLast         = ref(_init.useLast)
const deployTargets   = ref(_init.deployTargets)   // checked targets, persisted

watch([selectedFormats, selectedKeys, useLast, deployTargets], () => {
  saveStored(STORAGE_KEY, {
    formats: selectedFormats.value,
    keys:    selectedKeys.value,
    useLast: useLast.value,
    deployTargets: deployTargets.value,
  })
}, { deep: true })

// ── Deploy Options (issue #215) ──────────────────────────────────────────────
// Live status polls only while this dialog is mounted; deploy/destroy runs use
// the durable job engine so they survive a refresh and reattach on reload.
const _active = ref(true)
const { status: deployStatus, loading: deployLoading, refresh: refreshDeploy } =
  useDeployStatus(_active)
const { runningJobs, launchDeployJob, reattach: reattachJobs, linesFor } = useDurableJobs()

function statusFor(target) {
  return deployStatus.value?.[target] || { state: 'unknown', url: null }
}

const STATE_LABELS = {
  not_deployed: 'not deployed',
  deploying:    'deploying…',
  destroying:   'destroying…',
  deployed:     'deployed',
  error:        'error',
  unknown:      'checking…',
}
function stateLabel(target) {
  return STATE_LABELS[statusFor(target).state] || statusFor(target).state
}
function badgeClass(target) {
  const s = statusFor(target).state
  if (s === 'error')  return 'deploy-badge--err'
  if (s === 'deploying' || s === 'destroying') return 'deploy-badge--busy'
  return 'deploy-badge--idle'
}

// A deploy/destroy job for this target that hasn't finished yet.
function deployJobFor(target) {
  return runningJobs.value.find(j => j.kind === 'deploy' && j.params?.target === target)
}
function inFlight(target) {
  const s = statusFor(target).state
  return !!deployJobFor(target) || s === 'deploying' || s === 'destroying'
}
function inFlightLabel(target) {
  const job = deployJobFor(target)
  if (job) return job.params?.action === 'destroy' ? 'destroying…' : 'deploying…'
  return statusFor(target).state === 'destroying' ? 'destroying…' : 'deploying…'
}
function lastLogLine(target) {
  const job = deployJobFor(target)
  if (!job) return ''
  const lines = linesFor(job.id).filter(l => l.trim())
  return lines.length ? lines[lines.length - 1] : ''
}

function shortUrl(url) {
  try { return new URL(url).host } catch { return url }
}

// Only targets shown as a checkbox (not deployed, not in flight) count as
// selectable for the Deploy button.
const selectableChecked = computed(() =>
  deployTargets.value.filter(t =>
    statusFor(t).state !== 'deployed' && !inFlight(t)))

// Pre-flight queue: confirm each checked target one at a time.
const preflight   = ref(null)   // { target, action } | null
const _queue      = ref([])

function startDeploy() {
  _queue.value = [...selectableChecked.value]
  _advanceQueue('deploy')
}
function requestDeploy(target, action) {
  _queue.value = []
  preflight.value = { target, action }
}
function _advanceQueue(action) {
  const next = _queue.value.shift()
  preflight.value = next ? { target: next, action } : null
}

async function confirmDeploy() {
  const { target, action } = preflight.value
  try {
    await launchDeployJob(target, action)
  } catch (e) {
    // Surface nothing intrusive here — the job list shows failures; just log.
    console.error(`deploy ${action} ${target} failed to launch:`, e)
  }
  // Uncheck a target we've just launched a deploy for.
  if (action === 'deploy') {
    deployTargets.value = deployTargets.value.filter(t => t !== target)
  }
  refreshDeploy()
  if (_queue.value.length) _advanceQueue(action)
  else preflight.value = null
}
function cancelDeploy() {
  _queue.value = []
  preflight.value = null
}

const allSelected = computed(() => selectedKeys.value.length === props.reports.length)
const canLaunch   = computed(() => selectedKeys.value.length > 0 && selectedFormats.value.length > 0)

// Equivalent CLI command(s) for the current selection — one `-r` line per
// chosen report, sharing --formats / --last (#140) — shown in the in-dialog
// CliCommandStrip and mirrored to the docked CommandBar. Only non-empty commands
// are mirrored, so closing the picker leaves the last command on the bar for
// later reference instead of wiping it (issue #185).
const { setPreview } = useCommandPreview()
const cliCommand = computed(() =>
  buildReportCommand(selectedKeys.value, selectedFormats.value, useLast.value))
watch(cliCommand, cmd => { if (cmd) setPreview(cmd) }, { immediate: true })

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
  if (e.key === 'Escape') {
    if (preflight.value) cancelDeploy()   // Esc backs out of pre-flight first
    else emit('close')
  }
}
onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  // Re-adopt any deploy/destroy job that was already running before the dialog
  // (or the whole page) was (re)opened, so its progress shows here immediately.
  reattachJobs()
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
})

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

/* ── Deploy Options (issue #215) ── */
.deploy-loading {
  font-size: 0.7rem;
  font-weight: 400;
  text-transform: none;
  letter-spacing: 0;
  color: var(--text-3);
}
.deploy-list {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  padding: 0.15rem 1rem 0.65rem;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.deploy-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  min-height: 1.6rem;
}
.deploy-check { flex-shrink: 0; }
.deploy-name {
  font-size: 0.85rem;
  color: var(--text-1);
  min-width: 3rem;
}
.deploy-badge {
  font-size: 0.7rem;
  border-radius: 3px;
  padding: 1px 6px;
  font-weight: 600;
  white-space: nowrap;
}
.deploy-badge--idle { color: var(--text-3); }
.deploy-badge--ok   { background: var(--badge-run-bg, rgba(40,160,90,0.15)); color: #3fa66a; }
.deploy-badge--busy { background: var(--badge-run-bg); color: var(--badge-run-text); }
.deploy-badge--err  { color: #f87171; }
.deploy-url {
  font-size: 0.76rem;
  color: var(--action);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.deploy-url:hover { text-decoration: underline; }
.deploy-logline {
  font-size: 0.72rem;
  color: var(--text-3);
  font-family: monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}
.deploy-destroy {
  margin-left: auto;
  padding: 2px 10px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: 4px;
  color: #d16b57;
  cursor: pointer;
  font-size: 0.76rem;
  transition: border-color 0.15s, color 0.15s;
}
.deploy-destroy:hover { border-color: #d16b57; color: #b1442f; }
.deploy-actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 0.15rem;
}
.btn-deploy {
  padding: 4px 12px;
  background: var(--action);
  border: none;
  border-radius: 5px;
  color: #fff;
  cursor: pointer;
  font-size: 0.8rem;
  transition: background 0.15s;
}
.btn-deploy:hover { background: var(--action-hover); }

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

/* ── In-dialog CLI command strip (issue #185) ── */
.dialog-cmd {
  flex-shrink: 0;
  border-top: 1px solid var(--border);
  background: var(--surface-alt);
}

/* ── Mobile (issue #160): the dialog takes the whole screen ── */
@media (max-width: 768px) {
  .overlay { padding: 0; }
  .dialog {
    width: 100vw;
    max-width: none;
    height: 100vh;    /* fallback for browsers without dvh */
    height: 100dvh;   /* tracks the real visible height under mobile URL bars */
    max-height: none;
    border-radius: 0;
  }
}

</style>
