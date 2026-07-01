// Helpers for the export download links emitted by the tools as
// `/api/download/<filename>` log lines.  Shared by useJobs (auto-download on
// live completion) and LogPane (the clean "Download <filename>" button).

// Extract the suggested filename (basename) from an /api/download/ URL.
export function downloadFilename(url) {
  try {
    // Works for both absolute and app-relative URLs.
    const path = new URL(url, location.origin).pathname
    const base = path.split('/').pop() || ''
    return decodeURIComponent(base)
  } catch {
    const base = url.split('?')[0].split('#')[0].split('/').pop() || ''
    try { return decodeURIComponent(base) } catch { return base }
  }
}

// Programmatically start a browser download.  The `download` attribute carries
// the suggested filename; the endpoint also sends Content-Disposition.
export function triggerDownload(url) {
  const a = document.createElement('a')
  a.href = url
  a.download = downloadFilename(url)
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
}
