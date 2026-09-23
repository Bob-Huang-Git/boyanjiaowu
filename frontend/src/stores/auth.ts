import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, type User } from '../api'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const loaded = ref(false)

  async function load() {
    try {
      user.value = await api<User>('/auth/me')
    } catch {
      user.value = null
    } finally {
      loaded.value = true
    }
  }

  async function login(username: string, password: string) {
    user.value = await api<User>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    loaded.value = true
  }

  async function logout() {
    await api('/auth/logout', { method: 'POST' })
    user.value = null
  }

  return { user, loaded, load, login, logout }
})

