<script setup lang="ts">
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { CopyDocument, Star, StarFilled } from '@element-plus/icons-vue'
import type { ChatMessage, Citation } from '@/types'

const props = defineProps<{
  message: ChatMessage
  streaming?: boolean
  feedback?: number
}>()

const emit = defineEmits<{
  (e: 'open-citation', citation: Citation): void
  (e: 'feedback', rating: number): void
}>()

const isUser = computed(() => props.message.role === 'user')

const citations = computed(() => [...(props.message.citations || [])].sort((a, b) => a.rank - b.rank))

const validRanks = computed(() => new Set(citations.value.map((item) => item.rank)))

const html = computed(() => {
  const escaped = props.message.content
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
  return escaped.replace(/\[(\d{1,2})\]/g, (match, index: string) =>
    validRanks.value.has(Number(index))
      ? `<span class="cite-badge" data-index="${index}">${index}</span>`
      : match
  )
})

const time = computed(() => {
  const date = new Date(props.message.created_at)
  if (Number.isNaN(date.getTime())) return ''
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
})

function onClick(event: MouseEvent): void {
  const target = (event.target as HTMLElement).closest('.cite-badge') as HTMLElement | null
  if (!target) return
  const index = Number(target.dataset.index)
  const citation = citations.value.find((item) => item.rank === index)
  if (citation) emit('open-citation', citation)
}

async function copy(): Promise<void> {
  try {
    await navigator.clipboard.writeText(props.message.content)
    ElMessage.success('已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择文本')
  }
}
</script>

<template>
  <div class="msg" :class="isUser ? 'user' : 'assistant'">
    <div class="avatar">{{ isUser ? '我' : 'AI' }}</div>
    <div class="bubble-wrap">
      <div class="bubble" v-html="html" @click="onClick" />
      <div v-if="!isUser && citations.length" class="sources">
        <button
          v-for="item in citations"
          :key="item.chunk_id"
          class="source-chip"
          type="button"
          @click="emit('open-citation', item)"
        >
          <span class="index">[{{ item.rank }}]</span>
          <span class="name">{{ item.doc_name }}</span>
          <span v-if="item.page > 0" style="color: #94a3b8">P{{ item.page }}</span>
        </button>
      </div>
      <div v-if="!isUser" class="msg-meta">
        <span v-if="streaming" style="color: var(--brand)">生成中…</span>
        <template v-else>
          <span v-if="message.from_cache" style="color: var(--ok)">缓存命中</span>
          <span v-if="message.latency_ms">{{ (message.latency_ms / 1000).toFixed(2) }}s</span>
          <span v-if="message.first_token_ms">首字 {{ message.first_token_ms }}ms</span>
          <span v-if="message.completion_tokens">{{ message.completion_tokens }} tokens</span>
          <el-tooltip content="复制回答" placement="top">
            <el-icon style="cursor: pointer" @click="copy"><CopyDocument /></el-icon>
          </el-tooltip>
          <el-tooltip content="有帮助" placement="top">
            <el-icon
              :style="{ cursor: 'pointer', color: feedback === 1 ? 'var(--ok)' : '' }"
              @click="emit('feedback', 1)"
            >
              <StarFilled v-if="feedback === 1" /><Star v-else />
            </el-icon>
          </el-tooltip>
          <el-tooltip content="需要改进" placement="top">
            <el-icon
              :style="{ cursor: 'pointer', color: feedback === -1 ? 'var(--danger)' : '' }"
              @click="emit('feedback', -1)"
            >
              <StarFilled v-if="feedback === -1" /><Star v-else />
            </el-icon>
          </el-tooltip>
        </template>
        <span>{{ time }}</span>
      </div>
      <div v-else class="msg-meta">{{ time }}</div>
    </div>
  </div>
</template>
