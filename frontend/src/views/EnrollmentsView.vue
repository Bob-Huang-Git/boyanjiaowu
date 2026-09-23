<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

type Student = { id: string; student_no: string; full_name: string }
type Course = { id: string; course_name: string }
type Version = { id: string; version_name: string; status: string }
const students = ref<Student[]>([]); const courses = ref<Course[]>([]); const versions = ref<Version[]>([]); const enrollments = ref<Record<string, unknown>[]>([])
const form = ref({ student_id: '', course_id: '', course_offering_version_id: '' })
async function load() { students.value = (await api<{items:Student[]}>('/students?page_size=100')).items; courses.value = (await api<{items:Course[]}>('/courses')).items; enrollments.value = (await api<{items:Record<string, unknown>[]}>('/enrollments')).items }
async function courseChanged() { versions.value = form.value.course_id ? (await api<{items:Version[]}>(`/courses/${form.value.course_id}/versions`)).items.filter(v => v.status === 'PUBLISHED') : []; form.value.course_offering_version_id = '' }
async function create() { try { await api('/enrollments', { method:'POST', body:JSON.stringify({ student_id:form.value.student_id, course_offering_version_id:form.value.course_offering_version_id, idempotency_key:crypto.randomUUID() }) }); await load(); ElMessage.success('报名已创建') } catch (error) { ElMessage.error(error instanceof Error ? error.message : '报名失败') } }
onMounted(load)
</script>
<template><section><h1>课程报名</h1><p>新报名会固化当前已发布课程版本的方案和规则；滚班将在后续班级阶段处理。</p><el-card><el-form inline @submit.prevent="create"><el-form-item label="学员"><el-select v-model="form.student_id" filterable><el-option v-for="student in students" :key="student.id" :label="`${student.student_no} · ${student.full_name}`" :value="student.id"/></el-select></el-form-item><el-form-item label="课程"><el-select v-model="form.course_id" @change="courseChanged"><el-option v-for="course in courses" :key="course.id" :label="course.course_name" :value="course.id"/></el-select></el-form-item><el-form-item label="已发布版本"><el-select v-model="form.course_offering_version_id"><el-option v-for="version in versions" :key="version.id" :label="version.version_name" :value="version.id"/></el-select></el-form-item><el-button type="primary" :disabled="!form.student_id || !form.course_offering_version_id" native-type="submit">创建报名</el-button></el-form></el-card><el-table :data="enrollments" style="margin-top:16px"><el-table-column prop="enrollment_no" label="报名编号"/><el-table-column prop="course_name" label="课程"/><el-table-column prop="version_name" label="版本"/><el-table-column prop="lifecycle_status" label="生命周期"/><el-table-column prop="financial_status" label="收费状态"/></el-table></section></template>
