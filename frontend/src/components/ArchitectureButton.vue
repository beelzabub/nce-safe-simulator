<template>
  <button class="arch-fab" title="Architecture" @click="$emit('open')">
    <!-- AWS wordmark + smile-arrow, faithful to the actual logo -->
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 58 32" width="42" height="23" aria-hidden="true">
      <!-- "aws" lettering -->
      <text
        x="29" y="17"
        text-anchor="middle"
        font-family="'Amazon Ember', Arial, sans-serif"
        font-weight="700"
        font-size="17"
        letter-spacing="0.5"
        fill="#ffffff"
      >aws</text>
      <!-- smile arc -->
      <path
        d="M7 25 Q29 36 51 25"
        stroke="#FF9900" stroke-width="2.5" fill="none"
        stroke-linecap="round"
      />
      <!-- arrowhead at right end of smile -->
      <path
        d="M48 21 L53 25 L48 27"
        stroke="#FF9900" stroke-width="2.5" fill="none"
        stroke-linecap="round" stroke-linejoin="round"
      />
    </svg>
  </button>
</template>

<script setup>
defineEmits(['open'])
</script>

<style scoped>
.arch-fab {
  position: fixed;
  bottom: 1.1rem;
  right: 1.1rem;
  z-index: 150;
  width: 56px;
  height: 34px;
  border-radius: 6px;
  border: 1px solid rgba(255, 153, 0, 0.25);
  background: rgba(100, 116, 130, 0.18);
  backdrop-filter: blur(6px);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0.45;
  transition: opacity 0.2s, transform 0.15s, background 0.2s;
  box-shadow: 0 1px 6px rgba(0, 0, 0, 0.2);
  padding: 0;
}
.arch-fab:hover {
  opacity: 0.9;
  background: rgba(100, 116, 130, 0.35);
  transform: scale(1.05);
}
</style>
