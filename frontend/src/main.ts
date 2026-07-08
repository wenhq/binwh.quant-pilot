import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import Antd from 'ant-design-vue'
import zhCN from 'ant-design-vue/locale/zh_CN'
import 'ant-design-vue/dist/reset.css'

import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(router)
app.use(Antd, { locale: zhCN })
app.mount('#root')
