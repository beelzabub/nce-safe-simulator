<template>
  <div class="log-wrap">
    <button
      v-if="lines.length"
      type="button"
      class="copy-btn"
      :class="{ 'copy-btn--done': copied }"
      :title="copied ? 'Copied to clipboard' : 'Copy all output'"
      @click="copyAll"
    >
      <svg v-if="copied" viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
        <path d="M3.5 8.5 6.5 11.5 12.5 4.5" fill="none" stroke="currentColor"
              stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      <svg v-else viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
        <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" fill="none"
              stroke="currentColor" stroke-width="1.4" />
        <path d="M10.5 5.5V4A1.5 1.5 0 0 0 9 2.5H4A1.5 1.5 0 0 0 2.5 4v5A1.5 1.5 0 0 0 4 10.5h1.5"
              fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" />
      </svg>
      {{ copied ? 'Copied' : 'Copy' }}
    </button>

    <div ref="el" class="log-pane" @scroll.passive="onScroll">
      <div v-if="lines.length === 0" class="log-empty">Waiting for output…</div>
      <pre v-else class="log-content"><template v-for="(line, i) in lines" :key="i"><template v-for="part in parseLine(line)" :key="part.value"><a v-if="part.type === 'download'" :href="part.value" :download="part.filename" class="log-download" rel="noopener">⤓ Download {{ part.filename }}</a><a v-else-if="part.type === 'url'" :href="part.value" target="_blank" rel="noopener" class="log-link">{{ part.value }}</a><span v-else-if="part.type === 'hint'" class="log-hint">{{ part.value }}</span><span v-else>{{ part.value }}</span></template>{{ i < lines.length - 1 ? '\n' : '' }}</template></pre>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'
import { downloadFilename } from '../download.js'

const props = defineProps({
  lines: { type: Array, required: true },
})

const el = ref(null)
let pinned = true

const copied = ref(false)
let copiedTimer = null

async function copyAll() {
  const text = props.lines.join('\n')
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // Fallback for non-secure contexts / older browsers.
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    try { document.execCommand('copy') } catch { /* ignore */ }
    document.body.removeChild(ta)
  }
  copied.value = true
  clearTimeout(copiedTimer)
  copiedTimer = setTimeout(() => { copied.value = false }, 1500)
}

function onScroll() {
  const div = el.value
  if (!div) return
  pinned = div.scrollHeight - div.scrollTop - div.clientHeight < 8
}

watch(() => props.lines.length, async () => {
  if (!pinned) return
  await nextTick()
  const div = el.value
  if (div) div.scrollTop = div.scrollHeight
})

// Absolute http(s) URLs, plus app-relative export download links
// (e.g. /api/download/foo.csv) emitted by the export tools.
const URL_RE = /(?:https?:\/\/\S+|\/api\/download\/\S+)/g

const LINE_HINTS = [
  {
    pattern: /429|Too many requests/i,
    hint: ' — GitLab rate limit; retrying automatically (up to 5×, ~30 s backoff)',
  },
]

function parseLine(line) {
  const parts = []
  let last = 0
  URL_RE.lastIndex = 0
  let m
  while ((m = URL_RE.exec(line)) !== null) {
    if (m.index > last) parts.push({ type: 'text', value: line.slice(last, m.index) })
    if (m[0].startsWith('/api/download/')) {
      // Render a clean "⤓ Download <filename>" button instead of the raw path.
      parts.push({ type: 'download', value: m[0], filename: downloadFilename(m[0]) })
    } else {
      parts.push({ type: 'url', value: m[0] })
    }
    last = m.index + m[0].length
  }
  if (last < line.length) parts.push({ type: 'text', value: line.slice(last) })
  if (!parts.length) parts.push({ type: 'text', value: line })

  for (const { pattern, hint } of LINE_HINTS) {
    if (pattern.test(line)) {
      parts.push({ type: 'hint', value: hint })
      break
    }
  }
  return parts
}
</script>

<style scoped>
.log-wrap {
  position: relative;
  height: 100%;
}
.copy-btn {
  position: absolute;
  top: 8px;
  right: 14px;
  z-index: 5;
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 9px;
  font-size: 0.72rem;
  font-family: inherit;
  color: var(--text-2, #9aa4b2);
  background: color-mix(in srgb, var(--surface, #161b22) 88%, transparent);
  border: 1px solid var(--border, #30363d);
  border-radius: 5px;
  cursor: pointer;
  opacity: 0.65;
  backdrop-filter: blur(2px);
  transition: opacity 0.15s, color 0.15s, border-color 0.15s;
}
.log-wrap:hover .copy-btn { opacity: 1; }
.copy-btn:hover {
  color: var(--text-1, #e6edf3);
  border-color: var(--action, #2563eb);
}
.copy-btn--done {
  opacity: 1;
  color: #16a34a;
  border-color: #16a34a;
}

.log-pane {
  height: 100%;
  overflow-y: auto;
  background: var(--bg, #0d1117);
  padding: 0.75rem 1rem;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 0.8rem;
  color: var(--text-1, #e6edf3);
}
.log-empty {
  color: var(--text-3, #6e7681);
  font-style: italic;
}
.log-content {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.5;
}
.log-link {
  color: var(--action, #2563eb);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.log-link:hover {
  color: var(--action-hover, #3b82f6);
}
.log-hint {
  color: var(--text-3, #6e7681);
  font-style: italic;
}
/* Download affordance — an inline terminal-style link, not a boxed button,
   so it sits naturally inside the monospace output pane. */
.log-download {
  color: var(--action, #2563eb);
  text-decoration: underline;
  text-underline-offset: 2px;
  cursor: pointer;
}
.log-download:hover {
  color: var(--action-hover, #3b82f6);
}
</style>
