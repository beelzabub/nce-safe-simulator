import { createRouter, createWebHistory } from 'vue-router'
import { useAuthGate } from '../composables/useAuthGate.js'

const routes = [
  {
    path: '/',
    component: () => import('../views/HomeView.vue'),
  },
  {
    path: '/login',
    component: () => import('../views/LoginView.vue'),
  },
  {
    // JQL search — the "issue navigator" (epic #297, issue #302)
    path: '/search',
    component: () => import('../views/SearchView.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

// Front-door gate (epic #135): unauthenticated navigation lands on /login.
// The gate consults the server session (or the cosmetic client flag while
// auth.method is "none") — see composables/useAuthGate.js.
router.beforeEach(async (to) => {
  if (to.path !== '/login' && !(await useAuthGate().accepted())) return '/login'
})

export default router
