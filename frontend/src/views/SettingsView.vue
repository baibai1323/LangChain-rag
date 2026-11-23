<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const saving = ref(false)
const form = reactive({ oldPassword: '', newPassword: '', confirm: '' })

async function submit(): Promise<void> {
  if (!form.oldPassword) {
    ElMessage.warning('请输入原密码')
    return
  }
  if (form.newPassword.length < 6) {
    ElMessage.warning('新密码至少 6 位')
    return
  }
  if (form.newPassword !== form.confirm) {
    ElMessage.warning('两次输入的新密码不一致')
    return
  }
  saving.value = true
  try {
    await auth.changePassword(form.oldPassword, form.newPassword)
    form.oldPassword = ''
    form.newPassword = ''
    form.confirm = ''
    ElMessage.success('密码已修改，其他设备上的登录状态已失效')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '修改失败')
  } finally {
    saving.value = false
  }
}

async function logout(): Promise<void> {
  await auth.logout()
  await router.replace('/login')
}

function formatDate(value?: string | null): string {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <div style="max-width: 760px">
    <div class="card" style="margin-bottom: 16px">
      <div class="card-head"><strong style="font-size: 14px">账号信息</strong></div>
      <div class="card-body" style="display: flex; gap: 16px; align-items: center">
        <div
          class="avatar"
          style="width: 56px; height: 56px; border-radius: 16px; background: linear-gradient(135deg,#2563eb,#7c3aed); font-size: 22px"
        >
          {{ auth.user?.username?.slice(0, 1).toUpperCase() }}
        </div>
        <div style="flex: 1">
          <div style="font-size: 16px; font-weight: 700">{{ auth.user?.username }}</div>
          <div style="color: var(--muted); font-size: 12px; margin-top: 3px">
            角色：{{ auth.isAdmin ? '管理员（可管理知识库）' : '普通用户（知识库问答）' }}
          </div>
          <div style="color: var(--muted); font-size: 12px; margin-top: 2px">
            注册时间：{{ formatDate(auth.user?.created_at) }} · 最近登录：{{ formatDate(auth.user?.last_login_at) }}
          </div>
        </div>
        <el-button plain type="danger" @click="logout">退出登录</el-button>
      </div>
    </div>

    <div class="card" style="margin-bottom: 16px">
      <div class="card-head">
        <strong style="font-size: 14px">修改密码</strong>
        <span style="color: var(--muted); font-size: 12px">修改后需要使用新密码重新登录其他设备</span>
      </div>
      <div class="card-body">
        <el-form label-position="top" style="max-width: 420px">
          <el-form-item label="原密码">
            <el-input v-model="form.oldPassword" type="password" show-password placeholder="请输入当前密码" />
          </el-form-item>
          <el-form-item label="新密码">
            <el-input v-model="form.newPassword" type="password" show-password placeholder="至少 6 位" />
          </el-form-item>
          <el-form-item label="确认新密码">
            <el-input v-model="form.confirm" type="password" show-password placeholder="请再次输入新密码" />
          </el-form-item>
          <el-button type="primary" :loading="saving" @click="submit">保存修改</el-button>
        </el-form>
      </div>
    </div>

    <div class="card">
      <div class="card-head"><strong style="font-size: 14px">系统信息</strong></div>
      <div class="card-body" style="font-size: 13px; line-height: 2; color: var(--ink-2)">
        <div>技术栈：FastAPI · LangChain · SQLite(FTS5) · Chroma · Vue 3 · Element Plus</div>
        <div>模型服务：阿里云百炼 · qwen-max（回答）/ qwen-turbo（改写与标题）/ text-embedding-v3 / gte-rerank-v2</div>
        <div>检索策略：向量 Top20 + BM25 Top20 → RRF 融合 → 重排 Top6，回答附引用溯源</div>
        <div>性能优化：精确缓存 + 语义缓存（≥0.95）、SSE 流式输出、异步 IO、连接池与 WAL</div>
      </div>
    </div>
  </div>
</template>
