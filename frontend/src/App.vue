<template>
  <RouterView />
</template>

<script setup>
import './assets/theme.css'
import './composables/useTheme.js'  // applies data-theme before first render
</script>
