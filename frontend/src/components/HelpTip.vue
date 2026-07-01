<template>
  <span class="helptip" tabindex="0" role="note" :aria-label="'Help: ' + text">
    <span class="helptip-icon">?</span>
    <span class="helptip-bubble">{{ text }}</span>
  </span>
</template>

<script setup>
defineProps({ text: { type: String, required: true } })
</script>

<style scoped>
.helptip {
  position: relative;
  display: inline-flex;
  margin-left: 4px;
  cursor: help;
  outline: none;
}
.helptip-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 1px solid var(--border);
  color: var(--text-3);
  font-size: 0.62rem;
  font-weight: 700;
  line-height: 1;
  transition: color 0.12s, border-color 0.12s;
}
.helptip:hover .helptip-icon,
.helptip:focus .helptip-icon { border-color: var(--action); color: var(--action); }

.helptip-bubble {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 0;
  z-index: 30;
  width: max-content;
  max-width: 280px;
  white-space: pre-line;
  text-align: left;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 7px 9px;
  font-size: 0.72rem;
  font-weight: 400;
  line-height: 1.45;
  color: var(--text-1);
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.4);
  opacity: 0;
  visibility: hidden;
  transition: opacity 0.12s;
  pointer-events: none;
}
.helptip:hover .helptip-bubble,
.helptip:focus .helptip-bubble { opacity: 1; visibility: visible; }
</style>
