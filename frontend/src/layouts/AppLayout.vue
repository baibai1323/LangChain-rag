<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import {
  ChatDotRound,
  Collection,
  DataAnalysis,
  Setting,
  SwitchButton
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const title = computed(() => (route.meta.title as string) || '知识库问答')
const flush = computed(() => Boolean(route.meta.flush))
const crumb = computed(() => {
  if (route.name === 'admin-kb-detail') return '知识库管理 / 详情'
  if (route.name === 'admin-kbs') return '管理后台'
  if (route.name === 'admin-stats') return '管理后台'
  return '工作台'
})

async function logout(): Promise<void> {
  try {
    await ElMessageBox.confirm('确定要退出登录吗？', '提示', {
      confirmButtonText: '退出',
      cancelButtonText: '取消',
      type: 'warning'
    })
  } catch {
    return
  }
  await auth.logout()
  await router.replace('/login')
}
</script>

<template>
  <div class="layout">
    <aside class="sidebar">
      <div class="logo">
        <div class="brand-mark">RAG</div>
        <div>
          <span>知识库问答</span>
          <small>Enterprise RAG</small>
        </div>
      </div>

      <div class="section">工作台</div>
      <router-link class="nav-item" to="/chat">
        <el-icon><ChatDotRound /></el-icon><span>知识库问答</span>
      </router-link>

      <template v-if="auth.isAdmin">
        <div class="section">管理后台</div>
        <router-link class="nav-item" to="/admin/kbs">
          <el-icon><Collection /></el-icon><span>知识库管理</span>
        </router-link>
        <router-link class="nav-item" to="/admin/stats">
          <el-icon><DataAnalysis /></el-icon><span>数据统计</span>
        </router-link>
      </template>

      <div class="sidebar-foot">
        <router-link class="nav-item" to="/settings">
          <el-icon><Setting /></el-icon><span>账号设置</span>
        </router-link>
        <div class="nav-item" style="cursor: default">
          <div
            class="avatar"
            style="width: 26px; height: 26px; border-radius: 8px; background: #334155; font-size: 12px"
          >
            {{ auth.user?.username?.slice(0, 1).toUpperCase() }}
          </div>
          <div class="user-meta" style="min-width: 0; flex: 1">
            <div style="color: #e2e8f0; font-size: 13px; overflow: hidden; text-overflow: ellipsis">
              {{ auth.user?.username }}
            </div>
            <div style="color: #94a3b8; font-size: 11px">
              {{ auth.isAdmin ? '管理员' : '普通用户' }}
            </div>
          </div>
          <el-tooltip content="退出登录" placement="top">
            <el-icon style="cursor: pointer; color: #94a3b8" @click="logout"><SwitchButton /></el-icon>
          </el-tooltip>
        </div>
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <div>
          <h2>{{ title }}</h2>
          <div class="crumb">{{ crumb }}</div>
        </div>
        <div style="display: flex; align-items: center; gap: 10px">
          <el-tag v-if="auth.isAdmin" type="warning" effect="light" size="small">管理员</el-tag>
          <el-tag type="success" effect="plain" size="small">千问 · Qwen</el-tag>
        </div>
      </header>
      <div
        class="content"
        :style="flush ? 'padding:0;overflow:hidden;display:flex;flex-direction:column' : ''"
      >
        <router-view />
      </div>
    </div>
  </div>
</template>
