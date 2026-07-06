import { ref } from 'vue'

// Which surface the main pane is showing. JobRunner stays mounted (v-show)
// so live job streams never unmount; 'report' and 'analysis' render sibling
// panes (issues #167 / #169). Module-level singleton like the other
// composables — any component may switch the view without prop drilling.
const mainView = ref('jobs')

// The wiki page open in the report view: {date, time, slug} — MarkdownView
// fetches content itself so a stale page never flashes while loading.
const reportPage = ref(null)

// Bumped only by content actions (opening a page / an analysis), never by
// plain tab-driven view switches — the phone drawer closes on content
// actions so the result is visible, but stays open while browsing tabs.
const contentEpoch = ref(0)

export function useMainView() {
  function showMain(view) {
    mainView.value = view
  }
  function openReport(page) {
    reportPage.value = page
    mainView.value = 'report'
    contentEpoch.value++
  }
  function openAnalysis() {
    mainView.value = 'analysis'
    contentEpoch.value++
  }
  return { mainView, reportPage, contentEpoch, showMain, openReport, openAnalysis }
}
