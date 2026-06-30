<template>
  <div class="overlay" @click.self="$emit('close')">
    <div class="dialog">

      <div class="dialog-header">
        <span class="dialog-title">Config</span>
        <button class="dialog-close" @click="$emit('close')" aria-label="Close">×</button>
      </div>

      <div v-if="loading" class="state-msg">Loading…</div>
      <div v-else-if="loadError" class="state-msg state-error">{{ loadError }}</div>

      <template v-else>
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

          <!-- ── Bootstrap ── -->
          <div v-if="activeTab === 'bootstrap'" class="section">
            <div class="subsection-label">Counts <span class="field-hint">(min / max / desired)</span></div>
            <div class="range-grid">
              <span></span>
              <span class="range-col-hdr">Min</span>
              <span class="range-col-hdr">Max</span>
              <span class="range-col-hdr">Desired</span>
              <div
                v-for="f in BOOTSTRAP_RANGE_FIELDS"
                :key="f.key"
                style="display:contents"
              >
                <span class="range-row-label">{{ f.label }}</span>
                <input v-model.number="form.bootstrap[f.key].min"     type="number" min="0" class="field-input range-input" />
                <input v-model.number="form.bootstrap[f.key].max"     type="number" min="0" class="field-input range-input" />
                <input v-model.number="form.bootstrap[f.key].desired" type="number" min="0" class="field-input range-input" />
              </div>
            </div>
            <div class="subsection-label" style="margin-top:0.5rem">Ratios &amp; Rates</div>
            <div class="two-col-grid">
              <label class="field" v-for="f in BOOTSTRAP_SCALAR_FIELDS" :key="f.key">
                <span class="field-label">{{ f.label }}</span>
                <input v-model.number="form.bootstrap[f.key]" type="number" :step="f.step ?? 1" :min="f.min ?? 0" :max="f.max" class="field-input field-input--sm" />
              </label>
            </div>
            <div class="subsection-label" style="margin-top:0.5rem">Block Seeding</div>
            <label class="field field--row">
              <span class="field-label">Seed Blocks</span>
              <input v-model="form.bootstrap.seed_blocks" type="checkbox" class="field-check" />
            </label>
          </div>

          <!-- ── Tools ── -->
          <div v-if="activeTab === 'tools'" class="section">
            <div class="two-col-grid">
              <label class="field" v-for="f in TOOLS_FIELDS" :key="f.key">
                <span class="field-label">{{ f.label }}</span>
                <input v-model.number="form.tools[f.key]" type="number" :step="f.step ?? 1" :min="f.min ?? 0" :max="f.max" class="field-input field-input--sm" />
              </label>
            </div>
            <div class="subsection-label" style="margin-top:0.5rem">ROAM Risk Relations</div>
            <div class="range-grid range-grid--two">
              <span></span>
              <span class="range-col-hdr">Min</span>
              <span class="range-col-hdr">Max</span>
              <div style="display:contents">
                <span class="range-row-label">Count</span>
                <input v-model.number="form.tools.roam_risk_relations.min" type="number" min="0" class="field-input range-input" />
                <input v-model.number="form.tools.roam_risk_relations.max" type="number" min="0" class="field-input range-input" />
              </div>
            </div>
          </div>

          <!-- ── Reports ── -->
          <div v-if="activeTab === 'reports'" class="section">
            <div class="subsection-label">Stuck Item Age Thresholds <span class="field-hint">(days)</span></div>
            <div class="two-col-grid">
              <label class="field" v-for="f in STUCK_FIELDS" :key="f.key">
                <span class="field-label">{{ f.label }}</span>
                <input v-model.number="form.stuck_thresholds[f.key]" type="number" min="1" class="field-input field-input--sm" />
              </label>
            </div>
          </div>

          <!-- ── Help reference ── -->
          <div v-if="activeTab === 'help'" class="section help-ref">
            <template v-for="section in HELP_SECTIONS" :key="section.title">
              <div class="subsection-label help-section-label">{{ section.title }}</div>
              <div class="help-table">
                <template v-for="f in section.fields" :key="f.label">
                  <span class="help-table-name">{{ f.label }}</span>
                  <span class="help-table-desc">{{ f.help }}</span>
                </template>
              </div>
            </template>
          </div>

        </div><!-- end dialog-body -->

        <!-- Footer -->
        <div class="dialog-footer">
          <span v-if="saveError"   class="footer-msg footer-msg--error">{{ saveError }}</span>
          <span v-if="saveSuccess" class="footer-msg footer-msg--ok">Saved.</span>
          <button class="btn-cancel" @click="$emit('close')">Cancel</button>
          <button class="btn-save" :disabled="saving" @click="save">
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
  { key: 'bootstrap',  label: 'Bootstrap'  },
  { key: 'tools',      label: 'Tools'      },
  { key: 'reports',    label: 'Reports'    },
  { key: 'help',       label: 'Help'       },
]

const LABEL_FIELDS = [
  { key: 'project_labels',   label: 'Project Labels',   help: 'Labels that tag epics and issues to a specific project within the ART (e.g. project::DCGS). One label per line.' },
  { key: 'piid_labels',      label: 'PIID Labels',      help: 'PI Iteration ID labels used to assign issues to a specific PI quarter (e.g. PIID::2025Q1). One label per line.' },
  { key: 'epic_type_labels', label: 'Epic Type Labels', help: 'Labels that classify the level of an epic: portfolio epic, capability, or feature (e.g. epic::capability). One label per line.' },
  { key: 'risk_labels',      label: 'Risk Labels',      help: 'Labels indicating the risk level of an epic or issue (e.g. risk::high). Used by the risk register report. One label per line.' },
  { key: 'roam_labels',      label: 'ROAM Labels',      help: 'ROAM status labels applied to PI risk epics: Resolved, Owned, Accepted, Mitigated (e.g. roam::owned). One label per line.' },
  { key: 'work_type_labels', label: 'Work Type Labels', help: 'Labels classifying the nature of work an issue represents (e.g. type::feature, type::defect). One label per line.' },
  { key: 'lifecycle_labels', label: 'Lifecycle Labels', help: 'Labels tracking the lifecycle stage of an epic from funnel through done (e.g. lifecycle::backlog). One label per line.' },
]

const BOOTSTRAP_RANGE_FIELDS = [
  { key: 'num_value_streams', label: 'Value Streams',            help: 'Number of Value Stream subgroups to create under the parent group. The desired value is used as the target; actual count is randomised within min–max.' },
  { key: 'num_arts',          label: 'ARTs',                     help: 'Number of Agile Release Train subgroups to create per Value Stream. Each ART gets its own set of teams, capabilities, and features.' },
  { key: 'num_teams',         label: 'Teams per ART',            help: 'Number of team-level GitLab groups to create inside each ART. Teams own features and their associated issues.' },
  { key: 'portfolio_epics',   label: 'Portfolio Epics',          help: 'Number of Portfolio-level epics to generate at the parent group level. These are the highest-level epics in the SAFe hierarchy.' },
  { key: 'vs_caps_per_vs',    label: 'VS Capabilities per VS',   help: 'Number of Value Stream Capability epics to generate per Value Stream. Set min to 0 to allow VS\'s with no capabilities.' },
  { key: 'art_caps_per_art',  label: 'ART Capabilities per ART', help: 'Number of ART-level Capability epics to generate per ART. These roll up to portfolio epics and contain the ART\'s features.' },
  { key: 'features_per_team', label: 'Features per Team',        help: 'Number of Feature-level epics to generate per team. Features are the unit of work tracked across a PI.' },
]

const BOOTSTRAP_SCALAR_FIELDS = [
  { key: 'direct_feature_ratio',       label: 'Direct Feature Ratio',     step: 0.01, min: 0, max: 1, help: 'Fraction (0–1) of features created directly under an ART rather than under a capability. 0.85 means 85% of features are ART-direct.' },
  { key: 'history_close_rate_min',     label: 'History Close Rate Min',   step: 0.01, min: 0, max: 1, help: 'Minimum fraction of past-PI issues that will be closed when generating historical PI data. Actual rate is randomised between min and max.' },
  { key: 'history_close_rate_max',     label: 'History Close Rate Max',   step: 0.01, min: 0, max: 1, help: 'Maximum fraction of past-PI issues closed during history generation. Keep above History Close Rate Min.' },
  { key: 'current_pi_issue_close_pct', label: 'Current PI Issue Close %', step: 0.01, min: 0, max: 1, help: 'Fraction of current-PI issues to close when simulating PI progress mid-increment. Represents how far through the PI the simulation is set.' },
  { key: 'epic_block_percent',         label: 'Epic Block %',            step: 1, min: 0, max: 100, help: 'Percent of epics to block when seeding blocks during --create (only used when Seed Blocks is on).' },
  { key: 'issue_block_percent',        label: 'Issue Block %',           step: 1, min: 0, max: 100, help: 'Percent of open issues to block when seeding blocks during --create (only used when Seed Blocks is on).' },
]

const TOOLS_FIELDS = [
  { key: 'close_percent',                label: 'Close Percent',             min: 0, max: 100, help: 'Default percentage of open issues to close when running the Close Issues tool. Can be overridden per run.' },
  { key: 'generate_epic_blocks_count',   label: 'Generate Epic Blocks',      min: 1,           help: 'Number of blocking relationships to create between epics when running the Generate Epic Blocks tool.' },
  { key: 'generate_issue_blocks_count',  label: 'Generate Issue Blocks',     min: 1,           help: 'Number of blocking relationships to create between issues when running the Generate Issue Blocks tool.' },
  { key: 'simulate_pi_progress_percent', label: 'Simulate PI Progress %',    min: 0, max: 100, help: 'Default PI completion percentage used by the Simulate PI Progress tool. Drives how many issues are closed and weight progress applied.' },
  { key: 'generate_issues_count',        label: 'Generate Issues Count',     min: 1,           help: 'Number of child issues to generate per epic when running the Generate Issues tool.' },
  { key: 'weight_drift_threshold',       label: 'Weight Drift Threshold',    min: 0,           help: 'Maximum percentage deviation between planned and actual weights before an epic is flagged as drifted in reports.' },
]

const STUCK_FIELDS = [
  { key: 'lifecycle::funnel',    label: 'Funnel — stale after',    help: 'Epics in lifecycle::funnel older than this many days (measured from created_at) are flagged as stale in the Epic Lifecycle report. Default 90.' },
  { key: 'lifecycle::analyzing', label: 'Analyzing — stuck after', help: 'Epics in lifecycle::analyzing older than this many days are flagged as stuck (Lean Business Case overdue for a decision). Default 30.' },
  { key: 'lifecycle::backlog',   label: 'Backlog — stuck after',   help: 'Epics in lifecycle::backlog older than this many days are flagged as stuck (approved work waiting too long for capacity). Default 60.' },
]

const HELP_SECTIONS = [
  {
    title: 'Connection',
    fields: [
      { label: 'GitLab URL',       help: 'Base URL of the GitLab instance (e.g. https://gitlab.com). All API calls are made relative to this URL.' },
      { label: 'Private Token',    help: 'Personal access token with api scope. Used to authenticate every GitLab API call. Keep this secret — never commit it to version control.' },
      { label: 'Parent Group',     help: 'Top-level GitLab group that owns all Value Stream subgroups. Bootstrap creates subgroups and projects directly inside this group.' },
      { label: 'GitLab Namespace', help: 'GitLab namespace path (user or group) used when constructing project URLs and API calls. Usually matches the parent group slug.' },
      { label: 'SSL Verify',       help: 'Whether to verify SSL certificates on API calls. Leave enabled for production instances. Disable only for self-signed certificates in lab environments.' },
      { label: 'API Timeout',      help: 'HTTP request timeout in seconds applied to every GitLab API call. Increase for slow or heavily-loaded GitLab instances, or when fetching large groups.' },
      { label: 'Delete Workers',   help: 'Number of parallel worker threads used when bulk-deleting GitLab objects. Higher values are faster but may hit API rate limits.' },
    ],
  },
  {
    title: 'Labels',
    fields: [
      ...LABEL_FIELDS,
      { label: 'WSJF Urgency Labels', help: 'Labels encoding WSJF Time Criticality / Urgency scores. Each label\'s numeric suffix is used as the score value (e.g. wsjf-urgency::8 → 8).' },
      { label: 'WSJF Risk Labels',    help: 'Labels encoding WSJF Risk Reduction / Opportunity Enablement scores. Each label\'s numeric suffix is used as the score value.' },
    ],
  },
  {
    title: 'Weights',
    fields: [
      { label: 'Fibonacci Weights',         help: 'Story point values offered as choices during simulation. Used when randomly assigning weights to issues and epics. Standard SAFe Fibonacci sequence.' },
      { label: 'Epic Type Planned Weights', help: 'Weight values (story points) randomly assigned to epics of each type when generating planned weights during bootstrap or simulation. One value per line per type.' },
      { label: 'Business Value Field Name', help: 'Name of the GitLab custom field used to record Business Value scores on epics. Must match the field name exactly as configured in GitLab.' },
      { label: 'Business Value Options',    help: 'Allowed values for the Business Value select field. These must match the select options configured in GitLab. One value per line.' },
    ],
  },
  {
    title: 'Bootstrap — Counts (min / max / desired)',
    fields: BOOTSTRAP_RANGE_FIELDS,
  },
  {
    title: 'Bootstrap — Ratios & Rates',
    fields: BOOTSTRAP_SCALAR_FIELDS,
  },
  {
    title: 'Tools',
    fields: [
      ...TOOLS_FIELDS,
      { label: 'ROAM Risk Relations', help: 'Number of blocking/linked relationships to generate between ROAM risk epics and their related features or capabilities during simulation.' },
    ],
  },
  {
    title: 'Reports — Stuck Item Thresholds',
    fields: STUCK_FIELDS,
  },
]

// ── Form state ─────────────────────────────────────────────────────────────

const activeTab  = ref('connection')
const loading    = ref(true)
const loadError  = ref(null)
const saving     = ref(false)
const saveError  = ref(null)
const saveSuccess= ref(false)
const showToken  = ref(false)

let rawConfig = {}

const form = reactive({
  url:              '',
  private_token:    '',
  parent_group:     '',
  gitlab_namespace: '',
  ssl_verify:       true,
  api_timeout:      300,
  delete_workers:   5,
  project_labels:   '',
  piid_labels:      '',
  epic_type_labels: '',
  risk_labels:      '',
  roam_labels:      '',
  work_type_labels: '',
  lifecycle_labels: '',
  wsjf_urgency:     '',
  wsjf_risk:        '',
  fibonacci_weights: '',
  epic_weights:      {},
  bv_name:           undefined,
  bv_options:        '',
  bootstrap: {
    num_value_streams:          { min: 1, max: 4, desired: 2 },
    num_arts:                   { min: 1, max: 3, desired: 2 },
    num_teams:                  { min: 1, max: 4, desired: 2 },
    portfolio_epics:            { min: 3, max: 8, desired: 5 },
    vs_caps_per_vs:             { min: 0, max: 2, desired: 1 },
    art_caps_per_art:           { min: 1, max: 3, desired: 2 },
    features_per_team:          { min: 3, max: 6, desired: 4 },
    direct_feature_ratio:       0.85,
    history_close_rate_min:     0.7,
    history_close_rate_max:     0.95,
    current_pi_issue_close_pct: 0.5,
    seed_blocks:                true,
    epic_block_percent:         12,
    issue_block_percent:        8,
  },
  tools: {
    close_percent:                30,
    generate_epic_blocks_count:   10,
    generate_issue_blocks_count:  10,
    simulate_pi_progress_percent: 50,
    generate_issues_count:        5,
    weight_drift_threshold:       20,
    roam_risk_relations:          { min: 1, max: 3 },
  },
  stuck_thresholds: {
    'lifecycle::funnel':    90,
    'lifecycle::analyzing': 30,
    'lifecycle::backlog':   60,
  },
})

const epicWeightTypes = computed(() => Object.keys(form.epic_weights))

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

  const bs = cfg.defaults?.bootstrap ?? {}
  for (const f of BOOTSTRAP_RANGE_FIELDS) {
    form.bootstrap[f.key] = {
      min:     bs[f.key]?.min     ?? 0,
      max:     bs[f.key]?.max     ?? 0,
      desired: bs[f.key]?.desired ?? 0,
    }
  }
  form.bootstrap.direct_feature_ratio       = bs.direct_feature_ratio       ?? 0.85
  form.bootstrap.history_close_rate_min     = bs.history_close_rate_min     ?? 0.7
  form.bootstrap.history_close_rate_max     = bs.history_close_rate_max     ?? 0.95
  form.bootstrap.current_pi_issue_close_pct = bs.current_pi_issue_close_pct ?? 0.5
  form.bootstrap.seed_blocks                = bs.seed_blocks                ?? true
  form.bootstrap.epic_block_percent         = bs.epic_block_percent         ?? 12
  form.bootstrap.issue_block_percent        = bs.issue_block_percent        ?? 8

  const tl = cfg.defaults?.tools ?? {}
  form.tools.close_percent                = tl.close_percent                ?? 30
  form.tools.generate_epic_blocks_count   = tl.generate_epic_blocks_count   ?? 10
  form.tools.generate_issue_blocks_count  = tl.generate_issue_blocks_count  ?? 10
  form.tools.simulate_pi_progress_percent = tl.simulate_pi_progress_percent ?? 50
  form.tools.generate_issues_count        = tl.generate_issues_count        ?? 5
  form.tools.weight_drift_threshold       = tl.weight_drift_threshold       ?? 20
  form.tools.roam_risk_relations = {
    min: tl.roam_risk_relations?.min ?? 1,
    max: tl.roam_risk_relations?.max ?? 3,
  }

  const st = cfg.stuck_thresholds ?? {}
  form.stuck_thresholds = {
    'lifecycle::funnel':    st['lifecycle::funnel']    ?? 90,
    'lifecycle::analyzing': st['lifecycle::analyzing'] ?? 30,
    'lifecycle::backlog':   st['lifecycle::backlog']   ?? 60,
  }
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
  return str.split('\n').filter(s => s.trim() !== '').map(s => Number(s.trim())).filter(n => !isNaN(n))
}

function buildConfig() {
  const cfg = { ...rawConfig }

  cfg.url              = form.url.trim()
  cfg.private_token    = form.private_token.trim()
  cfg.parent_group     = form.parent_group.trim()
  cfg.gitlab_namespace = form.gitlab_namespace.trim()
  cfg.ssl_verify       = form.ssl_verify
  cfg.api_timeout      = Number(form.api_timeout)
  cfg.delete_workers   = Number(form.delete_workers)

  for (const f of LABEL_FIELDS) {
    cfg[f.key] = linesToArr(form[f.key])
  }
  cfg.wsjf_labels = {
    ...(rawConfig.wsjf_labels ?? {}),
    urgency: linesToArr(form.wsjf_urgency),
    risk:    linesToArr(form.wsjf_risk),
  }

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

  const bootstrap = { ...(rawConfig.defaults?.bootstrap ?? {}) }
  for (const f of BOOTSTRAP_RANGE_FIELDS) {
    bootstrap[f.key] = { ...form.bootstrap[f.key] }
  }
  bootstrap.direct_feature_ratio       = form.bootstrap.direct_feature_ratio
  bootstrap.history_close_rate_min     = form.bootstrap.history_close_rate_min
  bootstrap.history_close_rate_max     = form.bootstrap.history_close_rate_max
  bootstrap.current_pi_issue_close_pct = form.bootstrap.current_pi_issue_close_pct
  bootstrap.seed_blocks                = form.bootstrap.seed_blocks
  bootstrap.epic_block_percent         = form.bootstrap.epic_block_percent
  bootstrap.issue_block_percent        = form.bootstrap.issue_block_percent

  const tools = {
    ...(rawConfig.defaults?.tools ?? {}),
    close_percent:                form.tools.close_percent,
    generate_epic_blocks_count:   form.tools.generate_epic_blocks_count,
    generate_issue_blocks_count:  form.tools.generate_issue_blocks_count,
    simulate_pi_progress_percent: form.tools.simulate_pi_progress_percent,
    generate_issues_count:        form.tools.generate_issues_count,
    weight_drift_threshold:       form.tools.weight_drift_threshold,
    roam_risk_relations:          { ...form.tools.roam_risk_relations },
  }

  cfg.defaults = { ...(rawConfig.defaults ?? {}), bootstrap, tools }

  cfg.stuck_thresholds = {
    ...(rawConfig.stuck_thresholds ?? {}),
    ...form.stuck_thresholds,
  }
  return cfg
}

async function save() {
  saving.value      = true
  saveError.value   = null
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
  min-height: 0;
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
.field-textarea:focus { border-color: var(--action, #2563eb); }

/* ── Range grid (min / max / desired) ── */
.range-grid {
  display: grid;
  grid-template-columns: 1fr 80px 80px 80px;
  gap: 0.35rem 0.5rem;
  align-items: center;
}
.range-grid--two {
  grid-template-columns: 1fr 80px 80px;
}
.range-col-hdr {
  font-size: 0.72rem;
  font-weight: 600;
  color: var(--text-3, #6e7681);
  text-align: center;
}
.range-row-label {
  font-size: 0.82rem;
  color: var(--text-2, #8b949e);
}
.range-input {
  text-align: center;
  padding: 5px 4px;
  font-size: 0.82rem;
}

/* ── Two-column grid for scalar fields ── */
.two-col-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem;
}

/* ── Help reference tab ── */
.help-ref {
  gap: 0.75rem;
}
.help-section-label {
  margin-top: 0.5rem;
  padding-bottom: 0.35rem;
  border-bottom: 1px solid var(--border, #30363d);
}
.help-section-label:first-child {
  margin-top: 0;
}
.help-table {
  display: grid;
  grid-template-columns: 210px 1fr;
  column-gap: 0;
  row-gap: 0;
  margin-top: 0.4rem;
}
.help-table-name {
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--text-2, #8b949e);
  line-height: 1.4;
  padding: 0.4rem 0.75rem 0.4rem 0.5rem;
  border-radius: 4px 0 0 4px;
}
.help-table-desc {
  font-size: 0.8rem;
  color: var(--text-1, #e6edf3);
  line-height: 1.5;
  padding: 0.4rem 0.5rem 0.4rem 0.25rem;
  border-radius: 0 4px 4px 0;
}
/* zebra stripe — colour defined per-theme in theme.css via --stripe-bg */
.help-table > :nth-child(4n+1),
.help-table > :nth-child(4n+2) {
  background: var(--stripe-bg);
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
