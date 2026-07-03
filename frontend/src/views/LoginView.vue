<template>
  <div class="login-page" @click="summonCard">
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
    <div class="focus-dim" :class="{ on: cardActive }" />

    <Transition name="credit">
      <p v-if="currentCredit" :key="currentCredit" class="credit-chip">{{ currentCredit }}</p>
    </Transition>

    <Transition name="banner">
      <DodBanner v-if="bannerVisible" @accept="acceptBanner" />
    </Transition>

    <main class="card-wrap" :inert="bannerVisible">
      <!-- At rest the imagery owns the page; this whisper is the only trace
           of the form. Any intent signal — hovering or focusing it, clicking
           the page, Tab, or just starting to type — materializes the card. -->
      <Transition name="whisper">
        <button
          v-show="!cardActive"
          class="whisper"
          type="button"
          aria-label="Sign in"
          @mouseenter="onWhisperHover"
          @focus="summonCard"
        >
          <img class="whisper-seal" :src="sealSrc" alt="" />
          <span>Sign in</span>
        </button>
      </Transition>

      <Transition name="card" @after-enter="focusUsername">
        <form
          v-show="cardActive"
          class="login-card"
          @submit.prevent="onSubmit"
          @keydown="onCardActivity"
          @input="onCardActivity"
          @focusin="onCardActivity"
          @mousemove="onCardActivity"
        >
          <img class="seal" :src="sealSrc" alt="PMW-120 seal" />
          <h1>NCE SAFe Simulator</h1>
          <p class="tagline">Battlespace Awareness &amp; Information Operations</p>

          <label>
            <span>Username</span>
            <input ref="usernameInput" v-model="username" type="text" name="username" autocomplete="username" spellcheck="false" />
          </label>
          <label>
            <span>Password</span>
            <input v-model="password" type="password" name="password" autocomplete="current-password" />
          </label>

          <p v-if="loginError" class="login-error" role="alert">{{ loginError }}</p>
          <button type="submit">Sign in</button>
        </form>
      </Transition>
    </main>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { getAuthBackgrounds, getConfig } from '../api.js'
import { useAuthGate } from '../composables/useAuthGate.js'
import DodBanner from '../components/DodBanner.vue'
import heroSrc from '../assets/hero-carrier.png'
import sealSrc from '../assets/login-seal.png'

// DoD Notice and Consent acknowledgment is per browser session (DTM 08-060 —
// the banner must precede authentication and be explicitly acknowledged).
const BANNER_ACK_KEY = 'nce.auth.dodBannerAccepted'

const layers = ref(['', ''])
const activeLayer = ref(0)
const currentCredit = ref('')
const bannerVisible = ref(false)

const username = ref('')
const password = ref('')
const loginError = ref('')

// A rejected attempt's message clears as soon as the user edits either field.
watch([username, password], () => { loginError.value = '' })

// Card presence choreography (issue #158): the form stays dissolved until the
// user signals intent (whisper hover/focus, a click anywhere, Tab, or typing),
// then materializes with focus. Escape — or idling with untouched fields —
// dissolves it back to the whisper. Typed content pins the card up.
const IDLE_RETREAT_MS = 25_000

const cardActive = ref(false)
const usernameInput = ref(null)
let idleTimer = null

function focusUsername() {
  usernameInput.value?.focus()
}

let suppressHoverUntil = 0

function summonCard(e) {
  if (bannerVisible.value || cardActive.value) return
  // Clicks inside the banner (its OK) bubble here after dismissal — the
  // acknowledgment itself is not sign-in intent.
  if (e?.target?.closest?.('.banner-overlay')) return
  cardActive.value = true
  resetIdleTimer()
}

// The whisper reappears exactly where the card dissolved from; a stationary
// cursor over it would re-fire mouseenter and bounce the card straight back.
function onWhisperHover(e) {
  if (Date.now() < suppressHoverUntil) return
  summonCard(e)
}

function retreatCard() {
  if (!cardActive.value) return
  cardActive.value = false
  suppressHoverUntil = Date.now() + 600
  clearIdleTimer()
  document.activeElement?.blur?.()
}

function clearIdleTimer() {
  if (idleTimer) { clearTimeout(idleTimer); idleTimer = null }
}

function resetIdleTimer() {
  clearIdleTimer()
  idleTimer = setTimeout(() => {
    if (!username.value && !password.value) retreatCard()
    else resetIdleTimer()
  }, IDLE_RETREAT_MS)
}

function onCardActivity() {
  if (cardActive.value) resetIdleTimer()
}

function onDocKeydown(e) {
  if (bannerVisible.value) return
  if (e.key === 'Escape') { retreatCard(); return }
  if (!cardActive.value && (e.key === 'Enter' || e.key.length === 1)) summonCard()
}

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

function acceptBanner() {
  sessionStorage.setItem(BANNER_ACK_KEY, '1')
  bannerVisible.value = false
}

onMounted(async () => {
  if (!sessionStorage.getItem(BANNER_ACK_KEY)) {
    getConfig().then((cfg) => {
      bannerVisible.value = cfg.dod_banner_enabled !== false
    })
  }

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

onMounted(() => {
  document.addEventListener('keydown', onDocKeydown)
})

onUnmounted(() => {
  stopTimer()
  clearIdleTimer()
  document.removeEventListener('visibilitychange', onVisibility)
  document.removeEventListener('keydown', onDocKeydown)
})

const router = useRouter()
const gate = useAuthGate()

async function onSubmit() {
  if (!username.value.trim() || !password.value) return
  loginError.value = ''
  const ok = await gate.login(username.value.trim(), password.value)
  if (!ok) {
    // Server rejected the credentials — stay put and say so. (Don't touch
    // the field refs here: the watcher above clears the error on any edit.)
    loginError.value = 'Invalid username or password'
    return
  }
  router.push('/')
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

.banner-enter-active, .banner-leave-active { transition: opacity 0.4s ease; }
.banner-enter-from, .banner-leave-to { opacity: 0; }

/* ── Login card: dissolved until the user signals intent ── */

.card-wrap {
  position: absolute;
  inset: 0;
  display: flex;
  /* `safe` keeps the card's top reachable (scrollable) when the viewport is
     shorter than the card — e.g. a phone in landscape */
  align-items: safe center;
  justify-content: center;
  padding: 24px;
  overflow-y: auto;
}

/* Extra dim behind the materialized card so it owns the moment. */
.focus-dim {
  position: absolute;
  inset: 0;
  background: rgba(5, 8, 15, 0.3);
  opacity: 0;
  transition: opacity 0.35s ease;
  pointer-events: none;
}

.focus-dim.on { opacity: 1; }

/* Resting whisper — the only trace of the form. */
.whisper {
  position: absolute;
  bottom: 64px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  padding: 8px 22px;
  font-size: 12px;
  font-weight: 500;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: rgba(230, 237, 243, 0.6);
  background: rgba(5, 8, 15, 0.28);
  border: 1px solid rgba(255, 255, 255, 0.14);
  border-radius: 999px;
  backdrop-filter: blur(6px);
  cursor: pointer;
  transition: color 0.25s ease, border-color 0.25s ease, background 0.25s ease;
}

.whisper:hover,
.whisper:focus-visible {
  color: rgba(230, 237, 243, 0.95);
  border-color: rgba(255, 255, 255, 0.35);
  background: rgba(5, 8, 15, 0.45);
  outline: none;
}

.whisper-seal {
  width: 18px;
  height: 18px;
  opacity: 0.85;
}

.whisper-enter-active, .whisper-leave-active { transition: opacity 0.3s ease; }
.whisper-enter-from, .whisper-leave-to { opacity: 0; }

/* Materialize / dissolve choreography. */
.card-enter-active { transition: opacity 0.3s ease, transform 0.3s ease, filter 0.3s ease; }
.card-leave-active { transition: opacity 0.25s ease, transform 0.25s ease, filter 0.25s ease; }
.card-enter-from { opacity: 0; transform: scale(0.965) translateY(10px); filter: blur(6px); }
.card-leave-to   { opacity: 0; transform: scale(0.985); filter: blur(4px); }

/* A materialized card was summoned on purpose — it arrives awake. */
.login-card {
  width: min(360px, 100%);
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 36px 32px 32px;
  border-radius: 16px;
  background: rgba(9, 13, 22, 0.55);
  border: 1px solid rgba(255, 255, 255, 0.14);
  backdrop-filter: blur(10px);
  transition: background 0.35s ease, box-shadow 0.35s ease;
}

.login-card:hover,
.login-card:focus-within {
  background: rgba(9, 13, 22, 0.66);
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.55);
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

.login-error {
  margin: 0;
  font-size: 12.5px;
  font-weight: 500;
  text-align: center;
  color: #f87171;
}

@media (prefers-reduced-motion: reduce) {
  .bg-layer { transition-duration: 0.5s; animation: none !important; }
  .card-enter-active, .card-leave-active { transition: opacity 0.25s ease; }
  .card-enter-from, .card-leave-to { transform: none; filter: none; }
  .focus-dim { transition: none; }
}

/* ── Touch devices (issue #160): the whisper is the primary tap target for
   summoning the card (any page tap works too), so give it finger room. ── */
@media (pointer: coarse) {
  .whisper { min-height: 44px; padding: 10px 26px; }
}

@media (max-width: 480px) {
  .login-card { padding: 28px 22px 24px; }
  .credit-chip { right: 10px; bottom: 8px; }
}
</style>
