<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { login } from '../api/auth'
import { setUser } from '../stores/auth'

const router = useRouter()
const loading = ref(false)
const formData = ref({ username: '', password: '' })

async function handleLogin() {
  if (!formData.value.username || !formData.value.password) {
    message.error('请填写用户名和密码')
    return
  }
  loading.value = true
  try {
    const data = await login(formData.value.username, formData.value.password)
    message.success('登录成功')
    router.push('/#/')
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <a-card title="QuantPilot 登录" style="width: 400px; margin: 0 auto">
      <a-form layout="vertical" @finish="handleLogin">
        <a-form-item label="用户名" required>
          <a-input v-model:value="formData.username" placeholder="请输入用户名" size="large" />
        </a-form-item>
        <a-form-item label="密码" required>
          <a-input-password v-model:value="formData.password" placeholder="请输入密码" size="large" />
        </a-form-item>
        <a-form-item>
          <a-button type="primary" html-type="submit" :loading="loading" block size="large">登录</a-button>
        </a-form-item>
        <div class="register-link">
          还没有账号？<a href="/#/register">立即注册</a>
        </div>
      </a-form>
    </a-card>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background: #f0f2f5;
}
.register-link {
  text-align: center;
  color: #666;
}
</style>
