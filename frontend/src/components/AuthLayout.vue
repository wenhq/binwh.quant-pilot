<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { authState, restoreSession } from '../stores/auth'

const router = useRouter()
const route = useRoute()
const isLoggedIn = computed(() => !!authState.user)

onMounted(() => {
  restoreSession()
})

if (isLoggedIn.value && route.path === '/login') {
  router.push('/#/')
}
</script>

<template>
  <div v-if="!authState.initialized" class="loading">
    <a-spin size="large" />
  </div>
  <router-view v-else />
</template>

<style scoped>
.loading {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
}
</style>
