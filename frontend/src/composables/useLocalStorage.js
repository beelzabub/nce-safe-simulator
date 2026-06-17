export function loadStored(key, fallback) {
  try {
    const raw = localStorage.getItem(key)
    return raw !== null ? JSON.parse(raw) : fallback
  } catch {
    return fallback
  }
}

export function saveStored(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // quota exceeded or private browsing — silently ignore
  }
}
