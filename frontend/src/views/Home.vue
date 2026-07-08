<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { authState, restoreSession } from '../stores/auth'
import { logout } from '../api/auth'

const router = useRouter()

onMounted(() => {
  restoreSession()
})

function handleLogout() {
  logout().finally(() => {
    router.push('/#/login')
  })
}
</script>

<template>
  <a-layout style="min-height: 100vh">
    <a-layout-header class="header">
      <div class="logo">QuantPilot</div>
      <div class="user-info">
        <span>欢迎，{{ authState.user?.username }}</span>
        <a-button type="link" @click="handleLogout">退出</a-button>
      </div>
    </a-layout-header>
    <a-layout-content>
      <a-menu
        mode="horizontal"
        :selected-keys="[router.currentRoute.value.name as string]"
        @click="(e) => router.push(`/#/${e.key === 'Dashboard' ? '' : e.key.toLowerCase()}`)"
      >
        <a-menu-item key="Dashboard">市场状态</a-menu-item>
        <a-menu-item key="Etf">ETF 数据</a-menu-item>
      </a-menu>
      <div class="content">
        <router-view />
      </div>
    </a-layout-content>
  </a-layout>
</template>

<style scoped>
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #001529;
  color: white;
  padding: 0 24px;
}
.logo {
  font-size: 18px;
  font-weight: bold;
}
.user-info {
  display: flex;
  align-items: center;
  gap: 12px;
  color: white;
}
.content {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
}
</style>
