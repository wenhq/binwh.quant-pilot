import { createRouter, createWebHashHistory } from 'vue-router'
import PrivateRoute from '../components/PrivateRoute.vue'
import Login from '../views/Login.vue'
import Register from '../views/Register.vue'
import Dashboard from '../views/Dashboard.vue'
import EtfView from '../views/EtfView.vue'
import IndicatorView from '../views/IndicatorView.vue'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', name: 'Login', component: Login, meta: { public: true } },
    { path: '/register', name: 'Register', component: Register, meta: { public: true } },
    {
      path: '/',
      component: PrivateRoute,
      children: [
        { path: '', name: 'Dashboard', component: Dashboard },
        { path: 'etf', name: 'Etf', component: EtfView },
        { path: 'indicators', name: 'Indicators', component: IndicatorView },
      ],
    },
  ],
})

export default router
