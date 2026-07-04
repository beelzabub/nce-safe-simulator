import { ref } from 'vue'

// Which surface the main pane is showing. JobRunner stays mounted (v-show)
// so live job streams never unmount; 'report' and 'analysis' render sibling
// panes (issues #167 / #169). Module-level singleton like the other
// composables — any component may switch the view without prop drilling.
const mainView = ref('jobs')

export function useMainView() {
  function showMain(view) {
    mainView.value = view
  }
  return { mainView, showMain }
}
