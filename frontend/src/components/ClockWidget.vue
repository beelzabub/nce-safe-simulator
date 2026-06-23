<template>
  <div ref="widgetEl" class="clock-widget" :class="{ 'clock-widget--two': tz2On }">
    <div class="clock-row">
      <span class="clock-time">{{ utcTime }}</span>
    </div>
    <div v-if="tz2On" class="clock-row">
      <span class="clock-time clock-time--secondary">{{ tz2Time }}</span>
    </div>
    <button class="clock-gear" @click="openDialog" title="Clock settings" aria-label="Clock settings">⚙</button>
  </div>

  <Teleport to="body">
    <div v-if="open" class="clock-overlay" @click.self="open = false">
      <div class="clock-dialog" :style="dialogStyle">
        <div class="clock-dialog-header">
          <span>Clock settings</span>
          <button class="clock-dialog-close" @click="open = false" aria-label="Close">×</button>
        </div>
        <label class="clock-dialog-row">
          <input type="checkbox" :checked="tz2On" @change="toggleTz2($event.target.checked)" />
          <span>Show second clock</span>
        </label>
        <div v-if="tz2On" class="clock-dialog-tz-section">
          <div class="clock-dialog-tz-header">
            <span class="clock-dialog-label">Timezone</span>
            <input
              ref="tzSearchEl"
              v-model="tzSearch"
              class="clock-tz-search"
              type="search"
              placeholder="filter…"
              autocomplete="off"
            />
          </div>
          <select class="clock-tz-select" size="20" :value="tz2" @change="setTz2($event.target.value)">
            <template v-for="(tzs, group) in filteredTzGroups" :key="group">
              <optgroup :label="group">
                <option v-for="item in tzs" :key="item.tz" :value="item.tz">{{ item.label }}</option>
              </optgroup>
            </template>
          </select>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'
import { useClock } from '../composables/useClock.js'

const { utcTime, tz2Time, tz2, tz2On, setTz2, toggleTz2 } = useClock()
const open        = ref(false)
const widgetEl    = ref(null)
const dialogStyle = ref({})
const tzSearch    = ref('')
const tzSearchEl  = ref(null)

const tzGroups = computed(() => {
  const now = new Date()
  const groups = {}
  for (const tz of Intl.supportedValuesOf('timeZone')) {
    const slash = tz.indexOf('/')
    const prefix = slash === -1 ? 'Other' : tz.slice(0, slash)
    if (!groups[prefix]) groups[prefix] = []
    const city = slash === -1 ? tz : tz.slice(slash + 1).replace(/_/g, ' ').replace(/\//g, ' / ')
    const offsetPart = new Intl.DateTimeFormat('en', { timeZone: tz, timeZoneName: 'shortOffset' })
      .formatToParts(now).find(p => p.type === 'timeZoneName')?.value ?? ''
    const offset = offsetPart.replace('GMT', 'UTC')
    groups[prefix].push({ tz, label: `${city}  ${offset}` })
  }
  return groups
})

const filteredTzGroups = computed(() => {
  const q = tzSearch.value.trim().toLowerCase()
  if (!q) return tzGroups.value
  const result = {}
  for (const [group, tzs] of Object.entries(tzGroups.value)) {
    const matches = tzs.filter(item =>
      item.tz.toLowerCase().includes(q) || item.label.toLowerCase().includes(q)
    )
    if (matches.length) result[group] = matches
  }
  return result
})

async function openDialog() {
  const rect = widgetEl.value.getBoundingClientRect()
  dialogStyle.value = {
    position: 'fixed',
    top:  `${rect.bottom + 8}px`,
    left: `${rect.left + rect.width / 2}px`,
    transform: 'translateX(-50%)',
  }
  tzSearch.value = ''
  open.value = true
  await nextTick()
  tzSearchEl.value?.focus()
}
</script>

<style scoped>
.clock-widget {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1px;
  padding: 0 1.5rem 0 0.25rem;
}

.clock-row { display: flex; align-items: center; }

.clock-time {
  font-family: monospace;
  font-size: 0.95rem;
  color: var(--text-2);
  letter-spacing: 0.04em;
  white-space: nowrap;
  transition: font-size 0.4s ease, line-height 0.4s ease;
}

.clock-widget--two .clock-time {
  font-size: 0.78rem;
  line-height: 1.3;
}

.clock-time--secondary { color: var(--text-3); }

.clock-gear {
  position: absolute;
  top: 50%;
  right: 0;
  transform: translateY(-50%);
  background: transparent;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  font-size: 0.7rem;
  padding: 2px;
  line-height: 1;
  opacity: 0;
  transition: opacity 0.15s;
}
.clock-widget:hover .clock-gear { opacity: 1; }
.clock-gear:hover { color: var(--text-1); }

/* ── Teleported dialog ── */
.clock-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: transparent;
}

.clock-dialog {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.6rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  white-space: nowrap;
  box-shadow: 0 4px 16px rgba(0,0,0,0.45);
  min-width: 220px;
  max-height: 90vh;
  max-width: 90vw;
  overflow-y: auto;
}

.clock-dialog-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--text-2);
  padding-bottom: 0.35rem;
  border-bottom: 1px solid var(--border);
}

.clock-dialog-close {
  background: transparent;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  font-size: 1rem;
  line-height: 1;
  padding: 0 2px;
}
.clock-dialog-close:hover { color: var(--text-1); }

.clock-dialog-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8rem;
  color: var(--text-2);
}

.clock-dialog-label {
  font-size: 0.75rem;
  color: var(--text-3);
  min-width: 60px;
}

.clock-dialog-tz-section {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.clock-dialog-tz-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.clock-tz-search {
  flex: 1;
  background: var(--surface-alt);
  border: 1px solid var(--border);
  color: var(--text-1);
  border-radius: 4px;
  font-size: 0.78rem;
  padding: 3px 6px;
}
.clock-tz-search:focus { outline: 1px solid var(--accent, #4a9eff); }

.clock-tz-select {
  background: var(--surface-alt);
  border: 1px solid var(--border);
  color: var(--text-1);
  border-radius: 4px;
  font-size: 0.78rem;
  padding: 3px 6px;
  cursor: pointer;
  max-height: calc(90vh - 80px);
  overflow-y: auto;
}
</style>
