<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()
const submitting = ref(false)

const form = reactive({ username: '', password: '' })

async function submit(): Promise<void> {
  if (!form.username.trim() || !form.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  submitting.value = true
  try {
    await auth.login(form.username.trim(), form.password)
    ElMessage.success('登录成功')
    const redirect = (route.query.redirect as string) || '/chat'
    await router.replace(redirect)
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '登录失败')
  } finally {
    submitting.value = false
  }
}

function fillAdmin(): void {
  form.username = 'admin'
  form.password = '123456'
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
        <h1>让每一次回答<br />都有据可依</h1>
        <p>
          面向电商商品场景的企业级知识库问答系统。上传商品资料后，系统自动切分、向量化并建立
          BM25 索引，回答时给出可追溯的原文引用。
        </p>
        <div class="auth-points">
          <div class="auth-point"><i>1</i><span>混合检索：向量 + BM25 + RRF 融合 + 重排</span></div>
          <div class="auth-point"><i>2</i><span>流式输出：首字延迟低，引用片段实时可见</span></div>
          <div class="auth-point"><i>3</i><span>会话留痕：多用户隔离，历史对话随时找回</span></div>
          <div class="auth-point"><i>4</i><span>精确 + 语义两级缓存，重复问题秒级响应</span></div>
        </div>
      </div>

      <div style="color: #94a3b8; font-size: 12px">毕业设计演示系统 · 数据仅用于教学演示</div>
    </section>

    <section class="auth-panel">
      <div class="auth-card">
        <h2>欢迎回来</h2>
        <div class="sub">登录后即可开始知识库问答</div>
        <el-form label-position="top" @submit.prevent="submit">
          <el-form-item label="用户名">
            <el-input v-model="form.username" size="large" placeholder="请输入用户名" clearable />
          </el-form-item>
          <el-form-item label="密码">
            <el-input
              v-model="form.password"
              size="large"
              type="password"
              placeholder="请输入密码"
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
            登录
          </el-button>
        </el-form>
        <div class="auth-foot">
          还没有账号？<router-link to="/register">立即注册</router-link>
        </div>
        <div class="auth-foot" style="margin-top: 10px">
          演示管理员：
          <a href="javascript:void(0)" @click="fillAdmin">admin / 123456</a>
        </div>
      </div>
    </section>
  </div>
</template>
