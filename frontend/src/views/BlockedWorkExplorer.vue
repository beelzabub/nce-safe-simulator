<!-- Blocked Work Explorer (issue #169) — the Analysis tab's first capability.
     Built for a portfolio manager scanning for the biggest fires: totals up
     top, one GitLab-style card per threatened portfolio epic sorted by BV at
     risk, each expanding to the hierarchy chains that carry the block. -->
<template>
  <div class="bwx">

    <div class="bwx-header">
      <span class="bwx-title">Blocked Work Explorer</span>
      <span v-if="snapshot" class="bwx-run">snapshot {{ snapshotLabel }}</span>
      <button class="bwx-refresh" title="Reload from latest snapshot" @click="load">↻</button>
    </div>

    <div v-if="state === 'loading'" class="bwx-empty">Analyzing latest snapshot…</div>

    <div v-else-if="state === 'no-snapshot'" class="bwx-empty">
      <p class="bwx-empty-lead">No report snapshot yet</p>
      <p>Run reports from the Tools tab — the explorer reads the blocking data each run captures.</p>
    </div>

    <div v-else-if="state === 'error'" class="bwx-empty">
      Couldn't load the analysis. <button class="bwx-link" @click="load">Retry</button>
    </div>

    <template v-else>
      <div class="totals-strip">
        <div class="stat">
          <span class="stat-value">{{ totals.portfolio_epics_at_risk }}</span>
          <span class="stat-label">Portfolio epics at risk</span>
        </div>
        <div class="stat">
          <span class="stat-value">{{ totals.blocked_items }}</span>
          <span class="stat-label">Blocked items</span>
        </div>
        <div class="stat">
          <span class="stat-value">{{ totals.blocked_weight }}</span>
          <span class="stat-label">Blocked weight</span>
        </div>
        <div class="stat stat--bv">
          <span class="stat-value">{{ totals.blocked_business_value }}</span>
          <span class="stat-label">BV at risk</span>
        </div>
      </div>

      <div v-if="!portfolioEpics.length" class="bwx-empty">
        <p class="bwx-empty-lead">All clear</p>
        <p>No portfolio epic has a blocked descendant in this snapshot.</p>
      </div>

      <div v-else class="card-list">
        <div v-for="pe in portfolioEpics" :key="pe.epic.id" class="epic-card">

          <button class="card-head" @click="toggle(pe.epic.id)">
            <span class="chev" :class="{ open: expanded.has(pe.epic.id) }">▸</span>
            <span class="state-dot" :class="pe.epic.state" :title="pe.epic.state" />
            <span class="card-title">
              <a :href="pe.epic.web_url" target="_blank" rel="noopener" @click.stop>🏆 {{ pe.epic.title }}</a>
            </span>
            <span class="chips">
              <span v-if="pe.epic.piid" class="chip chip--piid">{{ pe.epic.piid }}</span>
              <span v-for="l in projectLabels(pe.epic)" :key="l" class="chip">{{ l }}</span>
            </span>
            <span class="badges">
              <span class="badge badge--weight" title="Blocked weight (planned, falling back to actual)">
                ⚓ {{ pe.rollup.blocked_weight }}
              </span>
              <span class="badge badge--bv" title="Business Value at risk">
                ★ {{ pe.rollup.blocked_business_value }}
              </span>
              <span class="badge badge--count" title="Blocked items under this epic">
                {{ pe.rollup.blocked_count }} blocked
              </span>
            </span>
          </button>

          <div class="card-meta">
            <div class="progress" :title="`${pct(pe.epic)}% complete`">
              <div class="progress-fill" :style="{ width: pct(pe.epic) + '%' }" />
            </div>
            <span class="meta-nums">{{ pct(pe.epic) }}% · planned {{ pe.epic.planned_weight ?? '—' }} · BV {{ pe.epic.business_value ?? '—' }}</span>
          </div>

          <div v-if="expanded.has(pe.epic.id)" class="chains">
            <div v-for="(chain, ci) in pe.chains" :key="ci" class="chain">
              <div
                v-for="(node, ni) in chain.nodes" :key="node.id"
                class="chain-node"
                :class="{ blocked: node.blocked }"
                :style="{ paddingLeft: (0.75 + ni * 1.1) + 'rem' }"
              >
                <span class="node-icon">{{ tierIcon(node.type) }}</span>
                <a class="node-title" :href="node.web_url" target="_blank" rel="noopener">{{ node.title }}</a>
                <span v-if="node.blocked" class="blocked-flag">blocked</span>
                <span class="node-nums">
                  w {{ node.planned_weight ?? node.actual_weight ?? '—' }} · bv {{ node.business_value ?? '—' }}
                </span>
              </div>
              <div v-if="chain.blockers.length" class="blockers" :style="{ paddingLeft: (0.75 + chain.nodes.length * 1.1) + 'rem' }">
                <span class="blockers-label">blocked by</span>
                <a
                  v-for="b in chain.blockers" :key="b.id"
                  class="blocker-link" :href="b.web_url" target="_blank" rel="noopener"
                >{{ b.title }}</a>
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

const state          = ref('loading')   // loading | no-snapshot | error | ready
const totals         = ref({})
const portfolioEpics = ref([])
const snapshot       = ref(null)
const expanded       = ref(new Set())

const snapshotLabel = computed(() => {
  if (!snapshot.value) return ''
  const { date: d, time: t } = snapshot.value
  return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6)} ${t.slice(0, 2)}:${t.slice(2, 4)}`
})

function pct(epic) {
  return Math.round((epic.pct_complete ?? 0))
}

function projectLabels(epic) {
  return (epic.labels || []).filter(l => l.startsWith('project::'))
}

const TIER_ICONS = { Epic: '🏆', Capability: '🧩', Feature: '🛠️' }
function tierIcon(type) {
  return TIER_ICONS[type] || '•'
}

function toggle(id) {
  const next = new Set(expanded.value)
  next.has(id) ? next.delete(id) : next.add(id)
  expanded.value = next
}

async function load() {
  state.value = 'loading'
  try {
    const r = await fetch('/api/analysis/blocked-chains')
    if (r.status === 404) { state.value = 'no-snapshot'; return }
    if (!r.ok) throw new Error(String(r.status))
    const body = await r.json()
    totals.value         = body.totals
    portfolioEpics.value = body.portfolio_epics
    snapshot.value       = body.snapshot
    // The top card is what the user came to see — start it expanded.
    expanded.value = new Set(
      body.portfolio_epics.length ? [body.portfolio_epics[0].epic.id] : [])
    state.value = 'ready'
  } catch {
    state.value = 'error'
  }
}

onMounted(load)
</script>

<style scoped>
.bwx {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.bwx-header {
  flex-shrink: 0;
  display: flex;
  align-items: baseline;
  gap: 0.75rem;
  padding: 0.65rem 1.25rem;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.bwx-title { font-size: 0.95rem; font-weight: 600; color: var(--text-1); }
.bwx-run   { font-size: 0.75rem; color: var(--text-3); }
.bwx-refresh {
  margin-left: auto;
  background: none;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  font-size: 0.95rem;
}
.bwx-refresh:hover { color: var(--text-1); }

.bwx-empty {
  padding: 2.5rem 1.5rem;
  text-align: center;
  color: var(--text-3);
  font-size: 0.85rem;
  line-height: 1.6;
}
.bwx-empty-lead { font-size: 1rem; font-weight: 600; color: var(--text-2); margin: 0 0 0.3rem; }
.bwx-link {
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
.stat--bv .stat-value { color: var(--accent); }
.stat-label {
  font-size: 0.68rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-3);
}

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
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}
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
.chev {
  color: var(--text-3);
  font-size: 0.8rem;
  transition: transform 0.15s;
  flex-shrink: 0;
}
.chev.open { transform: rotate(90deg); }
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
.badge--weight { background: var(--conflict-bg, rgba(210, 153, 34, 0.15)); color: #d29922; }
.badge--bv     { background: rgba(252, 109, 38, 0.15); color: var(--accent); }
.badge--count  { background: var(--surface-alt); color: var(--text-2); }

.card-meta {
  display: flex;
  align-items: center;
  gap: 0.7rem;
  padding: 0 0.9rem 0.65rem 2.2rem;
}
.progress {
  flex: 0 0 120px;
  height: 6px;
  background: var(--surface-alt);
  border-radius: 3px;
  overflow: hidden;
}
.progress-fill { height: 100%; background: #3fb950; }
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
.node-icon { flex-shrink: 0; font-size: 0.8rem; }
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
