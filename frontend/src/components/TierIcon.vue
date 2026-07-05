<!-- SAFe tier badge icons (issue #175) — Jira-style rounded-square badges
     with a white glyph, one color per tier: Epic purple lightning bolt
     (Jira's epic icon, instantly recognized), Capability teal layered
     diamond (the cross-cutting tier Jira lacks — hue sits between epic
     purple and feature blue), Feature blue bookmark (parallels Jira's
     story bookmark one tier down). Untyped/unknown epics get a neutral
     gray dot badge. Inline SVG: no icon fonts, no CDN. -->
<template>
  <svg
    class="tier-icon"
    :width="size" :height="size"
    viewBox="0 0 16 16"
    :aria-label="type || 'untyped'"
    role="img"
  >
    <rect x="0" y="0" width="16" height="16" rx="3.5" :fill="badge.bg" />
    <path v-if="badge.glyph" :d="badge.glyph" fill="#fff" :opacity="badge.opacity || 1" />
    <path v-if="badge.glyph2" :d="badge.glyph2" fill="#fff" opacity="0.55" />
    <circle v-if="badge.dot" cx="8" cy="8" r="2.6" fill="#fff" opacity="0.85" />
  </svg>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  type: { type: String, default: null },   // 'Epic' | 'Capability' | 'Feature' | null
  size: { type: [Number, String], default: 16 },
})

const BADGES = {
  Epic:       { bg: '#8250df', glyph: 'M9.2 1.8 4.4 8.8h3l-.9 5.4 5.1-7.2h-3z' },
  Capability: { bg: '#0d9488', glyph: 'M8 2.4 12.4 5.6 8 8.8 3.6 5.6Z',
                glyph2: 'M8 7.4 12.4 10.6 8 13.8 3.6 10.6Z' },
  Feature:    { bg: '#2563eb', glyph: 'M4.8 2.6h6.4v10.8L8 10.6l-3.2 2.8Z' },
}
const UNTYPED = { bg: '#6b7280', dot: true }

const badge = computed(() => BADGES[props.type] || UNTYPED)
</script>

<style scoped>
.tier-icon {
  flex-shrink: 0;
  display: inline-block;
  vertical-align: -0.18em;
}
</style>
