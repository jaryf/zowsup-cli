import React, { useEffect } from 'react'
import { Row, Col, Card, Statistic, Spin } from 'antd'
import {
  MessageOutlined,
  TeamOutlined,
  RobotOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { fetchStatistics } from '../../api/endpoints'
import { useDashboardStore } from '../../store'
import { useTranslation } from 'react-i18next'

const StatisticsPanel: React.FC = () => {
  const { t } = useTranslation()
  const stats = useDashboardStore((s) => s.stats)
  const statsLoading = useDashboardStore((s) => s.statsLoading)
  const setStats = useDashboardStore((s) => s.setStats)
  const setStatsLoading = useDashboardStore((s) => s.setStatsLoading)
  const activeBots = useDashboardStore((s) => s.activeBots)

  // Initial fetch (SSE hook will keep it updated afterwards)
  useEffect(() => {
    setStatsLoading(true)
    fetchStatistics()
      .then(setStats)
      .catch(() => {})
      .finally(() => setStatsLoading(false))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  if (statsLoading || !stats) {
    return <Spin style={{ display: 'block', margin: '40px auto' }} />
  }

  const aiRate =
    stats.total_messages > 0
      ? ((stats.ai_responses / stats.total_messages) * 100).toFixed(1)
      : '0.0'

  // Pie chart: message composition
  const pieOption = {
    tooltip: { trigger: 'item' },
    legend: { orient: 'vertical', right: 10, top: 'center', textStyle: { fontSize: 12 } },
    series: [
      {
        name: t('stats.messageComposition'),
        type: 'pie',
        radius: ['40%', '70%'],
        avoidLabelOverlap: false,
        label: { show: false },
        data: [
          { value: stats.ai_responses, name: t('stats.aiReplies') },
          { value: stats.total_messages - stats.ai_responses, name: t('stats.other') },
        ],
      },
    ],
  }

  // Bar chart placeholder: today vs total
  const barOption = {
    tooltip: {},
    xAxis: { data: [t('stats.todayMessages'), t('stats.totalMessages'), t('stats.activeUsers'), t('stats.aiReplies')] },
    yAxis: {},
    series: [
      {
        name: t('stats.overview'),
        type: 'bar',
        data: [
          stats.today_messages,
          stats.total_messages,
          stats.active_users,
          stats.ai_responses,
        ],
        itemStyle: { color: '#1890ff' },
        barMaxWidth: 40,
      },
    ],
  }

  return (
    <div style={{ padding: '0 8px' }}>
      <Row gutter={[12, 12]} style={{ marginBottom: 16 }}>
        <Col xs={8} sm={4}>
          <Card size="small">
            <Statistic
              title={t('stats.totalMessages')}
              value={stats.total_messages}
              prefix={<MessageOutlined />}
            />
          </Card>
        </Col>
        <Col xs={8} sm={4}>
          <Card size="small">
            <Statistic
              title={t('stats.activeUsers')}
              value={stats.active_users}
              prefix={<TeamOutlined />}
            />
          </Card>
        </Col>
        <Col xs={8} sm={4}>
          <Card size="small">
            <Statistic
              title={t('stats.aiReplies')}
              value={stats.ai_responses}
              prefix={<RobotOutlined />}
            />
          </Card>
        </Col>
        <Col xs={8} sm={4}>
          <Card size="small">
            <Statistic
              title={t('stats.todayMessages')}
              value={stats.today_messages}
              prefix={<ThunderboltOutlined />}
              suffix={<small style={{ fontSize: 11 }}>{t('stats.aiRate', { rate: aiRate })}</small>}
            />
          </Card>
        </Col>
        <Col xs={8} sm={4}>
          <Card size="small">
            <Statistic
              title={t('stats.onlineBots', '在线Bot')}
              value={stats.online_bots ?? activeBots.filter((b) => b.running).length}
              prefix={<RobotOutlined style={{ color: '#52c41a' }} />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>        
      </Row>


      <Row gutter={[12, 12]}>
        <Col xs={24} sm={12}>
          <Card title={t('stats.messageComposition')} size="small">
            <ReactECharts option={pieOption} style={{ height: 200 }} />
          </Card>
        </Col>
        <Col xs={24} sm={12}>
          <Card title={t('stats.overview')} size="small">
            <ReactECharts option={barOption} style={{ height: 200 }} />
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default StatisticsPanel
