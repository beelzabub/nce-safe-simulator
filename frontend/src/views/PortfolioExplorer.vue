<!-- Portfolio Explorer (issue #169) — the Analysis tab's first capability.
     Lists EVERY portfolio epic (the epic::epic tier) as a GitLab-style card
     and draws attention to the ones with issues: blocked descendants (with
     the full hierarchy chains and weight/BV at risk) and behind-schedule
     progress. Attention cards sort first; healthy epics read at a glance. -->
<template>
  <div class="pfx">

    <div class="pfx-header">
      <span class="pfx-title">Portfolio Explorer</span>
      <span v-if="snapshot" class="pfx-run">snapshot {{ snapshotLabel }}</span>
      <button class="pfx-refresh" title="Reload from latest snapshot" @click="load">↻</button>
    </div>

    <div v-if="state === 'loading'" class="pfx-empty">Analyzing latest snapshot…</div>

    <div v-else-if="state === 'no-snapshot'" class="pfx-empty">
      <p class="pfx-empty-lead">No report snapshot yet</p>
      <p>Run reports from the Tools tab — the explorer reads the portfolio data each run captures.</p>
    </div>

    <div v-else-if="state === 'error'" class="pfx-empty">
      Couldn't load the analysis. <button class="pfx-link" @click="load">Retry</button>
    </div>

    <template v-else>
      <div class="totals-strip">
        <div class="stat">
          <span class="stat-value">{{ totals.portfolio_epics }}</span>
          <span class="stat-label">Portfolio epics</span>
        </div>
        <div class="stat" :class="{ 'stat--attention': totals.needs_attention }">
          <span class="stat-value">{{ totals.needs_attention }}</span>
          <span class="stat-label">Need attention</span>
        </div>
        <div class="stat">
          <span class="stat-value">{{ totals.blocked_weight_downstream }}</span>
          <span class="stat-label">Weight at risk <button class="help-btn" title="What do these numbers mean?" aria-label="Explain the weight-at-risk metrics" :aria-expanded="showHelp" aria-controls="pfx-metrics-help" @click="showHelp = true">ⓘ</button></span>
          <span class="stat-sub">direct {{ totals.blocked_weight }} · subtree {{ totals.blocked_weight_subtree }}</span>
        </div>
        <div class="stat stat--bv">
          <span class="stat-value">{{ totals.blocked_business_value_downstream }}</span>
          <span class="stat-label">BV at risk <button class="help-btn" title="What do these numbers mean?" aria-label="Explain the BV-at-risk metrics" :aria-expanded="showHelp" aria-controls="pfx-metrics-help" @click="showHelp = true">ⓘ</button></span>
          <span class="stat-sub">direct {{ totals.blocked_business_value }} · subtree {{ totals.blocked_business_value_subtree }}</span>
        </div>
      </div>

      <!-- ── Metric definitions (#178) — toggled by the ⓘ icons ── -->
      <div v-if="showHelp" id="pfx-metrics-help" class="metrics-help">
        <div class="metrics-help-head">
          <span>How weight &amp; BV at risk are computed</span>
          <button class="close-btn" @click="showHelp = false" aria-label="Close">×</button>
        </div>
        <table class="metrics-table">
          <tbody>
          <tr><th>Direct</th><td>the blocked items themselves — "the work that can't move." BV counts those items; weight is each blocked branch's effective weight</td></tr>
          <tr><th>Downstream</th><td>blocked items <em>plus their open descendants</em> — "value that can't be delivered until this clears." Closed/done items are excluded: their value is already delivered, so a block can't hold it hostage (open work behind a closed item still counts)</td></tr>
          <tr><th>Subtree</th><td>blocked items plus <em>all</em> descendants, closed included — sizing/exposure of the threatened branch, not risk. For weight this equals Direct: a branch's effective weight already covers its subtree</td></tr>
          </tbody>
        </table>
        <p class="metrics-note">Weight is the <em>recursive effective weight</em>: an epic's own set weight — zero means unset — else the sum of its children's, down to the issue-weight roll-up at the leaves. A set weight speaks for its whole subtree, so overlapping blocked subtrees are never double-counted. BV is the GitLab Business Value field (epics only). A <em>closed</em> item still carrying blocking links stays in the tree (flagged "blocked · closed") as a data-cleanup signal but contributes 0 downstream.</p>
      </div>

      <div v-if="totals.untyped_in_chains" class="dq-hint">
        ⚠ {{ totals.untyped_in_chains }} epic{{ totals.untyped_in_chains === 1 ? '' : 's' }} in blocked chains
        {{ totals.untyped_in_chains === 1 ? 'has' : 'have' }} no epic-type label — shown unclassified below.
        Label them so reports can classify this work.
      </div>

      <div v-if="!portfolioEpics.length" class="pfx-empty">
        <p class="pfx-empty-lead">No portfolio epics</p>
        <p>This snapshot has no epics carrying the portfolio tier label (epic::epic).</p>
      </div>

      <div v-else class="card-list">
        <div
          v-for="pe in portfolioEpics" :key="pe.epic.id"
          class="epic-card"
          :class="{ 'epic-card--attention': pe.needs_attention }"
        >

          <button class="card-head" @click="toggle(pe.epic.id)" :disabled="!pe.chains.length">
            <span class="chev" :class="{ open: expanded.has(pe.epic.id), hidden: !pe.chains.length }">▸</span>
            <span class="state-dot" :class="pe.epic.state" :title="pe.epic.state" />
            <span class="card-title">
              <a :href="pe.epic.web_url" target="_blank" rel="noopener" @click.stop>
                <TierIcon type="Epic" size="15" /> {{ pe.epic.title }}
              </a>
            </span>
            <span class="chips">
              <span v-if="pe.epic.piid" class="chip chip--piid">{{ pe.epic.piid }}</span>
              <span v-for="l in projectLabels(pe.epic)" :key="l" class="chip">{{ l }}</span>
            </span>
            <span class="badges">
              <template v-if="pe.flags.blocked">
                <span class="badge badge--blocked" title="Blocked items under this epic">
                  ⛔ {{ pe.rollup.blocked_count }} blocked
                </span>
                <span class="badge badge--weight" :title="`Weight at risk — direct ${pe.rollup.blocked_weight} · downstream (open only) ${pe.rollup.blocked_weight_downstream} · subtree ${pe.rollup.blocked_weight_subtree}`">
                  ⚓ {{ pe.rollup.blocked_weight }} · dn {{ pe.rollup.blocked_weight_downstream }}
                </span>
                <span class="badge badge--bv" :title="`BV at risk — direct ${pe.rollup.blocked_business_value} · downstream (open only) ${pe.rollup.blocked_business_value_downstream} · subtree ${pe.rollup.blocked_business_value_subtree}`">
                  ★ {{ pe.rollup.blocked_business_value }} · dn {{ pe.rollup.blocked_business_value_downstream }}
                </span>
              </template>
              <span v-if="pe.flags.behind_schedule" class="badge badge--behind" title="% complete trails % through PI">
                ⏱ behind schedule
              </span>
              <span v-if="!pe.needs_attention" class="badge badge--ok">on track</span>
            </span>
          </button>

          <div class="card-meta">
            <!-- Progress vs the PI clock: the notch marks % through PI, so a
                 fill short of the notch is visibly behind schedule. -->
            <div class="progress" :title="progressTitle(pe.epic)">
              <div class="progress-fill" :class="{ behind: pe.flags.behind_schedule }" :style="{ width: pct(pe.epic.pct_complete) + '%' }" />
              <div v-if="pe.epic.pct_through_pi != null" class="progress-notch" :style="{ left: pct(pe.epic.pct_through_pi) + '%' }" />
            </div>
            <span class="meta-nums">
              {{ pct(pe.epic.pct_complete) }}% done<template v-if="pe.epic.pct_through_pi != null"> · {{ pct(pe.epic.pct_through_pi) }}% through PI</template>
              · planned {{ pe.epic.planned_weight ?? '—' }} · BV {{ pe.epic.business_value ?? '—' }}
            </span>
          </div>

          <div v-if="expanded.has(pe.epic.id)" class="chains">
            <div v-for="(chain, ci) in pe.chains" :key="ci" class="chain">
              <div
                v-for="(node, ni) in chain.nodes" :key="node.id"
                class="chain-node"
                :class="{ blocked: node.blocked }"
                :style="{ paddingLeft: (0.75 + ni * 1.1) + 'rem' }"
              >
                <TierIcon :type="node.type" size="14" class="node-icon" />
                <a class="node-title" :href="node.web_url" target="_blank" rel="noopener">{{ node.title }}</a>
                <span
                  v-if="!node.type"
                  class="untyped-flag"
                  title="Add an epic-type label (epic::capability / epic::feature) so reports can classify this epic"
                >untyped</span>
                <span
                  v-if="node.blocked"
                  class="blocked-flag"
                  :class="{ 'blocked-flag--closed': node.state === 'closed' }"
                  :title="node.state === 'closed' ? 'Closed but still carries blocking links — consider clearing them (data cleanup)' : undefined"
                >{{ node.state === 'closed' ? 'blocked · closed' : 'blocked' }}</span>
                <span class="node-nums">
                  w {{ node.planned_weight || node.actual_weight || '—' }} · bv {{ node.business_value ?? '—' }}
                </span>
              </div>
              <div v-if="chain.blockers.length" class="blockers" :style="{ paddingLeft: (0.75 + chain.nodes.length * 1.1) + 'rem' }">
                <span class="blockers-label">blocked by</span>
                <a
                  v-for="b in chain.blockers" :key="b.id"
                  class="blocker-link" :href="b.web_url" target="_blank" rel="noopener"
                  :title="b.item_type === 'Issue' ? 'Blocking issue' : 'Blocking epic'"
                ><TierIcon :type="b.item_type === 'Issue' ? 'Issue' : b.type" size="12" /> {{ b.title }}</a>
              </div>
            </div>
          </div>

        </div>
      </div>
    </template>

  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import TierIcon from '../components/TierIcon.vue'

const state          = ref('loading')   // loading | no-snapshot | error | ready
const totals         = ref({})
const portfolioEpics = ref([])
const snapshot       = ref(null)
const expanded       = ref(new Set())
const showHelp       = ref(false)

const snapshotLabel = computed(() => {
  if (!snapshot.value) return ''
  const { date: d, time: t } = snapshot.value
  return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)} ${t.slice(0, 2)}:${t.slice(2, 4)}`
})

function pct(v) {
  return Math.round(v ?? 0)
}

function progressTitle(epic) {
  const done = `${pct(epic.pct_complete)}% complete`
  return epic.pct_through_pi == null
    ? done
    : `${done} vs ${pct(epic.pct_through_pi)}% through PI`
}

function projectLabels(epic) {
  return (epic.labels || []).filter(l => l.startsWith('project::'))
}

function toggle(id) {
  const next = new Set(expanded.value)
  next.has(id) ? next.delete(id) : next.add(id)
  expanded.value = next
}

async function load() {
  state.value = 'loading'
  try {
    const r = await fetch('/api/analysis/portfolio')
    if (r.status === 404) { state.value = 'no-snapshot'; return }
    if (!r.ok) throw new Error(String(r.status))
    const body = await r.json()
    totals.value         = body.totals
    portfolioEpics.value = body.portfolio_epics
    snapshot.value       = body.snapshot
    // The top blocked card is what the user came to see — start it expanded.
    const first = body.portfolio_epics.find(pe => pe.chains.length)
    expanded.value = new Set(first ? [first.epic.id] : [])
    state.value = 'ready'
  } catch {
    state.value = 'error'
  }
}

onMounted(load)
</script>

<style scoped>
.pfx {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.pfx-header {
  flex-shrink: 0;
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
  padding: 0.65rem 1.25rem;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.pfx-title { font-size: 0.95rem; font-weight: 600; color: var(--text-1); }
.pfx-run   { font-size: 0.75rem; color: var(--text-3); }
.pfx-refresh {
  margin-left: auto;
  background: none;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  font-size: 0.95rem;
}
.pfx-refresh:hover { color: var(--text-1); }

.pfx-empty {
  padding: 2.5rem 1.5rem;
  text-align: center;
  color: var(--text-3);
  font-size: 0.85rem;
  line-height: 1.6;
}
.pfx-empty-lead { font-size: 1rem; font-weight: 600; color: var(--text-2); margin: 0 0 0.3rem; }
.pfx-link {
  background: none; border: none; color: var(--action);
  cursor: pointer; font-size: inherit; padding: 0;
}

/* ── Totals strip ── */
.totals-strip {
  flex-shrink: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.6rem;
  padding: 0.85rem 1.25rem;
  border-bottom: 1px solid var(--border);
}
.stat {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.55rem 0.8rem;
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}
.stat-value {
  font-size: 1.35rem;
  font-weight: 700;
  color: var(--text-1);
  font-variant-numeric: tabular-nums;
}
.stat--bv .stat-value        { color: var(--accent); }
.stat--attention .stat-value { color: #f85149; }
.stat-label {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-3);
}
.stat-sub {
  font-size: 0.68rem;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.help-btn {
  background: none;
  border: none;
  color: var(--action);
  cursor: pointer;
  font-size: 0.8rem;
  /* Inflate the touch target without shifting the inline layout */
  padding: 6px;
  margin: -6px -4px;
  vertical-align: baseline;
}
.help-btn:hover { color: var(--text-1); }

/* ── Metric definitions panel (#178) ── */
.metrics-help {
  flex-shrink: 0;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  padding: 0.7rem 1.25rem 0.85rem;
  font-size: 0.78rem;
  color: var(--text-2);
}
.metrics-help-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
  color: var(--text-1);
  margin-bottom: 0.45rem;
}
.metrics-help .close-btn {
  background: none; border: none; color: var(--text-3);
  cursor: pointer; font-size: 1rem; line-height: 1;
}
.metrics-help .close-btn:hover { color: var(--text-1); }
.metrics-table { border-collapse: collapse; }
.metrics-table th {
  text-align: left;
  padding: 0.2rem 0.9rem 0.2rem 0;
  color: var(--text-1);
  white-space: nowrap;
  vertical-align: top;
  font-size: 0.74rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.metrics-table td { padding: 0.2rem 0; line-height: 1.45; }
.metrics-note { margin: 0.5rem 0 0; color: var(--text-3); line-height: 1.45; }

/* ── Cards ── */
.card-list {
  flex: 1;
  overflow-y: auto;
  padding: 0.85rem 1.25rem 3rem;
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
}
.epic-card {
  flex-shrink: 0;   /* flex column children compress to fit by default,
                       crushing expanded cards and clipping their chains
                       once the list outgrows the pane — scroll instead */
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
.epic-card--attention { border-left: 3px solid #f85149; }
.card-head {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  padding: 0.7rem 0.9rem 0.35rem;
  cursor: pointer;
}
.card-head:disabled { cursor: default; }
.chev {
  color: var(--text-3);
  font-size: 0.8rem;
  transition: transform 0.15s;
  flex-shrink: 0;
}
.chev.open   { transform: rotate(90deg); }
.chev.hidden { visibility: hidden; }
.state-dot {
  width: 10px; height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}
.state-dot.opened { background: #3fb950; }
.state-dot.closed { background: var(--text-3); }
.card-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 0.9rem;
  font-weight: 600;
}
.card-title a { color: var(--text-1); text-decoration: none; }
.card-title a:hover { color: var(--action); }

.chips { display: flex; gap: 0.3rem; flex-shrink: 0; }
.chip {
  font-size: 0.66rem;
  font-weight: 600;
  background: var(--surface-alt);
  border: 1px solid var(--border);
  color: var(--text-2);
  border-radius: 999px;
  padding: 0.06rem 0.5rem;
  white-space: nowrap;
}
.chip--piid { color: var(--action); }

.badges { display: flex; gap: 0.35rem; margin-left: auto; flex-shrink: 0; }
.badge {
  font-size: 0.72rem;
  font-weight: 700;
  border-radius: 4px;
  padding: 0.14rem 0.5rem;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.badge--blocked { background: rgba(248, 81, 73, 0.14); color: #f85149; }
.badge--weight  { background: rgba(88, 166, 255, 0.14); color: #58a6ff; }
.badge--bv      { background: rgba(252, 109, 38, 0.15); color: var(--accent); }
.badge--behind  { background: rgba(210, 153, 34, 0.15); color: #d29922; }
.badge--ok      { background: rgba(63, 185, 80, 0.12); color: #3fb950; }

.card-meta {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  padding: 0 0.9rem 0.65rem 2.2rem;
}
.progress {
  position: relative;
  flex: 0 0 120px;
  height: 6px;
  background: var(--surface-alt);
  border-radius: 3px;
  overflow: hidden;
}
.progress-fill { height: 100%; background: #3fb950; }
.progress-fill.behind { background: #d29922; }
.progress-notch {
  position: absolute;
  top: -1px;
  bottom: -1px;
  width: 2px;
  background: var(--text-3);
}
.meta-nums {
  font-size: 0.72rem;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}

/* ── Chains ── */
.chains {
  border-top: 1px solid var(--border);
  padding: 0.5rem 0.9rem 0.7rem;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
}
.chain { display: flex; flex-direction: column; gap: 0.1rem; }
.chain-node {
  display: flex;
  align-items: center;
  gap: 0.45rem;
  font-size: 0.82rem;
  padding-top: 0.14rem;
  padding-bottom: 0.14rem;
  border-radius: 4px;
}
.chain-node.blocked { background: rgba(248, 81, 73, 0.09); }
.node-icon { flex-shrink: 0; }
.node-title {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-2);
  text-decoration: none;
}
.node-title:hover { color: var(--action); }
.chain-node.blocked .node-title { color: var(--text-1); font-weight: 600; }
.untyped-flag {
  flex-shrink: 0;
  font-size: 0.64rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #d29922;
  border: 1px solid rgba(210, 153, 34, 0.4);
  border-radius: 3px;
  padding: 0 0.35rem;
  cursor: help;
}
.dq-hint {
  flex-shrink: 0;
  font-size: 0.76rem;
  color: #d29922;
  background: rgba(210, 153, 34, 0.08);
  border-bottom: 1px solid var(--border);
  padding: 0.45rem 1.25rem;
}
.blocked-flag {
  flex-shrink: 0;
  font-size: 0.64rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #f85149;
  border: 1px solid rgba(248, 81, 73, 0.4);
  border-radius: 3px;
  padding: 0 0.35rem;
}
.blocked-flag.blocked-flag--closed {
  color: var(--text-3);
  border-color: var(--border);
  text-decoration: line-through;
  text-decoration-color: rgba(248, 81, 73, 0.55);
  cursor: help;
}
.node-nums {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 0.72rem;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
}
.blockers {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  flex-wrap: wrap;
  font-size: 0.76rem;
}
.blockers-label {
  font-size: 0.64rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #f85149;
}
.blocker-link { color: var(--text-2); text-decoration: none; }
.blocker-link:hover { color: var(--action); text-decoration: underline; }
</style>
