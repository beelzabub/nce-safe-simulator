<template>
  <div class="overlay" @click.self="$emit('close')">
    <div class="dialog">

      <div class="dialog-header">
        <span class="dialog-title">NCE Safe Simulator — Help</span>
        <button class="dialog-close" @click="$emit('close')" aria-label="Close">×</button>
      </div>

      <div class="tab-bar">
        <button
          v-for="t in TABS" :key="t.key"
          class="tab-btn" :class="{ active: activeTab === t.key }"
          @click="activeTab = t.key"
        >{{ t.label }}</button>
      </div>

      <div class="dialog-body">

        <!-- ── About ── -->
        <div v-if="activeTab === 'about'" class="section">
          <p class="lead">
            NCE Safe Simulator is a training and demonstration tool for SAFe practitioners.
            It populates a GitLab instance with a realistic, fully-labelled SAFe program hierarchy
            so analysts and coaches can explore NCE reporting without needing live program data.
          </p>

          <div class="subsection-label">What it creates</div>
          <p>
            The simulator connects to any GitLab instance and builds a configurable group structure
            that mirrors a real SAFe program increment:
          </p>
          <div class="hier-grid">
            <span class="hier-level hier-level--1">Portfolio Group</span>
            <span class="hier-desc">Root group; holds Value Streams and Portfolio-level epics</span>
            <span class="hier-level hier-level--2">Value Stream</span>
            <span class="hier-desc">Subgroup per VS; contains ART subgroups and VS Capability epics</span>
            <span class="hier-level hier-level--3">ART</span>
            <span class="hier-desc">Agile Release Train subgroup; contains Team groups and ART Capability epics</span>
            <span class="hier-level hier-level--4">Team / Backlog</span>
            <span class="hier-desc">Team group with a backlog project; owns Feature epics and child issues</span>
          </div>

          <div class="subsection-label">Labels and metadata</div>
          <p>
            Every epic is tagged with a configurable set of GitLab labels that drive reporting:
          </p>
          <div class="kv-grid">
            <span class="kv-key">Epic Type</span><span class="kv-val">Portfolio Epic · VS Capability · ART Capability · Feature</span>
            <span class="kv-key">Lifecycle</span><span class="kv-val">funnel → analyzing → backlog → implementing → done</span>
            <span class="kv-key">PIID</span><span class="kv-val">Assigns the epic to a PI quarter (e.g. PIID::2025Q2)</span>
            <span class="kv-key">Project</span><span class="kv-val">Associates the work with a named project stream</span>
            <span class="kv-key">Risk</span><span class="kv-val">high · medium · low</span>
            <span class="kv-key">Work Type</span><span class="kv-val">feature · enabler · infrastructure · defect</span>
            <span class="kv-key">WSJF</span><span class="kv-val">Urgency and Risk-Reduction scores (Fibonacci)</span>
            <span class="kv-key">Business Value</span><span class="kv-val">Custom field with Fibonacci score 1–21</span>
          </div>

          <div class="subsection-label">Story-point weights</div>
          <p>
            Issues carry numeric weights (story points). Planned weights are assigned to epics at creation;
            the reporting layer compares planned vs actual to measure PI predictability and weight drift.
          </p>
        </div>

        <!-- ── Setup ── -->
        <div v-if="activeTab === 'setup'" class="section">
          <p class="lead">
            Follow these steps to clone the repository, install dependencies, and start the web server.
          </p>

          <div class="subsection-label">Prerequisites</div>
          <div class="kv-grid">
            <span class="kv-key">Python</span><span class="kv-val">3.9 or later</span>
            <span class="kv-key">Node.js</span><span class="kv-val">18 or later (for building the web frontend)</span>
            <span class="kv-key">Git</span><span class="kv-val">any recent version</span>
            <span class="kv-key">GitLab PAT</span><span class="kv-val">Personal Access Token with <code>api</code> scope</span>
          </div>

          <div class="workflow-steps">

            <div class="step">
              <div class="step-num">1</div>
              <div class="step-body">
                <div class="step-title">Clone the repository</div>
                <pre class="code-block">git clone https://gitlab.com/saic-study-group/nce-safe-simulator.git
cd nce-safe-simulator</pre>
              </div>
            </div>

            <div class="step">
              <div class="step-num">2</div>
              <div class="step-body">
                <div class="step-title">Create a Python virtual environment</div>
                <div class="os-label">Linux / macOS</div>
                <pre class="code-block">python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt</pre>
                <div class="os-label">Windows — Command Prompt</div>
                <pre class="code-block">python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt</pre>
                <div class="os-label">Windows — PowerShell</div>
                <pre class="code-block">python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt</pre>
              </div>
            </div>

            <div class="step">
              <div class="step-num">3</div>
              <div class="step-body">
                <div class="step-title">Build the frontend</div>
                <pre class="code-block">cd frontend
npm install
npm run build
cd ..</pre>
                <div class="step-desc">Compiles the Vue app into <code>public/app/</code>. npm commands are the same on all platforms.</div>
              </div>
            </div>

            <div class="step">
              <div class="step-num">4</div>
              <div class="step-body">
                <div class="step-title">Configure</div>
                <div class="step-desc">
                  Edit <code>config.json</code> and set at minimum:
                </div>
                <div class="kv-grid" style="margin-top:0.5rem">
                  <span class="kv-key">url</span><span class="kv-val">GitLab instance URL (default: https://gitlab.com)</span>
                  <span class="kv-key">private_token</span><span class="kv-val">Your Personal Access Token</span>
                  <span class="kv-key">parent_group</span><span class="kv-val">Display name of the SAFe portfolio root group</span>
                  <span class="kv-key">gitlab_namespace</span><span class="kv-val">URL slug of the namespace that will contain the root group</span>
                </div>
                <div class="step-desc" style="margin-top:0.5rem">All other settings can be changed in the ⚙ Config dialog after the server is running.</div>
              </div>
            </div>

            <div class="step">
              <div class="step-num">5</div>
              <div class="step-body">
                <div class="step-title">Start the web server</div>
                <div class="os-label">Linux / macOS</div>
                <pre class="code-block">python3 NceGitLab.py --serve</pre>
                <div class="os-label">Windows</div>
                <pre class="code-block">python NceGitLab.py --serve</pre>
                <div class="step-desc">
                  The server starts on <code>http://localhost:80</code>.
                  Open <code>http://localhost:80/app/</code> in your browser.
                  Run the same command again to stop it.
                  If port 80 is unavailable, run with <code>sudo</code> (Linux/macOS) or from an Administrator terminal (Windows).
                </div>
              </div>
            </div>

          </div>
        </div>

        <!-- ── Workflow ── -->
        <div v-if="activeTab === 'workflow'" class="section">
          <p class="lead">
            A typical simulation session follows six steps. Each step builds on the previous one —
            you can stop after any step and still generate meaningful reports.
          </p>

          <div class="workflow-steps">
            <div class="step">
              <div class="step-num">1</div>
              <div class="step-body">
                <div class="step-title">Configure</div>
                <div class="step-desc">
                  Open <strong>Config</strong> (⚙ in the nav bar) and set your GitLab URL, private token,
                  parent group path, and namespace. Review the Labels tabs to confirm your instance's label
                  scheme matches the configured values. Adjust Weights and Bootstrap defaults as needed.
                </div>
              </div>
            </div>
            <div class="step">
              <div class="step-num">2</div>
              <div class="step-body">
                <div class="step-title">Bootstrap</div>
                <div class="step-desc">
                  Run <strong>Create Lorem Data</strong> (Seed Data group) to build the full SAFe hierarchy.
                  Always do a <em>Dry Run</em> first to preview the resolved structure without writing anything.
                  The tool creates subgroups, projects, epics, issues, and labels in one pass.
                </div>
              </div>
            </div>
            <div class="step">
              <div class="step-num">3</div>
              <div class="step-body">
                <div class="step-title">Seed realistic conditions</div>
                <div class="step-desc">
                  Use the <strong>Seed Data</strong> and <strong>Labels</strong> tools to layer in realistic
                  program conditions: assign lifecycle stages, PIID labels, WSJF scores, business value,
                  and work-type labels. Then generate ROAM risks, epic blocking relationships,
                  and risk reasons (behind-schedule, past-due, blocked) to simulate a mid-PI snapshot.
                </div>
              </div>
            </div>
            <div class="step">
              <div class="step-num">4</div>
              <div class="step-body">
                <div class="step-title">Simulate PI progress</div>
                <div class="step-desc">
                  Run <strong>Simulate PI Progress</strong> or <strong>Close Percent</strong> to close a
                  fraction of open issues, advancing the simulated PI completion percentage.
                  Use <strong>Set Issue Weights</strong> and <strong>Update Weights</strong> to ensure
                  planned and actual weight data is populated before reporting.
                </div>
              </div>
            </div>
            <div class="step">
              <div class="step-num">5</div>
              <div class="step-body">
                <div class="step-title">Audit and validate</div>
                <div class="step-desc">
                  Run <strong>Diagnose</strong> to verify API compatibility and label configuration.
                  Use <strong>Audit Hierarchy</strong> and <strong>Audit Labels</strong> to catch missing
                  parent links or incomplete label sets before generating reports.
                </div>
              </div>
            </div>
            <div class="step">
              <div class="step-num">6</div>
              <div class="step-body">
                <div class="step-title">Generate reports</div>
                <div class="step-desc">
                  Click <strong>Reports</strong> in the sidebar to select and run one or more Quarto reports.
                  Reports render as HTML (and optionally PDF/DOCX) and open automatically in your browser.
                  The Reports site link at the bottom of the sidebar opens the full report index.
                </div>
              </div>
            </div>
            <div class="step">
              <div class="step-num">7</div>
              <div class="step-body">
                <div class="step-title">Reset (optional)</div>
                <div class="step-desc">
                  Use the <strong>Reset / Clean</strong> tools to remove seeded data and restore a clean
                  state without rebuilding the group structure. Strip label sets individually, clean ROAM
                  risks and epic blocks, or reset PI progress to start the simulation cycle over.
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ── Tools ── -->
        <div v-if="activeTab === 'tools'" class="section">
          <div v-if="toolsLoading" class="loading-msg">Loading tools…</div>
          <div v-else-if="toolsError" class="error-msg">{{ toolsError }}</div>
          <template v-else>
            <div v-for="cat in toolCategories" :key="cat.name" class="tool-category">
              <div class="cat-header">
                <span class="cat-name">{{ cat.name }}</span>
                <span class="cat-desc">{{ cat.description }}</span>
              </div>
              <div class="tool-table">
                <template v-for="tool in cat.tools" :key="tool.key">
                  <span class="tool-name">{{ formatKey(tool.key) }}</span>
                  <span class="tool-desc">{{ tool.description }}</span>
                </template>
              </div>
            </div>
          </template>
        </div>

        <!-- ── Reports ── -->
        <div v-if="activeTab === 'reports'" class="section">
          <div class="tool-table">
            <template v-for="r in REPORTS" :key="r.key">
              <span class="tool-name">{{ r.label }}</span>
              <span class="tool-desc">{{ r.description }}</span>
            </template>
          </div>
        </div>

      </div><!-- end dialog-body -->
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { getTools } from '../api.js'

const emit = defineEmits(['close'])

const TABS = [
  { key: 'about',    label: 'About'    },
  { key: 'setup',    label: 'Setup'    },
  { key: 'workflow', label: 'Workflow' },
  { key: 'tools',    label: 'Tools'    },
  { key: 'reports',  label: 'Reports'  },
]

const CATEGORY_DEFS = [
  { name: 'Diagnose',       description: 'Environment, API compatibility, and label validation',    tools: ['diagnose'] },
  { name: 'Setup',          description: 'Initialize structure and custom fields',                  tools: ['scaffold', 'create-lorem-data', 'setup-bv-field'] },
  { name: 'Seed Data',      description: 'Generate and simulate realistic test conditions',         tools: ['generate-issues', 'generate-epic-blocks', 'generate-roam-risks', 'generate-risk-reasons', 'close-percent', 'simulate-pi-progress', 'set-epic-states', 'orphan-epics', 'orphan-issues'] },
  { name: 'Labels',         description: 'Assign or strip epic label sets',                        tools: ['set-lifecycle-labels', 'strip-lifecycle-labels', 'set-piid-labels', 'strip-piid-labels', 'set-project-labels', 'strip-project-labels', 'set-risk-labels', 'set-work-type-labels', 'strip-work-type-labels', 'set-business-value', 'strip-business-value', 'set-wsjf-labels', 'strip-wsjf-labels', 'strip-labels'] },
  { name: 'Weights',        description: 'Manage epic and issue story-point weights',              tools: ['set-issue-weights', 'strip-issue-weights', 'update-weights', 'validate-weights', 'weight-drift-check'] },
  { name: 'Reset / Clean',  description: 'Remove seeded data and restore a clean state',           tools: ['clean-roam-risks', 'clean-epic-blocks', 'reset-pi-progress', 'clean-wikis', 'clean-reports', 'clean-logs'] },
  { name: 'Audit',          description: 'Inspect data quality, labels, and hierarchy',            tools: ['audit-hierarchy', 'audit-labels', 'list-wikis'] },
  { name: 'Import / Export',description: 'Move epics and issues in and out of GitLab',             tools: ['export-epics', 'export-issues', 'import-epics', 'import-issues'] },
]

const REPORTS = [
  { key: 'health-dashboard',      label: 'Health Dashboard',          description: 'Consolidated health scorecard showing ART-level status, label completeness, weight coverage, and risk exposure at a glance.' },
  { key: 'portfolio',             label: 'Portfolio',                  description: 'Portfolio-level epic hierarchy with lifecycle stage, PIID assignment, weight totals, and business value rolled up by Value Stream.' },
  { key: 'flow-metrics',          label: 'Flow Metrics',               description: 'WIP counts, throughput rates, and cycle time distributions across the program, broken down by work type and ART.' },
  { key: 'wsjf',                  label: 'WSJF Prioritization',        description: 'WSJF-scored backlog ranking epics by Cost of Delay divided by job size. Highlights the highest-priority items for each PI.' },
  { key: 'risk-register',         label: 'Risk Register',              description: 'Open ROAM risk issues with their ROAM status, related epics, and PI assignment. Flags unresolved and accepted risks.' },
  { key: 'epic-lifecycle',        label: 'Epic Lifecycle',             description: 'Lifecycle stage distribution across the portfolio — how many epics are in funnel, backlog, implementing, and done at each level.' },
  { key: 'blocking',              label: 'Blocking',                   description: 'Dependency chain map of blocking relationships between epics, including blocked count per ART and longest dependency paths.' },
  { key: 'pi-predictability',     label: 'PI Predictability',          description: 'PI Predictability Measure (PPM) scores per ART and PI, calculated from planned vs actual feature completion percentages.' },
  { key: 'piid-project',          label: 'PI × Project',               description: 'Matrix view of epics organised by PI iteration and project stream, showing count and weight totals per cell.' },
  { key: 'piid-project-detail',   label: 'PI × Project Detail',        description: 'Detailed breakdown of individual epics within each PI × Project cell, including lifecycle stage and weight status.' },
  { key: 'team-backlog',          label: 'Team Backlog',               description: 'Team-level issue backlog with open/closed counts, weight totals, and percentage completion per Feature epic.' },
  { key: 'workload',              label: 'Workload',                   description: 'Work-type and weight distribution across teams and ARTs, highlighting imbalance and concentration of technical debt.' },
  { key: 'art-capacity-balance',  label: 'ART Capacity Balance',       description: 'Planned vs actual story-point weight balance across all ARTs, surfacing over- and under-loaded trains.' },
  { key: 'art-feature-status',    label: 'ART Feature Status',         description: 'Feature-level completion status per ART for the active PI, including weight progress and lifecycle stage.' },
  { key: 'vs-capability-dashboard', label: 'VS Capability Dashboard',  description: 'Value Stream capability health summary — delivery progress, dependent feature status, and risk exposure per VS.' },
  { key: 'premature-closures',    label: 'Premature Closures',         description: 'Epics and issues closed before reaching the implementing stage, indicating scope removal or process anomalies.' },
  { key: 'orphan-epics',          label: 'Orphan Epics',               description: 'Epics missing a parent in the expected SAFe hierarchy — Features without Capabilities, Capabilities without Portfolio Epics, etc.' },
  { key: 'orphan-issues',         label: 'Orphan Issues',              description: 'Issues with no linked epic. These will not contribute to weight totals or PI predictability calculations.' },
  { key: 'unassigned-pi',         label: 'Unassigned PI',              description: 'Epics not assigned to any PI iteration label, preventing them from appearing in PI-scoped reports and metrics.' },
  { key: 'diagnostics',           label: 'Diagnostics',                description: 'System health report: software versions, GitLab API capabilities, label configuration validation, and compatibility assessment.' },
]

const activeTab    = ref('about')
const toolsLoading = ref(false)
const toolsError   = ref(null)
const allTools     = ref([])

const toolCategories = computed(() => {
  const byKey = Object.fromEntries(allTools.value.map(t => [t.key, t]))
  return CATEGORY_DEFS.map(cat => ({
    ...cat,
    tools: cat.tools.map(k => byKey[k]).filter(Boolean),
  })).filter(cat => cat.tools.length > 0)
})

const ACRONYMS = new Set(['roam', 'wsjf', 'bv', 'piid', 'pi', 'art', 'vs'])
function formatKey(key) {
  return key.split('-').map(w =>
    ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1)
  ).join(' ')
}

onMounted(async () => {
  toolsLoading.value = true
  try {
    allTools.value = await getTools()
  } catch (e) {
    toolsError.value = `Could not load tools: ${e.message}`
  } finally {
    toolsLoading.value = false
  }
  document.addEventListener('keydown', onKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKeydown)
})

function onKeydown(e) {
  if (e.key === 'Escape') emit('close')
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
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  width: 780px;
  max-width: 96vw;
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
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.dialog-title { font-size: 0.95rem; font-weight: 600; color: var(--text-1); }
.dialog-close {
  background: none; border: none;
  color: var(--text-3); cursor: pointer; font-size: 1.1rem; line-height: 1;
}
.dialog-close:hover { color: var(--text-1); }

/* ── Tabs ── */
.tab-bar {
  display: flex;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.tab-btn {
  flex: 1;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  color: var(--text-3);
  cursor: pointer;
  font-size: 0.82rem;
  font-weight: 500;
  padding: 0.55rem 0.5rem;
  transition: color 0.15s, border-color 0.15s;
}
.tab-btn:hover { color: var(--text-1); }
.tab-btn.active { color: var(--text-1); border-bottom-color: var(--action); }

/* ── Body ── */
.dialog-body {
  flex: 1;
  overflow-y: auto;
  padding: 1.25rem 1.25rem 1.5rem;
  min-height: 0;
}

.section {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}

/* ── About tab ── */
.lead {
  margin: 0;
  font-size: 0.88rem;
  color: var(--text-1);
  line-height: 1.65;
  padding: 0.75rem 1rem;
  background: rgba(37, 99, 235, 0.07);
  border-left: 3px solid var(--action);
  border-radius: 0 5px 5px 0;
}

.subsection-label {
  font-size: 0.72rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--text-3);
  margin-top: 0.5rem;
}

p {
  margin: 0;
  font-size: 0.85rem;
  color: var(--text-2);
  line-height: 1.6;
}

.hier-grid {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 0.3rem 0.75rem;
  align-items: baseline;
}
.hier-level {
  font-size: 0.82rem;
  font-weight: 600;
  padding: 0.2rem 0.5rem;
  border-radius: 4px;
  color: var(--text-1);
}
.hier-level--1 { background: rgba(37,  99, 235, 0.18); }
.hier-level--2 { background: rgba(37,  99, 235, 0.12); }
.hier-level--3 { background: rgba(37,  99, 235, 0.08); }
.hier-level--4 { background: rgba(37,  99, 235, 0.04); }
.hier-desc {
  font-size: 0.82rem;
  color: var(--text-2);
  line-height: 1.5;
}

.kv-grid {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 0.35rem 0.75rem;
  align-items: baseline;
}
.kv-key {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text-2);
}
.kv-val {
  font-size: 0.8rem;
  color: var(--text-1);
  line-height: 1.5;
}

/* ── Workflow tab ── */
.workflow-steps {
  display: flex;
  flex-direction: column;
  gap: 0;
}
.step {
  display: flex;
  gap: 1rem;
  padding: 0.85rem 0;
  border-bottom: 1px solid var(--border);
}
.step:last-child { border-bottom: none; }
.step-num {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--action);
  color: #fff;
  font-size: 0.8rem;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-top: 1px;
}
.step-body { flex: 1; }
.step-title {
  font-size: 0.88rem;
  font-weight: 600;
  color: var(--text-1);
  margin-bottom: 0.3rem;
}
.step-desc {
  font-size: 0.83rem;
  color: var(--text-2);
  line-height: 1.6;
}
.step-desc strong { color: var(--text-1); }
.step-desc em { color: var(--text-2); font-style: italic; }

/* ── Setup tab ── */
.os-label {
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin: 0.65rem 0 0.2rem;
}
.code-block {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 0.55rem 0.75rem;
  font-family: ui-monospace, 'Cascadia Code', 'Fira Code', monospace;
  font-size: 0.8rem;
  color: var(--text-1);
  line-height: 1.6;
  white-space: pre;
  overflow-x: auto;
  margin: 0;
}
.step-body code {
  font-family: ui-monospace, 'Cascadia Code', 'Fira Code', monospace;
  font-size: 0.8rem;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 3px;
  padding: 0.1em 0.35em;
}

/* ── Tools tab ── */
.tool-category { margin-bottom: 1rem; }
.cat-header {
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
  padding-bottom: 0.35rem;
  border-bottom: 1px solid var(--border);
  margin-bottom: 0.4rem;
}
.cat-name {
  font-size: 0.8rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-1);
}
.cat-desc {
  font-size: 0.78rem;
  color: var(--text-3);
}

/* ── Shared tool/report table ── */
.tool-table {
  display: grid;
  grid-template-columns: 220px 1fr;
  column-gap: 0;
  row-gap: 0;
}
.tool-name {
  font-size: 0.8rem;
  font-weight: 500;
  color: var(--text-2);
  padding: 0.35rem 0.75rem 0.35rem 0.5rem;
  border-radius: 4px 0 0 4px;
  line-height: 1.4;
}
.tool-desc {
  font-size: 0.8rem;
  color: var(--text-1);
  padding: 0.35rem 0.5rem 0.35rem 0.25rem;
  border-radius: 0 4px 4px 0;
  line-height: 1.5;
}
/* zebra stripe */
.tool-table > :nth-child(4n+1),
.tool-table > :nth-child(4n+2) {
  background: var(--stripe-bg);
}

/* ── Loading / error ── */
.loading-msg {
  font-size: 0.85rem;
  color: var(--text-3);
  padding: 2rem;
  text-align: center;
}
.error-msg {
  font-size: 0.85rem;
  color: #f85149;
  padding: 1rem;
}
</style>
