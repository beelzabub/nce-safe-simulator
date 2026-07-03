<template>
  <div class="banner-overlay" role="dialog" aria-modal="true" aria-labelledby="dod-banner-title">
    <div class="banner">
      <h2 id="dod-banner-title">U.S. Government Information System</h2>
      <div class="banner-body">
        <p>
          You are accessing a U.S. Government (USG) Information System (IS) that is
          provided for USG-authorized use only.
        </p>
        <p>
          By using this IS (which includes any device attached to this IS), you consent
          to the following conditions:
        </p>
        <ul>
          <li>
            The USG routinely intercepts and monitors communications on this IS for
            purposes including, but not limited to, penetration testing, COMSEC
            monitoring, network operations and defense, personnel misconduct (PM),
            law enforcement (LE), and counterintelligence (CI) investigations.
          </li>
          <li>At any time, the USG may inspect and seize data stored on this IS.</li>
          <li>
            Communications using, or data stored on, this IS are not private, are
            subject to routine monitoring, interception, and search, and may be
            disclosed or used for any USG-authorized purpose.
          </li>
          <li>
            This IS includes security measures (e.g., authentication and access
            controls) to protect USG interests&mdash;not for your personal benefit or
            privacy.
          </li>
          <li>
            Notwithstanding the above, using this IS does not constitute consent to PM,
            LE or CI investigative searching or monitoring of the content of privileged
            communications, or work product, related to personal representation or
            services by attorneys, psychotherapists, or clergy, and their assistants.
            Such communications and work product are private and confidential. See User
            Agreement for details.
          </li>
        </ul>
      </div>
      <button ref="okButton" type="button" @click="$emit('accept')">OK</button>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'

// Standard DoD Notice and Consent Banner (DTM 08-060) — the text above is the
// mandated wording and must not be paraphrased. Shown before authentication;
// dismissal requires explicit acknowledgment.

defineEmits(['accept'])

const okButton = ref(null)

onMounted(() => okButton.value?.focus())
</script>

<style scoped>
/* Fronts the login page's dark-scrimmed slideshow — committed dark styling. */

.banner-overlay {
  position: absolute;
  inset: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(5, 8, 15, 0.55);
  backdrop-filter: blur(6px);
}

.banner {
  display: flex;
  flex-direction: column;
  width: min(720px, 100%);
  max-height: min(80vh, 680px);
  padding: 28px 30px 24px;
  border-radius: 14px;
  background: rgba(9, 13, 22, 0.92);
  border: 1px solid rgba(255, 255, 255, 0.16);
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.6);
}

h2 {
  margin: 0 0 12px;
  font-size: 16px;
  font-weight: 650;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  text-align: center;
  color: #e6edf3;
}

.banner-body {
  overflow-y: auto;
  font-size: 13px;
  line-height: 1.6;
  color: rgba(230, 237, 243, 0.88);
}

.banner-body p { margin: 0 0 10px; }

.banner-body ul {
  margin: 0;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

button {
  align-self: center;
  margin-top: 18px;
  padding: 9px 48px;
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

button:focus-visible {
  outline: 2px solid #93c5fd;
  outline-offset: 2px;
}
</style>
