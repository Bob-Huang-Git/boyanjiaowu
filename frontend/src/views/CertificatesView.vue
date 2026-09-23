<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

type Certificate = { id: string; certificate_case_no: string; course_enrollment_id: string; eligibility_status: string; certificate_status: string; certificate_no_masked?: string; version: number }
const rows = ref<Certificate[]>([])
const selected = ref<Record<string, unknown> | null>(null)
const attachment = ref<File | null>(null)
async function load() { rows.value = (await api<{ items: Certificate[] }>('/certificates')).items }
async function detail(item: Certificate) { selected.value = await api(`/certificates/${item.id}`) }
async function transition(item: Certificate, action: string, extra: Record<string, unknown> = {}) {
  try { await api(`/certificates/${item.id}/${action}`, { method:'POST', body:JSON.stringify({ version:item.version, ...extra }) }); await load(); ElMessage.success('证书状态已更新') } catch (error) { ElMessage.error(error instanceof Error ? error.message : '操作失败') }
}
async function issue(item: Certificate) { try { const value = await ElMessageBox.prompt('请输入证书编号', '标记已发证', { inputPattern:/.+/, inputErrorMessage:'必须填写证书编号' }); await transition(item, 'mark-issued', { certificate_no:value.value }) } catch { /* cancelled */ } }
async function deliver(item: Certificate) { await transition(item, 'deliver', { delivery_method:'PICKUP', recipient_name:'学员本人' }) }
function chooseAttachment(file: { raw: File }) { attachment.value = file.raw; return false }
async function uploadAttachment() { if (!selected.value || !attachment.value) return; const body = new FormData(); body.set('attachment_type', 'CERTIFICATE_SCAN'); body.set('file', attachment.value); await api(`/certificates/${String(selected.value.id)}/attachments`, { method:'POST', body }); attachment.value = null; selected.value = await api(`/certificates/${String(selected.value.id)}`); ElMessage.success('证书附件已上传到本地附件中心') }
onMounted(load)
</script>
<template><section><h1>证书工作台</h1><p>学校收到证书和学员收到证书分别记录，每次状态变化保留事件历史。</p><el-table :data="rows" @row-click="detail"><el-table-column prop="certificate_case_no" label="案例编号"/><el-table-column prop="course_enrollment_id" label="课程报名"/><el-table-column prop="eligibility_status" label="资格"/><el-table-column prop="certificate_status" label="证书状态"/><el-table-column prop="certificate_no_masked" label="证书编号"/><el-table-column label="操作" width="380"><template #default="scope"><el-button v-if="scope.row.certificate_status==='ELIGIBLE'" text @click.stop="transition(scope.row,'start-application')">申请</el-button><el-button v-if="scope.row.certificate_status==='APPLYING'" text @click.stop="issue(scope.row)">已发证</el-button><el-button v-if="scope.row.certificate_status==='ISSUED'" text @click.stop="transition(scope.row,'receive-by-school')">学校已收到</el-button><el-button v-if="scope.row.certificate_status==='RECEIVED_BY_SCHOOL'" text @click.stop="transition(scope.row,'ready-for-delivery')">待发放</el-button><el-button v-if="scope.row.certificate_status==='READY_FOR_DELIVERY'" text type="success" @click.stop="deliver(scope.row)">发放</el-button></template></el-table-column></el-table><el-card v-if="selected" style="margin-top:16px"><h2>证书详情</h2><div class="upload"><el-upload :auto-upload="false" :limit="1" :on-change="chooseAttachment"><el-button>选择证书扫描件或签收凭证</el-button></el-upload><el-button type="primary" :disabled="!attachment" @click="uploadAttachment">上传附件</el-button></div><el-descriptions :column="3" border><el-descriptions-item v-for="(value,key) in selected" :key="key" :label="String(key)">{{ value }}</el-descriptions-item></el-descriptions></el-card></section></template>
<style scoped>p{color:#667085}.upload{display:flex;gap:12px;align-items:center;margin-bottom:16px}</style>
