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
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

// Front-door gate (epic #135): unauthenticated navigation lands on /login.
// The gate is a client-side session flag until real AAA exists — see
// composables/useAuthGate.js.
router.beforeEach((to) => {
  if (to.path !== '/login' && !useAuthGate().accepted()) return '/login'
})

export default router
