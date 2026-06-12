<template>
  <main>
    <h1>NCE Safe Simulator</h1>
    <JobPicker :running-jobs="runningJobs" @launch="onLaunch" />
  </main>
</template>

<script setup>
import { ref } from 'vue'
import JobPicker from '../components/JobPicker.vue'

// Populated by WebSocket job events — wired in E3.
const runningJobs = ref([])

function onLaunch(job) {
  console.log('launch', job.key)
}
</script>

<style scoped>
main {
  padding: 2rem;
  font-family: system-ui, sans-serif;
}
h1 {
  margin-bottom: 1.5rem;
}
</style>
