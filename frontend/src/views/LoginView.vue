<script setup lang="ts">
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const form = reactive({ username: '', password: '' })
const busy = ref(false)
const auth = useAuthStore()
const router = useRouter()

async function submit() {
  busy.value = true
  try {
    await auth.login(form.username, form.password)
    await router.push({ name: 'home' })
  } catch {
    ElMessage.error('用户名或密码错误')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="login">
    <el-card class="login-card">
      <h1>职业培训教务系统</h1>
      <p>请使用机构账号登录</p>
      <el-form :model="form" @submit.prevent="submit">
        <el-form-item label="用户名"><el-input v-model="form.username" autocomplete="username" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="form.password" type="password" autocomplete="current-password" show-password /></el-form-item>
        <el-button type="primary" native-type="submit" :loading="busy" style="width: 100%">登录</el-button>
      </el-form>
    </el-card>
  </main>
</template>

<style scoped>
.login { min-height: 100vh; display: grid; place-items: center; background: #f4f7fb; padding: 24px; }
.login-card { width: min(420px, 100%); }
h1 { font-size: 22px; margin: 0 0 8px; }
p { color: #667085; margin-bottom: 24px; }
</style>

