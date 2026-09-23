<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

type Subject = { id: string; subject_code: string; subject_name: string }
type Scheme = { id: string; version_no: string; name: string; subjects: Subject[] }
type BatchSubject = Subject & { exam_start_at: string; initial_exam_fee_amount_cent?: number; resit_fee_amount_cent?: number }
type Batch = { id: string; batch_code: string; batch_name: string; exam_scheme_version_id?: string; batch_status: string; exam_start_date: string; exam_end_date: string; version: number; subjects?: BatchSubject[] }
type Enrollment = { id: string; enrollment_no: string; course_name: string; exam_status: string }
type Fee = { id: string; assessment_no: string; fee_type: string; responsibility: string; amount_cent: number; assessment_status: string; version: number }
type ImportLine = { row_number: number; status: string; result: { message: string } }

const tab = ref('batches')
const schemes = ref<Scheme[]>([])
const batches = ref<Batch[]>([])
const enrollments = ref<Enrollment[]>([])
const fees = ref<Fee[]>([])
const selectedBatch = ref<Batch | null>(null)
const selectedSubjectIds = ref<string[]>([])
const enrollmentId = ref('')
const importFile = ref<File | null>(null)
const importBatchId = ref('')
const importLines = ref<ImportLine[]>([])
const batchForm = ref({ batch_code: '', batch_name: '', exam_scheme_version_id: '', exam_start_date: '', exam_end_date: '' })
const subjectForm = ref({ course_subject_version_id: '', exam_start_at: '', initial_exam_fee_amount_cent: 0, resit_fee_amount_cent: 0 })
const chosenScheme = computed(() => schemes.value.find(item => item.id === batchForm.value.exam_scheme_version_id))
const selectedScheme = computed(() => schemes.value.find(item => item.id === selectedBatch.value?.exam_scheme_version_id))

async function load() {
  const [schemeData, batchData, enrollmentData, feeData] = await Promise.all([
    api<{ items: Scheme[] }>('/exam-schemes'),
    api<{ items: Batch[] }>('/exam-batches'),
    api<{ items: Enrollment[] }>('/enrollments'),
    api<{ items: Fee[] }>('/exam-fee-assessments'),
  ])
  schemes.value = schemeData.items
  batches.value = batchData.items
  enrollments.value = enrollmentData.items
  fees.value = feeData.items
}
async function createBatch() {
  try {
    await api('/exam-batches', { method: 'POST', body: JSON.stringify(batchForm.value) })
    ElMessage.success('考试批次已创建')
    await load()
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '创建失败') }
}
async function selectBatch(row: Batch) {
  selectedBatch.value = await api<Batch>(`/exam-batches/${row.id}`)
  selectedSubjectIds.value = []
}
async function addSubject() {
  if (!selectedBatch.value) return
  try {
    await api(`/exam-batches/${selectedBatch.value.id}/subjects`, { method: 'POST', body: JSON.stringify(subjectForm.value) })
    await selectBatch(selectedBatch.value)
    ElMessage.success('批次科目已添加')
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '添加失败') }
}
async function openBatch() {
  if (!selectedBatch.value) return
  const result = await api<Batch>(`/exam-batches/${selectedBatch.value.id}/open`, { method: 'POST', body: JSON.stringify({ version: selectedBatch.value.version }) })
  ElMessage.success('批次已开放报名')
  await load(); await selectBatch(result)
}
async function registerExam() {
  if (!selectedBatch.value) return
  try {
    await api('/exam-registrations', { method: 'POST', body: JSON.stringify({ course_enrollment_id: enrollmentId.value, exam_batch_id: selectedBatch.value.id, exam_batch_subject_ids: selectedSubjectIds.value, idempotency_key: crypto.randomUUID() }) })
    ElMessage.success('考试报名已创建；初考或补考由系统根据历史判断')
    await load()
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '报名失败') }
}
function chooseImport(file: { raw: File }) { importFile.value = file.raw; return false }
async function previewImport() {
  if (!importFile.value) return
  const body = new FormData(); body.set('file', importFile.value)
  try {
    const result = await api<{ id: string; items: ImportLine[] }>('/imports/exam-results/preview', { method: 'POST', body })
    importBatchId.value = result.id; importLines.value = result.items
    ElMessage.success('预检完成，尚未写入成绩')
  } catch (error) { ElMessage.error(error instanceof Error ? error.message : '预检失败') }
}
async function confirmImport() {
  const result = await api<{ items: ImportLine[] }>(`/imports/exam-results/${importBatchId.value}/confirm`, { method: 'POST', body: JSON.stringify({ idempotency_key: crypto.randomUUID() }) })
  importLines.value = result.items
  ElMessage.success('合法行已导入并进入待官方确认状态')
}
function downloadTemplate() { window.open('/api/imports/exam-results/template', '_blank', 'noopener') }
async function feeAction(item: Fee, action: 'confirm' | 'waive') {
  const reason = action === 'waive' ? '教务批准减免' : undefined
  await api(`/exam-fee-assessments/${item.id}/${action}`, { method: 'POST', body: JSON.stringify({ version: item.version, reason }) })
  await load(); ElMessage.success(action === 'waive' ? '费用依据已减免' : '费用依据已确认')
}
onMounted(load)
</script>

<template>
  <section>
    <h1>考试工作台</h1>
    <p>管理分科报名、多次补考、成绩确认与费用认定。费用仅表示待财务处理，不代表已收款。</p>
    <el-tabs v-model="tab">
      <el-tab-pane label="考试批次" name="batches">
        <el-card>
          <el-form inline @submit.prevent="createBatch">
            <el-form-item label="编码"><el-input v-model="batchForm.batch_code" /></el-form-item>
            <el-form-item label="名称"><el-input v-model="batchForm.batch_name" /></el-form-item>
            <el-form-item label="考试方案"><el-select v-model="batchForm.exam_scheme_version_id"><el-option v-for="item in schemes" :key="item.id" :value="item.id" :label="`${item.name} ${item.version_no}`" /></el-select></el-form-item>
            <el-form-item label="开始"><el-date-picker v-model="batchForm.exam_start_date" value-format="YYYY-MM-DD" /></el-form-item>
            <el-form-item label="结束"><el-date-picker v-model="batchForm.exam_end_date" value-format="YYYY-MM-DD" /></el-form-item>
            <el-button type="primary" native-type="submit">创建批次</el-button>
          </el-form>
        </el-card>
        <el-table :data="batches" style="margin-top: 16px" @row-click="selectBatch"><el-table-column prop="batch_code" label="编码"/><el-table-column prop="batch_name" label="名称"/><el-table-column prop="exam_start_date" label="考试日期"/><el-table-column prop="batch_status" label="状态"/></el-table>
        <el-card v-if="selectedBatch" class="panel">
          <h2>{{ selectedBatch.batch_name }} · 科目与报名</h2>
          <el-form v-if="selectedBatch.batch_status === 'DRAFT'" inline @submit.prevent="addSubject">
            <el-form-item label="科目"><el-select v-model="subjectForm.course_subject_version_id"><el-option v-for="item in selectedScheme?.subjects ?? chosenScheme?.subjects ?? []" :key="item.id" :value="item.id" :label="`${item.subject_code} · ${item.subject_name}`" /></el-select></el-form-item>
            <el-form-item label="考试时间"><el-date-picker v-model="subjectForm.exam_start_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ssZ" /></el-form-item>
            <el-form-item label="初考费(分)"><el-input-number v-model="subjectForm.initial_exam_fee_amount_cent" :min="0" /></el-form-item>
            <el-form-item label="补考费(分)"><el-input-number v-model="subjectForm.resit_fee_amount_cent" :min="0" /></el-form-item>
            <el-button native-type="submit">添加科目</el-button><el-button type="success" @click="openBatch">开放报名</el-button>
          </el-form>
          <el-checkbox-group v-model="selectedSubjectIds"><el-checkbox v-for="item in selectedBatch.subjects" :key="item.id" :value="item.id">{{ item.subject_code }} · {{ item.subject_name }}</el-checkbox></el-checkbox-group>
          <div v-if="selectedBatch.batch_status === 'OPEN'" class="register"><el-select v-model="enrollmentId" filterable placeholder="选择课程报名"><el-option v-for="item in enrollments" :key="item.id" :value="item.id" :label="`${item.enrollment_no} · ${item.course_name} · ${item.exam_status}`" /></el-select><el-button type="primary" :disabled="!enrollmentId || !selectedSubjectIds.length" @click="registerExam">报名所选科目</el-button></div>
        </el-card>
      </el-tab-pane>
      <el-tab-pane label="成绩导入" name="results">
        <el-alert title="Preview 只检查数据，不写入成绩；确认后合法行进入待官方确认状态。" type="info" :closable="false" />
        <div class="actions"><el-button @click="downloadTemplate">下载模板</el-button><el-upload :auto-upload="false" :limit="1" :on-change="chooseImport"><el-button>选择 xlsx</el-button></el-upload><el-button type="primary" :disabled="!importFile" @click="previewImport">预检</el-button><el-button type="success" :disabled="!importBatchId" @click="confirmImport">确认导入</el-button></div>
        <el-table :data="importLines"><el-table-column prop="row_number" label="行"/><el-table-column prop="status" label="状态"/><el-table-column label="说明"><template #default="scope">{{ scope.row.result.message }}</template></el-table-column></el-table>
      </el-tab-pane>
      <el-tab-pane label="费用认定" name="fees">
        <el-alert title="以下为考试业务产生的费用依据，等待 Sprint 5 财务模块处理。" type="warning" :closable="false" />
        <el-table :data="fees"><el-table-column prop="assessment_no" label="认定编号"/><el-table-column prop="fee_type" label="类型"/><el-table-column prop="responsibility" label="责任方"/><el-table-column label="金额"><template #default="scope">¥{{ (scope.row.amount_cent / 100).toFixed(2) }}</template></el-table-column><el-table-column prop="assessment_status" label="状态"/><el-table-column label="操作"><template #default="scope"><el-button v-if="scope.row.assessment_status === 'DRAFT'" text @click="feeAction(scope.row, 'confirm')">确认</el-button><el-button v-if="['DRAFT','CONFIRMED'].includes(scope.row.assessment_status)" text type="warning" @click="feeAction(scope.row, 'waive')">减免</el-button></template></el-table-column></el-table>
      </el-tab-pane>
    </el-tabs>
  </section>
</template>

<style scoped>.panel{margin-top:16px}.register,.actions{display:flex;gap:12px;align-items:center;margin:16px 0}.register .el-select{width:420px}p{color:#667085}</style>
