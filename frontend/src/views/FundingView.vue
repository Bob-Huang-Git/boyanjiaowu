<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { useAuthStore } from '../stores/auth'

type Program = { id: string; program_code: string; program_name: string; department: string; active: boolean }
type DayFact = {
  id: string
  student_id: string
  course_enrollment_id: string
  fact_date: string
  planned_minutes: number
  attended_minutes: number
  late_minutes: number
  leave_minutes: number
  absent_minutes: number
  day_part: string
  fact_version: number
  fact_status: string
}
type LodgingNight = {
  id: string
  student_id: string
  course_enrollment_id: string
  night_date: string
  location: string
  review_status: string
}
type Policy = {
  id: string
  region: string
  department: string
  allowance_type: string
  version_no: string
  basis_rule: string
  unit_amount_cent: number
  effective_from: string
  effective_to?: string
  policy_status: string
}
type Payable = {
  id: string
  student_id: string
  allowance_type: string
  payable_amount_cent: number
  paid_amount_cent: number
  outstanding_amount_cent: number
  payable_status: string
}

const auth = useAuthStore()
const permissions = computed(() => new Set(auth.user?.permissions ?? []))
const can = (permission: string) => permissions.value.has('system.admin') || permissions.value.has(permission)
const activeTab = ref('programs')
const loading = ref(false)
const programs = ref<Program[]>([])
const facts = ref<DayFact[]>([])
const nights = ref<LodgingNight[]>([])
const policies = ref<Policy[]>([])
const payables = ref<Payable[]>([])
const factEnrollmentId = ref('')
const factStudentId = ref('')
const nightEnrollmentId = ref('')
const payableStatus = ref('')
const programDialog = ref(false)
const programForm = ref({ program_code: '', program_name: '', department: '', remarks: '' })
const yuan = (cent: number | undefined) => `¥${(Number(cent || 0) / 100).toFixed(2)}`

function query(params: Record<string, string>) {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => value && search.set(key, value))
  const text = search.toString()
  return text ? `?${text}` : ''
}

async function loadPrograms() {
  if (!can('funding_program.read')) return
  programs.value = (await api<{ items: Program[] }>('/funding-programs')).items
}

async function loadFacts() {
  if (!can('funding.allowance.read')) return
  facts.value = await api<DayFact[]>(`/attendance-day-facts${query({ enrollment_id: factEnrollmentId.value, student_id: factStudentId.value })}`)
}

async function loadNights() {
  if (!can('funding.allowance.read')) return
  nights.value = await api<LodgingNight[]>(`/lodging-night-facts${query({ enrollment_id: nightEnrollmentId.value })}`)
}

async function loadPolicies() {
  if (!can('funding.allowance.read')) return
  policies.value = await api<Policy[]>('/allowance-policies')
}

async function loadPayables() {
  if (!can('funding.allowance.read')) return
  payables.value = await api<Payable[]>(`/allowance-payables${query({ status: payableStatus.value })}`)
}

async function load() {
  loading.value = true
  try {
    await Promise.all([loadPrograms(), loadFacts(), loadNights(), loadPolicies(), loadPayables()])
  } finally {
    loading.value = false
  }
}

async function createProgram() {
  try {
    await api('/funding-programs', { method: 'POST', body: JSON.stringify(programForm.value) })
    programDialog.value = false
    programForm.value = { program_code: '', program_name: '', department: '', remarks: '' }
    ElMessage.success('政府项目已建立')
    await loadPrograms()
  } catch (error) {
    ElMessage.error(`政府项目保存失败：${String(error)}`)
  }
}

async function confirmFact(item: DayFact) {
  try {
    await api(`/attendance-day-facts/${item.id}/confirm`, { method: 'POST' })
    ElMessage.success('每日出勤事实已确认')
    await loadFacts()
  } catch (error) {
    ElMessage.error(`每日事实确认失败：${String(error)}`)
  }
}

async function pay(item: Payable) {
  let amountCent = 0
  try {
    const result = await ElMessageBox.prompt(`当前未付 ${yuan(item.outstanding_amount_cent)}，请输入本次支付金额（元）`, '登记补贴支付', {
      inputPattern: /^\d+(\.\d{1,2})?$/,
      inputErrorMessage: '请输入有效金额，最多两位小数',
    })
    amountCent = Math.round(Number(result.value) * 100)
  } catch {
    return
  }
  try {
    await api(`/allowance-payables/${item.id}/payments`, {
      method: 'POST',
      body: JSON.stringify({
        amount_cent: amountCent,
        payment_method: 'BANK_TRANSFER',
        paid_on: new Date().toISOString().slice(0, 10),
        idempotency_key: `web-${item.id}-${Date.now()}`,
      }),
    })
    ElMessage.success('补贴支付已登记')
    await loadPayables()
  } catch (error) {
    ElMessage.error(`补贴支付登记失败：${String(error)}`)
  }
}

onMounted(load)
</script>

<template>
  <section v-loading="loading">
    <div class="page-heading">
      <div><h1>政府项目与补贴</h1><p>政府项目、出勤事实、住宿事实、补贴政策和学员补贴支付。</p></div>
      <el-button @click="load">刷新</el-button>
    </div>
    <el-tabs v-model="activeTab">
      <el-tab-pane v-if="can('funding_program.read')" label="政府项目" name="programs">
        <div class="toolbar">
          <el-button v-if="can('funding_program.manage')" type="primary" @click="programDialog = true">新建项目</el-button>
        </div>
        <el-table :data="programs">
          <el-table-column prop="program_code" label="项目编码" />
          <el-table-column prop="program_name" label="项目名称" />
          <el-table-column prop="department" label="主管部门" />
          <el-table-column label="状态"><template #default="scope"><el-tag :type="scope.row.active ? 'success' : 'info'">{{ scope.row.active ? '启用' : '停用' }}</el-tag></template></el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane v-if="can('funding.allowance.read')" label="每日出勤事实" name="facts">
        <div class="toolbar">
          <el-input v-model="factEnrollmentId" clearable placeholder="报名 ID" />
          <el-input v-model="factStudentId" clearable placeholder="学员 ID" />
          <el-button type="primary" @click="loadFacts">查询</el-button>
        </div>
        <el-table :data="facts">
          <el-table-column prop="fact_date" label="日期" />
          <el-table-column prop="student_id" label="学员 ID" min-width="190" />
          <el-table-column prop="course_enrollment_id" label="报名 ID" min-width="190" />
          <el-table-column prop="planned_minutes" label="计划分钟" />
          <el-table-column prop="attended_minutes" label="出勤分钟" />
          <el-table-column prop="late_minutes" label="迟到" />
          <el-table-column prop="leave_minutes" label="请假" />
          <el-table-column prop="absent_minutes" label="缺勤" />
          <el-table-column prop="day_part" label="计日" />
          <el-table-column prop="fact_status" label="状态" />
          <el-table-column label="操作">
            <template #default="scope"><el-button v-if="can('funding.allowance.manage') && scope.row.fact_status !== 'CONFIRMED'" text type="primary" @click="confirmFact(scope.row)">确认</el-button></template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane v-if="can('funding.allowance.read')" label="住宿事实" name="lodging">
        <div class="toolbar">
          <el-input v-model="nightEnrollmentId" clearable placeholder="报名 ID" />
          <el-button type="primary" @click="loadNights">查询</el-button>
        </div>
        <el-table :data="nights">
          <el-table-column prop="night_date" label="住宿日期" />
          <el-table-column prop="student_id" label="学员 ID" min-width="190" />
          <el-table-column prop="course_enrollment_id" label="报名 ID" min-width="190" />
          <el-table-column prop="location" label="地点" />
          <el-table-column prop="review_status" label="审核状态" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane v-if="can('funding.allowance.read')" label="补贴政策" name="policies">
        <el-table :data="policies">
          <el-table-column prop="region" label="地区" />
          <el-table-column prop="department" label="部门" />
          <el-table-column prop="allowance_type" label="补贴类型" />
          <el-table-column prop="version_no" label="版本" />
          <el-table-column prop="basis_rule" label="计发规则" />
          <el-table-column label="单位金额"><template #default="scope">{{ yuan(scope.row.unit_amount_cent) }}</template></el-table-column>
          <el-table-column prop="effective_from" label="生效日期" />
          <el-table-column prop="effective_to" label="失效日期" />
          <el-table-column prop="policy_status" label="状态" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane v-if="can('funding.allowance.read')" label="补贴应付" name="payables">
        <div class="toolbar">
          <el-select v-model="payableStatus" clearable placeholder="应付状态">
            <el-option label="待支付" value="PENDING" />
            <el-option label="部分支付" value="PARTIALLY_PAID" />
            <el-option label="已结清" value="SETTLED" />
          </el-select>
          <el-button type="primary" @click="loadPayables">查询</el-button>
        </div>
        <el-table :data="payables">
          <el-table-column prop="student_id" label="学员 ID" min-width="190" />
          <el-table-column prop="allowance_type" label="补贴类型" />
          <el-table-column label="应付"><template #default="scope">{{ yuan(scope.row.payable_amount_cent) }}</template></el-table-column>
          <el-table-column label="已付"><template #default="scope">{{ yuan(scope.row.paid_amount_cent) }}</template></el-table-column>
          <el-table-column label="未付"><template #default="scope">{{ yuan(scope.row.outstanding_amount_cent) }}</template></el-table-column>
          <el-table-column prop="payable_status" label="状态" />
          <el-table-column label="操作">
            <template #default="scope"><el-button v-if="can('funding.allowance.pay') && scope.row.outstanding_amount_cent > 0" text type="primary" @click="pay(scope.row)">登记支付</el-button></template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="programDialog" title="新建政府项目" width="540px">
      <el-form label-width="100px">
        <el-form-item label="项目编码"><el-input v-model="programForm.program_code" /></el-form-item>
        <el-form-item label="项目名称"><el-input v-model="programForm.program_name" /></el-form-item>
        <el-form-item label="主管部门"><el-input v-model="programForm.department" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="programForm.remarks" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="programDialog = false">取消</el-button>
        <el-button type="primary" :disabled="!programForm.program_code || !programForm.program_name || !programForm.department" @click="createProgram">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.page-heading { display: flex; justify-content: space-between; align-items: flex-start; }
.page-heading h1 { margin-bottom: 4px; }
.page-heading p { color: #667085; }
.toolbar { display: flex; gap: 10px; margin-bottom: 16px; }
.toolbar .el-input, .toolbar .el-select { width: 240px; }
</style>
