<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import {
  createChart, ColorType, IChartApi,
  type CandlestickData, type LineData, type HistogramData, type SeriesMarker,
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
let mainChart: IChartApi | null = null
let macdChart: IChartApi | null = null
let rsiChart: IChartApi | null = null
let ro: ResizeObserver | null = null

function renderMain() {
  if (!container.value || props.data.length === 0) return
  mainChart?.remove()

  mainChart = createChart(container.value, {
    width: container.value.clientWidth,
    height: 420,
    layout: { background: { type: ColorType.Solid, color: '#ffffff' }, textColor: '#333' },
    grid: { vertLines: { color: '#f0f0f0' }, horzLines: { color: '#f0f0f0' } },
    crosshair: { mode: 1 },
    timeScale: { timeVisible: true, secondsVisible: false },
  })

  const candle = mainChart.addCandlestickSeries({
    upColor: '#26a69a', downColor: '#ef5350',
    borderUpColor: '#26a69a', borderDownColor: '#ef5350',
    wickUpColor: '#26a69a', wickDownColor: '#ef5350',
  })
  candle.setData(
    props.data.map((d) => ({
      time: d.trade_date, open: d.open, high: d.high, low: d.low, close: d.close,
    }))
  )

  const volume = mainChart.addHistogramSeries({
    color: 'rgba(100,181,246,0.3)',
    priceFormat: { type: 'volume' },
    priceScaleId: 'vol',
  })
  volume.setData(
    props.data.map((d) => ({ time: d.trade_date, value: d.volume, color: 'rgba(100,181,246,0.3)' }))
  )
  volume.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })

  if (props.showBoll) {
    const upper = mainChart.addLineSeries({ color: 'rgba(255,152,0,0.6)', lineWidth: 1 })
    const mid = mainChart.addLineSeries({ color: 'rgba(156,39,176,0.6)', lineWidth: 1, lineStyle: 2 })
    const lower = mainChart.addLineSeries({ color: 'rgba(255,152,0,0.6)', lineWidth: 1 })

    upper.setData(props.data.filter(d => d.boll_upper != null).map(d => ({ time: d.trade_date, value: d.boll_upper! })) as LineData[])
    mid.setData(props.data.filter(d => d.boll_mid != null).map(d => ({ time: d.trade_date, value: d.boll_mid! })) as LineData[])
    lower.setData(props.data.filter(d => d.boll_lower != null).map(d => ({ time: d.trade_date, value: d.boll_lower! })) as LineData[])
  }

  const markers: SeriesMarker<Time>[] = []
  for (const d of props.data) {
    if (d.close > d.open) {
      markers.push({ time: d.trade_date as Time, position: 'belowBar', shape: 'arrowUp', color: '#26a69a' })
    } else if (d.close < d.open) {
      markers.push({ time: d.trade_date as Time, position: 'aboveBar', shape: 'arrowDown', color: '#ef5350' })
    }
  }
  candle.setMarkers(markers)
}

function renderMACD() {
  if (!macdContainer.value || !props.showMACD || props.data.length === 0) return
  macdChart?.remove()

  macdChart = createChart(macdContainer.value, {
    width: macdContainer.value.clientWidth,
    height: 150,
    layout: { background: { type: ColorType.Solid, color: '#fafafa' }, textColor: '#666' },
    grid: { vertLines: { color: '#f0f0f0' }, horzLines: { color: '#f0f0f0' } },
    timeScale: { timeVisible: true, secondsVisible: false },
  })

  const hist = macdChart.addHistogramSeries({})
  const histData: HistogramData[] = []
  for (const d of props.data) {
    if (d.macd_hist != null) {
      histData.push({
        time: d.trade_date, value: d.macd_hist,
        color: d.macd_hist >= 0 ? 'rgba(38,166,154,0.6)' : 'rgba(239,83,80,0.6)',
      })
    }
  }
  hist.setData(histData)

  const dif = macdChart.addLineSeries({ color: '#2196f3', lineWidth: 1 })
  const dea = macdChart.addLineSeries({ color: '#ff9800', lineWidth: 1 })
  dif.setData(props.data.filter(d => d.macd_dif != null).map(d => ({ time: d.trade_date, value: d.macd_dif! })) as LineData[])
  dea.setData(props.data.filter(d => d.macd_dea != null).map(d => ({ time: d.trade_date, value: d.macd_dea! })) as LineData[])
}

function renderRSI() {
  if (!rsiContainer.value || !props.showRSI || props.data.length === 0) return
  rsiChart?.remove()

  rsiChart = createChart(rsiContainer.value, {
    width: rsiContainer.value.clientWidth,
    height: 120,
    layout: { background: { type: ColorType.Solid, color: '#fafafa' }, textColor: '#666' },
    grid: { vertLines: { color: '#f0f0f0' }, horzLines: { color: '#f0f0f0' } },
    timeScale: { timeVisible: true, secondsVisible: false },
  })

  const rsi = rsiChart.addLineSeries({ color: '#9c27b0', lineWidth: 2 })
  rsi.setData(props.data.filter(d => d.rsi != null).map(d => ({ time: d.trade_date, value: d.rsi! })) as LineData[])

  const upper = rsiChart.addLineSeries({ color: 'rgba(239,83,80,0.3)', lineWidth: 1, lineStyle: 2 })
  const lower = rsiChart.addLineSeries({ color: 'rgba(38,166,154,0.3)', lineWidth: 1, lineStyle: 2 })
  const dates = props.data.map(d => d.trade_date)
  upper.setData(dates.map(t => ({ time: t, value: 70 })) as LineData[])
  lower.setData(dates.map(t => ({ time: t, value: 30 })) as LineData[])
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
