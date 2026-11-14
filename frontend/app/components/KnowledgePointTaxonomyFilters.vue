<script setup lang="ts">
import type { KnowledgePoint } from '~/types'
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select'

const props = defineProps<{
  knowledgePoints: KnowledgePoint[]
  grade?: number | null
  semester?: string | null
  chapter?: string | null
  domain?: string | null
  compact?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:grade', value: number | null): void
  (e: 'update:semester', value: string | null): void
  (e: 'update:chapter', value: string | null): void
  (e: 'update:domain', value: string | null): void
}>()

const grades = computed(() =>
  [...new Set(
    props.knowledgePoints
      .map(kp => kp.grade)
      .filter((g): g is number => typeof g === 'number'),
  )].sort((a, b) => a - b),
)

const semesters = computed(() =>
  [...new Set(
    props.knowledgePoints
      .filter(kp => props.grade == null || kp.grade === props.grade)
      .map(kp => kp.semester)
      .filter((s): s is string => !!s),
  )].sort(),
)

const domains = computed(() =>
  [...new Set(
    props.knowledgePoints
      .map(kp => kp.domain)
      .filter((d): d is string => !!d),
  )].sort(),
)

const chapters = computed(() =>
  [...new Set(
    props.knowledgePoints
      .filter(kp => props.grade == null || kp.grade === props.grade)
      .filter(kp => !props.semester || kp.semester === props.semester)
      .filter(kp => !props.domain || kp.domain === props.domain)
      .map(kp => kp.chapter)
      .filter((c): c is string => !!c),
  )].sort(),
)

const width = computed(() => (props.compact ? 'w-24' : 'w-28'))

function onGrade(value: unknown) {
  emit('update:grade', value === '' || value == null ? null : Number(value))
  emit('update:semester', null)
  emit('update:chapter', null)
}

function onSemester(value: unknown) {
  emit('update:semester', value === '' || value == null ? null : String(value))
  emit('update:chapter', null)
}

function onChapter(value: unknown) {
  emit('update:chapter', value === '' || value == null ? null : String(value))
}

function onDomain(value: unknown) {
  emit('update:domain', value === '' || value == null ? null : String(value))
  emit('update:chapter', null)
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-2">
    <NativeSelect :model-value="grade ?? ''" :class="['h-8', width]" @update:model-value="onGrade">
      <NativeSelectOption value="">全部年级</NativeSelectOption>
      <NativeSelectOption v-for="g in grades" :key="g" :value="g">{{ g }} 年级</NativeSelectOption>
    </NativeSelect>

    <NativeSelect :model-value="semester ?? ''" :class="['h-8', width]" @update:model-value="onSemester">
      <NativeSelectOption value="">全部学期</NativeSelectOption>
      <NativeSelectOption v-for="s in semesters" :key="s" :value="s">{{ s }}学期</NativeSelectOption>
    </NativeSelect>

    <NativeSelect :model-value="domain ?? ''" :class="['h-8', compact ? 'w-28' : 'w-32']" @update:model-value="onDomain">
      <NativeSelectOption value="">全部领域</NativeSelectOption>
      <NativeSelectOption v-for="d in domains" :key="d" :value="d">{{ d }}</NativeSelectOption>
    </NativeSelect>

    <NativeSelect :model-value="chapter ?? ''" :class="['h-8', compact ? 'w-40' : 'w-52']" @update:model-value="onChapter">
      <NativeSelectOption value="">全部章节</NativeSelectOption>
      <NativeSelectOption v-for="c in chapters" :key="c" :value="c">{{ c }}</NativeSelectOption>
    </NativeSelect>
  </div>
</template>
