<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const submitting = ref(false)

const form = reactive({ username: '', password: '', confirm: '' })

async function submit(): Promise<void> {
  if (!/^[A-Za-z0-9_\u4e00-\u9fa5]{3,32}$/.test(form.username.trim())) {
    ElMessage.warning('用户名需 3-32 位，仅支持中英文、数字与下划线')
    return
  }
  if (form.password.length < 6) {
    ElMessage.warning('密码至少 6 位')
    return
  }
  if (form.password !== form.confirm) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }
  submitting.value = true
  try {
    await auth.register(form.username.trim(), form.password)
    ElMessage.success('注册成功，已自动登录')
    await router.replace('/chat')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '注册失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <section class="auth-hero">
      <div class="auth-brand">
        <div class="brand-mark">RAG</div>
        <div>
          电商知识库问答
          <small style="display: block; font-size: 12px; color: #64748b; font-weight: 400">
            LangChain · 千问 · 混合检索
          </small>
        </div>
      </div>
      <div>
        <h1>创建账号<br />开启知识问答</h1>
        <p>普通用户可以自由创建会话、提问并查看引用原文；知识库的维护由管理员统一负责。</p>
        <div class="auth-points">
          <div class="auth-point"><i>✓</i><span>多会话隔离，历史记录云端保存</span></div>
          <div class="auth-point"><i>✓</i><span>回答附带引用编号，可展开查看原文</span></div>
          <div class="auth-point"><i>✓</i><span>支持点赞点踩，帮助优化问答质量</span></div>
        </div>
      </div>
      <div style="color: #94a3b8; font-size: 12px">毕业设计演示系统 · 数据仅用于教学演示</div>
    </section>

    <section class="auth-panel">
      <div class="auth-card">
        <h2>注册账号</h2>
        <div class="sub">注册后自动登录</div>
        <el-form label-position="top" @submit.prevent="submit">
          <el-form-item label="用户名">
            <el-input v-model="form.username" size="large" placeholder="3-32 位中英文/数字/下划线" clearable />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="form.password" size="large" type="password" placeholder="至少 6 位" show-password />
          </el-form-item>
          <el-form-item label="确认密码">
            <el-input
              v-model="form.confirm"
              size="large"
              type="password"
              placeholder="请再次输入密码"
              show-password
              @keyup.enter="submit"
            />
          </el-form-item>
          <el-button
            type="primary"
            size="large"
            style="width: 100%; margin-top: 6px"
            :loading="submitting"
            @click="submit"
          >
            注册
          </el-button>
        </el-form>
        <div class="auth-foot">已有账号？<router-link to="/login">返回登录</router-link></div>
      </div>
    </section>
  </div>
</template>
