<template>
  <div class="overlay" @click.self="$emit('close')">
    <div class="dialog">

      <div class="dialog-header">
        <span class="dialog-title">AWS Architecture</span>
        <div class="header-right">
          <div v-if="availableTabs.length > 1" class="tab-bar">
            <button
              v-for="t in availableTabs" :key="t.key"
              class="tab-btn" :class="{ active: activeTab === t.key }"
              @click="activeTab = t.key; zoomReset()"
            >{{ t.label }}</button>
          </div>
          <button class="dialog-close" @click="$emit('close')" aria-label="Close">×</button>
        </div>
      </div>

      <div class="dialog-body">
        <div v-if="!availableTabs.length" class="no-diagram">
          <p>No architecture diagram available.</p>
          <p class="hint">Run <code>make eks-diagram</code> or <code>make ecs-diagram</code> in <code>cdk/</code>, then rebuild the container.</p>
        </div>
        <div
          v-else
          class="img-viewport"
          ref="viewport"
          :class="{ dragging }"
          @mousedown="onDragStart"
        >
          <img
            :key="imgUrl"
            :src="imgUrl"
            :alt="`${activeTab.toUpperCase()} architecture diagram`"
            class="arch-img"
            :style="{ width: `${zoom * 100}%` }"
            draggable="false"
          />
        </div>
      </div>

      <div class="dialog-footer">
        <div v-if="availableTabs.length" class="zoom-controls">
          <button class="zoom-btn" :disabled="zoom <= MIN_ZOOM" @click="zoomOut" title="Zoom out">−</button>
          <button class="zoom-reset" @click="zoomReset" title="Reset zoom">{{ zoomLabel }}</button>
          <button class="zoom-btn" :disabled="zoom >= MAX_ZOOM" @click="zoomIn" title="Zoom in">+</button>
        </div>
        <div class="footer-actions">
          <a v-if="availableTabs.length" :href="imgUrl" :download="`${activeTab}-architecture.png`" class="dl-btn">
            ↓ Download
          </a>
          <button class="close-btn" @click="$emit('close')">Close</button>
        </div>
      </div>

    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  deploymentType: { type: String, default: '' },
})
defineEmits(['close'])

const ALL_TABS = [
  { key: 'eks', label: 'EKS' },
  { key: 'ecs', label: 'ECS' },
]

const availableTabs = ref([])
const activeTab     = ref('')
const viewport      = ref(null)

const MIN_ZOOM  = 0.25
const MAX_ZOOM  = 4.0
const ZOOM_STEP = 0.25
const zoom      = ref(1.0)
const dragging  = ref(false)
let dragStart   = { x: 0, y: 0, scrollLeft: 0, scrollTop: 0 }

const imgUrl    = computed(() => `/architecture/${activeTab.value}-architecture.png`)
const zoomLabel = computed(() => `${Math.round(zoom.value * 100)}%`)

function zoomIn()    { zoom.value = Math.min(MAX_ZOOM, +(zoom.value + ZOOM_STEP).toFixed(2)) }
function zoomOut()   { zoom.value = Math.max(MIN_ZOOM, +(zoom.value - ZOOM_STEP).toFixed(2)) }
function zoomReset() {
  zoom.value = 1.0
  if (viewport.value) { viewport.value.scrollTop = 0; viewport.value.scrollLeft = 0 }
}

function onDragStart(e) {
  if (e.button !== 0) return
  dragging.value = true
  dragStart = { x: e.clientX, y: e.clientY, scrollLeft: viewport.value.scrollLeft, scrollTop: viewport.value.scrollTop }
  e.preventDefault()
}
function onDragMove(e) {
  if (!dragging.value || !viewport.value) return
  viewport.value.scrollLeft = dragStart.scrollLeft - (e.clientX - dragStart.x)
  viewport.value.scrollTop  = dragStart.scrollTop  - (e.clientY - dragStart.y)
}
function onDragEnd() { dragging.value = false }

function onKey(e) {
  if (e.key === '=' || e.key === '+') { e.preventDefault(); zoomIn() }
  if (e.key === '-')                  { e.preventDefault(); zoomOut() }
  if (e.key === '0')                  { e.preventDefault(); zoomReset() }
}

async function probe(key) {
  try {
    const r = await fetch(`/architecture/${key}-architecture.png`, { method: 'HEAD' })
    return r.ok
  } catch {
    return false
  }
}

onMounted(async () => {
  window.addEventListener('keydown', onKey)
  window.addEventListener('mousemove', onDragMove)
  window.addEventListener('mouseup', onDragEnd)

  // If we know the deployment type, only probe that one diagram.
  const candidates = props.deploymentType
    ? ALL_TABS.filter(t => t.key === props.deploymentType)
    : ALL_TABS

  const results = await Promise.all(candidates.map(t => probe(t.key)))
  availableTabs.value = candidates.filter((_, i) => results[i])
  if (availableTabs.value.length) activeTab.value = availableTabs.value[0].key
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  window.removeEventListener('mousemove', onDragMove)
  window.removeEventListener('mouseup', onDragEnd)
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
  z-index: 210;
}

.dialog {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  width: 85vw;
  height: 85vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.dialog-title {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-1);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.tab-bar {
  display: flex;
  gap: 0.25rem;
}

.tab-btn {
  padding: 0.25rem 0.75rem;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-2);
  font-size: 0.82rem;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.tab-btn:hover  { background: var(--surface-raised); color: var(--text-1); }
.tab-btn.active { background: var(--accent); color: #fff; border-color: var(--accent); }

.dialog-close {
  background: none;
  border: none;
  font-size: 1.4rem;
  line-height: 1;
  color: var(--text-3);
  cursor: pointer;
  padding: 0 0.2rem;
}
.dialog-close:hover { color: var(--text-1); }

.dialog-body {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.img-viewport {
  flex: 1;
  overflow: auto;
  padding: 0.75rem;
  cursor: grab;
  user-select: none;
}
.img-viewport.dragging {
  cursor: grabbing;
}

.arch-img {
  display: block;
  height: auto;
  margin: 0 auto;
  border-radius: 4px;
  transition: width 0.15s ease;
  pointer-events: none;
}

.no-diagram {
  text-align: center;
  color: var(--text-2);
  padding: 3rem 1rem;
}
.no-diagram p     { margin: 0.5rem 0; }
.no-diagram .hint { font-size: 0.85rem; color: var(--text-3); }
.no-diagram code  {
  background: var(--surface-raised);
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  font-size: 0.82rem;
}

.dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.6rem 1rem;
  border-top: 1px solid var(--border);
  flex-shrink: 0;
  gap: 0.75rem;
}

.zoom-controls {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.zoom-btn {
  width: 28px;
  height: 28px;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--surface-raised);
  color: var(--text-1);
  font-size: 1.1rem;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.12s;
}
.zoom-btn:hover:not(:disabled) { background: var(--surface-active); }
.zoom-btn:disabled { opacity: 0.35; cursor: default; }

.zoom-reset {
  min-width: 52px;
  height: 28px;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-2);
  font-size: 0.78rem;
  cursor: pointer;
  transition: background 0.12s, color 0.12s;
  text-align: center;
}
.zoom-reset:hover { background: var(--surface-raised); color: var(--text-1); }

.footer-actions {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.dl-btn {
  padding: 0.35rem 0.85rem;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--surface-raised);
  color: var(--text-1);
  font-size: 0.82rem;
  text-decoration: none;
  transition: background 0.15s;
}
.dl-btn:hover { background: var(--surface-active); }

.close-btn {
  padding: 0.35rem 0.85rem;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text-2);
  font-size: 0.82rem;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}
.close-btn:hover { background: var(--surface-raised); color: var(--text-1); }
</style>
