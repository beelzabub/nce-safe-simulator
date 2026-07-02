import { ref } from 'vue'

// Shared "command for the operation the user is currently looking at" — set by
// launch surfaces (a hovered job row, an open tool dialog updating live as
// params change, the report picker) and read by the docked CommandBar. A single
// surface replaces the per-widget previews so every operation is covered
// uniformly and there is one place to style (issue #140).
//
// Kept separate from useCliCommand.js (the pure builders) so that module stays
// dependency-free for the cross-language contract test.
const _previewCommand = ref('')

export function useCommandPreview() {
  return {
    previewCommand: _previewCommand,
    setPreview:   (cmd) => { _previewCommand.value = cmd || '' },
    clearPreview: (only) => {
      // Optional guard: only clear if the current value still matches `only`,
      // so a stale event can't wipe a newer preview.
      if (only === undefined || _previewCommand.value === only) _previewCommand.value = ''
    },
  }
}
