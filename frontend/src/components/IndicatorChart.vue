<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import {
  createChart, ColorType, CandlestickSeries, HistogramSeries, LineSeries, createSeriesMarkers,
} from 'lightweight-charts'
import type { IndicatorData } from '../api/indicators'

const props = defineProps<{
  data: IndicatorData[]
  showMACD?: boolean
  showRSI?: boolean
  showBoll?: boolean
}>()

const container = ref<HTMLDivElement | null>(null)
const macdContainer = ref<HTMLDivElement | null>(null)
const rsiContainer = ref<HTMLDivElement | null>(null)
let mainChart: ReturnType<typeof createChart> | null = null
let macdChart: ReturnType<typeof createChart> | null = null
let rsiChart: ReturnType<typeof createChart> | null = null
let ro: ResizeObserver | null = null

function renderMain() {
  if (!container.value || props.data.length === 0) return
  mainChart?.remove()

  mainChart = createChart(container.value, {
    width: container.value.clientWidth,
    height: 420,
    layout: { background: { color: '#ffffff' }, textColor: '#333' },
    grid: { vertLines: { color: '#f0f0f0' }, horzLines: { color: '#f0f0f0' } },
    crosshair: { mode: 1 },
    timeScale: { timeVisible: true, secondsVisible: false },
  })

  const candle = mainChart.addSeries(CandlestickSeries, {
    upColor: '#26a69a', downColor: '#ef5350',
    borderUpColor: '#26a69a', borderDownColor: '#ef5350',
    wickUpColor: '#26a69a', wickDownColor: '#ef5350',
  })
  candle.setData(
    props.data.map((d) => ({
      time: d.trade_date, open: d.open, high: d.high, low: d.low, close: d.close,
    }))
  )

  const volume = mainChart.addSeries(HistogramSeries, {
    color: 'rgba(100,181,246,0.3)',
    priceFormat: { type: 'volume' },
    priceScaleId: 'vol',
  })
  volume.setData(
    props.data.map((d) => ({ time: d.trade_date, value: d.volume, color: 'rgba(100,181,246,0.3)' }))
  )
  volume.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })

  if (props.showBoll) {
    const upper = mainChart.addSeries(LineSeries, { color: 'rgba(255,152,0,0.6)', lineWidth: 1 })
    const mid = mainChart.addSeries(LineSeries, { color: 'rgba(156,39,176,0.6)', lineWidth: 1, lineStyle: 2 })
    const lower = mainChart.addSeries(LineSeries, { color: 'rgba(255,152,0,0.6)', lineWidth: 1 })

    upper.setData(props.data.filter(d => d.boll_upper != null).map(d => ({ time: d.trade_date, value: d.boll_upper! })))
    mid.setData(props.data.filter(d => d.boll_mid != null).map(d => ({ time: d.trade_date, value: d.boll_mid! })))
    lower.setData(props.data.filter(d => d.boll_lower != null).map(d => ({ time: d.trade_date, value: d.boll_lower! })))
  }

  const markers = props.data.map((d) => {
    if (d.close > d.open) {
      return { time: d.trade_date, position: 'belowBar' as const, shape: 'arrowUp' as const, color: '#26a69a' }
    } else if (d.close < d.open) {
      return { time: d.trade_date, position: 'aboveBar' as const, shape: 'arrowDown' as const, color: '#ef5350' }
    }
    return null
  }).filter(Boolean)
  createSeriesMarkers(candle, markers as any[])
}

function renderMACD() {
  if (!macdContainer.value || !props.showMACD || props.data.length === 0) return
  macdChart?.remove()

  macdChart = createChart(macdContainer.value, {
    width: macdContainer.value.clientWidth,
    height: 150,
    layout: { background: { color: '#fafafa' }, textColor: '#666' },
    grid: { vertLines: { color: '#f0f0f0' }, horzLines: { color: '#f0f0f0' } },
    timeScale: { timeVisible: true, secondsVisible: false },
  })

  const hist = macdChart.addSeries(HistogramSeries, {})
  const histData = []
  for (const d of props.data) {
    if (d.macd_hist != null) {
      histData.push({
        time: d.trade_date, value: d.macd_hist,
        color: d.macd_hist >= 0 ? 'rgba(38,166,154,0.6)' : 'rgba(239,83,80,0.6)',
      })
    }
  }
  hist.setData(histData)

  const dif = macdChart.addSeries(LineSeries, { color: '#2196f3', lineWidth: 1 })
  const dea = macdChart.addSeries(LineSeries, { color: '#ff9800', lineWidth: 1 })
  dif.setData(props.data.filter(d => d.macd_dif != null).map(d => ({ time: d.trade_date, value: d.macd_dif! })))
  dea.setData(props.data.filter(d => d.macd_dea != null).map(d => ({ time: d.trade_date, value: d.macd_dea! })))
}

function renderRSI() {
  if (!rsiContainer.value || !props.showRSI || props.data.length === 0) return
  rsiChart?.remove()

  rsiChart = createChart(rsiContainer.value, {
    width: rsiContainer.value.clientWidth,
    height: 120,
    layout: { background: { color: '#fafafa' }, textColor: '#666' },
    grid: { vertLines: { color: '#f0f0f0' }, horzLines: { color: '#f0f0f0' } },
    timeScale: { timeVisible: true, secondsVisible: false },
  })

  const rsi = rsiChart.addSeries(LineSeries, { color: '#9c27b0', lineWidth: 2 })
  rsi.setData(props.data.filter(d => d.rsi != null).map(d => ({ time: d.trade_date, value: d.rsi! })))

  const upper = rsiChart.addSeries(LineSeries, { color: 'rgba(239,83,80,0.3)', lineWidth: 1, lineStyle: 2 })
  const lower = rsiChart.addSeries(LineSeries, { color: 'rgba(38,166,154,0.3)', lineWidth: 1, lineStyle: 2 })
  const dates = props.data.map(d => d.trade_date)
  upper.setData(dates.map(t => ({ time: t, value: 70 })))
  lower.setData(dates.map(t => ({ time: t, value: 30 })))
}

function renderAll() {
  renderMain()
  renderMACD()
  renderRSI()
}

function handleResize() {
  if (container.value && mainChart) {
    mainChart.applyOptions({ width: container.value.clientWidth })
  }
  if (macdContainer.value && macdChart) {
    macdChart.applyOptions({ width: macdContainer.value.clientWidth })
  }
  if (rsiContainer.value && rsiChart) {
    rsiChart.applyOptions({ width: rsiContainer.value.clientWidth })
  }
}

onMounted(() => {
  renderAll()
  ro = new ResizeObserver(handleResize)
  if (container.value) ro.observe(container.value)
})

onUnmounted(() => {
  ro?.disconnect()
  mainChart?.remove()
  macdChart?.remove()
  rsiChart?.remove()
})

watch(() => props.data, renderAll, { deep: true })
watch(() => [props.showMACD, props.showRSI, props.showBoll], renderAll)
</script>

<template>
  <div class="indicator-chart">
    <div ref="container" class="main-chart"></div>
    <div v-if="showMACD" ref="macdContainer" class="sub-chart"></div>
    <div v-if="showRSI" ref="rsiContainer" class="sub-chart"></div>
  </div>
</template>

<style scoped>
.indicator-chart {
  width: 100%;
}
.main-chart {
  width: 100%;
  height: 420px;
  border: 1px solid #e8e8e8;
  border-radius: 4px;
}
.sub-chart {
  width: 100%;
  margin-top: 8px;
  border: 1px solid #e8e8e8;
  border-radius: 4px;
}
</style>
