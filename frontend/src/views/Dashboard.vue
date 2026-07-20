<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Card, Statistic, Row, Col, Spin, message, Select, Tag, Empty } from 'ant-design-vue'
import KlineChart from '../components/KlineChart.vue'
import { getRegimeStates, getIndexKlines } from '../api/marketRegime'
import type { RegimeResponse, KlineResponse } from '../types/market'

const activeMarket = ref<'A' | 'HK'>('A')
const loading = ref(false)
const regime = ref<RegimeResponse | null>(null)
const klines = ref<KlineResponse | null>(null)

const stateLabelMap: Record<number, { text: string; color: string }> = {
  0: { text: '平静', color: 'green' },
  1: { text: '动荡', color: 'red' },
}

const latestState = computed(() => {
  if (!regime.value?.states?.length) return null
  return regime.value.states[regime.value.states.length - 1]
})

const stateLabel = computed(() => {
  if (!latestState.value) return '-'
  return stateLabelMap[latestState.value.state_label]?.text || `状态${latestState.value.state_label}`
})

const stateColor = computed(() => {
  if (!latestState.value) return ''
  return stateLabelMap[latestState.value.state_label]?.color || ''
})

const klineRange = computed(() => {
  if (!klines.value?.data?.length) return null
  const d = klines.value.data
  return { from: d[0].trade_date, to: d[d.length - 1].trade_date }
})

const bands = computed(() => {
  if (!regime.value?.states || !klines.value?.data) return []
  const dates = klines.value.data.map((k) => k.trade_date)
  const dateSet = new Set(dates)
  const states = regime.value.states

  const result: { from: string; to: string; state: number }[] = []
  let i = 0
  while (i < states.length) {
    if (!dateSet.has(states[i].trade_date)) {
      i++
      continue
    }
    const s = states[i]
    let k = i + 1
    while (
      k < states.length &&
      k - i < dates.length &&
      states[k].state_label === s.state_label &&
      dateSet.has(states[k].trade_date)
    ) {
      k++
    }
    const lastIdx = dates.indexOf(states[k - 1].trade_date)
    const firstIdx = dates.indexOf(s.trade_date)
    if (firstIdx !== -1 && lastIdx !== -1) {
      result.push({
        from: dates[firstIdx],
        to: dates[lastIdx],
        state: s.state_label,
      })
    }
    i = k
  }
  return result
})

const bandsCoverage = computed(() => {
  if (!klines.value?.data || !bands.value.length) return 0
  const total = klines.value.data.length
  const covered = bands.value.reduce((sum, b) => {
    const fromIdx = klines.value!.data.findIndex((k) => k.trade_date === b.from)
    const toIdx = klines.value!.data.findIndex((k) => k.trade_date === b.to)
    if (fromIdx === -1 || toIdx === -1) return sum
    return sum + (toIdx - fromIdx + 1)
  }, 0)
  return total > 0 ? Math.round((covered / total) * 100) : 0
})

function handleMarketChange(v: any) {
  activeMarket.value = v
  loadData()
}

async function loadData() {
  loading.value = true
  try {
    const [r, k] = await Promise.all([
      getRegimeStates(activeMarket.value).catch(() => null),
      getIndexKlines(activeMarket.value === 'A' ? '000001' : 'HSI').catch(() => null),
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
    <Row :gutter="[16, 16]">
      <Col :span="24">
        <Card>
          <template #title>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>市场状态仪表盘</span>
              <Select :value="activeMarket" @change="handleMarketChange" style="width:120px">
                <Select.Option value="A">A股</Select.Option>
                <Select.Option value="HK">港股</Select.Option>
              </Select>
            </div>
          </template>

          <Row :gutter="16" v-if="latestState">
            <Col :span="6">
              <Statistic title="当前状态">
                <template #formatter>
                  <Tag :color="stateColor">{{ stateLabel }}</Tag>
                </template>
              </Statistic>
            </Col>
            <Col :span="6">
              <Statistic
                title="状态概率"
                :value="(latestState.state_prob * 100).toFixed(1)"
                suffix="%"
              />
            </Col>
            <Col :span="6">
              <Statistic title="训练时间" :value="regime?.trained_at || '-'" />
            </Col>
            <Col :span="6">
              <Statistic title="算法" :value="regime?.algorithm || '-'" />
            </Col>
          </Row>

          <Empty
            v-else-if="!loading"
            description="暂无市场状态数据（需先训练 market_regime 模型）"
          />
        </Card>
      </Col>

      <Col :span="24" v-if="klines">
        <Card>
          <template #title>
            <div style="display:flex;justify-content:space-between;align-items:center">
              <span>K 线图 + 市场状态背景</span>
              <span style="font-size:12px;color:#999">
                K 线范围：{{ klineRange?.from }} ~ {{ klineRange?.to }}
                <Tag v-if="bandsCoverage > 0" color="blue" style="margin-left:8px">
                  状态覆盖 {{ bandsCoverage }}%
                </Tag>
                <Tag v-else color="orange" style="margin-left:8px">
                  状态与 K 线日期未重叠
                </Tag>
              </span>
            </div>
          </template>
          <KlineChart :klines="klines.data" :bands="bands" />
        </Card>
      </Col>
      <Col :span="24" v-else-if="!loading">
        <Card title="K 线图">
          <Empty description="暂无 K 线数据" />
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
