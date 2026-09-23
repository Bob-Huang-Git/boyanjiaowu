<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import { useAuthStore } from '../stores/auth'

type Enrollment = Record<string, unknown>
type VeteranIdentity = {
  exists: boolean
  id?: string
  retirement_card_no_masked?: string
  retired_on?: string
  service_branch?: string
  identity_status?: string
  verified_status?: string
}
type FundingCase = {
  exists: boolean
  id?: string
  case_status?: string
  region?: string
  department?: string
  components?: { component_type: string; component_status: string }[]
}
type AllowanceSummary = {
  cases: {
    funding_case_id: string
    course_enrollment_id: string
    region: string
    department: string
    case_status: string
    payables: {
      id: string
      allowance_type: string
      payable_amount_cent: number
      paid_amount_cent: number
      outstanding_amount_cent: number
      payable_status: string
    }[]
  }[]
  payable_total_cent: number
  paid_total_cent: number
}

const props = defineProps<{ studentId: string; enrollments: Enrollment[] }>()
const auth = useAuthStore()
const permissions = computed(() => new Set(auth.user?.permissions ?? []))
const can = (permission: string) =>
  permissions.value.has('system.admin') || permissions.value.has(permission)

const loading = ref(false)
const identity = ref<VeteranIdentity>({ exists: false })
const verifications = ref<Record<string, unknown>[]>([])
const attributes = ref<Record<string, unknown>[]>([])
const cases = ref<Record<string, FundingCase>>({})
const summary = ref<AllowanceSummary>({ cases: [], payable_total_cent: 0, paid_total_cent: 0 })

const identityForm = ref({ retirement_card_no: '', retired_on: '', service_branch: '', remarks: '' })
const identityDialog = ref(false)
const yuan = (cent: number | undefined) => `¥${(Number(cent || 0) / 100).toFixed(2)}`

async function loadIdentity() {
  if (!can('veteran_identity.read')) return
  identity.value = await api<VeteranIdentity>(`/students/${props.studentId}/veteran-identity`)
  if (identity.value.exists && identity.value.id) {
    const [verificationResult, attributeResult] = await Promise.all([
      api<{ items: Record<string, unknown>[] }>(`/veteran-identities/${identity.value.id}/verifications`),
      api<{ items: Record<string, unknown>[] }>(`/veteran-identities/${identity.value.id}/attributes`),
    ])
    verifications.value = verificationResult.items
    attributes.value = attributeResult.items
  } else {
    verifications.value = []
    attributes.value = []
  }
}

async function loadCases() {
  if (!can('funding_case.read')) return
  const results = await Promise.all(
    props.enrollments.map(async (enrollment) => [
      String(enrollment.id),
      await api<FundingCase>(`/enrollments/${enrollment.id}/funding-case`),
    ] as const),
  )
  cases.value = Object.fromEntries(results)
}

async function loadSummary() {
  if (!can('funding.allowance.read')) return
  summary.value = await api<AllowanceSummary>(`/students/${props.studentId}/allowance-summary`)
}

async function load() {
  loading.value = true
  try {
    await Promise.all([loadIdentity(), loadCases(), loadSummary()])
  } finally {
    loading.value = false
  }
}

async function createIdentity() {
  try {
    await api(`/students/${props.studentId}/veteran-identity`, {
      method: 'POST',
      body: JSON.stringify({
        retirement_card_no: identityForm.value.retirement_card_no || null,
        retired_on: identityForm.value.retired_on || null,
        service_branch: identityForm.value.service_branch || null,
        remarks: identityForm.value.remarks || null,
      }),
    })
    identityDialog.value = false
    ElMessage.success('退役身份主档已建立')
    await loadIdentity()
  } catch (error) {
    ElMessage.error(`身份主档保存失败：${String(error)}`)
  }
}

async function verifyIdentity(status: 'PASSED' | 'FAILED') {
  if (!identity.value.id) return
  let method = ''
  try {
    const result = await ElMessageBox.prompt('请输入核验方式或依据', status === 'PASSED' ? '核验通过' : '核验不通过', {
      inputPattern: /.+/,
      inputErrorMessage: '必须填写核验依据',
    })
    method = result.value
  } catch {
    return
  }
  try {
    await api(`/veteran-identities/${identity.value.id}/verifications`, {
      method: 'POST',
      body: JSON.stringify({ verification_status: status, method }),
    })
    ElMessage.success('核验结论已保存，历史记录已保留')
    await loadIdentity()
  } catch (error) {
    ElMessage.error(`核验保存失败：${String(error)}`)
  }
}

async function openCase(enrollmentId: string) {
  let programVersionId = ''
  try {
    const result = await ElMessageBox.prompt('请输入已发布的政府项目版本 ID', '建立资格案', {
      inputPattern: /.+/,
      inputErrorMessage: '项目版本 ID 不能为空',
    })
    programVersionId = result.value
  } catch {
    return
  }
  try {
    await api(`/enrollments/${enrollmentId}/funding-case`, {
      method: 'POST',
      body: JSON.stringify({ funding_program_version_id: programVersionId }),
    })
    ElMessage.success('资格案已建立')
    await Promise.all([loadCases(), loadSummary()])
  } catch (error) {
    ElMessage.error(`资格案建立失败：${String(error)}`)
  }
}

onMounted(load)
watch(() => props.enrollments, loadCases)
</script>

<template>
  <div v-loading="loading" class="funding-panel">
    <el-alert
      v-if="!can('veteran_identity.read')"
      type="warning"
      :closable="false"
      title="当前账号没有退役身份查看权限"
    />
    <template v-else>
      <div class="section-title">
        <h3>退役身份</h3>
        <el-button
          v-if="!identity.exists && can('veteran_identity.manage')"
          type="primary"
          @click="identityDialog = true"
        >建立身份主档</el-button>
      </div>
      <el-empty v-if="!identity.exists" description="尚未建立退役身份主档" />
      <template v-else>
        <el-descriptions :column="3" border>
          <el-descriptions-item label="退役证号">{{ identity.retirement_card_no_masked || '未登记' }}</el-descriptions-item>
          <el-descriptions-item label="退役日期">{{ identity.retired_on || '—' }}</el-descriptions-item>
          <el-descriptions-item label="军种">{{ identity.service_branch || '—' }}</el-descriptions-item>
          <el-descriptions-item label="身份状态">{{ identity.identity_status }}</el-descriptions-item>
          <el-descriptions-item label="核验状态">
            <el-tag :type="identity.verified_status === 'VERIFIED' ? 'success' : 'warning'">
              {{ identity.verified_status }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="核验操作">
            <template v-if="can('veteran_identity.verify')">
              <el-button text type="success" @click="verifyIdentity('PASSED')">通过</el-button>
              <el-button text type="danger" @click="verifyIdentity('FAILED')">不通过</el-button>
            </template>
          </el-descriptions-item>
        </el-descriptions>

        <h4>核验历史</h4>
        <el-table :data="verifications" empty-text="暂无核验记录">
          <el-table-column prop="verification_no" label="核验编号" />
          <el-table-column prop="verification_status" label="结论" />
          <el-table-column prop="method" label="方式/依据" />
          <el-table-column prop="verified_on" label="核验日期" />
          <el-table-column prop="note" label="备注" />
        </el-table>

        <h4>身份属性历史</h4>
        <el-table :data="attributes" empty-text="暂无身份属性历史">
          <el-table-column prop="attribute_code" label="属性" />
          <el-table-column prop="value_text" label="值" />
          <el-table-column prop="effective_from" label="生效日期" />
          <el-table-column prop="effective_to" label="失效日期" />
          <el-table-column prop="source" label="来源" />
        </el-table>
      </template>
    </template>

    <template v-if="can('funding_case.read')">
      <h3>报名资格案</h3>
      <el-table :data="enrollments" empty-text="暂无报名记录">
        <el-table-column prop="enrollment_no" label="报名编号" />
        <el-table-column prop="course_name" label="课程" />
        <el-table-column prop="lifecycle_status" label="报名状态" />
        <el-table-column label="资格案状态">
          <template #default="scope">
            <el-tag v-if="cases[String(scope.row.id)]?.exists">
              {{ cases[String(scope.row.id)]?.case_status }}
            </el-tag>
            <span v-else>未建立</span>
          </template>
        </el-table-column>
        <el-table-column label="地区/部门">
          <template #default="scope">
            {{ cases[String(scope.row.id)]?.region || '—' }} /
            {{ cases[String(scope.row.id)]?.department || '—' }}
          </template>
        </el-table-column>
        <el-table-column label="操作">
          <template #default="scope">
            <el-button
              v-if="!cases[String(scope.row.id)]?.exists && can('funding_case.manage')"
              text
              type="primary"
              @click="openCase(String(scope.row.id))"
            >建立资格案</el-button>
          </template>
        </el-table-column>
      </el-table>
    </template>

    <template v-if="can('funding.allowance.read')">
      <div class="section-title totals">
        <h3>补贴权益与支付</h3>
        <div>
          应付合计 <strong>{{ yuan(summary.payable_total_cent) }}</strong>
          · 已付合计 <strong>{{ yuan(summary.paid_total_cent) }}</strong>
          · 未付 <strong>{{ yuan(summary.payable_total_cent - summary.paid_total_cent) }}</strong>
        </div>
      </div>
      <el-table :data="summary.cases.flatMap((item) => item.payables.map((payable) => ({ ...payable, ...item })))" empty-text="暂无补贴应付">
        <el-table-column prop="allowance_type" label="补贴类型" />
        <el-table-column prop="region" label="地区" />
        <el-table-column prop="department" label="部门" />
        <el-table-column label="应付"><template #default="scope">{{ yuan(scope.row.payable_amount_cent) }}</template></el-table-column>
        <el-table-column label="已付"><template #default="scope">{{ yuan(scope.row.paid_amount_cent) }}</template></el-table-column>
        <el-table-column label="未付"><template #default="scope">{{ yuan(scope.row.outstanding_amount_cent) }}</template></el-table-column>
        <el-table-column prop="payable_status" label="状态" />
      </el-table>
    </template>

    <el-dialog v-model="identityDialog" title="建立退役身份主档" width="560px">
      <el-form label-width="100px">
        <el-form-item label="退役证号"><el-input v-model="identityForm.retirement_card_no" /></el-form-item>
        <el-form-item label="退役日期"><el-date-picker v-model="identityForm.retired_on" value-format="YYYY-MM-DD" /></el-form-item>
        <el-form-item label="军种"><el-input v-model="identityForm.service_branch" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="identityForm.remarks" type="textarea" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="identityDialog = false">取消</el-button>
        <el-button type="primary" @click="createIdentity">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.funding-panel { display: grid; gap: 16px; }
.section-title { display: flex; align-items: center; justify-content: space-between; }
.section-title h3, h4 { margin: 0; }
.totals { margin-top: 8px; }
</style>
