import React from 'react'
import { Row, Col, Card } from 'antd'
import { useTranslation } from 'react-i18next'
import ContactList from '../components/ContactList/ContactList'
import ChatHistory from '../components/ChatHistory/ChatHistory'
import UserProfile from '../components/UserProfile/UserProfile'
import GroupInfo from '../components/GroupInfo/GroupInfo'
import StatisticsPanel from '../components/StatisticsPanel/StatisticsPanel'
import { useDashboardStore } from '../store'

/**
 * Main Dashboard page.
 *
 * Layout (desktop):
 *   ┌──────────────┬──────────────────────────────┬───────────────┐
 *   │ ContactList  │       ChatHistory            │  UserProfile  │
 *   │  (240px)     │                              │   (280px)     │
 *   └──────────────┴──────────────────────────────┴───────────────┘
 *   │                   StatisticsPanel                           │
 *   └─────────────────────────────────────────────────────────────┘
 */
const DashboardPage: React.FC = () => {
  const { t } = useTranslation()
  const selectedJid = useDashboardStore((s) => s.selectedJid)
  const isGroup = selectedJid?.endsWith('@g.us') ?? false
  return (
    <div style={{ padding: 16, height: '100%', display: 'flex', flexDirection: 'column', gap: 12 }}>
      {/* Top row — 3 columns */}
      <Row gutter={12} style={{ flex: '0 0 calc(60vh - 60px)' }}>
        <Col flex="288px">
          <Card
            size="small"
            title={t('dashboard.contacts')}
            bodyStyle={{ padding: 0, height: 'calc(60vh - 100px)', overflow: 'hidden' }}
            style={{ height: '100%' }}
          >
            <ContactList />
          </Card>
        </Col>

        <Col flex="1">
          <Card
            size="small"
            title={t('dashboard.chatHistory')}
            bodyStyle={{ padding: 0, height: 'calc(60vh - 100px)', overflow: 'hidden' }}
            style={{ height: '100%' }}
          >
            <ChatHistory />
          </Card>
        </Col>

        <Col flex="420px">
          <Card
            size="small"
            title={isGroup ? t('dashboard.groupInfo') : t('dashboard.userProfile')}
            bodyStyle={{ height: 'calc(60vh - 100px)', overflow: 'auto', padding: 0 }}
            style={{ height: '100%' }}
          >
            {isGroup ? <GroupInfo jid={selectedJid!} /> : <UserProfile />}
          </Card>
        </Col>
      </Row>

      {/* Bottom row — statistics */}
      <Card size="small" title={t('dashboard.statistics')} style={{ flex: 1 }}>
        <StatisticsPanel />
      </Card>
    </div>
  )
}

export default DashboardPage
