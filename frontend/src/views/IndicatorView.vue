<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { Card, Select, Switch, Row, Col, Spin, message } from 'ant-design-vue'
import IndicatorChart from '../components/IndicatorChart.vue'
import { getAllIndicators, type IndicatorData } from '../api/indicators'

const props = defineProps<{
  defaultCode?: string
  defaultAssetType?: string
}>()

const loading = ref(false)
const data = ref<IndicatorData[]>([])
const assetType = ref(props.defaultAssetType || 'etf')
const code = ref(props.defaultCode || '510300')
const adjustMode = ref('forward')
const showMACD = ref(true)
const showRSI = ref(false)
const showBoll = ref(true)

const assetOptions = [
  { label: 'ETF', value: 'etf' },
  { label: '指数', value: 'index' },
  { label: '股票', value: 'stock' },
]

const adjustOptions = [
  { label: '前复权', value: 'forward' },
  { label: '后复权', value: 'backward' },
  { label: '不复权', value: 'none' },
]

async function loadData() {
  loading.value = true
  try {
    const resp = await getAllIndicators(assetType.value, code.value, 120, adjustMode.value)
    data.value = resp.data || []
  } catch (e: any) {
    message.error(e?.response?.data?.detail || '加载指标数据失败')
    data.value = []
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadData()
})

watch([assetType, code, adjustMode], loadData)
</script>

<template>
  <Card title="技术指标分析">
    <template #extra>
      <Row :gutter="8" align="middle">
        <Col>
          <Select :value="assetType" @change="(v: string) => assetType = v" :options="assetOptions" style="width:90px" size="small" />
        </Col>
        <Col>
          <a-input v-model:value="code" placeholder="代码" style="width:100px" size="small" />
        </Col>
        <Col>
          <Select :value="adjustMode" @change="(v: string) => adjustMode = v" :options="adjustOptions" style="width:100px" size="small" />
        </Col>
      </Row>
    </template>

    <Row :gutter="16" style="margin-bottom: 12px">
      <Col :span="8">
        <span style="margin-right:8px">MACD</span>
        <Switch v-model:checked="showMACD" size="small" />
      </Col>
      <Col :span="8">
        <span style="margin-right:8px">RSI</span>
        <Switch v-model:checked="showRSI" size="small" />
      </Col>
      <Col :span="8">
        <span style="margin-right:8px">BOLL</span>
        <Switch v-model:checked="showBoll" size="small" />
      </Col>
    </Row>

    <Spin :spinning="loading">
      <IndicatorChart
        :data="data"
        :show-m-a-c-d="showMACD"
        :show-r-s-i="showRSI"
        :show-boll="showBoll"
      />
    </Spin>
  </Card>
</template>
