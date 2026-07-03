// Session gate for the login front door (epic #135).
//
// Cosmetic for now: no server-side identity exists yet, so "authenticated"
// is a per-browser-session flag. sessionStorage is deliberate — closing the
// browser re-triggers the front door (login + DoD banner), matching the
// consent-notice session semantics. All flag logic lives here so the future
// real-AAA work (server-issued session via POST /api/auth/login) replaces
// this one file instead of touching views and the router.

const GATE_KEY = 'nce.auth.accepted'

export function useAuthGate() {
  return {
    accepted: () => sessionStorage.getItem(GATE_KEY) === '1',
    accept:   () => sessionStorage.setItem(GATE_KEY, '1'),
    clear:    () => sessionStorage.removeItem(GATE_KEY),
  }
}
