<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import { createChart, ColorType, IChartApi, ISeriesApi, CandlestickData, HistogramData } from 'lightweight-charts'
import type { Kline } from '../types/market'

const props = defineProps<{
  klines: Kline[]
  bands?: { from: string; to: string; state: number }[]
}>()

const container = ref<HTMLDivElement | null>(null)
const chart = ref<IChartApi | null>(null)
const candleSeries = ref<ISeriesApi<'Candlestick'> | null>(null)

const STATE_COLORS: Record<number, string> = {
  0: 'rgba(0, 200, 0, 0.12)',
  1: 'rgba(255, 0, 0, 0.12)',
}

function buildBands(): HistogramData[] {
  if (!props.bands || props.bands.length === 0) return []
  const stateByDate = new Map<string, number>()
  for (const b of props.bands) {
    stateByDate.set(b.from, b.state)
    stateByDate.set(b.to, b.state)
  }
  const result: HistogramData[] = []
  for (const k of props.klines) {
    const state = stateByDate.get(k.trade_date)
    if (state !== undefined) {
      result.push({
        time: k.trade_date,
        value: 1,
        color: STATE_COLORS[state] || 'rgba(128,128,128,0.08)',
      })
    }
  }
  return result
}

function renderChart() {
  if (!container.value) return
  chart.value?.remove()

  chart.value = createChart(container.value, {
    width: container.value.clientWidth,
    height: 420,
    layout: {
      background: { type: ColorType.Solid, color: '#ffffff' },
      textColor: '#333',
    },
    grid: {
      vertLines: { color: '#f0f0f0' },
      horzLines: { color: '#f0f0f0' },
    },
    crosshair: { mode: 1 },
    timeScale: { timeVisible: true, secondsVisible: false },
  })

  chart.value.addHistogramSeries({
    color: 'rgba(128,128,128,0.08)',
    priceFormat: { type: 'volume' },
    priceScaleId: 'band',
  }).setData(buildBands())

  candleSeries.value = chart.value.addCandlestickSeries({
    upColor: '#26a69a',
    downColor: '#ef5350',
    borderUpColor: '#26a69a',
    borderDownColor: '#ef5350',
    wickUpColor: '#26a69a',
    wickDownColor: '#ef5350',
  })
  candleSeries.value.setData(
    props.klines.map((k) => ({
      time: k.trade_date,
      open: k.open,
      high: k.high,
      low: k.low,
      close: k.close,
    }))
  )

  props.klines.forEach((k) => {
    if (k.close > k.open) {
      candleSeries.value!.setMark({
        time: k.trade_date,
        position: 'belowBar',
        shape: 'arrowUp',
        color: '#26a69a',
      })
    } else if (k.close < k.open) {
      candleSeries.value!.setMark({
        time: k.trade_date,
        position: 'aboveBar',
        shape: 'arrowDown',
        color: '#ef5350',
      })
    }
  })
}

let ro: ResizeObserver | null = null
function handleResize() {
  if (container.value && chart.value) {
    chart.value.applyOptions({ width: container.value.clientWidth })
  }
}

onMounted(() => {
  renderChart()
  ro = new ResizeObserver(handleResize)
  if (container.value) ro.observe(container.value)
})

onUnmounted(() => {
  ro?.disconnect()
  chart.value?.remove()
})

watch(() => props.klines, renderChart, { deep: true })
</script>

<template>
  <div ref="container" class="kline-chart"></div>
</template>

<style scoped>
.kline-chart {
  width: 100%;
  height: 420px;
  border: 1px solid #e8e8e8;
  border-radius: 4px;
}
</style>
