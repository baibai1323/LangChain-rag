<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import { kbApi } from '@/api'
import type { Kb } from '@/types'

const router = useRouter()
const kbs = ref<Kb[]>([])
const loading = ref(false)
const keyword = ref('')
const dialog = ref(false)
const editing = ref<Kb | null>(null)
const saving = ref(false)
const form = reactive({ name: '', description: '' })

async function load(): Promise<void> {
  loading.value = true
  try {
    kbs.value = await kbApi.list()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '加载失败')
  } finally {
    loading.value = false
  }
}

function openCreate(): void {
  editing.value = null
  form.name = ''
  form.description = ''
  dialog.value = true
}

function openEdit(kb: Kb): void {
  editing.value = kb
  form.name = kb.name
  form.description = kb.description
  dialog.value = true
}

async function save(): Promise<void> {
  if (!form.name.trim()) {
    ElMessage.warning('请输入知识库名称')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await kbApi.update(editing.value.id, { name: form.name.trim(), description: form.description })
      ElMessage.success('已更新')
    } else {
      await kbApi.create(form.name.trim(), form.description)
      ElMessage.success('创建成功')
    }
    dialog.value = false
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '保存失败')
  } finally {
    saving.value = false
  }
}

async function remove(kb: Kb): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `删除知识库「${kb.name}」会同时删除其文档、切片与相关会话，且不可恢复。`,
      '危险操作',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  try {
    await kbApi.remove(kb.id)
    ElMessage.success('已删除')
    await load()
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : '删除失败')
  }
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '-' : date.toLocaleString('zh-CN', { hour12: false })
}

onMounted(load)
</script>

<template>
  <div>
    <div class="card" style="margin-bottom: 16px">
      <div class="card-body" style="display: flex; gap: 12px; align-items: center; flex-wrap: wrap">
        <el-input
          v-model="keyword"
          placeholder="搜索知识库名称"
          :prefix-icon="Search"
          style="width: 280px"
          clearable
        />
        <div style="flex: 1" />
        <el-button type="primary" :icon="Plus" @click="openCreate">新建知识库</el-button>
      </div>
    </div>

    <div class="card">
      <el-table v-loading="loading" :data="kbs.filter((k) => !keyword || k.name.includes(keyword))" style="width: 100%">
        <el-table-column label="知识库" min-width="240">
          <template #default="{ row }">
            <div style="font-weight: 600">{{ row.name }}</div>
            <div style="color: var(--muted); font-size: 12px; margin-top: 2px">
              {{ row.description || '暂无描述' }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="文档" width="90">
          <template #default="{ row }">{{ row.document_count }}</template>
        </el-table-column>
        <el-table-column label="片段" width="90">
          <template #default="{ row }">{{ row.chunk_count }}</template>
        </el-table-column>
        <el-table-column label="向量模型" width="180">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.embedding_model }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="router.push(`/admin/kbs/${row.id}`)">进入</el-button>
            <el-button link @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <div class="empty">还没有知识库，点击右上角「新建知识库」开始</div>
        </template>
      </el-table>
    </div>

    <el-dialog v-model="dialog" :title="editing ? '编辑知识库' : '新建知识库'" width="480px">
      <el-form label-position="top">
        <el-form-item label="名称">
          <el-input v-model="form.name" maxlength="64" show-word-limit placeholder="例如：服饰商品知识库" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            maxlength="500"
            show-word-limit
            placeholder="简要说明知识库覆盖的商品范围"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
