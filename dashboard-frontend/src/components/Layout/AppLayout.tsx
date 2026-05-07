import React, { useEffect, useState } from 'react'
import { Layout, Menu, Badge, Tooltip, Typography, Space, Button, Segmented } from 'antd'
import logoSrc from '../../assets/zowsup-logo.png'
import {
  DashboardOutlined,
  SettingOutlined,
  WifiOutlined,
  DisconnectOutlined,
  RobotOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import { useNavigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useDashboardStore } from '../../store'
import { fetchBotAccounts } from '../../api/endpoints'

const { Sider, Header, Content } = Layout
const { Text } = Typography

interface AppLayoutProps {
  children: React.ReactNode
}

const AppLayout: React.FC<AppLayoutProps> = ({ children }) => {
  const navigate = useNavigate()
  const location = useLocation()
  const { t, i18n } = useTranslation()
  const wsConnected = useDashboardStore((s) => s.wsConnected)
  const collapsed = useDashboardStore((s) => s.siderCollapsed)
  const setSiderCollapsed = useDashboardStore((s) => s.setSiderCollapsed)
  const [runningCount, setRunningCount] = useState<number>(0)

  // Poll running bot count every 10 s
  useEffect(() => {
    const load = () => {
      fetchBotAccounts()
        .then((res) => setRunningCount(res.accounts.filter((a) => a.is_running).length))
        .catch(() => setRunningCount(0))
    }
    load()
    const timer = setInterval(load, 10_000)
    return () => clearInterval(timer)
  }, [])

  const menuItems = [
    {
      key: '/',
      icon: <DashboardOutlined />,
      label: t('nav.dashboard'),
    },
    {
      key: '/strategy',
      icon: <SettingOutlined />,
      label: t('nav.strategy'),
    },
    {
      key: '/login',
      icon: <RobotOutlined />,
      label: t('nav.botManagement'),
    },
  ]

  const isZh = i18n.language.startsWith('zh')
  const toggleLang = () => i18n.changeLanguage(isZh ? 'en' : 'zh')

  return (
    <Layout style={{ height: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setSiderCollapsed}
        theme="dark"
        width={200}
      >
        <div
          style={{
            height: 48,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            userSelect: 'none',
            overflow: 'hidden',
            padding: '0 8px',
          }}
        >
          {collapsed ? (
            <span style={{ color: '#4ade80', fontWeight: 700, fontSize: 16, letterSpacing: 1 }}>
              ZS
            </span>
          ) : (
            <img src={logoSrc} alt="ZOWSUP" style={{ height: 34, objectFit: 'contain' }} />
          )}
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>

      <Layout>
        <Header
          style={{
            background: '#fff',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderBottom: '1px solid #f0f0f0',
          }}
        >
          <Text strong style={{ fontSize: 16 }}>
          {['/','','/logs'].includes(location.pathname) && (
            <Segmented
              value={location.pathname === '/logs' ? '/logs' : '/'}
              onChange={(val) => navigate(val as string)}
              options={[
                { value: '/', label: <span><DashboardOutlined style={{ marginRight: 4 }} />{t('nav.dashboard')}</span> },
                { value: '/logs', label: <span><FileTextOutlined style={{ marginRight: 4 }} />{t('nav.botLogs')}</span> },
              ]}
            />
          )}
          </Text>
          <Space size={20}>
            {/* Language toggle */}
            <Tooltip title={isZh ? 'Switch to English' : '切换到中文'}>
              <Button size="small" onClick={toggleLang}>
                {isZh ? t('langSwitcher.en') : t('langSwitcher.zh')}
              </Button>
            </Tooltip>

            {/* Running bot count */}
            <Tooltip title={runningCount > 0 ? t('header.botsRunning', { count: runningCount }) : t('header.botsNone')}>
              <Badge
                status={runningCount > 0 ? 'success' : 'default'}
                text={
                  runningCount > 0 ? (
                    <span style={{ color: '#52c41a' }}>
                      <RobotOutlined style={{ marginRight: 4 }} />
                      {runningCount}
                    </span>
                  ) : (
                    <span style={{ color: '#8c8c8c' }}>
                      <RobotOutlined style={{ marginRight: 4 }} />
                      0
                    </span>
                  )
                }
              />
            </Tooltip>

            {/* WebSocket connection status */}
            <Tooltip title={wsConnected ? t('header.wsConnected') : t('header.wsDisconnected')}>
              <Badge
                status={wsConnected ? 'success' : 'error'}
                text={
                  wsConnected ? (
                    <span>
                      <WifiOutlined style={{ color: '#52c41a', marginRight: 4 }} />
                      {t('header.realtime')}
                    </span>
                  ) : (
                    <span>
                      <DisconnectOutlined style={{ color: '#ff4d4f', marginRight: 4 }} />
                      {t('header.disconnected')}
                    </span>
                  )
                }
              />
            </Tooltip>
          </Space>
        </Header>

        <Content style={{ overflow: 'auto', background: '#f0f2f5' }}>{children}</Content>
      </Layout>
    </Layout>
  )
}

export default AppLayout
