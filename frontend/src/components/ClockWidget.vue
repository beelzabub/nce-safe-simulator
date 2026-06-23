<template>
  <div class="clock-widget" :class="{ 'clock-widget--two': tz2On }" @click.stop>
    <div class="clock-row">
      <span class="clock-time">{{ utcTime }}</span>
    </div>
    <div v-if="tz2On" class="clock-row">
      <span class="clock-time clock-time--secondary">{{ tz2Time }}</span>
    </div>
    <button class="clock-gear" @click.stop="open = !open" title="Clock settings" aria-label="Clock settings">⚙</button>

    <div v-if="open" class="clock-popover">
      <label class="clock-popover-row">
        <input type="checkbox" :checked="tz2On" @change="toggleTz2($event.target.checked)" />
        <span>Show second clock</span>
      </label>
      <div v-if="tz2On" class="clock-popover-row">
        <span class="clock-popover-label">Timezone</span>
        <select class="clock-tz-select" :value="tz2" @change="setTz2($event.target.value)">
          <optgroup label="US / Canada">
            <option value="America/New_York">Eastern (New York)</option>
            <option value="America/Chicago">Central (Chicago)</option>
            <option value="America/Denver">Mountain (Denver)</option>
            <option value="America/Los_Angeles">Pacific (San Diego)</option>
            <option value="America/Anchorage">Alaska</option>
            <option value="Pacific/Honolulu">Hawaii</option>
          </optgroup>
          <optgroup label="Europe">
            <option value="Europe/London">London</option>
            <option value="Europe/Paris">Central Europe</option>
            <option value="Europe/Helsinki">Eastern Europe</option>
          </optgroup>
          <optgroup label="Asia / Pacific">
            <option value="Asia/Tokyo">Tokyo</option>
            <option value="Asia/Shanghai">Beijing / Shanghai</option>
            <option value="Asia/Kolkata">India (IST)</option>
            <option value="Australia/Sydney">Sydney</option>
          </optgroup>
          <optgroup label="Other">
            <option value="UTC">UTC</option>
          </optgroup>
        </select>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useClock } from '../composables/useClock.js'

const { utcTime, tz2Time, tz2, tz2On, setTz2, toggleTz2 } = useClock()
const open = ref(false)

function onDocClick() { open.value = false }
onMounted(()   => document.addEventListener('click', onDocClick))
onUnmounted(() => document.removeEventListener('click', onDocClick))
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

.clock-row {
  display: flex;
  align-items: center;
}

.clock-time {
  font-family: monospace;
  font-size: 0.82rem;
  color: var(--text-2);
  letter-spacing: 0.04em;
  white-space: nowrap;
}

.clock-widget--two .clock-time {
  font-size: 0.72rem;
  line-height: 1.2;
}

.clock-time--secondary {
  color: var(--text-3);
}

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

.clock-popover {
  position: absolute;
  top: calc(100% + 6px);
  left: 50%;
  transform: translateX(-50%);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.6rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  z-index: 100;
  white-space: nowrap;
  box-shadow: 0 4px 12px rgba(0,0,0,0.35);
}

.clock-popover-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.8rem;
  color: var(--text-2);
}

.clock-popover-label {
  font-size: 0.75rem;
  color: var(--text-3);
  min-width: 60px;
}

.clock-tz-select {
  background: var(--surface-alt);
  border: 1px solid var(--border);
  color: var(--text-1);
  border-radius: 4px;
  font-size: 0.78rem;
  padding: 3px 6px;
  cursor: pointer;
}
</style>
