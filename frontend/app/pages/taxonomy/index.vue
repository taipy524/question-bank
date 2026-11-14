<script setup lang="ts">
import PageHeader from '~/components/PageHeader.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { toast } from 'vue-sonner'
import { batchModeLabel, canReviewAction, describeCandidate, statusLabel } from '~/lib/taxonomy'

const { $api } = useNuxtApp()

interface Source { id: number; slug: string; commit_sha: string; license_status: string }
interface Mapping {
  id: number
  external: { external_id: string; name: string; grade?: number; semester?: string; chapter?: string }
  internal: { id: number; name: string } | null
  match_type: string
  confidence?: number | null
  high_risk: boolean
  risk?: string | null
  reason: string
  review_status: string
  revision: number
}
interface Subject { id: number; name: string }
interface KnowledgePoint { id: number; name: string; subject_id: number }
interface Batch { id: number; mode: string; status: string; summary?: Record<string, number>; conflicts?: unknown[] }

const sources = ref<Source[]>([])
const sourceId = ref<number | null>(null)
const mappings = ref<Mapping[]>([])
const newTopics = ref<Mapping[]>([])
const subjects = ref<Subject[]>([])
const knowledgePoints = ref<KnowledgePoint[]>([])
const batches = ref<Batch[]>([])
const preview = ref<{ summary: Record<string, number>; conflicts: unknown[] } | null>(null)
const loading = ref(false)
const statusFilter = ref('')
const highRiskOnly = ref(false)
const subjectId = ref<number | null>(null)
const parentId = ref('')

const filteredMappings = computed(() => {
  let rows = mappings.value
  if (statusFilter.value) rows = rows.filter(row => row.review_status === statusFilter.value)
  if (highRiskOnly.value) rows = rows.filter(row => row.high_risk)
  return rows
})
const filteredKnowledgePoints = computed(() =>
  knowledgePoints.value.filter(row => !subjectId.value || row.subject_id === subjectId.value),
)

async function loadSources() {
  sources.value = await $api<Source[]>('/taxonomy/sources')
  if (sourceId.value == null && sources.value.length > 0) sourceId.value = sources.value[0]!.id
}
async function loadMappings() {
  if (sourceId.value == null) return
  mappings.value = await $api<Mapping[]>('/taxonomy/mappings', { query: { source_id: sourceId.value, limit: 500 } })
}
async function loadNewTopics() {
  if (sourceId.value == null) return
  newTopics.value = await $api<Mapping[]>('/taxonomy/new-topics', { query: { source_id: sourceId.value, limit: 500 } })
}
async function loadBatches() {
  if (sourceId.value == null) return
  batches.value = await $api<Batch[]>('/taxonomy/batches', { query: { source_id: sourceId.value, limit: 50 } })
}
async function refreshAll() {
  if (sourceId.value == null) return
  loading.value = true
  try { await Promise.all([loadMappings(), loadNewTopics(), loadBatches()]) } finally { loading.value = false }
}

async function review(row: Mapping, action: 'confirm' | 'reject' | 'undo') {
  if (!canReviewAction(row.review_status as any, action)) return
  let comment = ''
  let acknowledge = false
  if (action === 'confirm' && row.high_risk) {
    comment = window.prompt('高风险候选：请填写审核意见（不能为空）') || ''
    if (!comment.trim()) return
    acknowledge = true
  }
  try {
    await $api(`/taxonomy/mappings/${row.id}/review`, {
      method: 'POST',
      body: { action, comment, acknowledge_high_risk: acknowledge },
    })
    toast.success('审核已记录')
    await refreshAll()
  } catch (error: any) {
    toast.error(error?.data?.detail || error.message)
  }
}

async function approveNewTopic(row: Mapping) {
  if (!subjectId.value) { toast.error('请先选择学科'); return }
  try {
    await $api(`/taxonomy/new-topics/${row.id}/approve`, {
      method: 'POST',
      body: { subject_id: subjectId.value, parent_id: parentId.value ? Number(parentId.value) : null, comment: 'UI 人工审核新增' },
    })
    toast.success('已创建并确认新增知识点')
    await refreshAll()
  } catch (error: any) {
    toast.error(error?.data?.detail || error.message)
  }
}

async function rejectNewTopic(row: Mapping) {
  try {
    await $api(`/taxonomy/new-topics/${row.id}/reject`, { method: 'POST', body: { action: 'reject', comment: 'UI 拒绝新增' } })
    toast.success('已拒绝')
    await refreshAll()
  } catch (error: any) {
    toast.error(error?.data?.detail || error.message)
  }
}

async function loadPreview() {
  if (sourceId.value == null) return
  try {
    preview.value = await $api('/taxonomy/batches/preview', { method: 'POST', body: { source_id: sourceId.value, mode: 'dry_run' } })
  } catch (error: any) {
    toast.error(error?.data?.detail || error.message)
  }
}
async function createBatch() {
  if (sourceId.value == null) return
  try {
    await $api('/taxonomy/batches', { method: 'POST', body: { source_id: sourceId.value, mode: 'apply', notes: 'UI 创建的批次' } })
    toast.success('批次已创建')
    await loadBatches()
  } catch (error: any) {
    toast.error(error?.data?.detail || error.message)
  }
}
async function executeBatch(batch: Batch) {
  try {
    const result = await $api<{ change_count: number }>(`/taxonomy/batches/${batch.id}/execute`, { method: 'POST' })
    toast.success(`批次执行完成，变更 ${result.change_count} 条`)
    await Promise.all([loadBatches(), loadPreview()])
  } catch (error: any) {
    toast.error(error?.data?.detail || error.message)
  }
}
async function rollbackBatch(batch: Batch) {
  try {
    const result = await $api<{ restored_changes: number }>(`/taxonomy/batches/${batch.id}/rollback`, { method: 'POST' })
    toast.success(`已回滚 ${result.restored_changes} 条变更`)
    await Promise.all([loadBatches(), loadPreview()])
  } catch (error: any) {
    toast.error(error?.data?.detail || error.message)
  }
}
async function loadReferenceData() {
  subjects.value = await $api<Subject[]>('/subjects')
  if (subjectId.value == null && subjects.value.length > 0) subjectId.value = subjects.value[0]!.id
  if (subjectId.value != null) {
    knowledgePoints.value = await $api<KnowledgePoint[]>('/knowledge-points', { query: { subject_id: subjectId.value, limit: -1 } })
  }
}

watch(sourceId, refreshAll)
watch(subjectId, loadReferenceData)
onMounted(async () => {
  await loadSources()
  await loadReferenceData()
  await refreshAll()
})
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="知识体系接入" description="外部 taxonomy 映射审核、无候选新增审核与导入批次（全部需人工确认）" />

    <div class="flex flex-wrap items-end gap-3">
      <label class="text-sm">来源
        <select v-model.number="sourceId" class="ml-2 rounded border px-3 py-2">
          <option :value="null" disabled>请选择来源</option>
          <option v-for="source in sources" :key="source.id" :value="source.id">
            {{ source.slug }} · {{ source.commit_sha.slice(0, 8) }} · {{ source.license_status }}
          </option>
        </select>
      </label>
      <label class="text-sm">学科
        <select v-model.number="subjectId" class="ml-2 rounded border px-3 py-2">
          <option :value="null" disabled>请选择学科</option>
          <option v-for="subject in subjects" :key="subject.id" :value="subject.id">{{ subject.name }}</option>
        </select>
      </label>
      <Button variant="outline" :disabled="loading" @click="refreshAll">刷新</Button>
    </div>

    <div v-if="sources.length === 0" class="rounded border p-4 text-sm text-muted-foreground">
      尚未登记外部来源。请先通过后端服务/命令导入来源与外部节点，再进行审核。
    </div>

    <Tabs default-value="mappings" class="space-y-4">
      <TabsList>
        <TabsTrigger value="mappings">映射审核（{{ mappings.length }}）</TabsTrigger>
        <TabsTrigger value="new-topics">无候选新增（{{ newTopics.length }}）</TabsTrigger>
        <TabsTrigger value="batches">导入批次（{{ batches.length }}）</TabsTrigger>
      </TabsList>

      <TabsContent value="mappings" class="space-y-3">
        <div class="flex flex-wrap items-center gap-3">
          <select v-model="statusFilter" class="rounded border px-3 py-2 text-sm">
            <option value="">全部状态</option>
            <option value="pending_review">待审核</option>
            <option value="confirmed">已确认</option>
            <option value="rejected">已拒绝</option>
            <option value="needs_split">需拆分</option>
            <option value="needs_merge">需合并</option>
          </select>
          <label class="flex items-center gap-2 text-sm"><input v-model="highRiskOnly" type="checkbox" /> 只看高风险</label>
        </div>
        <div class="overflow-x-auto rounded border">
          <table class="w-full text-sm">
            <thead class="bg-muted/50 text-left">
              <tr>
                <th class="p-2">外部知识点</th><th class="p-2">内部候选</th><th class="p-2">说明</th><th class="p-2">状态</th><th class="p-2">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in filteredMappings" :key="row.id" class="border-t align-top">
                <td class="p-2">
                  <div class="font-medium">{{ row.external.name }}</div>
                  <div class="text-xs text-muted-foreground">{{ row.external.external_id }} · {{ row.external.semester }} · {{ row.external.chapter || '未标注章节' }}</div>
                </td>
                <td class="p-2">
                  <div v-if="row.internal">{{ row.internal.name }}（#{{ row.internal.id }}）</div>
                  <div v-else class="text-muted-foreground">无匹配内部节点</div>
                </td>
                <td class="p-2 text-xs">
                  <div>{{ describeCandidate(row) }}</div>
                  <div class="text-muted-foreground">{{ row.reason }}</div>
                </td>
                <td class="p-2">
                  <Badge :variant="row.review_status === 'confirmed' ? 'default' : 'secondary'">{{ statusLabel(row.review_status) }}</Badge>
                  <Badge v-if="row.high_risk" variant="destructive" class="ml-1">高风险</Badge>
                </td>
                <td class="p-2">
                  <div class="flex flex-wrap gap-1">
                    <Button v-if="canReviewAction(row.review_status as any, 'confirm')" size="sm" @click="review(row, 'confirm')">确认</Button>
                    <Button v-if="canReviewAction(row.review_status as any, 'reject')" size="sm" variant="outline" @click="review(row, 'reject')">拒绝</Button>
                    <Button v-if="canReviewAction(row.review_status as any, 'undo')" size="sm" variant="ghost" @click="review(row, 'undo')">撤销</Button>
                  </div>
                </td>
              </tr>
              <tr v-if="filteredMappings.length === 0"><td colspan="5" class="p-4 text-center text-muted-foreground">暂无映射候选</td></tr>
            </tbody>
          </table>
        </div>
      </TabsContent>

      <TabsContent value="new-topics" class="space-y-3">
        <div class="flex flex-wrap items-end gap-3">
          <label class="text-sm">父节点 ID（可选）<Input v-model="parentId" class="ml-2 inline-block w-32" placeholder="例如 2" /></label>
          <div class="text-xs text-muted-foreground">
            当前学科知识点：{{ filteredKnowledgePoints.slice(0, 8).map(kp => `${kp.id}:${kp.name}`).join('，') }}
          </div>
        </div>
        <div class="overflow-x-auto rounded border">
          <table class="w-full text-sm">
            <thead class="bg-muted/50 text-left"><tr><th class="p-2">外部知识点</th><th class="p-2">册次/章节</th><th class="p-2">状态</th><th class="p-2">操作</th></tr></thead>
            <tbody>
              <tr v-for="row in newTopics" :key="row.id" class="border-t align-top">
                <td class="p-2"><div class="font-medium">{{ row.external.name }}</div><div class="text-xs text-muted-foreground">{{ row.external.external_id }}</div></td>
                <td class="p-2 text-xs">{{ row.external.grade }}年级{{ row.external.semester }} · {{ row.external.chapter }}</td>
                <td class="p-2"><Badge variant="secondary">{{ statusLabel(row.review_status) }}</Badge></td>
                <td class="p-2"><div class="flex gap-1"><Button size="sm" @click="approveNewTopic(row)">批准新增</Button><Button size="sm" variant="outline" @click="rejectNewTopic(row)">拒绝</Button></div></td>
              </tr>
              <tr v-if="newTopics.length === 0"><td colspan="4" class="p-4 text-center text-muted-foreground">暂无待审核新增节点</td></tr>
            </tbody>
          </table>
        </div>
      </TabsContent>

      <TabsContent value="batches" class="space-y-4">
        <div class="flex flex-wrap gap-2">
          <Button variant="outline" @click="loadPreview">生成差异预览</Button>
          <Button @click="createBatch">创建执行批次</Button>
        </div>
        <div v-if="preview" class="rounded border p-3 text-sm">
          <div class="mb-2 font-medium">差异预览</div>
          <div class="grid gap-1 sm:grid-cols-2"><div v-for="(value, key) in preview.summary" :key="key">{{ key }}：{{ value }}</div></div>
          <div v-if="preview.conflicts?.length" class="mt-2 text-destructive">发现 {{ preview.conflicts.length }} 个先修冲突，需先审核。</div>
        </div>
        <div class="overflow-x-auto rounded border">
          <table class="w-full text-sm">
            <thead class="bg-muted/50 text-left"><tr><th class="p-2">批次</th><th class="p-2">模式</th><th class="p-2">状态</th><th class="p-2">摘要</th><th class="p-2">操作</th></tr></thead>
            <tbody>
              <tr v-for="batch in batches" :key="batch.id" class="border-t align-top">
                <td class="p-2">#{{ batch.id }}</td>
                <td class="p-2">{{ batchModeLabel(batch.mode) }}</td>
                <td class="p-2"><Badge variant="secondary">{{ batch.status }}</Badge></td>
                <td class="p-2 text-xs"><pre class="whitespace-pre-wrap">{{ JSON.stringify(batch.summary || {}, null, 0) }}</pre></td>
                <td class="p-2"><div class="flex gap-1">
                  <Button v-if="batch.mode === 'apply' && batch.status === 'validated'" size="sm" @click="executeBatch(batch)">执行</Button>
                  <Button v-if="batch.status === 'applied'" size="sm" variant="outline" @click="rollbackBatch(batch)">回滚</Button>
                </div></td>
              </tr>
              <tr v-if="batches.length === 0"><td colspan="5" class="p-4 text-center text-muted-foreground">暂无批次</td></tr>
            </tbody>
          </table>
        </div>
      </TabsContent>
    </Tabs>
  </div>
</template>
