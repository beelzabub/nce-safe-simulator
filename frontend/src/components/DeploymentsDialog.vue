<template>
  <div class="overlay" @click.self="$emit('close')">
    <div class="dialog">

      <div class="dialog-header">
        <span class="dialog-title">
          Deployments
          <span v-if="deployLoading" class="dep-loading">checking…</span>
        </span>
        <button class="dialog-close" @click="$emit('close')" aria-label="Close">×</button>
      </div>

      <div class="dialog-body">
        <p class="dep-lede">
          Stand the app up on AWS, or tear it down. Each target shows its live status; deploy and
          destroy run as durable jobs that survive a page refresh.
        </p>

        <div class="dep-list">
          <div v-for="t in DEPLOY_TARGETS" :key="t.key" class="dep-row">
            <span class="dep-dot" :class="dotClass(t.key)" :title="stateLabel(t.key)"></span>

            <div class="dep-main">
              <div class="dep-title">
                <span class="dep-name">{{ t.label }}</span>
                <span class="dep-desc">{{ t.desc }}</span>
              </div>
              <div class="dep-meta">
                <span class="dep-status" :class="statusClass(t.key)">{{ stateLabel(t.key) }}</span>
                <a
                  v-if="statusFor(t.key).state === 'deployed' && statusFor(t.key).url"
                  :href="statusFor(t.key).url"
                  target="_blank"
                  rel="noopener"
                  class="dep-url"
                  :title="statusFor(t.key).url"
                >{{ shortUrl(statusFor(t.key).url) }} ↗</a>
                <!-- Server-supplied context: ECR image count / S3 propagation note. -->
                <span v-if="statusFor(t.key).detail" class="dep-detail" :title="statusFor(t.key).detail">
                  {{ statusFor(t.key).detail }}
                </span>
              </div>

              <!-- S3 publish target: pick an existing bucket or create a new,
                   globally-unique one (issue #225). -->
              <div v-if="showBucketPicker(t.key)" class="dep-bucket">
                <label class="dep-bucket-label">Bucket</label>
                <select v-model="selectedBucket" class="dep-bucket-select">
                  <option v-for="name in bucketOptions" :key="name" :value="name">{{ name }}</option>
                  <option :value="NEW">＋ Create new…</option>
                </select>
                <template v-if="selectedBucket === NEW">
                  <input
                    v-model="newBase"
                    class="dep-bucket-input"
                    spellcheck="false"
                    placeholder="base name"
                  />
                  <span class="dep-bucket-preview" :title="resolvedNewBucket">→ {{ resolvedNewBucket }}</span>
                </template>
              </div>
            </div>

            <div class="dep-action">
              <button
                v-if="canDestroy(t.key)"
                class="dep-btn dep-btn--destroy"
                @click="requestDeploy(t.key, 'destroy')"
              >Destroy</button>
              <button
                v-else-if="inFlight(t.key)"
                class="dep-btn dep-btn--busy"
                disabled
              >{{ inFlightLabel(t.key) }}</button>
              <button
                v-else
                class="dep-btn dep-btn--deploy"
                @click="requestDeploy(t.key, 'deploy')"
              >Deploy</button>
            </div>
          </div>
        </div>
      </div>

      <div class="dialog-footer">
        <button class="btn-cancel" @click="$emit('close')">Close</button>
      </div>

    </div>
  </div>

  <!-- Pre-flight confirmation for a deploy/destroy (issue #215), reused as-is. -->
  <DeployPreflightDialog
    v-if="preflight"
    :target="preflight.target"
    :action="preflight.action"
    @confirm="confirmDeploy"
    @cancel="cancelDeploy"
  />
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { getS3Buckets } from '../api.js'
import { useDeployStatus } from '../composables/useDeployStatus.js'
import { useJobs } from '../composables/useJobs.js'
import { useMainView } from '../composables/useMainView.js'
import DeployPreflightDialog from './DeployPreflightDialog.vue'

const emit = defineEmits(['close'])

const DEPLOY_TARGETS = [
  { key: 's3',  label: 'S3',  desc: 'Static site (CloudFront + OAC)' },
  { key: 'ecr', label: 'ECR', desc: 'Container image registry — required by ECS/EKS' },
  { key: 'ecs', label: 'ECS', desc: 'Fargate service' },
  { key: 'eks', label: 'EKS', desc: 'Kubernetes cluster' },
]

// Live status polls only while this dialog is mounted. Deploy/destroy runs go
// through the shared job runner (useJobs), so launching one drops the user onto
// the streaming job card — the same UX as a report run — and it survives a
// refresh (HomeView reattaches running jobs on load).
const _active = ref(true)
const { status: deployStatus, loading: deployLoading, refresh: refreshDeploy } =
  useDeployStatus(_active)
const { launchDeploy, runningDeployJob } = useJobs()
const { showMain } = useMainView()

function statusFor(target) {
  return deployStatus.value?.[target] || { state: 'unknown', url: null }
}

const STATE_LABELS = {
  not_deployed: 'not deployed',
  deploying:    'deploying…',
  destroying:   'destroying…',
  deployed:     'deployed',
  no_image:     'repo created — no image',   // ECR only (issue #234)
  error:        'error',
  unknown:      'checking…',
}
function stateLabel(target) {
  return STATE_LABELS[statusFor(target).state] || statusFor(target).state
}

// Red/green status indicator: green when deployed, amber while a deploy/destroy
// is in flight, red for not-deployed/error. The visible status text carries the
// same meaning, so the dot is decorative (no hover-only affordance).
function dotClass(target) {
  const s = statusFor(target).state
  if (s === 'deployed') return 'dep-dot--ok'
  if (s === 'deploying' || s === 'destroying') return 'dep-dot--busy'
  if (s === 'no_image') return 'dep-dot--warn'   // half-way there: repo, no image
  if (s === 'unknown')  return 'dep-dot--unknown'
  return 'dep-dot--off'
}
function statusClass(target) {
  const s = statusFor(target).state
  if (s === 'deployed') return 'dep-status--ok'
  if (s === 'deploying' || s === 'destroying' || s === 'no_image') return 'dep-status--busy'
  if (s === 'error')    return 'dep-status--err'
  return 'dep-status--off'
}

// Destroy applies to anything that exists server-side: a deployed target, or
// an ECR repo that exists but holds no image yet (issue #234).
function canDestroy(target) {
  const s = statusFor(target).state
  return s === 'deployed' || s === 'no_image'
}

// A running deploy/destroy job for this target, if any (from the shared runner).
function deployJobFor(target) {
  return runningDeployJob(target)
}
function inFlight(target) {
  const s = statusFor(target).state
  return !!deployJobFor(target) || s === 'deploying' || s === 'destroying'
}
function inFlightLabel(target) {
  const job = deployJobFor(target)
  if (job) return job.params?.action === 'destroy' ? 'Destroying…' : 'Deploying…'
  return statusFor(target).state === 'destroying' ? 'Destroying…' : 'Deploying…'
}

function shortUrl(url) {
  try { return new URL(url).host } catch { return url }
}

// ── S3 bucket selector (issue #225) ─────────────────────────────────────────
// S3 bucket names are globally unique, so an S3 publish targets either an
// existing bucket (dropdown) or a new one whose name is the deterministic
// `${base}-${accountId}`. Choices are fetched once when the dialog opens.
const NEW = '__new__'
const bucketData = ref({ buckets: [], default: null, account_id: null, suggested_base: 'nce-safe-sim-site' })
const selectedBucket = ref(NEW)
const newBase = ref('nce-safe-sim-site')

const bucketOptions = computed(() => {
  const names = bucketData.value.buckets.map(b => b.name)
  const d = bucketData.value.default
  if (d && !names.includes(d)) names.unshift(d)
  return names
})
const resolvedNewBucket = computed(() => {
  const base = (newBase.value || '').trim()
  const acct = bucketData.value.account_id
  return base && acct ? `${base}-${acct}` : base
})
const chosenS3Bucket = computed(() =>
  selectedBucket.value === NEW ? resolvedNewBucket.value : selectedBucket.value)

async function loadBuckets() {
  const data = await getS3Buckets()
  bucketData.value = data
  newBase.value = data.suggested_base || 'nce-safe-sim-site'
  // Default to the live/configured bucket when it's a real existing choice,
  // otherwise fall to the "Create new" path.
  selectedBucket.value =
    data.default && bucketOptions.value.includes(data.default) ? data.default : NEW
}

function showBucketPicker(target) {
  return target === 's3'
    && statusFor('s3').state !== 'deployed'
    && !inFlight('s3')
}

// Pre-flight: each target's Deploy/Destroy button opens the confirm directly.
const preflight = ref(null)   // { target, action } | null

function requestDeploy(target, action) {
  preflight.value = { target, action }
}
function confirmDeploy() {
  const { target, action } = preflight.value
  const bucket = (target === 's3' && action === 'deploy') ? (chosenS3Bucket.value || null) : null
  // Launch through the shared runner so a live streaming job card appears, then
  // drop the user onto the jobs view to watch it (success or failure).
  launchDeploy(target, action, bucket)
  refreshDeploy()
  preflight.value = null
  showMain('jobs')
  emit('close')
}
function cancelDeploy() {
  preflight.value = null
}

function onKeydown(e) {
  if (e.key === 'Escape') {
    if (preflight.value) cancelDeploy()   // Esc backs out of pre-flight first
    else emit('close')
  }
}
onMounted(() => {
  document.addEventListener('keydown', onKeydown)
  loadBuckets()
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
})
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
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
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
.dialog-title { font-size: 0.95rem; font-weight: 600; color: var(--text-1); display: flex; align-items: baseline; gap: 0.5rem; }
.dep-loading { font-size: 0.7rem; font-weight: 400; color: var(--text-3); }
.dialog-close {
  background: none; border: none;
  color: var(--text-3); cursor: pointer; font-size: 1.4rem; line-height: 1;
}
.dialog-close:hover { color: var(--text-1); }

/* ── Body ── */
.dialog-body { padding: 0.85rem 1rem; overflow-y: auto; }
.dep-lede { margin: 0 0 0.85rem; color: var(--text-2); font-size: 0.83rem; line-height: 1.45; }

.dep-list { display: flex; flex-direction: column; gap: 0.55rem; }
.dep-row {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  padding: 0.6rem 0.7rem;
  border: 1px solid var(--border);
  border-radius: 6px;
}

/* Red/green status indicator — decorative; the status text carries the meaning. */
.dep-dot {
  flex-shrink: 0;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--text-3);
}
.dep-dot--ok      { background: #3fa66a; box-shadow: 0 0 0 2px rgba(63,166,106,0.18); }
.dep-dot--off     { background: #e05656; box-shadow: 0 0 0 2px rgba(224,86,86,0.18); }
.dep-dot--unknown { background: var(--text-3); }
.dep-dot--busy {
  background: #e0a13f;
  box-shadow: 0 0 0 2px rgba(224,161,63,0.18);
  animation: dep-pulse 1.1s ease-in-out infinite;
}
/* Static amber — a partial state (ECR repo without an image), not activity. */
.dep-dot--warn {
  background: #e0a13f;
  box-shadow: 0 0 0 2px rgba(224,161,63,0.18);
}
@keyframes dep-pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }

.dep-main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 0.15rem; }
.dep-title { display: flex; align-items: baseline; gap: 0.5rem; min-width: 0; }
.dep-name { font-size: 0.9rem; font-weight: 600; color: var(--text-1); }
.dep-desc {
  font-size: 0.78rem;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dep-meta { display: flex; align-items: baseline; gap: 0.55rem; min-width: 0; }
.dep-status { font-size: 0.76rem; font-weight: 600; }
.dep-status--ok  { color: #3fa66a; }
.dep-status--off { color: #e05656; }
.dep-status--busy { color: var(--badge-run-text, #e0a13f); }
.dep-status--err { color: #e05656; }
.dep-url {
  font-size: 0.76rem;
  color: var(--action);
  text-decoration: none;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dep-url:hover { text-decoration: underline; }
.dep-detail {
  font-size: 0.74rem;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* S3 bucket picker (issue #225) */
.dep-bucket {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 0.35rem;
}
.dep-bucket-label {
  font-size: 0.72rem;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.dep-bucket-select,
.dep-bucket-input {
  font-size: 0.78rem;
  padding: 2px 6px;
  background: var(--surface-alt, var(--surface));
  color: var(--text-1);
  border: 1px solid var(--border);
  border-radius: 4px;
  max-width: 100%;
}
.dep-bucket-select { max-width: 15rem; }
.dep-bucket-input { min-width: 8rem; }
.dep-bucket-preview {
  font-size: 0.74rem;
  font-family: monospace;
  color: var(--text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dep-action { flex-shrink: 0; }
.dep-btn {
  padding: 5px 14px;
  border-radius: 5px;
  font-size: 0.8rem;
  cursor: pointer;
  border: 1px solid var(--border);
  background: transparent;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}
.dep-btn--deploy { color: #fff; background: var(--action); border-color: var(--action); }
.dep-btn--deploy:hover { background: var(--action-hover); border-color: var(--action-hover); }
.dep-btn--destroy { color: #d16b57; }
.dep-btn--destroy:hover { border-color: #d16b57; color: #b1442f; }
.dep-btn--busy { color: var(--text-3); cursor: not-allowed; }

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
}
.btn-cancel:hover { border-color: var(--text-2); color: var(--text-1); }

@media (max-width: 768px) {
  .overlay { padding: 0; }
  .dialog {
    width: 100vw;
    max-width: none;
    height: 100vh;
    height: 100dvh;
    max-height: none;
    border-radius: 0;
  }
}
</style>
