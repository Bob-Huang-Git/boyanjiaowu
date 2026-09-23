<script setup lang="ts">
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const menu = [
  { label: '工作台', route: 'home', permission: null },
  { label: '学员', route: 'students', permission: 'student.read' },
  { label: '课程', route: 'courses', permission: 'course.read' },
  { label: '报名', route: 'enrollments', permission: 'enrollment.read' },
  { label: '班级', route: 'classes', permission: 'class.read' },
  { label: '考试', route: 'exams', permission: 'exam.batch.read' },
  { label: '证书', route: 'certificates', permission: 'certificate.read' },
  { label: '财务', route: 'finance', permission: 'receivable.read' },
  { label: '教师结算', route: 'teacher-settlements', permission: 'teacher_settlement.read' },
  { label: '政府项目与补贴', route: 'funding', permission: 'funding_case.read' },
  { label: '系统管理', permission: 'system.admin' },
]

async function logout() {
  try {
    await auth.logout()
    await router.push({ name: 'login' })
  } catch {
    ElMessage.error('退出失败，请重试')
  }
}
</script>

<template>
  <el-container class="shell">
    <el-aside width="220px" class="sidebar">
      <h2>教务系统</h2>
      <el-menu default-active="工作台">
        <el-menu-item v-for="item in menu.filter((entry) => !entry.permission || auth.user?.permissions.includes(entry.permission))" :key="item.label" :index="item.label" @click="item.route && router.push({ name: item.route })">{{ item.label }}</el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header"><span>{{ auth.user?.display_name }}</span><el-button text @click="logout">退出</el-button></el-header>
      <el-main><h1>工作台</h1><p>学员、课程、教学、考试、证书、资金结算与政府补贴业务已接入。</p></el-main>
    </el-container>
  </el-container>
</template>

<style scoped>
.shell { min-height: 100vh; }
.sidebar { border-right: 1px solid #e4e7ec; }
.sidebar h2 { padding: 16px 20px; font-size: 18px; }
.header { display: flex; align-items: center; justify-content: flex-end; gap: 12px; border-bottom: 1px solid #e4e7ec; }
</style>
