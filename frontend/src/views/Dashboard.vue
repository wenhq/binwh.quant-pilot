<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Tabs, Card, Statistic, Row, Col, Spin, message, Select } from 'ant-design-vue'
import KlineChart from '../components/KlineChart.vue'
import { getRegimeStates, getIndexKlines } from '../api/marketRegime'
import type { RegimeResponse, KlineResponse } from '../types/market'

const { TabPane } = Tabs
const activeMarket = ref<'A' | 'HK'>('A')
const loading = ref(false)
const regime = ref<RegimeResponse | null>(null)
const klines = ref<KlineResponse | null>(null)

const stateLabelMap: Record<number, string> = {
  0: '平静',
  1: '动荡',
}

const bands = computed(() => {
  if (!regime.value?.states || !klines.value?.data) return []
  const dates = klines.value.data.map((k) => k.trade_date)
  const states = regime.value.states
  const result: { from: string; to: string; state: number }[] = []
  let i = 0
  while (i < states.length) {
    const s = states[i]
    const j = dates.indexOf(s.trade_date)
    if (j === -1) { i++; continue }
    let k = i + 1
    while (k < states.length && j + (k - i) < dates.length) {
      if (states[k].state_label !== s.state_label) break
      k++
    }
    result.push({
      from: dates[j],
      to: dates[j + (k - i - 1)],
      state: s.state_label,
    })
    i = k
  }
  return result
})

async function loadData() {
  loading.value = true
  try {
    const [r, k] = await Promise.all([
      getRegimeStates(activeMarket.value),
      getIndexKlines(activeMarket.value === 'A' ? '000001' : 'HSI'),
    ])
    regime.value = r
    klines.value = k
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '加载数据失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <Spin :spinning="loading">
    <Row gutter={[16, 16]}>
      <Col :span="24">
        <Card>
          <template #title>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>市场状态仪表盘</span>
              <Select :value="activeMarket" @change="(v: 'A' | 'HK') => { activeMarket = v; loadData() }" style="width:120px">
                <Select.Option value="A">A股</Select.Option>
                <Select.Option value="HK">港股</Select.Option>
              </Select>
            </div>
          </template>
          <Row gutter={16} v-if="regime">
            <Col :span="6">
              <Statistic title="当前状态" :value="stateLabelMap[regime.states[regime.states.length-1].state_label] || '-'" />
            </Col>
            <Col :span="6">
              <Statistic title="状态概率" :value="(regime.states[regime.states.length-1].state_prob * 100).toFixed(1)" suffix="%" />
            </Col>
            <Col :span="6">
              <Statistic title="训练时间" :value="regime.trained_at" />
            </Col>
            <Col :span="6">
              <Statistic title="算法" :value="regime.algorithm" />
            </Col>
          </Row>
        </Card>
      </Col>
      <Col :span="24}>
        <Card title="K 线图 + 市场状态背景" v-if="klines">
          <KlineChart :klines="klines.data" :bands="bands" />
        </Card>
      </Col>
    </Row>
  </Spin>
</template>

<style scoped>
:deep(.ant-card) {
  margin-bottom: 16px;
}
</style>
