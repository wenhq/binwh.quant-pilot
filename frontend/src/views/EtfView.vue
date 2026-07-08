<script setup lang="ts">
import { h, ref, onMounted } from 'vue'
import { Table, Spin, message } from 'ant-design-vue'
import KlineChart from '../components/KlineChart.vue'
import { getEtfList, getEtfKlines } from '../api/etf'
import type { Kline } from '../types/market'

const etfs = ref<any[]>([])
const loading = ref(false)
const expandedKeys = ref<Set<number>>(new Set())
const expandedKlines = ref<Map<number, Kline[]>>(new Map())
const expandedLoading = ref<Set<number>>(new Set())

async function loadEtfs() {
  loading.value = true
  try {
    const { data } = await getEtfList()
    etfs.value = data.etfs || []
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '加载 ETF 列表失败')
  } finally {
    loading.value = false
  }
}

async function handleExpand(etfCode: string, etfIndex: number) {
  if (expandedKeys.value.has(etfIndex)) {
    expandedKeys.value.delete(etfIndex)
    expandedKeys.value = new Set(expandedKeys.value)
    return
  }
  expandedKeys.value.add(etfIndex)
  expandedKeys.value = new Set(expandedKeys.value)
  expandedLoading.value.add(etfIndex)
  try {
    const { data } = await getEtfKlines(etfCode)
    expandedKlines.value.set(etfIndex, data.data || [])
  } catch {
    message.error(`加载 ${etfCode} K 线失败`)
    expandedKeys.value.delete(etfIndex)
    expandedKeys.value = new Set(expandedKeys.value)
  } finally {
    expandedLoading.value.delete(etfIndex)
  }
}

onMounted(() => {
  loadEtfs()
})

const columns = [
  { title: '代码', dataIndex: 'code', key: 'code' },
  { title: '名称', dataIndex: 'name', key: 'name' },
  { title: '跟踪标的', dataIndex: 'tracks', key: 'tracks' },
  { title: '最新收盘', dataIndex: 'latest_close', key: 'latest_close' },
  { title: '涨跌幅 (%)', dataIndex: 'change_pct', key: 'change_pct' },
]
</script>

<template>
  <Spin :spinning="loading">
    <Table
      :columns="columns"
      :data-source="etfs"
      :pagination="{ pageSize: 20 }"
      size="middle"
      bordered
      expandable={{
        expandedRowRender: (record: any) => {
          if (expandedLoading.value.has(record.code)) {
            return h('div', { style: { padding: '24px', textAlign: 'center' } }, [
              h(Spin)
            ])
          }
          const klines = expandedKlines.value.get(record.code) || []
          return h('div', { style: { padding: '16px 0' } }, [
            h(KlineChart, { klines })
          ])
        },
        onExpand: (expanded: boolean, record: any) => handleExpand(record.code, record.code),
      }}
    />
  </Spin>
</template>

<style scoped>
:deep(.ant-table-expanded-row > td) {
  padding: 16px 24px;
}
</style>

