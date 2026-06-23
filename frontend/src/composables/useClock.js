import { ref, computed, onUnmounted } from 'vue'
import { loadStored, saveStored } from './useLocalStorage.js'

const STORAGE_KEY_TZ2         = 'nce-clock-tz2'
const STORAGE_KEY_TZ2_ENABLED = 'nce-clock-tz2-enabled'
const DEFAULT_TZ2              = 'America/Los_Angeles'

// Singleton — one interval for the whole app lifetime
const now       = ref(new Date())
const tz2       = ref(loadStored(STORAGE_KEY_TZ2, DEFAULT_TZ2))
const tz2On     = ref(loadStored(STORAGE_KEY_TZ2_ENABLED, true))
let   _timer    = null
let   _refCount = 0

function _tick() { now.value = new Date() }
function _start() { if (!_timer) _timer = setInterval(_tick, 1000) }
function _stop()  { clearInterval(_timer); _timer = null }

function _fmt(date, timeZone) {
  // hourCycle:'h23' avoids Chrome rendering midnight as "24:00:00"
  const parts = new Intl.DateTimeFormat('en-US', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hourCycle: 'h23', timeZone, timeZoneName: 'short'
  }).formatToParts(date)
  const get = type => parts.find(p => p.type === type)?.value ?? ''
  return `${get('hour')}:${get('minute')}:${get('second')} ${get('timeZoneName')}`
}

export function useClock() {
  _refCount++
  _start()

  onUnmounted(() => {
    _refCount--
    if (_refCount === 0) _stop()
  })

  const utcTime = computed(() => _fmt(now.value, 'UTC'))
  const tz2Time = computed(() => tz2On.value ? _fmt(now.value, tz2.value) : null)

  function setTz2(newTz) {
    tz2.value = newTz
    saveStored(STORAGE_KEY_TZ2, newTz)
  }

  function toggleTz2(enabled) {
    tz2On.value = enabled
    saveStored(STORAGE_KEY_TZ2_ENABLED, enabled)
  }

  return { utcTime, tz2Time, tz2, tz2On, setTz2, toggleTz2 }
}
