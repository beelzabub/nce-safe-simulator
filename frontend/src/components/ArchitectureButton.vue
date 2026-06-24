<template>
  <button class="arch-fab" title="AWS Architecture" @click="$emit('open')">
    <!-- AWS logo-mark: orange square with white "a" -->
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40" width="24" height="24" aria-hidden="true">
      <rect width="40" height="40" rx="4" fill="#FF9900"/>
      <path d="M12.3 26.1l-1.4 1.5c-.1.1-.1.3 0 .4.9.8 2 1.2 3.2 1.2 1.7 0 2.9-.9 2.9-2.4 0-1.3-.8-2-2.3-2.5l-.7-.3c-.8-.3-1.1-.6-1.1-1.1 0-.6.5-.9 1.2-.9.6 0 1.2.2 1.7.6.1.1.3.1.4 0l1.2-1.4c.1-.1.1-.3 0-.4-.8-.7-1.8-1-2.8-1-1.7 0-2.9.9-2.9 2.3 0 1.3.9 2 2.2 2.5l.7.3c.8.3 1.2.6 1.2 1.1 0 .6-.5 1-1.3 1-.8 0-1.5-.3-2.1-.9-.1-.1-.2-.1-.3 0zm8.6 3.1h2l1.3-3.8 1.4 3.8h2l2.2-6.2h-2l-1.2 3.8-1.3-3.8h-1.8l-1.3 3.8-1.2-3.8h-2l2.2 6.2z" fill="#fff"/>
    </svg>
  </button>
</template>

<script setup>
defineEmits(['open'])
</script>

<style scoped>
.arch-fab {
  position: fixed;
  bottom: 1.25rem;
  right: 1.25rem;
  z-index: 150;
  width: 44px;
  height: 44px;
  border-radius: 50%;
  border: none;
  background: rgba(35, 47, 62, 0.55);
  backdrop-filter: blur(4px);
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0.7;
  transition: opacity 0.2s, transform 0.2s;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
}
.arch-fab:hover {
  opacity: 1;
  transform: scale(1.08);
}
</style>
