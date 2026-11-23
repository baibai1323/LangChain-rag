<script setup lang="ts">
import { computed } from 'vue'
import type { Citation } from '@/types'

const props = defineProps<{
  modelValue: boolean
  citations: Citation[]
  activeRank?: number
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
}>()

const list = computed(() => [...props.citations].sort((a, b) => a.rank - b.rank))

function scoreText(value: number): string {
  if (!value) return '-'
  return value > 1 ? value.toFixed(3) : value.toFixed(4)
}
</script>

<template>
  <el-drawer
    :model-value="modelValue"
    title="引用来源"
    size="480px"
    class="citation-drawer"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div v-if="!list.length" class="empty">本次回答没有检索到可引用的知识库片段</div>
    <div v-for="item in list" :key="item.chunk_id" style="margin-bottom: 16px">
      <div
        class="card"
        :style="
          activeRank === item.rank
            ? 'border-color:#93b4f8;box-shadow:0 0 0 3px rgba(37,99,235,.12)'
            : ''
        "
      >
        <div class="card-head" style="padding: 12px 14px">
          <div style="display: flex; align-items: center; gap: 8px; min-width: 0">
            <span class="cite-badge" style="cursor: default">{{ item.rank }}</span>
            <strong style="font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
              {{ item.doc_name }}
            </strong>
          </div>
          <el-tag v-if="item.page > 0" size="small" type="info" effect="plain">第 {{ item.page }} 页</el-tag>
        </div>
        <div class="card-body" style="padding: 12px 14px">
          <div class="quote">{{ item.quote }}</div>
          <div class="meta" style="margin-top: 10px; margin-bottom: 0">
            <span>相关度 {{ scoreText(item.score) }}</span>
            <span>片段 ID {{ item.chunk_id.slice(0, 8) }}</span>
          </div>
        </div>
      </div>
    </div>
  </el-drawer>
</template>
