<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
type Session = { id:string; session_title:string; service_date:string; planned_minutes:number; actual_minutes:number|null; session_status:string; version:number }
const route=useRoute(); const router=useRouter(); const rows=ref<Session[]>([]); const progress=ref<Record<string,number>>({}); const form=ref({session_title:'',planned_start_at:'',planned_end_at:''})
async function load(){const id=String(route.params.id); rows.value=(await api<{items:Session[]}>(`/classes/${id}/sessions`)).items; progress.value=await api(`/classes/${id}/teaching-progress`)}
async function create(){try{await api(`/classes/${route.params.id}/sessions`,{method:'POST',body:JSON.stringify(form.value)});await load();ElMessage.success('课次已创建')}catch(error){ElMessage.error(error instanceof Error?error.message:'创建失败')}}
async function schedule(item:Session){try{await api(`/class-sessions/${item.id}/schedule`,{method:'POST',body:JSON.stringify({version:item.version,reason:'教务排定'})});await load()}catch(error){ElMessage.error(error instanceof Error?error.message:'操作失败')}}
onMounted(load)
</script>
<template><section><el-button text @click="router.push('/classes')">← 返回班级</el-button><h1>班级教学计划</h1><div class="summary"><el-tag>计划 {{ progress.planned_minutes || 0 }} 分钟</el-tag><el-tag type="success">已完成 {{ progress.completed_minutes || 0 }} 分钟</el-tag><el-tag type="warning">已取消 {{ progress.cancelled_minutes || 0 }} 分钟</el-tag></div><el-card><el-form inline @submit.prevent="create"><el-form-item label="课次主题"><el-input v-model="form.session_title"/></el-form-item><el-form-item label="计划开始"><el-input v-model="form.planned_start_at" placeholder="2026-09-23T09:00:00+08:00"/></el-form-item><el-form-item label="计划结束"><el-input v-model="form.planned_end_at" placeholder="2026-09-23T11:00:00+08:00"/></el-form-item><el-button type="primary" native-type="submit">创建课次</el-button></el-form></el-card><el-table :data="rows" style="margin-top:16px"><el-table-column prop="service_date" label="日期"/><el-table-column prop="session_title" label="主题"/><el-table-column prop="planned_minutes" label="计划分钟"/><el-table-column prop="actual_minutes" label="实际分钟"/><el-table-column prop="session_status" label="状态"/><el-table-column label="操作"><template #default="scope"><el-button v-if="scope.row.session_status==='DRAFT'" text @click="schedule(scope.row)">排定</el-button></template></el-table-column></el-table></section></template>
<style scoped>.summary{display:flex;gap:8px;margin-bottom:14px}</style>
