import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { guest: true, title: '登录' }
    },
    {
      path: '/register',
      name: 'register',
      component: () => import('@/views/RegisterView.vue'),
      meta: { guest: true, title: '注册' }
    },
    {
      path: '/',
      component: () => import('@/layouts/AppLayout.vue'),
      children: [
        { path: '', redirect: '/chat' },
        {
          path: 'chat',
          name: 'chat',
          component: () => import('@/views/ChatView.vue'),
          meta: { title: '知识库问答', flush: true }
        },
        {
          path: 'admin/kbs',
          name: 'admin-kbs',
          component: () => import('@/views/AdminKbsView.vue'),
          meta: { title: '知识库管理', admin: true }
        },
        {
          path: 'admin/kbs/:id',
          name: 'admin-kb-detail',
          component: () => import('@/views/AdminKbDetailView.vue'),
          meta: { title: '知识库详情', admin: true }
        },
        {
          path: 'admin/stats',
          name: 'admin-stats',
          component: () => import('@/views/AdminStatsView.vue'),
          meta: { title: '数据统计', admin: true }
        },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('@/views/SettingsView.vue'),
          meta: { title: '账号设置' }
        }
      ]
    },
    { path: '/:pathMatch(.*)*', redirect: '/chat' }
  ]
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.bootstrap()
  if (to.meta.guest) {
    return auth.isLoggedIn ? { name: 'chat' } : true
  }
  if (!auth.isLoggedIn) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.meta.admin && !auth.isAdmin) {
    return { name: 'chat' }
  }
  return true
})

router.afterEach((to) => {
  document.title = `${(to.meta.title as string) || '知识库'} · 电商知识库问答`
})

export default router
