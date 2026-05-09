import React, { useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import { ConfigProvider } from 'antd'
import enUS from 'antd/locale/en_US'
import zhCN from 'antd/locale/zh_CN'
import type { Locale } from 'antd/es/locale'
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import App from './App'
import './index.css'
import './i18n'
import i18n from './i18n'

function Root() {
  const [antdLocale, setAntdLocale] = useState<Locale>(
    i18n.language.startsWith('zh') ? zhCN : enUS,
  )

  useEffect(() => {
    const onChange = (lng: string) => {
      setAntdLocale(lng.startsWith('zh') ? zhCN : enUS)
      dayjs.locale(lng.startsWith('zh') ? 'zh-cn' : 'en')
    }
    i18n.on('languageChanged', onChange)
    // Set initial dayjs locale
    dayjs.locale(i18n.language.startsWith('zh') ? 'zh-cn' : 'en')
    return () => { i18n.off('languageChanged', onChange) }
  }, [])

  return (
    <ConfigProvider locale={antdLocale}>
      <App />
    </ConfigProvider>
  )
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
