<template>
  <div class="overlay" @click.self="$emit('close')">
    <div class="dialog" @keydown.esc="$emit('close')">

      <div class="dialog-header">
        <span class="dialog-title">AWS Architecture</span>
        <div class="header-right">
          <div class="tab-bar">
            <button
              v-for="t in TABS" :key="t.key"
              class="tab-btn" :class="{ active: activeTab === t.key }"
              @click="activeTab = t.key; imageError = false"
            >{{ t.label }}</button>
          </div>
          <button class="dialog-close" @click="$emit('close')" aria-label="Close">×</button>
        </div>
      </div>

      <div class="dialog-body">
        <div v-if="imageError" class="no-diagram">
          <p>Diagram not available for <strong>{{ activeTab.toUpperCase() }}</strong>.</p>
          <p class="hint">Run <code>make {{ activeTab }}-diagram</code> in <code>cdk/</code>, then rebuild the container.</p>
        </div>
        <img
          v-else
          :key="imgUrl"
          :src="imgUrl"
          :alt="`${activeTab.toUpperCase()} architecture diagram`"
          class="arch-img"
          :class="{ zoomed }"
          @click="zoomed = !zoomed"
          @error="imageError = true"
        />
      </div>

      <div class="dialog-footer">
        <a v-if="!imageError" :href="imgUrl" :download="`${activeTab}-architecture.png`" class="dl-btn">
          ↓ Download
        </a>
        <button class="close-btn" @click="$emit('close')">Close</button>
      </div>

    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

defineEmits(['close'])

const TABS = [
  { key: 'eks', label: 'EKS' },
  { key: 'ecs', label: 'ECS' },
]

const activeTab  = ref('eks')
const zoomed     = ref(false)
const imageError = ref(false)

const imgUrl = computed(() => `/architecture/${activeTab.value}-architecture.png`)
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
  width: min(92vw, 1100px);
  max-height: 90vh;
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
.tab-btn:hover { background: var(--surface-raised); color: var(--text-1); }
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
  overflow: auto;
  padding: 1rem;
  display: flex;
  align-items: flex-start;
  justify-content: center;
}

.arch-img {
  max-width: 100%;
  height: auto;
  cursor: zoom-in;
  transition: transform 0.2s;
  border-radius: 4px;
}
.arch-img.zoomed {
  max-width: none;
  cursor: zoom-out;
  transform: scale(1.5);
  transform-origin: top left;
}

.no-diagram {
  text-align: center;
  color: var(--text-2);
  padding: 3rem 1rem;
}
.no-diagram p { margin: 0.5rem 0; }
.no-diagram .hint { font-size: 0.85rem; color: var(--text-3); }
.no-diagram code {
  background: var(--surface-raised);
  padding: 0.1rem 0.35rem;
  border-radius: 3px;
  font-size: 0.82rem;
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 0.75rem;
  padding: 0.6rem 1rem;
  border-top: 1px solid var(--border);
  flex-shrink: 0;
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
