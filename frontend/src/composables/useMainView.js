import { ref } from 'vue'

// Which surface the main pane is showing. JobRunner stays mounted (v-show)
// so live job streams never unmount; 'report' and 'analysis' render sibling
// panes (issues #167 / #169). Module-level singleton like the other
// composables — any component may switch the view without prop drilling.
const mainView = ref('jobs')

// The wiki page open in the report view: {date, time, slug} — MarkdownView
// fetches content itself so a stale page never flashes while loading.
const reportPage = ref(null)

export function useMainView() {
  function showMain(view) {
    mainView.value = view
  }
  function openReport(page) {
    reportPage.value = page
    mainView.value = 'report'
  }
  function openAnalysis() {
    mainView.value = 'analysis'
  }
  return { mainView, reportPage, showMain, openReport, openAnalysis }
}
