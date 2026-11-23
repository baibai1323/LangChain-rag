<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/api'
import type { AuditLogItem, LlmCallItem, SeriesPoint } from '@/api'
import type { AdminStats, User } from '@/types'

const stats = ref<AdminStats | null>(null)
const series = ref<SeriesPoint[]>([])
const users = ref<User[]>([])
const calls = ref<LlmCallItem[]>([])
const logs = ref<AuditLogItem[]>([])
const cache = ref<Record<string, number>>({})
const loading = ref(false)
const tab = ref('overview')

const maxMessages = computed(() => Math.max(1, ...series.value.map((point) => point.messages)))
const satisfaction = computed(() => {
  if (!stats.value) return 0
  const total = stats.value.feedback_positive + stats.value.feedback_negative
  return total ? Math.round((stats.value.feedback_positive / total) * 100) : 0
})

async function load(): Promise<void> {
  loading.value = true
  try {
    const [statData, seriesData, userData, callData, logData, cacheData] = await Promise.all([
      adminApi.stats(),
      adminApi.series(),
      adminApi.users(),
      adminApi.llmCalls(30),
      adminApi.auditLogs(30),
      adminApi.cache()
    ])
    stats.value = statData
    series.value = seriesData
    users.value = userData
    calls.value = callData
    logs.value = logData
    cache.value = cacheData
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '统计加载失败')
  } finally {
    loading.value = false
  }
}

async function changeRole(user: User, role: string): Promise<void> {
  try {
    await adminApi.updateUser(user.id, { role })
    ElMessage.success('角色已更新')
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '更新失败')
    await load()
  }
}

async function toggleStatus(user: User): Promise<void> {
  try {
    const next = user.status === 'active' ? 'disabled' : 'active'
    await adminApi.updateUser(user.id, { status: next })
    ElMessage.success(next === 'active' ? '账号已启用' : '账号已禁用')
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '更新失败')
    await load()
  }
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString('zh-CN', { hour12: false })
}

onMounted(load)
</script>

<template>
  <div v-loading="loading">
    <el-tabs v-model="tab">
      <el-tab-pane label="平台概览" name="overview">
        <div class="stat-grid" style="margin-bottom: 16px">
          <div class="stat">
            <div class="label">注册用户</div>
            <div class="value">{{ stats?.users ?? 0 }}</div>
            <div class="hint">含管理员账号</div>
          </div>
          <div class="stat">
            <div class="label">知识库 / 文档</div>
            <div class="value">{{ stats?.knowledge_bases ?? 0 }} / {{ stats?.documents ?? 0 }}</div>
            <div class="hint">{{ stats?.chunks ?? 0 }} 个知识片段</div>
          </div>
          <div class="stat">
            <div class="label">会话 / 消息</div>
            <div class="value">{{ stats?.conversations ?? 0 }} / {{ stats?.messages ?? 0 }}</div>
            <div class="hint">多用户独立会话</div>
          </div>
          <div class="stat">
            <div class="label">今日模型调用</div>
            <div class="value">{{ stats?.llm_calls_today ?? 0 }}</div>
            <div class="hint">{{ (stats?.tokens_today ?? 0).toLocaleString() }} tokens</div>
          </div>
          <div class="stat">
            <div class="label">平均响应延迟</div>
            <div class="value">{{ ((stats?.avg_latency_ms ?? 0) / 1000).toFixed(2) }}s</div>
            <div class="hint">端到端生成耗时</div>
          </div>
          <div class="stat">
            <div class="label">反馈满意度</div>
            <div class="value">{{ satisfaction }}%</div>
            <div class="hint">👍 {{ stats?.feedback_positive ?? 0 }} · 👎 {{ stats?.feedback_negative ?? 0 }}</div>
          </div>
        </div>

        <div class="card">
          <div class="card-head">
            <strong style="font-size: 14px">近 7 天提问量</strong>
            <span style="color: var(--muted); font-size: 12px">按用户消息统计</span>
          </div>
          <div class="card-body">
            <div v-for="point in series" :key="point.date" class="bar-row">
              <span class="label">{{ point.date.slice(5) }}</span>
              <div class="bar-track">
                <div class="bar-fill" :style="{ width: `${(point.messages / maxMessages) * 100}%` }" />
              </div>
              <span style="width: 34px; text-align: right; color: var(--ink-2)">{{ point.messages }}</span>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="用户管理" name="users">
        <div class="card">
          <el-table :data="users" style="width: 100%">
            <el-table-column label="用户名" min-width="160">
              <template #default="{ row }">
                <strong>{{ row.username }}</strong>
                <el-tag v-if="row.username === 'admin'" size="small" type="warning" effect="plain" style="margin-left: 8px">
                  内置
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="角色" width="150">
              <template #default="{ row }">
                <el-select
                  :model-value="row.role"
                  size="small"
                  :disabled="row.username === 'admin'"
                  @change="(value: string) => changeRole(row, value)"
                >
                  <el-option label="普通用户" value="user" />
                  <el-option label="管理员" value="admin" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <el-tag :type="row.status === 'active' ? 'success' : 'danger'" size="small" effect="light">
                  {{ row.status === 'active' ? '正常' : '已禁用' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="会话数" width="90" prop="conversation_count" />
            <el-table-column label="注册时间" width="170">
              <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="最近登录" width="170">
              <template #default="{ row }">{{ row.last_login_at ? formatDate(row.last_login_at) : '从未登录' }}</template>
            </el-table-column>
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }">
                <el-button
                  link
                  :type="row.status === 'active' ? 'danger' : 'success'"
                  :disabled="row.username === 'admin'"
                  @click="toggleStatus(row)"
                >
                  {{ row.status === 'active' ? '禁用' : '启用' }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="模型调用" name="calls">
        <div class="card">
          <el-table :data="calls" style="width: 100%">
            <el-table-column label="用途" width="140" prop="purpose" />
            <el-table-column label="模型" width="180" prop="model" />
            <el-table-column label="输入 tokens" width="120" prop="prompt_tokens" />
            <el-table-column label="输出 tokens" width="120" prop="completion_tokens" />
            <el-table-column label="耗时" width="100">
              <template #default="{ row }">{{ (row.latency_ms / 1000).toFixed(2) }}s</template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="row.status === 'success' ? 'success' : 'danger'" size="small" effect="light">
                  {{ row.status }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="时间" min-width="170">
              <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
            </el-table-column>
            <template #empty><div class="empty">还没有模型调用记录</div></template>
          </el-table>
        </div>
      </el-tab-pane>

      <el-tab-pane label="审计日志" name="logs">
        <div class="card" style="margin-bottom: 16px">
          <div class="card-body" style="font-size: 12px; color: var(--muted)">
            缓存状态：
            <span v-for="(value, key) in cache" :key="key" style="margin-right: 16px">
              {{ key }} = <strong style="color: var(--ink-2)">{{ value }}</strong>
            </span>
          </div>
        </div>
        <div class="card">
          <el-table :data="logs" style="width: 100%">
            <el-table-column label="用户" width="140" prop="username" />
            <el-table-column label="动作" width="150" prop="action" />
            <el-table-column label="对象" width="180" prop="target" />
            <el-table-column label="详情" min-width="180" prop="detail" />
            <el-table-column label="IP" width="140" prop="ip" />
            <el-table-column label="时间" width="170">
              <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>
