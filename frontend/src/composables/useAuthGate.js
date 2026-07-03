// Session gate for the login front door (epic #135, issue #157).
//
// Dispatches on the server's auth method (GET /api/auth/session):
// - "none":  no server enforcement — the cosmetic per-browser-session flag
//   keeps today's front-door behavior (sessionStorage so closing the browser
//   re-triggers login + DoD banner).
// - "basic" (and future AAA methods): the server session is the truth;
//   login/logout round-trip to /api/auth/*.
//
// All gate logic lives here so each new AAA method (#152-#156) lands in the
// server and this file, never in views or the router.

import { getSession, postLogin, postLogout } from '../api.js'

const GATE_KEY = 'nce.auth.accepted'

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
      await postLogout()
    },
  }
}
