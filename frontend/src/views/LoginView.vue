<template>
  <div class="login-page">
    <!-- Two stacked layers crossfade; the active one gets the Ken Burns drift.
         Alternating pan direction per layer keeps consecutive slides from
         feeling like the same move twice. -->
    <div
      v-for="n in [0, 1]"
      :key="n"
      class="bg-layer"
      :class="{ active: activeLayer === n, 'pan-east': n === 0, 'pan-west': n === 1 }"
      :style="{ backgroundImage: layers[n] ? `url('${layers[n]}')` : 'none' }"
    />
    <div class="scrim" />

    <Transition name="credit">
      <p v-if="currentCredit" :key="currentCredit" class="credit-chip">{{ currentCredit }}</p>
    </Transition>

    <main class="card-wrap">
      <form class="login-card" @submit.prevent="onSubmit">
        <img class="seal" :src="sealSrc" alt="PMW-120 seal" />
        <h1>NCE SAFe Simulator</h1>
        <p class="tagline">Battlespace Awareness &amp; Information Operations</p>

        <label>
          <span>Username</span>
          <input v-model="username" type="text" name="username" autocomplete="username" spellcheck="false" />
        </label>
        <label>
          <span>Password</span>
          <input v-model="password" type="password" name="password" autocomplete="current-password" />
        </label>

        <button type="submit">Sign in</button>
      </form>
    </main>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { getAuthBackgrounds } from '../api.js'
import heroSrc from '../assets/hero-carrier.png'
import sealSrc from '../assets/login-seal.png'

const layers = ref(['', ''])
const activeLayer = ref(0)
const currentCredit = ref('')

const username = ref('')
const password = ref('')

// Rotation pool: only images whose preload completed are eligible, so a slow
// network can never crossfade to a half-loaded background.
let pool = []
let poolIdx = 0
let rotationMs = 15000
let timer = null

function preload(img) {
  return new Promise((resolve) => {
    const el = new Image()
    el.onload = () => resolve(img)
    el.onerror = () => resolve(null)
    el.src = img.url
  })
}

function showNext() {
  if (pool.length < 2) return
  poolIdx = (poolIdx + 1) % pool.length
  const next = pool[poolIdx]
  const hidden = activeLayer.value === 0 ? 1 : 0
  layers.value[hidden] = next.url
  activeLayer.value = hidden
  currentCredit.value = next.credit || ''
}

function startTimer() {
  if (!timer && pool.length >= 2) timer = setInterval(showNext, rotationMs)
}

function stopTimer() {
  if (timer) { clearInterval(timer); timer = null }
}

// Background tabs skip rotation entirely; catching up serves no one.
function onVisibility() {
  document.hidden ? stopTimer() : startTimer()
}

onMounted(async () => {
  const { rotation_seconds, fallback, images } = await getAuthBackgrounds()
  rotationMs = Math.max(3, rotation_seconds || 15) * 1000

  if (fallback || !images.length) {
    layers.value[0] = heroSrc
    return
  }

  // Paint the server's random pick immediately, then lazily preload the rest
  // of the pool in sequence.
  layers.value[0] = images[0].url
  currentCredit.value = images[0].credit || ''
  preload(images[0]).then((ok) => { if (ok) startTimer() })
  ;(async () => {
    for (const img of images.slice(1)) {
      const ok = await preload(img)
      if (ok) { pool.push(ok); startTimer() }
    }
  })()
  pool.push(images[0])

  document.addEventListener('visibilitychange', onVisibility)
})

onUnmounted(() => {
  stopTimer()
  document.removeEventListener('visibilitychange', onVisibility)
})

function onSubmit() {
  // TODO(#150): session gate — accept + route to '/'; real AAA later still.
}
</script>

<style scoped>
/* The imagery is dark-scrimmed, so this view commits to dark styling
   regardless of the app theme. */

.login-page {
  position: fixed;
  inset: 0;
  overflow: hidden;
  background: #05080f;
}

/* ── Slideshow ── */

.bg-layer {
  position: absolute;
  inset: -4%;               /* bleed so the Ken Burns pan never shows an edge */
  background-size: cover;
  background-position: center;
  opacity: 0;
  transition: opacity 1.5s ease;
  will-change: opacity, transform;
}

.bg-layer.active { opacity: 1; }

/* Ken Burns: a slow scale + drift for the lifetime of the slide. Re-adding
   .active restarts the animation, so every slide gets the full move. */
.bg-layer.active.pan-east { animation: kb-east 24s ease-out forwards; }
.bg-layer.active.pan-west { animation: kb-west 24s ease-out forwards; }

@keyframes kb-east {
  from { transform: scale(1.06) translate(-0.8%, 0.4%); }
  to   { transform: scale(1.14) translate(1.2%, -0.6%); }
}

@keyframes kb-west {
  from { transform: scale(1.06) translate(0.8%, -0.4%); }
  to   { transform: scale(1.14) translate(-1.2%, 0.6%); }
}

.scrim {
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse at center, rgba(5, 8, 15, 0) 35%, rgba(5, 8, 15, 0.55) 100%),
    linear-gradient(180deg, rgba(5, 8, 15, 0.35) 0%, rgba(5, 8, 15, 0.15) 40%, rgba(5, 8, 15, 0.5) 100%);
}

/* ── Photo credit ── */

.credit-chip {
  position: absolute;
  right: 16px;
  bottom: 12px;
  margin: 0;
  padding: 4px 10px;
  font-size: 11px;
  letter-spacing: 0.02em;
  color: rgba(230, 237, 243, 0.75);
  background: rgba(5, 8, 15, 0.45);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 999px;
  backdrop-filter: blur(6px);
}

.credit-enter-active, .credit-leave-active { transition: opacity 1.5s ease; }
.credit-enter-from, .credit-leave-to { opacity: 0; }
.credit-leave-active { position: absolute; }

/* ── Login card: quiet until the user reaches for it ── */

.card-wrap {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.login-card {
  width: min(360px, 100%);
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 36px 32px 32px;
  border-radius: 16px;
  background: rgba(9, 13, 22, 0.35);
  border: 1px solid rgba(255, 255, 255, 0.12);
  backdrop-filter: blur(10px);
  opacity: 0.78;
  transition: opacity 0.35s ease, background 0.35s ease, box-shadow 0.35s ease, transform 0.35s ease;
}

.login-card:hover,
.login-card:focus-within {
  opacity: 1;
  background: rgba(9, 13, 22, 0.62);
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.55);
  transform: translateY(-2px);
}

.seal {
  width: 84px;
  height: 84px;
  margin: 0 auto 4px;
  filter: drop-shadow(0 4px 12px rgba(0, 0, 0, 0.5));
}

h1 {
  margin: 0;
  text-align: center;
  font-size: 22px;
  font-weight: 650;
  letter-spacing: 0.01em;
  color: #e6edf3;
}

.tagline {
  margin: 0 0 10px;
  text-align: center;
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: rgba(230, 237, 243, 0.55);
}

label { display: flex; flex-direction: column; gap: 5px; }

label span {
  font-size: 12px;
  font-weight: 500;
  color: rgba(230, 237, 243, 0.7);
}

input {
  padding: 9px 12px;
  font-size: 14px;
  color: #e6edf3;
  background: rgba(5, 8, 15, 0.5);
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 8px;
  outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

input:focus {
  border-color: var(--action, #2563eb);
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.35);
}

button {
  margin-top: 8px;
  padding: 10px 12px;
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  background: var(--action, #2563eb);
  border: none;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.2s ease;
}

button:hover { background: var(--action-hover, #1d4ed8); }

@media (prefers-reduced-motion: reduce) {
  .bg-layer { transition-duration: 0.5s; animation: none !important; }
  .login-card { transition: opacity 0.35s ease; transform: none; }
}
</style>
