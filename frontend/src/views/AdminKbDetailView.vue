<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Search, UploadFilled } from '@element-plus/icons-vue'
import { docApi, kbApi, taskApi } from '@/api'
import type { ChunkItem, DocumentItem, Kb, SearchHit, TaskItem } from '@/types'
import type { UploadRequestOptions } from 'element-plus'

const route = useRoute()
const router = useRouter()
const kbId = String(route.params.id)
const kb = ref<Kb | null>(null)
const stats = ref({ documents: 0, ready_documents: 0, chunks: 0, tokens: 0 })
const docs = ref<DocumentItem[]>([])
const tasks = reactive<Record<string, TaskItem>>({})
const loading = ref(false)
const uploading = ref(false)
const timer = ref<number | null>(null)

const chunkDialog = ref(false)
const chunkDoc = ref<DocumentItem | null>(null)
const chunks = ref<ChunkItem[]>([])
const chunkTotal = ref(0)
const chunkPage = ref(1)
const chunkLoading = ref(false)

const searchQuery = ref('')
const searchHits = ref<SearchHit[]>([])
const searching = ref(false)

const runningCount = computed(
  () => Object.values(tasks).filter((task) => task.status === 'running').length
)

function statusTag(status: string): { type: 'info' | 'warning' | 'success' | 'danger'; text: string } {
  if (status === 'ready') return { type: 'success', text: '已就绪' }
  if (status === 'processing') return { type: 'warning', text: '处理中' }
  if (status === 'failed') return { type: 'danger', text: '失败' }
  return { type: 'info', text: '等待中' }
}

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(2)} MB`
}

async function loadAll(): Promise<void> {
  loading.value = true
  try {
    const [detail, statistics, documents, recent] = await Promise.all([
      kbApi.get(kbId),
      kbApi.stats(kbId),
      docApi.list(kbId),
      taskApi.listByKb(kbId)
    ])
    kb.value = detail
    stats.value = statistics
    docs.value = documents
    for (const task of recent) {
      if (task.status === 'running') tasks[task.doc_id] = task
    }
    if (runningCount.value) startPolling()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载失败')
  } finally {
    loading.value = false
  }
}

function startPolling(): void {
  if (timer.value) return
  timer.value = window.setInterval(async () => {
    const running = Object.entries(tasks).filter(([, task]) => task.status === 'running')
    if (!running.length) {
      stopPolling()
      return
    }
    let changed = false
    for (const [docId, task] of running) {
      try {
        const fresh = await taskApi.get(task.id)
        tasks[docId] = fresh
        if (fresh.status !== 'running') changed = true
      } catch {
        /* 单个任务查询失败忽略 */
      }
    }
    if (changed) {
      try {
        docs.value = await docApi.list(kbId)
        stats.value = await kbApi.stats(kbId)
        kb.value = await kbApi.get(kbId)
      } catch {
        /* ignore */
      }
    }
  }, 1500)
}

function stopPolling(): void {
  if (timer.value) {
    window.clearInterval(timer.value)
    timer.value = null
  }
}

async function upload(options: UploadRequestOptions): Promise<void> {
  uploading.value = true
  try {
    const result = await docApi.upload(kbId, options.file as File)
    tasks[result.document.id] = {
      id: result.task_id,
      doc_id: result.document.id,
      stage: 'pending',
      progress: 0,
      status: 'running',
      error: null,
      started_at: new Date().toISOString(),
      finished_at: null
    }
    docs.value.unshift(result.document)
    startPolling()
    ElMessage.success(`${result.document.filename} 上传成功，正在后台入库`)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '上传失败')
  } finally {
    uploading.value = false
  }
}

async function reindex(doc: DocumentItem): Promise<void> {
  try {
    const result = await docApi.reindex(doc.id)
    tasks[doc.id] = {
      id: result.task_id,
      doc_id: doc.id,
      stage: 'pending',
      progress: 0,
      status: 'running',
      error: null,
      started_at: new Date().toISOString(),
      finished_at: null
    }
    startPolling()
    ElMessage.success('已开始重新入库')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '操作失败')
  }
}

async function remove(doc: DocumentItem): Promise<void> {
  try {
    await ElMessageBox.confirm(`确定删除文档「${doc.filename}」及其全部切片？`, '提示', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }
  try {
    await docApi.remove(doc.id)
    ElMessage.success('已删除')
    await loadAll()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '删除失败')
  }
}

async function loadChunks(): Promise<void> {
  if (!chunkDoc.value) return
  chunkLoading.value = true
  try {
    const data = await docApi.chunks(chunkDoc.value.id, (chunkPage.value - 1) * 8, 8)
    chunks.value = data.items
    chunkTotal.value = data.total
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '切片加载失败')
  } finally {
    chunkLoading.value = false
  }
}

function openChunks(doc: DocumentItem): void {
  chunkDoc.value = doc
  chunkPage.value = 1
  chunks.value = []
  chunkDialog.value = true
  void loadChunks()
}

function onChunkPage(page: number): void {
  chunkPage.value = page
  void loadChunks()
}

async function runSearch(): Promise<void> {
  if (!searchQuery.value.trim()) return
  searching.value = true
  try {
    searchHits.value = await kbApi.searchTest(kbId, searchQuery.value.trim(), 6)
    if (!searchHits.value.length) ElMessage.info('没有检索到相关片段')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '检索失败')
  } finally {
    searching.value = false
  }
}

onMounted(loadAll)
onBeforeUnmount(stopPolling)
</script>

<template>
  <div v-loading="loading">
    <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 16px">
      <el-button :icon="ArrowLeft" circle @click="router.push('/admin/kbs')" />
      <div style="flex: 1; min-width: 0">
        <div style="font-size: 18px; font-weight: 700">{{ kb?.name || '知识库' }}</div>
        <div style="color: var(--muted); font-size: 12px">{{ kb?.description || '暂无描述' }}</div>
      </div>
      <el-tag v-if="runningCount" type="warning" effect="light">后台入库中 · {{ runningCount }}</el-tag>
    </div>

    <div class="stat-grid" style="margin-bottom: 16px">
      <div class="stat">
        <div class="label">文档总数</div>
        <div class="value">{{ stats.documents }}</div>
        <div class="hint">已就绪 {{ stats.ready_documents }}</div>
      </div>
      <div class="stat">
        <div class="label">知识片段</div>
        <div class="value">{{ stats.chunks }}</div>
        <div class="hint">子块 400 字，父块 1200 字</div>
      </div>
      <div class="stat">
        <div class="label">估算 Token</div>
        <div class="value">{{ stats.tokens.toLocaleString() }}</div>
        <div class="hint">用于上下文预算控制</div>
      </div>
      <div class="stat">
        <div class="label">向量模型</div>
        <div class="value" style="font-size: 16px">{{ kb?.embedding_model || '-' }}</div>
        <div class="hint">{{ kb?.embedding_dim || 0 }} 维 · cosine</div>
      </div>
    </div>

    <div class="card" style="margin-bottom: 16px">
      <div class="card-head">
        <strong style="font-size: 14px">上传文档</strong>
        <span style="color: var(--muted); font-size: 12px">支持 PDF / DOCX / TXT / MD / CSV / JSON，单个不超过 20MB</span>
      </div>
      <div class="card-body">
        <el-upload
          drag
          multiple
          :show-file-list="false"
          :http-request="upload"
          :disabled="uploading"
          accept=".pdf,.docx,.txt,.md,.csv,.json,.log"
        >
          <el-icon style="font-size: 34px; color: #93b4f8"><UploadFilled /></el-icon>
          <div style="margin-top: 8px; font-size: 14px">
            {{ uploading ? '正在上传…' : '将文件拖到此处，或点击选择文件' }}
          </div>
          <div class="hint">上传后自动执行：解析 → 切片 → 向量化 → 建立 BM25 索引</div>
        </el-upload>
      </div>
    </div>

    <div class="card" style="margin-bottom: 16px">
      <div class="card-head">
        <strong style="font-size: 14px">文档列表</strong>
        <span style="color: var(--muted); font-size: 12px">共 {{ docs.length }} 个文档</span>
      </div>
      <el-table :data="docs" style="width: 100%">
        <el-table-column label="文件名" min-width="240">
          <template #default="{ row }">
            <div style="font-weight: 500">{{ row.filename }}</div>
            <div style="color: var(--muted); font-size: 12px">
              {{ formatSize(row.size) }} · {{ row.chunk_count }} 个切片
            </div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusTag(row.status).type" size="small" effect="light">
              {{ statusTag(row.status).text }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="入库进度" width="200">
          <template #default="{ row }">
            <div v-if="tasks[row.id] && tasks[row.id].status === 'running'" class="task-progress">
              <el-progress
                :percentage="tasks[row.id].progress"
                :stroke-width="6"
                style="flex: 1"
                :show-text="false"
              />
              <span class="stage">{{ tasks[row.id].stage }}</span>
            </div>
            <span v-else-if="row.status === 'failed'" style="color: var(--danger); font-size: 12px">
              {{ row.error || '处理失败' }}
            </span>
            <span v-else style="color: var(--muted); font-size: 12px">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" :disabled="!row.chunk_count" @click="openChunks(row)">
              切片
            </el-button>
            <el-button link @click="reindex(row)">重新入库</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty">还没有文档，先上传商品资料吧</div>
        </template>
      </el-table>
    </div>

    <div class="card">
      <div class="card-head">
        <strong style="font-size: 14px">检索测试</strong>
        <span style="color: var(--muted); font-size: 12px">验证混合检索与重排效果</span>
      </div>
      <div class="card-body">
        <div style="display: flex; gap: 10px; margin-bottom: 14px">
          <el-input
            v-model="searchQuery"
            placeholder="输入一个商品问题，例如：支持七天无理由退货吗"
            :prefix-icon="Search"
            @keyup.enter="runSearch"
          />
          <el-button type="primary" :loading="searching" @click="runSearch">检索</el-button>
        </div>
        <div v-if="searchHits.length">
          <div v-for="(hit, idx) in searchHits" :key="hit.chunk_id" class="search-hit">
            <div class="head">
              <span>#{{ idx + 1 }} · {{ hit.doc_name }}<span v-if="hit.page > 0"> · 第 {{ hit.page }} 页</span></span>
              <span>
                融合分 {{ hit.score.toFixed(4) }}
                <template v-if="hit.rerank_score !== null"> · 重排 {{ hit.rerank_score.toFixed(3) }}</template>
              </span>
            </div>
            <div class="body">{{ hit.content }}</div>
          </div>
        </div>
        <div v-else class="empty" style="padding: 20px 0">输入问题后点击检索，查看 Top6 命中片段</div>
      </div>
    </div>

    <el-dialog v-model="chunkDialog" :title="`切片预览 · ${chunkDoc?.filename || ''}`" width="820px">
      <div v-loading="chunkLoading">
        <div v-for="chunk in chunks" :key="chunk.id" class="card" style="margin-bottom: 10px">
          <div class="card-head" style="padding: 10px 14px">
            <span style="font-size: 12px; color: var(--muted)">
              切片 #{{ chunk.chunk_index + 1 }} · {{ chunk.char_count }} 字 · {{ chunk.token_count }} tokens
            </span>
          </div>
          <div class="card-body" style="padding: 12px 14px">
            <div style="font-size: 13px; line-height: 1.75; white-space: pre-wrap; color: var(--ink-2)">
              {{ chunk.content }}
            </div>
          </div>
        </div>
        <div v-if="!chunks.length && !chunkLoading" class="empty">暂无切片</div>
      </div>
      <template #footer>
        <el-pagination
          layout="prev, pager, next"
          :total="chunkTotal"
          :page-size="8"
          :current-page="chunkPage"
          @current-change="onChunkPage"
        />
      </template>
    </el-dialog>
  </div>
</template>
