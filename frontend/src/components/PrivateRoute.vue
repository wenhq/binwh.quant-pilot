<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Layout, Button, message } from 'ant-design-vue'
import {
  DashboardOutlined,
  FundOutlined,
  LineChartOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from '@ant-design/icons-vue'
import { authState, restoreSession } from '../stores/auth'
import { logout } from '../api/auth'

const { Header, Content } = Layout
const router = useRouter()
const route = useRoute()

const collapsed = ref(false)

const isLoggedIn = computed(() => !!authState.user)

const selectedKeys = computed(() => {
  const name = route.name
  if (typeof name === 'string') {
    if (name === 'Dashboard') return ['dashboard']
    if (name === 'Etf') return ['etf']
    if (name === 'Indicators') return ['indicators']
  }
  return ['dashboard']
})

onMounted(() => {
  restoreSession()
})

async function handleLogout() {
  await logout()
  message.success('已退出登录')
  router.push('/#/login')
}

function handleMenuClick(e: any) {
  if (e.key === 'dashboard') router.push('/')
  else if (e.key === 'etf') router.push('/etf')
  else if (e.key === 'indicators') router.push('/indicators')
}
</script>

<template>
  <template v-if="!authState.initialized">
    <a-spin size="large" />
  </template>
  <template v-else-if="isLoggedIn">
    <Layout style="min-height: 100vh">
      <a-layout-sider
        v-model:collapsed="collapsed"
        collapsible
        :trigger="null"
        style="background: #001529"
      >
        <div class="logo">
          <span v-if="!collapsed">QuantPilot</span>
          <span v-else>QP</span>
        </div>
        <a-menu
          theme="dark"
          mode="inline"
          :selected-keys="selectedKeys"
          @click="handleMenuClick"
        >
          <a-menu-item key="dashboard">
            <DashboardOutlined />
            <span>市场状态</span>
          </a-menu-item>
          <a-menu-item key="etf">
            <FundOutlined />
            <span>ETF 数据</span>
          </a-menu-item>
          <a-menu-item key="indicators">
            <LineChartOutlined />
            <span>指标分析</span>
          </a-menu-item>
        </a-menu>
      </a-layout-sider>

      <Layout>
        <Header class="header">
          <button class="collapse-btn" @click="collapsed = !collapsed">
            <MenuFoldOutlined v-if="!collapsed" />
            <MenuUnfoldOutlined v-else />
          </button>
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
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  font-size: 18px;
  font-weight: bold;
  background: rgba(255, 255, 255, 0.08);
  margin: 8px;
  border-radius: 4px;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #fff;
  padding: 0 16px;
  border-bottom: 1px solid #e8e8e8;
  box-shadow: 0 1px 4px rgba(0, 21, 41, 0.08);
}
.collapse-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 18px;
  padding: 8px;
  color: #333;
}
.collapse-btn:hover {
  color: #1890ff;
}
.user-info {
  display: flex;
  align-items: center;
  gap: 12px;
  color: #333;
}
.content {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
  width: 100%;
}
</style>
