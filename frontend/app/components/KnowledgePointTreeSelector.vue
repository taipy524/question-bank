<script setup lang="ts">
import { ref, computed } from 'vue'
import type { KnowledgePoint } from '~/types'
import { Folder, Search } from '@lucide/vue'
import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import ClearableInput from './ClearableInput.vue'
import KnowledgePointTreeItem from './KnowledgePointTreeItem.vue'
import { buildKnowledgePointTree, filterKnowledgePointTree } from '@/lib/knowledgePointTree'

const props = defineProps<{
  knowledgePoints: KnowledgePoint[]
  selectedIds: string[]
}>()

const emit = defineEmits<{
  (e: 'toggle', id: string): void
  (e: 'clear'): void
}>()

const searchQuery = ref('')
const showLegacy = ref(false)
const filterGrade = ref<number | null>(null)
const filterSemester = ref<string | null>(null)
const filterChapter = ref<string | null>(null)
const filterDomain = ref<string | null>(null)

const legacyCount = computed(
  () => (props.knowledgePoints ?? []).filter(kp => kp.is_formal === false).length,
)

const filteredKnowledgePoints = computed(() =>
  (props.knowledgePoints ?? []).filter((kp) => {
    if (!showLegacy.value && kp.is_formal === false) return false
    if (filterGrade.value != null && kp.grade !== filterGrade.value) return false
    if (filterSemester.value && kp.semester !== filterSemester.value) return false
    if (filterChapter.value && kp.chapter !== filterChapter.value) return false
    if (filterDomain.value && kp.domain !== filterDomain.value) return false
    return true
  }),
)

const tree = computed(() => buildKnowledgePointTree(filteredKnowledgePoints.value))
const filteredTree = computed(() => filterKnowledgePointTree(tree.value, searchQuery.value))
</script>

<template>
  <div class="space-y-2">
    <Button
      v-if="legacyCount > 0"
      variant="ghost"
      size="sm"
      class="h-7 self-start px-2 text-xs"
      @click="showLegacy = !showLegacy"
    >
      {{ showLegacy ? '隐藏旧知识点' : `显示旧知识点（${legacyCount}）` }}
    </Button>

    <KnowledgePointTaxonomyFilters
      :knowledge-points="knowledgePoints"
      :grade="filterGrade"
      :semester="filterSemester"
      :chapter="filterChapter"
      :domain="filterDomain"
      compact
      @update:grade="filterGrade = $event"
      @update:semester="filterSemester = $event"
      @update:chapter="filterChapter = $event"
      @update:domain="filterDomain = $event"
    />

    <div class="relative">
      <Search class="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" />
      <ClearableInput v-model="searchQuery" placeholder="搜索知识点..." class="pl-7" autofocus />
    </div>

    <div class="space-y-0.5">
      <div 
        :class="cn(
          'flex items-center py-1 px-2 rounded-md cursor-pointer hover:bg-accent/50 text-sm transition-colors',
          selectedIds.length === 0 ? 'bg-accent text-accent-foreground font-medium' : 'text-muted-foreground'
        )"
        @click="emit('clear')"
      >
        <Folder class="w-4 h-4 mr-2 text-primary" />
        <span>全部知识点</span>
      </div>
      
      <KnowledgePointTreeItem
        v-for="node in filteredTree" 
        :key="node.id" 
        :node="node" 
        :level="0"
        :selected-ids="selectedIds"
        :search="searchQuery"
        @toggle="(id) => emit('toggle', id)"
      />

      <div v-if="searchQuery && filteredTree.length === 0" class="py-4 text-center text-xs text-muted-foreground">
        未找到匹配的知识点
      </div>
    </div>
  </div>
</template>
