import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { authApi } from '@/api'
import { clearTokens, getAccessToken, setTokens } from '@/api/client'
import type { User } from '@/types'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const ready = ref(false)
  const loading = ref(false)

  const isLoggedIn = computed(() => Boolean(user.value))
  const isAdmin = computed(() => user.value?.role === 'admin')

  async function bootstrap(): Promise<void> {
    if (ready.value) return
    if (!getAccessToken()) {
      ready.value = true
      return
    }
    try {
      user.value = await authApi.me()
    } catch {
      clearTokens()
      user.value = null
    } finally {
      ready.value = true
    }
  }

  async function login(username: string, password: string): Promise<void> {
    loading.value = true
    try {
      const data = await authApi.login(username, password)
      setTokens(data)
      user.value = data.user
      ready.value = true
    } finally {
      loading.value = false
    }
  }

  async function register(username: string, password: string): Promise<void> {
    loading.value = true
    try {
      const data = await authApi.register(username, password)
      setTokens(data)
      user.value = data.user
      ready.value = true
    } finally {
      loading.value = false
    }
  }

  async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
    const data = await authApi.changePassword(oldPassword, newPassword)
    setTokens(data)
    user.value = data.user
  }

  async function logout(): Promise<void> {
    try {
      await authApi.logout()
    } catch {
      /* 忽略网络异常，本地清除即可 */
    }
    clearTokens()
    user.value = null
  }

  return {
    user,
    ready,
    loading,
    isLoggedIn,
    isAdmin,
    bootstrap,
    login,
    register,
    changePassword,
    logout
  }
})
