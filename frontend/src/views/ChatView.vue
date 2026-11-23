<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ChatLineRound,
  Delete,
  MoreFilled,
  Plus,
  Promotion,
  Refresh,
  VideoPause
} from '@element-plus/icons-vue'
import { convApi, kbApi, streamChat } from '@/api'
import type { ChatMessage, Citation, Conversation, Kb } from '@/types'
import MessageBubble from '@/components/MessageBubble.vue'
import CitationDrawer from '@/components/CitationDrawer.vue'

const kbs = ref<Kb[]>([])
const kbId = ref('')
const conversations = ref<Conversation[]>([])
const current = ref<Conversation | null>(null)
const messages = ref<ChatMessage[]>([])
const question = ref('')
const streaming = ref(false)
const statusText = ref('')
const loadingMessages = ref(false)
const bodyRef = ref<HTMLElement | null>(null)
const drawerVisible = ref(false)
const drawerCitations = ref<Citation[]>([])
const drawerActive = ref<number | undefined>(undefined)
const feedbacks = reactive<Record<string, number>>({})
let controller: AbortController | null = null

const activeKb = computed(() => kbs.value.find((kb) => kb.id === kbId.value) || null)
const isEmpty = computed(() => !messages.value.length)

const suggestions = [
  '这款商品支持七天无理由退货吗？',
  '商品保修政策和售后流程是什么？',
  '发什么快递，一般多久能到？',
  '帮我对比一下这两款商品的主要区别'
]

function emptyMessage(role: 'user' | 'assistant', content: string): ChatMessage {
  return {
    id: `temp-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    conversation_id: current.value?.id || '',
    role,
    content,
    status: 'streaming',
    model: '',
    prompt_tokens: 0,
    completion_tokens: 0,
    first_token_ms: 0,
    latency_ms: 0,
    from_cache: 0,
    created_at: new Date().toISOString(),
    citations: []
  }
}

function scrollToBottom(): void {
  nextTick(() => {
    const el = bodyRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function loadKbs(): Promise<void> {
  try {
    kbs.value = await kbApi.list()
    if (!kbId.value && kbs.value.length) kbId.value = kbs.value[0].id
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '知识库加载失败')
  }
}

async function loadConversations(selectFirst = false): Promise<void> {
  if (!kbId.value) {
    conversations.value = []
    return
  }
  try {
    conversations.value = await convApi.list(kbId.value)
    if (selectFirst && conversations.value.length) {
      await selectConversation(conversations.value[0])
    }
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '会话加载失败')
  }
}

async function selectConversation(conv: Conversation): Promise<void> {
  if (streaming.value) return
  current.value = conv
  loadingMessages.value = true
  try {
    messages.value = await convApi.messages(conv.id)
    scrollToBottom()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '历史消息加载失败')
  } finally {
    loadingMessages.value = false
  }
}

async function newConversation(): Promise<void> {
  if (!kbId.value) {
    ElMessage.warning('请先让管理员创建知识库')
    return
  }
  if (streaming.value) return
  try {
    const conv = await convApi.create(kbId.value, '新会话')
    conversations.value.unshift(conv)
    current.value = conv
    messages.value = []
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '创建会话失败')
  }
}

async function send(): Promise<void> {
  const text = question.value.trim()
  if (!text || streaming.value) return
  if (!kbId.value) {
    ElMessage.warning('暂无可用知识库，请联系管理员')
    return
  }
  if (!current.value) {
    await newConversation()
    if (!current.value) return
  }

  question.value = ''
  const userMessage = emptyMessage('user', text)
  const assistant = emptyMessage('assistant', '')
  messages.value.push(userMessage, assistant)
  const index = messages.value.length - 1
  streaming.value = true
  statusText.value = '正在理解问题…'
  controller = new AbortController()
  scrollToBottom()

  try {
    await streamChat(
      { conversation_id: current.value.id, question: text },
      {
        onStatus: (data) => {
          statusText.value = data.message
        },
        onRetrieval: (data) => {
          messages.value[index].citations = data.hits || []
          scrollToBottom()
        },
        onDelta: (delta) => {
          messages.value[index].content += delta
          statusText.value = ''
          scrollToBottom()
        },
        onDone: (data) => {
          const target = messages.value[index]
          target.id = String(data.message_id || target.id)
          target.status = 'done'
          target.from_cache = data.from_cache ? 1 : 0
          target.latency_ms = Number(data.latency_ms || 0)
          target.first_token_ms = Number(data.first_token_ms || 0)
          const usage = (data.usage || {}) as Record<string, number>
          target.prompt_tokens = usage.prompt_tokens || 0
          target.completion_tokens = usage.completion_tokens || 0
          if (Array.isArray(data.citations) && data.citations.length) {
            target.citations = data.citations as Citation[]
          }
          if (current.value && data.conversation_title) {
            current.value.title = String(data.conversation_title)
          }
          void refreshConversationList()
          scrollToBottom()
        },
        onError: (message) => {
          const target = messages.value[index]
          target.status = 'failed'
          target.content = target.content || `生成失败：${message}`
          ElMessage.error(message)
        }
      },
      { signal: controller.signal }
    )
  } catch (error) {
    const target = messages.value[index]
    if (error instanceof DOMException && error.name === 'AbortError') {
      target.status = 'cancelled'
      target.content = target.content || '已停止生成'
    } else {
      target.status = 'failed'
      target.content = target.content || (error instanceof Error ? error.message : '请求失败')
      ElMessage.error(error instanceof Error ? error.message : '请求失败')
    }
  } finally {
    streaming.value = false
    statusText.value = ''
    controller = null
    scrollToBottom()
  }
}

async function refreshConversationList(): Promise<void> {
  if (!kbId.value) return
  try {
    const list = await convApi.list(kbId.value)
    conversations.value = list
    if (current.value) {
      const fresh = list.find((item) => item.id === current.value?.id)
      if (fresh) current.value = fresh
    }
  } catch {
    /* 列表刷新失败不打断对话 */
  }
}

function stop(): void {
  controller?.abort()
}

function openCitation(citation: Citation): void {
  const message = messages.value.find((item) =>
    item.citations.some((c) => c.chunk_id === citation.chunk_id)
  )
  drawerCitations.value = message?.citations?.length ? message.citations : [citation]
  drawerActive.value = citation.rank
  drawerVisible.value = true
}

async function feedback(message: ChatMessage, rating: number): Promise<void> {
  if (!message.id || message.id.startsWith('temp-')) return
  try {
    await convApi.feedback(message.id, rating)
    feedbacks[message.id] = feedbacks[message.id] === rating ? 0 : rating
    ElMessage.success('感谢反馈')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '反馈失败')
  }
}

async function rename(conv: Conversation): Promise<void> {
  try {
    const { value } = await ElMessageBox.prompt('请输入新的会话名称', '重命名', {
      inputValue: conv.title,
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValidator: (v) => (v && v.trim().length > 0 ? true : '名称不能为空')
    })
    const updated = await convApi.update(conv.id, { title: value.trim() })
    Object.assign(conv, updated)
    if (current.value?.id === conv.id) current.value = { ...current.value, title: updated.title }
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(error instanceof Error ? error.message : '重命名失败')
  }
}

async function togglePin(conv: Conversation): Promise<void> {
  try {
    await convApi.update(conv.id, { is_pinned: conv.is_pinned ? 0 : 1 })
    await refreshConversationList()
    ElMessage.success(conv.is_pinned ? '已取消置顶' : '已置顶')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '操作失败')
  }
}

async function remove(conv: Conversation): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定删除会话「${conv.title}」？删除后不可恢复。`, '提示', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  try {
    await convApi.remove(conv.id)
    conversations.value = conversations.value.filter((item) => item.id !== conv.id)
    if (current.value?.id === conv.id) {
      current.value = null
      messages.value = []
      if (conversations.value.length) await selectConversation(conversations.value[0])
    }
    ElMessage.success('会话已删除')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '删除失败')
  }
}

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const now = new Date()
  const sameDay = date.toDateString() === now.toDateString()
  const hm = `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
  return sameDay ? hm : `${date.getMonth() + 1}-${date.getDate()} ${hm}`
}

watch(kbId, async () => {
  current.value = null
  messages.value = []
  await loadConversations(true)
})

onMounted(async () => {
  await loadKbs()
  await loadConversations(true)
})
</script>

<template>
  <div class="chat-page">
    <aside class="conv-panel">
      <div class="conv-head">
        <el-select
          v-model="kbId"
          placeholder="选择知识库"
          size="default"
          style="width: 100%"
          :disabled="streaming"
        >
          <el-option v-for="kb in kbs" :key="kb.id" :label="kb.name" :value="kb.id" />
        </el-select>
        <el-button
          type="primary"
          style="width: 100%; margin-top: 8px"
          :icon="Plus"
          :disabled="!kbId || streaming"
          @click="newConversation"
        >
          新建会话
        </el-button>
      </div>
      <div class="conv-list">
        <div v-if="!conversations.length" class="empty" style="padding: 26px 8px; font-size: 12px">
          <el-icon style="font-size: 22px; margin-bottom: 6px"><ChatLineRound /></el-icon>
          <div>还没有会话</div>
          <div style="margin-top: 4px">点击上方「新建会话」开始</div>
        </div>
        <div
          v-for="conv in conversations"
          :key="conv.id"
          class="conv-item"
          :class="{ active: current?.id === conv.id }"
          @click="selectConversation(conv)"
        >
          <div style="display: flex; align-items: center; gap: 4px">
            <div class="title" style="flex: 1">{{ conv.title }}</div>
            <el-dropdown trigger="click" @command="(cmd: string) => cmd === 'rename' ? rename(conv) : cmd === 'pin' ? togglePin(conv) : remove(conv)">
              <el-icon style="color: #94a3b8" @click.stop><MoreFilled /></el-icon>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="rename">重命名</el-dropdown-item>
                  <el-dropdown-item command="pin">{{ conv.is_pinned ? '取消置顶' : '置顶' }}</el-dropdown-item>
                  <el-dropdown-item command="delete" divided>
                    <span style="color: var(--danger)">删除会话</span>
                  </el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
          <div class="meta">
            <span>{{ conv.message_count }} 条提问</span>
            <span>{{ formatTime(conv.updated_at) }}</span>
          </div>
        </div>
      </div>
      <div style="padding: 10px 12px; border-top: 1px solid var(--line); font-size: 11px; color: #94a3b8">
        历史会话永久保存，登录后可随时找回
      </div>
    </aside>

    <section class="chat-main">
      <header class="chat-head">
        <div style="min-width: 0">
          <div class="title">{{ current?.title || '新对话' }}</div>
          <div style="font-size: 11px; color: var(--muted); margin-top: 2px">
            {{ activeKb ? `${activeKb.name} · ${activeKb.document_count} 个文档 / ${activeKb.chunk_count} 个片段` : '请选择知识库' }}
          </div>
        </div>
        <div style="flex: 1" />
        <el-tooltip content="刷新会话列表" placement="top">
          <el-icon style="cursor: pointer; color: #64748b" @click="refreshConversationList">
            <Refresh />
          </el-icon>
        </el-tooltip>
      </header>

      <div ref="bodyRef" class="chat-body" v-loading="loadingMessages">
        <div class="chat-body-inner">
          <div v-if="isEmpty && !loadingMessages" class="welcome">
            <span class="badge">RAG · 检索增强生成</span>
            <h1>你好，想了解哪件商品？</h1>
            <p>
              我会先检索知识库，再基于商品资料回答，并在回答中标注引用来源，方便你核对原文。
            </p>
            <div class="suggest-grid">
              <button v-for="item in suggestions" :key="item" class="suggest" @click="question = item">
                {{ item }}
              </button>
            </div>
            <div v-if="!kbs.length" style="margin-top: 24px; color: var(--warn); font-size: 13px">
              当前还没有知识库，请使用管理员账号在「知识库管理」中创建并上传资料。
            </div>
          </div>

          <MessageBubble
            v-for="(message, idx) in messages"
            :key="message.id || idx"
            :message="message"
            :streaming="streaming && idx === messages.length - 1 && !message.content"
            :feedback="feedbacks[message.id] || 0"
            @open-citation="openCitation"
            @feedback="(rating: number) => feedback(message, rating)"
          />

          <div
            v-if="streaming && statusText"
            style="display: flex; align-items: center; gap: 8px; color: var(--muted); font-size: 12px; margin: 4px 0 18px 46px"
          >
            <span class="spinner" />
            {{ statusText }}
          </div>
        </div>
      </div>

      <div class="composer">
        <div class="composer-inner">
          <div class="composer-box">
            <textarea
              v-model="question"
              rows="1"
              placeholder="输入你的问题，Enter 发送，Shift + Enter 换行"
              :disabled="streaming"
              @keydown.enter.exact.prevent="send"
            />
            <el-button v-if="!streaming" type="primary" :icon="Promotion" circle @click="send" />
            <el-button v-else type="danger" :icon="VideoPause" circle plain @click="stop" />
          </div>
          <div class="composer-tip">
            回答由 AI 基于知识库生成，如有偏差请以商品详情页为准 · 支持引用溯源
          </div>
        </div>
      </div>
    </section>

    <CitationDrawer
      v-model="drawerVisible"
      :citations="drawerCitations"
      :active-rank="drawerActive"
    />
  </div>
</template>

<style scoped>
.spinner {
  width: 12px;
  height: 12px;
  border: 2px solid #c7d2e5;
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
