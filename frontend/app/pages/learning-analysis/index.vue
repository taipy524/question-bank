<script setup lang="ts">
import PageHeader from '~/components/PageHeader.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '@/components/ui/table'
import { toast } from 'vue-sonner'

const { $api } = useNuxtApp()

interface Subject { id: number; name: string }
interface Student { id: number; subject_id: number; name: string; grade: number; created_at?: string }
interface Attempt {
  id: number; student_id: number; question_id: number; result: string
  error_reasons: string[]; note?: string; answered_at: string; source: string
}
interface WrongQuestion {
  student_id: number; question_id: number; wrong_count: number; partial_count: number
  total_error_count: number; last_wrong_at?: string; error_reasons: string[]; note?: string
  question: { id: number; q_type: string; difficulty: number; status: string; content: string }
}
interface MasteryRow {
  knowledge_point_id: number; name: string; attempts: number; correct: number
  wrong: number; partial: number; score: number; status: string
}
interface TypeMasteryRow {
  q_type: string; attempts: number; correct: number; wrong: number; partial: number
  score: number; status: string
}
interface Recommendation {
  question_id: number; q_type: string; difficulty: number; status: string
  reasons: string[]; score: number; knowledge_point_ids: number[]
}
interface Report {
  student: Student
  summary: { attempts: number; correct: number; wrong: number; partial: number; wrong_question_count: number; total_error_count: number; last_wrong_at?: string; partial_weight: number }
  wrong_questions: WrongQuestion[]
  mastery: { knowledge_points: MasteryRow[] }
  type_mastery: TypeMasteryRow[]
  reviews: Array<{ question_id: number; due_at: string; interval_days: number; last_result?: string }>
  sessions: Array<{ id: number; mode: string; stage?: number; status: string; created_at: string }>
  recommendations: Recommendation[]
  stage_names: Record<string, string>
}
interface ImportRow {
  row: number; student_id?: number | null; student_name: string; grade?: number | null
  question_id?: number | null; error_reasons: string[]; note?: string | null
  answered_at?: string | null; status: string; errors: string[]
}

const subjects = ref<Subject[]>([])
const subjectId = ref<number | null>(null)
const students = ref<Student[]>([])
const selectedStudentId = ref<number | null>(null)
const attempts = ref<Attempt[]>([])
const wrongQuestions = ref<WrongQuestion[]>([])
const report = ref<Report | null>(null)
const recommendations = ref<Recommendation[]>([])
const recommendationReason = ref('')
const reviewRows = ref<Report['reviews']>([])
const config = ref<Record<string, any> | null>(null)

const newStudent = reactive({ name: '', grade: 9 })
const recordForm = reactive({
  question_id: '',
  result: 'wrong',
  reasons: [] as string[],
  note: '',
})
const recoForm = reactive({ mode: 'recommendation', stage: 1, limit: 10, includeUnpublished: false })
const importFile = ref<File | null>(null)
const importPreview = ref<{ batch_id: number; rows: ImportRow[]; summary: Record<string, any> } | null>(null)
const nlText = ref('')
const nlPreview = ref<{ batch_id: number; rows: ImportRow[]; summary: Record<string, any> } | null>(null)
const loading = ref(false)

const ERROR_REASONS = ['概念不清', '公式记忆错误', '方法不会', '计算错误', '审题错误', '思路错误', '知识点混淆', '表达不规范', '粗心失误', '综合应用困难', '其他']
const RESULT_LABELS: Record<string, string> = { correct: '正确', wrong: '错误', partial: '部分正确' }
const MASTERY_LABELS: Record<string, string> = { unassessed: '未评估', weak: '薄弱', learning: '学习中', basic: '基本掌握', mastered: '熟练掌握' }
const STAGE_NAMES: Record<string, string> = { '1': '基础补弱', '2': '核心巩固', '3': '变式训练', '4': '综合检测' }
const selectedStudent = computed(() => students.value.find(s => s.id === selectedStudentId.value) || null)

async function loadSubjects() {
  subjects.value = await $api<Subject[]>('/subjects')
  if (subjectId.value == null && subjects.value.length) subjectId.value = subjects.value[0]!.id
}
async function loadStudents() {
  if (subjectId.value == null) return
  students.value = await $api<Student[]>('/learning-analysis/students', { query: { subject_id: subjectId.value, limit: 500 } })
  if (selectedStudentId.value == null || !students.value.some(s => s.id === selectedStudentId.value)) {
    selectedStudentId.value = students.value[0]?.id ?? null
  }
}
async function loadStudentData() {
  if (subjectId.value == null || selectedStudentId.value == null) {
    attempts.value = []
    wrongQuestions.value = []
    report.value = null
    reviewRows.value = []
    return
  }
  const query = { subject_id: subjectId.value, student_id: selectedStudentId.value }
  attempts.value = await $api<Attempt[]>('/learning-analysis/attempts', { query: { ...query, limit: 200 } })
  wrongQuestions.value = await $api<WrongQuestion[]>('/learning-analysis/wrong-questions', { query: { ...query, limit: 200 } })
  report.value = await $api<Report>(`/learning-analysis/students/${selectedStudentId.value}/report`, { query: { subject_id: subjectId.value } })
  reviewRows.value = report.value.reviews
}
async function refreshAll() {
  loading.value = true
  try {
    await loadStudents()
    await loadStudentData()
  } finally { loading.value = false }
}

async function addStudent() {
  if (subjectId.value == null || !newStudent.name.trim()) return
  try {
    await $api('/learning-analysis/students', {
      method: 'POST',
      body: { subject_id: subjectId.value, name: newStudent.name.trim(), grade: newStudent.grade },
    })
    newStudent.name = ''
    toast.success('学生已创建')
    await refreshAll()
  } catch (error: any) { toast.error(error?.data?.detail || error.message) }
}
async function deleteStudent(student: Student) {
  if (!confirm(`删除学生「${student.name}」及其全部学习数据？此操作不可恢复。`)) return
  try {
    await $api(`/learning-analysis/students/${student.id}`, { method: 'DELETE', query: { subject_id: subjectId.value! } })
    toast.success('学生及其学习数据已删除')
    await refreshAll()
  } catch (error: any) { toast.error(error?.data?.detail || error.message) }
}
async function createRecord() {
  if (subjectId.value == null || selectedStudentId.value == null || !recordForm.question_id) return
  try {
    await $api('/learning-analysis/attempts', {
      method: 'POST',
      body: {
        subject_id: subjectId.value,
        student_id: selectedStudentId.value,
        question_id: Number(recordForm.question_id),
        result: recordForm.result,
        error_reasons: recordForm.reasons,
        note: recordForm.note || null,
      },
    })
    recordForm.note = ''
    toast.success('答题记录已保存')
    await loadStudentData()
  } catch (error: any) { toast.error(error?.data?.detail || error.message) }
}
async function generateRecommendations() {
  if (subjectId.value == null || selectedStudentId.value == null) return
  try {
    const result = await $api<{ items: Recommendation[]; reason?: string }>('/learning-analysis/recommendations', {
      query: {
        subject_id: subjectId.value,
        student_id: selectedStudentId.value,
        mode: recoForm.mode,
        stage: recoForm.mode === 'four_stage' ? recoForm.stage : undefined,
        limit: recoForm.limit,
        include_unpublished: recoForm.includeUnpublished,
      },
    })
    recommendations.value = result.items
    recommendationReason.value = result.reason || ''
  } catch (error: any) { toast.error(error?.data?.detail || error.message) }
}
async function createSessionFromRecommendations() {
  if (subjectId.value == null || selectedStudentId.value == null || !recommendations.value.length) return
  try {
    await $api('/learning-analysis/sessions', {
      method: 'POST',
      body: {
        subject_id: subjectId.value,
        student_id: selectedStudentId.value,
        question_ids: recommendations.value.map(item => item.question_id),
        mode: recoForm.mode,
        stage: recoForm.mode === 'four_stage' ? recoForm.stage : null,
        title: `${STAGE_NAMES[String(recoForm.stage)] || '推荐练习'} - ${selectedStudent.value?.name || ''}`,
        reasons: Object.fromEntries(recommendations.value.map(item => [String(item.question_id), item.reasons])),
      },
    })
    toast.success('练习会话已创建')
    await loadStudentData()
  } catch (error: any) { toast.error(error?.data?.detail || error.message) }
}
async function loadConfig() {
  try { config.value = await $api('/learning-analysis/config') } catch { config.value = null }
}
async function saveConfig() {
  if (!config.value) return
  try {
    await $api('/learning-analysis/config', { method: 'PUT', body: { partial_weight: config.value.partial_weight } })
    toast.success('配置已保存')
  } catch (error: any) { toast.error(error?.data?.detail || error.message) }
}
async function downloadTemplate() {
  try {
    const blob = await $api<Blob>('/learning-analysis/imports/template', { responseType: 'blob' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'learning_wrong_import.xlsx'
    link.click()
    URL.revokeObjectURL(url)
  } catch (error: any) { toast.error(error?.data?.detail || error.message) }
}
async function downloadErrors(preview: { batch_id: number }) {
  try {
    const blob = await $api<Blob>(`/learning-analysis/imports/${preview.batch_id}/errors.csv`, {
      query: { subject_id: subjectId.value! },
      responseType: 'blob',
    })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `import_errors_${preview.batch_id}.csv`
    link.click()
    URL.revokeObjectURL(url)
  } catch (error: any) { toast.error(error?.data?.detail || error.message) }
}
function chooseFile(event: Event) {
  const input = event.target as HTMLInputElement
  importFile.value = input.files?.[0] || null
}
async function previewExcel() {
  if (subjectId.value == null || !importFile.value) return
  const form = new FormData()
  form.append('subject_id', String(subjectId.value))
  form.append('file', importFile.value)
  try {
    importPreview.value = await $api('/learning-analysis/imports/excel', { method: 'POST', body: form })
  } catch (error: any) { toast.error(error?.data?.detail || error.message) }
}
async function previewNL() {
  if (subjectId.value == null || !nlText.value.trim()) return
  try {
    nlPreview.value = await $api('/learning-analysis/imports/nl', {
      method: 'POST',
      body: { subject_id: subjectId.value, text: nlText.value },
    })
  } catch (error: any) { toast.error(error?.data?.detail || error.message) }
}
async function commitPreview(preview: { batch_id: number } | null) {
  if (subjectId.value == null || !preview) return
  try {
    const result = await $api<{ created: number }>(`/learning-analysis/imports/${preview.batch_id}/commit`, {
      method: 'POST', query: { subject_id: subjectId.value },
    })
    toast.success(`已导入 ${result.created} 条错题记录`)
    importPreview.value = null
    nlPreview.value = null
    await loadStudentData()
  } catch (error: any) { toast.error(error?.data?.detail || error.message) }
}
function reasonsText(reasons: string[]) { return reasons?.length ? reasons.join('、') : '—' }

watch(subjectId, async () => { await refreshAll() })
watch(selectedStudentId, loadStudentData)
onMounted(async () => {
  await loadSubjects()
  await refreshAll()
  await loadConfig()
})
</script>

<template>
  <div class="space-y-6">
    <PageHeader title="学习分析" description="学生档案、错题、练习记录、推荐与掌握度（仅管理员/学科负责人）" />

    <div class="flex flex-wrap items-end gap-3">
      <label class="text-sm">学科
        <select v-model.number="subjectId" class="ml-2 rounded border px-3 py-2">
          <option :value="null" disabled>请选择学科</option>
          <option v-for="subject in subjects" :key="subject.id" :value="subject.id">{{ subject.name }}</option>
        </select>
      </label>
      <Button variant="outline" :disabled="loading" @click="refreshAll">刷新</Button>
    </div>

    <Tabs default-value="students" class="space-y-4">
      <TabsList class="flex flex-wrap">
        <TabsTrigger value="students">学生档案</TabsTrigger>
        <TabsTrigger value="records">错题与记录</TabsTrigger>
        <TabsTrigger value="recommend">推荐 / 四阶段</TabsTrigger>
        <TabsTrigger value="mastery">掌握度与报告</TabsTrigger>
        <TabsTrigger value="imports">批量导入</TabsTrigger>
        <TabsTrigger value="config">规则配置</TabsTrigger>
      </TabsList>

      <TabsContent value="students" class="space-y-4">
        <div class="flex flex-wrap items-end gap-3 rounded border p-3">
          <Label>姓名 <Input v-model="newStudent.name" class="mt-1 w-40" placeholder="学生姓名" /></Label>
          <Label>年级 <Input v-model.number="newStudent.grade" type="number" min="1" max="12" class="mt-1 w-24" /></Label>
          <Button @click="addStudent">新增学生</Button>
        </div>
        <Table>
          <TableHeader><TableRow><TableHead>姓名</TableHead><TableHead>年级</TableHead><TableHead>创建时间</TableHead><TableHead>操作</TableHead></TableRow></TableHeader>
          <TableBody>
            <TableRow v-for="student in students" :key="student.id">
              <TableCell>{{ student.name }}</TableCell>
              <TableCell>{{ student.grade }}</TableCell>
              <TableCell>{{ student.created_at }}</TableCell>
              <TableCell><Button size="sm" variant="outline" @click="deleteStudent(student)">删除</Button></TableCell>
            </TableRow>
            <TableRow v-if="!students.length"><TableCell colspan="4" class="text-center text-muted-foreground">暂无学生</TableCell></TableRow>
          </TableBody>
        </Table>
      </TabsContent>

      <TabsContent value="records" class="space-y-4">
        <div class="flex flex-wrap items-end gap-3">
          <label class="text-sm">学生
            <select v-model.number="selectedStudentId" class="ml-2 rounded border px-3 py-2">
              <option :value="null" disabled>请选择学生</option>
              <option v-for="student in students" :key="student.id" :value="student.id">{{ student.name }}（{{ student.grade }}年级）</option>
            </select>
          </label>
        </div>
        <div class="grid gap-4 lg:grid-cols-2">
          <div class="space-y-3 rounded border p-3">
            <h3 class="font-medium">登记答题记录</h3>
            <Label>题目 ID <Input v-model="recordForm.question_id" placeholder="例如 1" /></Label>
            <Label>结果
              <select v-model="recordForm.result" class="mt-1 w-full rounded border px-3 py-2">
                <option value="correct">正确</option><option value="wrong">错误</option><option value="partial">部分正确</option>
              </select>
            </Label>
            <div>
              <div class="mb-1 text-sm">错误原因（可多选）</div>
              <div class="grid grid-cols-2 gap-1 text-sm">
                <label v-for="reason in ERROR_REASONS" :key="reason" class="flex items-center gap-2">
                  <input v-model="recordForm.reasons" type="checkbox" :value="reason" /> {{ reason }}
                </label>
              </div>
            </div>
            <Label>备注 <textarea v-model="recordForm.note" class="mt-1 w-full rounded border px-3 py-2" rows="2" /></Label>
            <Button @click="createRecord">保存记录</Button>
          </div>
          <div class="space-y-3 rounded border p-3">
            <h3 class="font-medium">错题汇总</h3>
            <Table>
              <TableHeader><TableRow><TableHead>题目</TableHead><TableHead>错误</TableHead><TableHead>部分</TableHead><TableHead>原因</TableHead><TableHead>最近</TableHead></TableRow></TableHeader>
              <TableBody>
                <TableRow v-for="row in wrongQuestions" :key="row.question_id">
                  <TableCell>#{{ row.question_id }}（{{ row.question.q_type }} / 难度 {{ row.question.difficulty }}）</TableCell>
                  <TableCell>{{ row.wrong_count }}</TableCell>
                  <TableCell>{{ row.partial_count }}</TableCell>
                  <TableCell>{{ reasonsText(row.error_reasons) }}</TableCell>
                  <TableCell>{{ row.last_wrong_at }}</TableCell>
                </TableRow>
                <TableRow v-if="!wrongQuestions.length"><TableCell colspan="5" class="text-center text-muted-foreground">暂无错题</TableCell></TableRow>
              </TableBody>
            </Table>
          </div>
        </div>
        <div class="rounded border p-3">
          <h3 class="mb-2 font-medium">答题历史</h3>
          <Table>
            <TableHeader><TableRow><TableHead>时间</TableHead><TableHead>题目</TableHead><TableHead>结果</TableHead><TableHead>原因</TableHead><TableHead>备注</TableHead></TableRow></TableHeader>
            <TableBody>
              <TableRow v-for="attempt in attempts" :key="attempt.id">
                <TableCell>{{ attempt.answered_at }}</TableCell>
                <TableCell>#{{ attempt.question_id }}</TableCell>
                <TableCell>{{ RESULT_LABELS[attempt.result] || attempt.result }}</TableCell>
                <TableCell>{{ reasonsText(attempt.error_reasons) }}</TableCell>
                <TableCell>{{ attempt.note || '—' }}</TableCell>
              </TableRow>
              <TableRow v-if="!attempts.length"><TableCell colspan="5" class="text-center text-muted-foreground">暂无记录</TableCell></TableRow>
            </TableBody>
          </Table>
        </div>
      </TabsContent>

      <TabsContent value="recommend" class="space-y-4">
        <div class="flex flex-wrap items-end gap-3">
          <label class="text-sm">学生
            <select v-model.number="selectedStudentId" class="ml-2 rounded border px-3 py-2">
              <option :value="null" disabled>请选择学生</option>
              <option v-for="student in students" :key="student.id" :value="student.id">{{ student.name }}</option>
            </select>
          </label>
          <label class="text-sm">模式
            <select v-model="recoForm.mode" class="ml-2 rounded border px-3 py-2">
              <option value="recommendation">错题/薄弱推荐</option>
              <option value="four_stage">四阶段递进</option>
            </select>
          </label>
          <label v-if="recoForm.mode === 'four_stage'" class="text-sm">阶段
            <select v-model.number="recoForm.stage" class="ml-2 rounded border px-3 py-2">
              <option v-for="(name, key) in STAGE_NAMES" :key="key" :value="Number(key)">{{ name }}</option>
            </select>
          </label>
          <label class="text-sm">题量 <Input v-model.number="recoForm.limit" type="number" min="1" max="100" class="ml-2 w-24" /></label>
          <label class="flex items-center gap-2 text-sm"><input v-model="recoForm.includeUnpublished" type="checkbox" /> 包含未发布题</label>
          <Button @click="generateRecommendations">生成推荐</Button>
          <Button variant="outline" :disabled="!recommendations.length" @click="createSessionFromRecommendations">创建练习会话</Button>
        </div>
        <div v-if="recommendationReason" class="rounded border border-amber-300 bg-amber-50 p-3 text-sm">
          暂无推荐：{{ recommendationReason }}（当前默认仅使用已发布题）
        </div>
        <Table>
          <TableHeader><TableRow><TableHead>题目</TableHead><TableHead>类型</TableHead><TableHead>难度</TableHead><TableHead>状态</TableHead><TableHead>推荐理由</TableHead></TableRow></TableHeader>
          <TableBody>
            <TableRow v-for="item in recommendations" :key="item.question_id">
              <TableCell>#{{ item.question_id }}</TableCell>
              <TableCell>{{ item.q_type }}</TableCell>
              <TableCell>{{ item.difficulty }}</TableCell>
              <TableCell>{{ item.status }}</TableCell>
              <TableCell>{{ item.reasons.join('、') }}</TableCell>
            </TableRow>
            <TableRow v-if="!recommendations.length"><TableCell colspan="5" class="text-center text-muted-foreground">暂无推荐结果</TableCell></TableRow>
          </TableBody>
        </Table>
      </TabsContent>

      <TabsContent value="mastery" class="space-y-4">
        <div class="flex flex-wrap items-end gap-3">
          <label class="text-sm">学生
            <select v-model.number="selectedStudentId" class="ml-2 rounded border px-3 py-2">
              <option :value="null" disabled>请选择学生</option>
              <option v-for="student in students" :key="student.id" :value="student.id">{{ student.name }}</option>
            </select>
          </label>
        </div>
        <div v-if="report" class="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <div class="rounded border p-3 text-sm">练习次数<br><b>{{ report.summary.attempts }}</b></div>
          <div class="rounded border p-3 text-sm">正确<br><b>{{ report.summary.correct }}</b></div>
          <div class="rounded border p-3 text-sm">错误<br><b>{{ report.summary.wrong }}</b></div>
          <div class="rounded border p-3 text-sm">部分正确<br><b>{{ report.summary.partial }}</b></div>
          <div class="rounded border p-3 text-sm">错题数<br><b>{{ report.summary.wrong_question_count }}</b></div>
          <div class="rounded border p-3 text-sm">错误总次数<br><b>{{ report.summary.total_error_count }}</b></div>
        </div>
        <div class="grid gap-4 lg:grid-cols-2">
          <div class="rounded border p-3">
            <h3 class="mb-2 font-medium">知识点掌握</h3>
            <Table>
              <TableHeader><TableRow><TableHead>知识点</TableHead><TableHead>次数</TableHead><TableHead>得分</TableHead><TableHead>状态</TableHead></TableRow></TableHeader>
              <TableBody>
                <TableRow v-for="row in report?.mastery.knowledge_points || []" :key="row.knowledge_point_id">
                  <TableCell>{{ row.name }}</TableCell><TableCell>{{ row.attempts }}</TableCell>
                  <TableCell>{{ row.score }}</TableCell><TableCell><Badge variant="secondary">{{ MASTERY_LABELS[row.status] || row.status }}</Badge></TableCell>
                </TableRow>
                <TableRow v-if="!report?.mastery.knowledge_points?.length"><TableCell colspan="4" class="text-center text-muted-foreground">暂无数据（未评估）</TableCell></TableRow>
              </TableBody>
            </Table>
          </div>
          <div class="rounded border p-3">
            <h3 class="mb-2 font-medium">题型熟练度</h3>
            <Table>
              <TableHeader><TableRow><TableHead>题型</TableHead><TableHead>次数</TableHead><TableHead>得分</TableHead><TableHead>状态</TableHead></TableRow></TableHeader>
              <TableBody>
                <TableRow v-for="row in report?.type_mastery || []" :key="row.q_type">
                  <TableCell>{{ row.q_type }}</TableCell><TableCell>{{ row.attempts }}</TableCell>
                  <TableCell>{{ row.score }}</TableCell><TableCell>{{ MASTERY_LABELS[row.status] || row.status }}</TableCell>
                </TableRow>
                <TableRow v-if="!report?.type_mastery?.length"><TableCell colspan="4" class="text-center text-muted-foreground">暂无数据</TableCell></TableRow>
              </TableBody>
            </Table>
          </div>
        </div>
        <div class="rounded border p-3">
          <h3 class="mb-2 font-medium">间隔复习</h3>
          <Table>
            <TableHeader><TableRow><TableHead>题目</TableHead><TableHead>到期</TableHead><TableHead>间隔(天)</TableHead><TableHead>最近结果</TableHead></TableRow></TableHeader>
            <TableBody>
              <TableRow v-for="row in reviewRows" :key="row.question_id">
                <TableCell>#{{ row.question_id }}</TableCell><TableCell>{{ row.due_at }}</TableCell>
                <TableCell>{{ row.interval_days }}</TableCell><TableCell>{{ RESULT_LABELS[row.last_result || ''] || row.last_result || '—' }}</TableCell>
              </TableRow>
              <TableRow v-if="!reviewRows.length"><TableCell colspan="4" class="text-center text-muted-foreground">暂无复习计划</TableCell></TableRow>
            </TableBody>
          </Table>
        </div>
      </TabsContent>

      <TabsContent value="imports" class="space-y-4">
        <div class="flex flex-wrap gap-2">
          <Button variant="outline" @click="downloadTemplate">下载 Excel 模板</Button>
          <input type="file" accept=".xlsx,.csv" @change="chooseFile" />
          <Button :disabled="!importFile" @click="previewExcel">预览 Excel/CSV</Button>
        </div>
        <div v-if="importPreview" class="space-y-2 rounded border p-3">
          <div class="text-sm">批次 #{{ importPreview.batch_id }}：{{ importPreview.summary }}</div>
          <Table>
            <TableHeader><TableRow><TableHead>行</TableHead><TableHead>学生</TableHead><TableHead>题目</TableHead><TableHead>状态</TableHead><TableHead>错误</TableHead></TableRow></TableHeader>
            <TableBody>
              <TableRow v-for="row in importPreview.rows" :key="row.row">
                <TableCell>{{ row.row }}</TableCell><TableCell>{{ row.student_name }}</TableCell>
                <TableCell>{{ row.question_id }}</TableCell>
                <TableCell>{{ row.status }}</TableCell><TableCell>{{ row.errors.join('；') }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
          <div class="flex gap-2">
            <Button @click="commitPreview(importPreview)">确认导入</Button>
            <Button
              v-if="importPreview.rows.some(row => row.status !== 'ready')"
              variant="outline"
              @click="downloadErrors(importPreview)"
            >下载失败清单</Button>
          </div>
        </div>
        <div class="space-y-2 rounded border p-3">
          <h3 class="font-medium">自然语言导入</h3>
          <textarea v-model="nlText" rows="5" class="w-full rounded border px-3 py-2" placeholder="例如：张三（9年级）第 1 题错了，原因是计算错误；李四第 2 题部分正确，思路错误……" />
          <div class="flex gap-2">
            <Button variant="outline" @click="previewNL">AI 解析预览</Button>
            <Button v-if="nlPreview" @click="commitPreview(nlPreview)">确认导入</Button>
          </div>
          <div v-if="nlPreview" class="text-sm">批次 #{{ nlPreview.batch_id }}：{{ nlPreview.summary }}</div>
        </div>
      </TabsContent>

      <TabsContent value="config" class="space-y-3">
        <div v-if="config" class="max-w-md space-y-3 rounded border p-3">
          <Label>部分正确权重（0-1）
            <Input v-model.number="config.partial_weight" type="number" step="0.1" min="0" max="1" class="mt-1" />
          </Label>
          <Button @click="saveConfig">保存配置</Button>
        </div>
        <div v-else class="text-sm text-muted-foreground">仅超级管理员可查看/修改全局规则配置。</div>
      </TabsContent>
    </Tabs>
  </div>
</template>
