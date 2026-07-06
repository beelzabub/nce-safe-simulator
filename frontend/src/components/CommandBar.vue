<!-- Bottom-docked "equivalent CLI command" bar (issue #140). Shows the command
     for whatever operation the user is currently looking at — a hovered job row,
     an open tool dialog (live as params change), or the report picker — with a
     copy button. One persistent surface for every operation, replacing the
     per-widget previews. The command persists after a dialog closes so the last
     one stays reachable (issue #185). The authoritative command for a *launched*
     run is echoed into that run's output by the server. -->
<template>
  <div class="cmd-bar">
    <CliCommandStrip
      :command="previewCommand"
      empty-hint="Hover or configure an operation to see its CLI command"
    />
  </div>
</template>

<script setup>
import CliCommandStrip from './CliCommandStrip.vue'
import { useCommandPreview } from '../composables/useCommandPreview.js'

const { previewCommand } = useCommandPreview()
</script>

<style scoped>
.cmd-bar {
  flex-shrink: 0;
  border-top: 1px solid var(--border);
  background: var(--surface);
}

/* ── Mobile (issue #160): the bar is a hover affordance, and on touch the
   emulated mouseenter fires mid-tap — the bar popping in reflows the job list
   between touchend and the synthesized click, eating the tap. Hide it outright
   below the phone breakpoint; the authoritative command is still echoed into
   every run's output, and dialogs carry their own copy of the command bar. ── */
@media (max-width: 768px) {
  .cmd-bar { display: none; }
}
</style>
