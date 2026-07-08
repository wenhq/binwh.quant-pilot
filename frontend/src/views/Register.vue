<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import { register } from '../api/auth'

const router = useRouter()
const loading = ref(false)
const formData = ref({ username: '', password: '', confirmPassword: '' })

async function handleRegister() {
  if (!formData.value.username || !formData.value.password) {
    message.error('请填写用户名和密码')
    return
  }
  if (formData.value.password !== formData.value.confirmPassword) {
    message.error('两次密码不一致')
    return
  }
  loading.value = true
  try {
    await register(formData.value.username, formData.value.password)
    message.success('注册成功，请登录')
    router.push('/#/login')
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '注册失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="register-page">
    <a-card title="QuantPilot 注册" style="width: 400px; margin: 0 auto">
      <a-form layout="vertical" @finish="handleRegister">
        <a-form-item label="用户名" required>
          <a-input v-model:value="formData.username" placeholder="请输入用户名" size="large" />
        </a-form-item>
        <a-form-item label="密码" required>
          <a-input-password v-model:value="formData.password" placeholder="请输入密码" size="large" />
        </a-form-item>
        <a-form-item label="确认密码" required>
          <a-input-password v-model:value="formData.confirmPassword" placeholder="请再次输入密码" size="large" />
        </a-form-item>
        <a-form-item>
          <a-button type="primary" html-type="submit" :loading="loading" block size="large">注册</a-button>
        </a-form-item>
        <div class="login-link">
          已有账号？<a href="/#/login">立即登录</a>
        </div>
      </a-form>
    </a-card>
  </div>
</template>

<style scoped>
.register-page {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background: #f0f2f5;
}
.login-link {
  text-align: center;
  color: #666;
}
</style>
