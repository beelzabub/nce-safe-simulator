// Session gate for the login front door (epic #135, issue #157).
//
// Dispatches on the server's auth method (GET /api/auth/session):
// - "none":  no server enforcement — the cosmetic per-browser-session flag
//   keeps today's front-door behavior (sessionStorage-scoped).
// - "basic" (and future AAA methods): the server session is the truth;
//   login/logout round-trip to /api/auth/*.
// Either way, logout() clears both the gate flag and the DoD banner ack, so
// closing the browser OR signing out both re-trigger the banner on the next
// logon attempt.
//
// All gate logic lives here so each new AAA method (#152-#156) lands in the
// server and this file, never in views or the router.

import { getSession, postLogin, postLogout } from '../api.js'

const GATE_KEY = 'nce.auth.accepted'

// DoD Notice and Consent acknowledgment (DTM 08-060) — exported so LoginView
// can gate the banner on it and logout() can clear it. The banner must be
// re-acknowledged on every fresh logon attempt, not just once per browser
// tab: signing out and back in is a new access attempt.
export const BANNER_ACK_KEY = 'nce.auth.dodBannerAccepted'

export function useAuthGate() {
  return {
    // Async: consults the server. With method "none" falls back to the
    // cosmetic client-side flag.
    async accepted() {
      const s = await getSession()
      if (s.method === 'none') return sessionStorage.getItem(GATE_KEY) === '1'
      return s.authenticated === true
    },

    // Returns true on success; false means invalid credentials (the caller
    // shows the inline error).
    async login(username, password) {
      const s = await postLogin(username, password)
      if (s.method === 'none') {
        sessionStorage.setItem(GATE_KEY, '1')
        return true
      }
      return s.authenticated === true
    },

    async logout() {
      sessionStorage.removeItem(GATE_KEY)
      sessionStorage.removeItem(BANNER_ACK_KEY)
      await postLogout()
    },
  }
}
