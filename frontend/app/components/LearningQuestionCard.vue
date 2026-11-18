<script setup lang="ts">
import { computed, ref } from 'vue'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ChevronDown, Star } from '@lucide/vue'
import RichContent from '@/components/rich-editor/RichContent.vue'
import AnswerDisplay from '@/components/AnswerDisplay.vue'
import { isEmptyRichDoc } from '@/components/rich-editor/richDoc'
import type { AnswerSpec, OptionSpec, RichDoc } from '@/types'
import { toast } from 'vue-sonner'

interface KnowledgePointBrief {
  id: number
  name: string
}

interface RecommendationItem {
  question_id: number
  q_type: string
  difficulty: number
  status: string
  reasons: string[]
  score: number
  knowledge_point_ids?: number[]
  knowledge_points?: KnowledgePointBrief[]
  content?: RichDoc
  options?: OptionSpec[] | null
  answer?: AnswerSpec | null
  thinking?: RichDoc
  analysis?: RichDoc
}

const props = withDefaults(
  defineProps<{
    item: RecommendationItem
    subjectId: number | null
    studentId: number | null
    errorReasons?: string[]
  }>(),
  { errorReasons: () => [] },
)

const emit = defineEmits<{ (e: 'marked', result: string): void }>()
const { $api } = useNuxtApp()

const TYPE_LABELS: Record<string, string> = {
  single_choice: '单选题',
  multiple_choice: '多选题',
  true_false: '判断题',
  fill_in_the_blank: '填空题',
  free_response: '解答题',
}
const STATUS_LABELS: Record<string, string> = {
  published: '已发布',
  pending: '待审核',
  draft: '草稿',
  archived: '已归档',
}

const RESULTS = [
  { value: 'correct', label: '正确' },
  { value: 'wrong', label: '错误' },
  { value: 'partial', label: '部分正确' },
] as const
type Result = (typeof RESULTS)[number]['value']
const RESULT_LABELS: Record<Result, string> = {
  correct: '正确',
  wrong: '错误',
  partial: '部分正确',
}

const expanded = ref(false)
const result = ref<Result | ''>('')
const reasons = ref<string[]>([])
const note = ref('')
const saving = ref(false)
const savedResult = ref<Result | null>(null)

const typeLabel = computed(() => TYPE_LABELS[props.item.q_type] || props.item.q_type)
const statusLabel = computed(() => STATUS_LABELS[props.item.status] || props.item.status)
const statusVariant = computed<'default' | 'secondary' | 'outline'>(() => {
  switch (props.item.status) {
    case 'published':
      return 'default'
    case 'pending':
      return 'secondary'
    case 'archived':
      return 'outline'
    default:
      return 'secondary'
  }
})
const statusClass = computed(() => {
  switch (props.item.status) {
    case 'published':
      return 'bg-green-600 hover:bg-green-700 dark:bg-green-700 dark:hover:bg-green-600'
    case 'pending':
      return 'bg-amber-100 text-amber-800 hover:bg-amber-200 dark:bg-amber-500/15 dark:text-amber-400'
    default:
      return ''
  }
})
const accentClass = computed(() => {
  switch (props.item.status) {
    case 'published':
      return 'border-l-green-600'
    case 'pending':
      return 'border-l-amber-400 dark:border-l-amber-500'
    case 'archived':
      return 'border-l-muted-foreground/25'
    default:
      return 'border-l-muted-foreground/40'
  }
})
const choiceOptions = computed<OptionSpec[]>(() => {
  if (props.item.q_type !== 'single_choice' && props.item.q_type !== 'multiple_choice') return []
  return props.item.options || []
})
const showReasons = computed(() => result.value === 'wrong' || result.value === 'partial')
const canSave = computed(
  () => !!result.value && props.subjectId != null && props.studentId != null && !saving.value,
)

function chooseResult(value: Result) {
  result.value = value
  if (value === 'correct') reasons.value = []
  if (savedResult.value !== value) savedResult.value = null
}

async function saveMark() {
  if (!canSave.value) return
  saving.value = true
  try {
    await $api('/learning-analysis/attempts', {
      method: 'POST',
      body: {
        subject_id: props.subjectId,
        student_id: props.studentId,
        question_id: props.item.question_id,
        result: result.value,
        error_reasons: showReasons.value ? reasons.value : [],
        note: note.value.trim() || null,
      },
    })
    savedResult.value = result.value
    toast.success(`已标记为${RESULT_LABELS[result.value]}`)
    emit('marked', result.value)
  } catch (error: any) {
    toast.error(error?.data?.detail || error?.message || '保存标记失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Card class="py-0 border-l-4" :class="accentClass">
    <div class="p-4">
      <div class="flex flex-col gap-3">
        <div class="flex flex-wrap items-center gap-2">
          <Badge variant="outline" class="font-mono text-xs">#{{ item.question_id }}</Badge>
          <Badge :variant="statusVariant" :class="['text-xs', statusClass]">{{ statusLabel }}</Badge>
          <Badge variant="outline">{{ typeLabel }}</Badge>
          <div class="flex items-center gap-1 text-xs text-muted-foreground" :title="`难度 ${item.difficulty}`">
            <span>难度</span>
            <Star
              v-for="i in 5"
              :key="i"
              class="h-3 w-3"
              :class="i <= item.difficulty ? 'fill-primary text-primary' : 'fill-none text-muted-foreground/30'"
            />
          </div>
          <Badge v-for="reason in item.reasons || []" :key="reason" variant="secondary" class="text-xs">
            {{ reason }}
          </Badge>
        </div>

        <div>
          <RichContent :content="item.content ?? null" empty-text="（空）" />
          <div v-if="choiceOptions.length" class="mt-2 flex flex-wrap gap-x-6 gap-y-1.5">
            <div
              v-for="opt in choiceOptions"
              :key="opt.id"
              class="flex max-w-full items-baseline gap-2 text-xs"
            >
              <span class="shrink-0 font-bold text-muted-foreground">{{ opt.label }}.</span>
              <div class="min-w-0 text-foreground/80 [&_.prose]:my-0 [&_.prose_p]:my-0 [&_.prose]:text-xs [&_.prose]:leading-normal">
                <RichContent :content="opt.content" />
              </div>
            </div>
          </div>
        </div>

        <div v-if="(item.knowledge_points || []).length" class="flex flex-wrap gap-2">
          <Badge v-for="kp in item.knowledge_points" :key="kp.id" variant="secondary" class="text-xs">
            {{ kp.name }}
          </Badge>
        </div>

        <div class="flex justify-center">
          <Button
            variant="ghost"
            size="sm"
            class="h-6 w-full gap-1 text-muted-foreground hover:bg-muted/50"
            @click="expanded = !expanded"
          >
            <span class="text-xs">{{ expanded ? '收起详情' : '展开详情' }}</span>
            <ChevronDown
              class="h-4 w-4 transition-transform duration-200"
              :class="{ 'rotate-180': expanded }"
            />
          </Button>
        </div>

        <div v-if="expanded" class="space-y-3 border-t border-border/50 pt-3">
          <div class="space-y-1">
            <div class="text-sm font-semibold text-foreground">答案</div>
            <div class="rounded bg-muted/30 p-2 text-sm">
              <AnswerDisplay
                :answer="item.answer ?? null"
                :options="item.options || []"
                empty-text="未填写"
              />
            </div>
          </div>
          <div v-if="!isEmptyRichDoc(item.thinking ?? null)" class="space-y-1">
            <div class="text-sm font-semibold text-foreground">分析</div>
            <div class="rounded bg-muted/20 p-3 text-sm [&_.prose]:my-0 [&_.prose_p]:my-0">
              <RichContent :content="item.thinking ?? null" />
            </div>
          </div>
          <div v-if="!isEmptyRichDoc(item.analysis ?? null)" class="space-y-1">
            <div class="text-sm font-semibold text-foreground">解析</div>
            <div class="rounded bg-muted/20 p-3 text-sm [&_.prose]:my-0 [&_.prose_p]:my-0">
              <RichContent :content="item.analysis ?? null" />
            </div>
          </div>
        </div>

        <div class="space-y-2 border-t border-border/50 pt-3">
          <div class="text-sm font-medium">标记本题结果</div>
          <div class="flex flex-wrap gap-2">
            <Button
              v-for="option in RESULTS"
              :key="option.value"
              size="sm"
              :variant="result === option.value ? 'default' : 'outline'"
              :disabled="saving"
              @click="chooseResult(option.value)"
            >
              {{ option.label }}
            </Button>
          </div>

          <div v-if="showReasons" class="space-y-1">
            <div class="text-xs text-muted-foreground">错误原因（选填）</div>
            <div class="grid grid-cols-2 gap-1 text-sm sm:grid-cols-3">
              <label v-for="reason in errorReasons" :key="reason" class="flex items-center gap-2">
                <input v-model="reasons" type="checkbox" :value="reason" />
                {{ reason }}
              </label>
            </div>
          </div>

          <textarea
            v-if="result"
            v-model="note"
            class="w-full rounded border px-3 py-2 text-sm"
            rows="2"
            placeholder="备注（选填）"
          />

          <div class="flex flex-wrap items-center gap-3">
            <Button size="sm" :disabled="!canSave" @click="saveMark">
              {{ saving ? '保存中...' : '保存标记' }}
            </Button>
            <Badge v-if="savedResult" variant="secondary">本次：{{ RESULT_LABELS[savedResult] }}</Badge>
          </div>
        </div>
      </div>
    </div>
  </Card>
</template>
