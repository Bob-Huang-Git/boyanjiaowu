<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

type Row = Record<string, any>
const tab = ref('receivables')
const receivables = ref<Row[]>([]); const payments = ref<Row[]>([]); const payables = ref<Row[]>([]); const refunds = ref<Row[]>([])
const exceptions = ref<Record<string, Row[]>>({}); const agency = ref<Row>({})
const studentId = ref(''); const amount = ref<number>(); const paymentMethod = ref('BANK_TRANSFER'); const paymentId = ref(''); const receivableId = ref(''); const allocationAmount = ref<number>()
const busy = ref(false)
const yuan = (cent: unknown) => `¥${(Number(cent || 0) / 100).toFixed(2)}`

async function load() {
  const [r, p, a, rr, ex] = await Promise.all([
    api<{items: Row[]}>('/receivables'), api<{items: Row[]}>('/payments'), api<Row>('/finance/agency-summary'),
    api<{items: Row[]}>('/refund-requests'), api<Record<string, Row[]>>('/finance/exceptions'),
  ])
  receivables.value = r.items; payments.value = p.items; agency.value = a; payables.value = a.items || []; refunds.value = rr.items; exceptions.value = ex
}
async function createPayment() {
  if (!studentId.value || !amount.value) return
  busy.value = true
  try {
    const row = await api<Row>('/payments', { method:'POST', body:JSON.stringify({ student_id:studentId.value, received_amount_cent:amount.value, payment_method:paymentMethod.value, received_at:new Date().toISOString(), idempotency_key:crypto.randomUUID() }) })
    await api(`/payments/${row.id}/confirm`, { method:'POST', body:JSON.stringify({ version:row.version }) })
    ElMessage.success('收款已确认'); await load()
  } catch (e) { ElMessage.error(String(e)) } finally { busy.value = false }
}
async function allocate() {
  const payment = payments.value.find(row => row.id === paymentId.value)
  if (!payment || !receivableId.value || !allocationAmount.value) return
  try { await api(`/payments/${payment.id}/allocate`, { method:'POST', body:JSON.stringify({ version:payment.version, receivable_id:receivableId.value, allocated_amount_cent:allocationAmount.value, idempotency_key:crypto.randomUUID() }) }); ElMessage.success('收款分配成功'); await load() } catch (e) { ElMessage.error(String(e)) }
}
onMounted(() => load().catch(e => ElMessage.error(String(e))))
</script>

<template>
  <section class="page"><header><div><h1>财务工作台</h1><p>金额单位为分，页面换算为人民币元展示。确认资金记录通过冲正保留历史。</p></div><el-button @click="$router.push('/')">返回工作台</el-button></header>
    <el-tabs v-model="tab">
      <el-tab-pane label="应收与收款" name="receivables">
        <el-card class="form"><h3>录入并确认线下收款</h3><el-input v-model="studentId" placeholder="学员 ID"/><el-input-number v-model="amount" :min="1" placeholder="金额（分）"/><el-select v-model="paymentMethod"><el-option label="银行转账" value="BANK_TRANSFER"/><el-option label="现金" value="CASH"/><el-option label="微信线下确认" value="WECHAT_OFFLINE_CONFIRMED"/><el-option label="支付宝线下确认" value="ALIPAY_OFFLINE_CONFIRMED"/></el-select><el-button type="primary" :loading="busy" @click="createPayment">录入并确认</el-button></el-card>
        <el-table :data="receivables"><el-table-column prop="receivable_no" label="应收编号"/><el-table-column prop="receivable_type" label="类型"/><el-table-column prop="economic_nature" label="资金性质"/><el-table-column label="应付"><template #default="s">{{ yuan(s.row.payable_amount_cent) }}</template></el-table-column><el-table-column label="已分配"><template #default="s">{{ yuan(s.row.allocated_amount_cent) }}</template></el-table-column><el-table-column label="待收"><template #default="s">{{ yuan(s.row.outstanding_amount_cent) }}</template></el-table-column><el-table-column prop="receivable_status" label="状态"/></el-table>
      </el-tab-pane>
      <el-tab-pane label="收款分配" name="payments"><el-card class="form"><el-select v-model="paymentId" filterable placeholder="选择收款"><el-option v-for="p in payments" :key="p.id" :label="`${p.payment_no} · 未分配 ${yuan(p.unallocated_amount_cent)}`" :value="p.id"/></el-select><el-select v-model="receivableId" filterable placeholder="选择应收"><el-option v-for="r in receivables.filter(x=>x.outstanding_amount_cent>0)" :key="r.id" :label="`${r.receivable_no} · ${r.economic_nature} · ${yuan(r.outstanding_amount_cent)}`" :value="r.id"/></el-select><el-input-number v-model="allocationAmount" :min="1"/><el-button type="primary" @click="allocate">确认分配</el-button></el-card><el-table :data="payments"><el-table-column prop="payment_no" label="收款编号"/><el-table-column prop="student_id" label="学员"/><el-table-column label="实收"><template #default="s">{{ yuan(s.row.received_amount_cent) }}</template></el-table-column><el-table-column label="未分配"><template #default="s">{{ yuan(s.row.unallocated_amount_cent) }}</template></el-table-column><el-table-column prop="payment_status" label="状态"/></el-table></el-tab-pane>
      <el-tab-pane label="代收代缴" name="agency"><el-row :gutter="12" class="stats"><el-col :span="6"><el-statistic title="已代收" :value="agency.collected_amount_cent || 0" suffix=" 分"/></el-col><el-col :span="6"><el-statistic title="应代缴" :value="agency.payable_amount_cent || 0" suffix=" 分"/></el-col><el-col :span="6"><el-statistic title="已代缴" :value="agency.paid_amount_cent || 0" suffix=" 分"/></el-col><el-col :span="6"><el-statistic title="未代缴" :value="agency.unpaid_amount_cent || 0" suffix=" 分"/></el-col></el-row><el-table :data="payables"><el-table-column prop="agency_payable_no" label="应代缴编号"/><el-table-column prop="payee_name" label="考试机构"/><el-table-column label="应代缴"><template #default="s">{{ yuan(s.row.payable_amount_cent) }}</template></el-table-column><el-table-column label="已代缴"><template #default="s">{{ yuan(s.row.paid_amount_cent) }}</template></el-table-column><el-table-column prop="payable_status" label="状态"/></el-table></el-tab-pane>
      <el-tab-pane label="退费" name="refunds"><el-table :data="refunds"><el-table-column prop="refund_request_no" label="退费编号"/><el-table-column prop="course_enrollment_id" label="报名"/><el-table-column label="计算可退"><template #default="s">{{ yuan(s.row.calculated_refundable_amount_cent) }}</template></el-table-column><el-table-column label="批准"><template #default="s">{{ yuan(s.row.approved_refund_amount_cent) }}</template></el-table-column><el-table-column label="已退"><template #default="s">{{ yuan(s.row.paid_refund_amount_cent) }}</template></el-table-column><el-table-column prop="request_status" label="状态"/></el-table></el-tab-pane>
      <el-tab-pane label="异常队列" name="exceptions"><el-alert title="异常均可下钻到原始资金或业务记录" type="warning" :closable="false"/><h3>收款未分配</h3><el-table :data="exceptions.unallocated_payments"><el-table-column prop="payment_no" label="收款编号"/><el-table-column label="未分配"><template #default="s">{{ yuan(s.row.amount_cent) }}</template></el-table-column></el-table><h3>考试费用未交接</h3><el-table :data="exceptions.exam_assessments_not_handed_off"><el-table-column prop="assessment_no" label="费用认定编号"/></el-table><h3>批准退款待付款</h3><el-table :data="exceptions.approved_refunds_unpaid"><el-table-column prop="refund_request_no" label="退费编号"/><el-table-column label="待付"><template #default="s">{{ yuan(s.row.unpaid_amount_cent) }}</template></el-table-column></el-table></el-tab-pane>
    </el-tabs>
  </section>
</template>
<style scoped>.page{padding:24px}header{display:flex;justify-content:space-between;align-items:start}p{color:#667085}.form{margin-bottom:16px}.form :deep(.el-card__body){display:flex;gap:12px;align-items:center}.form h3{white-space:nowrap}.stats{margin:16px 0}h3{margin-top:20px}</style>
