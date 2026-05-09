import React, { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Modal, Form, Input, Button, Typography, message } from 'antd'
import { KeyOutlined } from '@ant-design/icons'
import AppLayout from './components/Layout/AppLayout'
import DashboardPage from './pages/DashboardPage'
import StrategyPage from './pages/StrategyPage'
import BotLoginPage from './pages/BotLoginPage'
import BotLogsPage from './pages/BotLogsPage'
import { useWebSocket } from './hooks/useWebSocket'
import { useSSE } from './hooks/useSSE'
import { setApiToken, getApiToken } from './api/client'
import { useDashboardStore } from './store'
import { fetchHealth } from './api/endpoints'

const { Text } = Typography

/** Root component that handles token entry and real-time hooks. */
function AppInner() {
  useWebSocket()
  useSSE()
  return (
    <BrowserRouter>
      <AppLayout>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/logs" element={<BotLogsPage />} />
          <Route path="/strategy" element={<StrategyPage />} />
          <Route path="/login" element={<BotLoginPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppLayout>
    </BrowserRouter>
  )
}

export default function App() {
  const [tokenReady, setTokenReady] = useState(false)
  const [showModal, setShowModal] = useState(false)
  const [checking, setChecking] = useState(false)
  const [form] = Form.useForm()
  const setStoreToken = useDashboardStore((s) => s.setApiToken)

  useEffect(() => {
    const existing = getApiToken()
    if (!existing) {
      // No token stored yet — open entry modal
      setShowModal(true)
    } else {
      // Verify stored token is still valid
      setChecking(true)
      fetchHealth()
        .then(() => setTokenReady(true))
        .catch(() => {
          // Token may be invalid or server in dev mode (no auth)
          setTokenReady(true)
        })
        .finally(() => setChecking(false))
    }
  }, [])

  async function handleTokenSubmit({ token }: { token: string }) {
    setChecking(true)
    setApiToken(token.trim())
    setStoreToken(token.trim())
    try {
      await fetchHealth()
      setShowModal(false)
      setTokenReady(true)
      message.success('连接成功')
    } catch {
      message.error('Token 无效或服务未启动')
    } finally {
      setChecking(false)
    }
  }

  function handleSkip() {
    // Dev mode: server may not require auth
    setShowModal(false)
    setTokenReady(true)
  }

  if (checking && !tokenReady) return null // brief loading state

  return (
    <>
      {tokenReady && <AppInner />}

      <Modal
        title={
          <span>
            <KeyOutlined style={{ marginRight: 8 }} />
            输入 API Token
          </span>
        }
        open={showModal}
        footer={null}
        closable={false}
        maskClosable={false}
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          请输入 <code>DASHBOARD_API_TOKEN</code> 环境变量配置的令牌。开发模式下可点击"跳过"。
        </Text>
        <Form form={form} onFinish={handleTokenSubmit} layout="vertical">
          <Form.Item
            name="token"
            label="Bearer Token"
            rules={[{ required: true, message: '请输入 Token' }]}
          >
            <Input.Password placeholder="输入 Token..." />
          </Form.Item>
          <div style={{ display: 'flex', gap: 8 }}>
            <Button type="primary" htmlType="submit" loading={checking}>
              确认
            </Button>
            <Button onClick={handleSkip}>跳过（开发模式）</Button>
          </div>
        </Form>
      </Modal>
    </>
  )
}
