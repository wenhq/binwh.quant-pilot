<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Layout, Menu, Button, message } from 'ant-design-vue'
import { authState, restoreSession } from '../stores/auth'
import { logout } from '../api/auth'

const { Header, Content } = Layout
const router = useRouter()
const route = useRoute()
const isLoggedIn = computed(() => !!authState.user)

onMounted(() => {
  restoreSession()
})

async function handleLogout() {
  await logout()
  message.success('已退出登录')
  router.push('/#/login')
}
</script>

<template>
  <template v-if="!authState.initialized">
    <a-spin size="large" />
  </template>
  <template v-else-if="isLoggedIn">
    <Layout>
      <Header>
        <div class="logo">QuantPilot</div>
        <a-menu
          mode="horizontal"
          :selected-keys="[route.name as string]"
          style="background: transparent; line-height: 64px; border-bottom: none; flex: 1"
          @click="(e) => router.push(`/#/${e.key === 'Dashboard' ? '' : e.key.toLowerCase()}`)"
        >
          <a-menu-item key="Dashboard">市场状态</a-menu-item>
          <a-menu-item key="Etf">ETF 数据</a-menu-item>
          <a-menu-item key="Indicators">技术指标</a-menu-item>
        </a-menu>
        <div class="user-info">
          <span>欢迎，{{ authState.user?.username }}</span>
          <a-button type="link" @click="handleLogout">退出</a-button>
        </div>
      </Header>
      <Content>
        <div class="content">
          <router-view />
        </div>
      </Content>
    </Layout>
  </template>
  <template v-else>
    <a-result status="403" title="未授权" sub-title="请先登录">
      <template #extra>
        <a-button type="primary" @click="router.push('/#/login')">去登录</a-button>
      </template>
    </a-result>
  </template>
</template>

<style scoped>
.logo {
  font-size: 18px;
  font-weight: bold;
  color: white;
  margin-right: 24px;
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
