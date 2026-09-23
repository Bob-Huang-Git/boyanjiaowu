<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useRouter } from 'vue-router'
import { api } from '../api'

type Student = { id: string; student_no: string; full_name: string; gender: string; phone_masked: string | null; document_summary: string | null; enrollment_count: number; student_status: string; updated_at: string }
const router = useRouter()
const rows = ref<Student[]>([])
const total = ref(0)
const query = reactive({ keyword: '', page: 1, page_size: 20 })
const open = ref(false)
const form = reactive({ full_name: '', phone: '', document_number: '', birth_date: '' })

async function load() {
  const params = new URLSearchParams({ page: String(query.page), page_size: String(query.page_size) })
  if (query.keyword) params.set('keyword', query.keyword)
  const result = await api<{ items: Student[]; total: number }>(`/students?${params}`)
  rows.value = result.items; total.value = result.total
}
async function create() {
  try {
    await api('/students', { method: 'POST', body: JSON.stringify({ full_name: form.full_name, phone: form.phone || undefined, birth_date: form.birth_date || undefined, identity_document: form.document_number ? { document_type: 'PRC_ID', document_number: form.document_number } : undefined }) })
    ElMessage.success('学员已创建'); open.value = false; await load()
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '创建失败') }
}
function openStudent(row: Student) {
  const returnTo = `/students?keyword=${encodeURIComponent(query.keyword)}&page=${query.page}`
  router.push({ name: 'student-detail', params: { id: row.id }, query: { returnTo, tab: 'basic' } })
}
onMounted(load)
</script>

<template>
  <section>
    <header class="toolbar"><div><h1>学员</h1><p>自然人唯一主档，列表默认展示脱敏信息。</p></div><div><el-button v-if="$route.name === 'students'" @click="router.push({ name: 'student-import' })">Excel 导入</el-button><el-button type="primary" @click="open = true">新增学员</el-button></div></header>
    <el-form inline @submit.prevent="query.page = 1; load()"><el-form-item label="关键词"><el-input v-model="query.keyword" placeholder="学员编号或姓名" clearable /></el-form-item><el-button native-type="submit">查询</el-button></el-form>
    <el-table :data="rows" @row-click="openStudent"><el-table-column prop="student_no" label="学员编号" width="170" /><el-table-column prop="full_name" label="姓名" /><el-table-column prop="gender" label="性别" width="90" /><el-table-column prop="phone_masked" label="手机号" /><el-table-column prop="document_summary" label="主证件" /><el-table-column prop="enrollment_count" label="报名数" width="90" /><el-table-column prop="student_status" label="状态" width="100" /></el-table>
    <el-pagination v-model:current-page="query.page" :page-size="query.page_size" :total="total" layout="total, prev, pager, next" @current-change="load" />
    <el-dialog v-model="open" title="新增学员" width="460"><el-form label-width="100"><el-form-item label="姓名" required><el-input v-model="form.full_name" /></el-form-item><el-form-item label="手机号"><el-input v-model="form.phone" /></el-form-item><el-form-item label="身份证件号"><el-input v-model="form.document_number" /></el-form-item><el-form-item label="出生日期"><el-date-picker v-model="form.birth_date" value-format="YYYY-MM-DD" /></el-form-item></el-form><template #footer><el-button @click="open = false">取消</el-button><el-button type="primary" @click="create">创建</el-button></template></el-dialog>
  </section>
</template>

<style scoped>.toolbar { display:flex; justify-content:space-between; align-items:center; margin-bottom:20px; } h1 { margin:0; } p { color:#667085; } .el-pagination { margin-top:16px; }</style>
