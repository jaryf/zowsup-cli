import React, { useEffect, useState } from 'react'
import {
  Card,
  Form,
  Select,
  Input,
  InputNumber,
  Button,
  Table,
  Tag,
  Typography,
  message,
  Divider,
  Row,
  Col,
  Popconfirm,
  Alert,
} from 'antd'
import { ReloadOutlined, RollbackOutlined, GlobalOutlined, StopOutlined, CheckCircleOutlined, DeleteOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  fetchStrategy,
  fetchStrategyHistory,
  postApplyGlobalStrategy,
  postRollbackStrategy,
  patchToggleStrategy,
  deleteStrategyRow,
} from '../api/endpoints'
import { useDashboardStore } from '../store'
import { useTranslation } from 'react-i18next'
import type { StrategyRecord, StrategyConfig } from '../types'

const { Title, Text } = Typography
const { TextArea } = Input

const StrategyPage: React.FC = () => {
  const { t } = useTranslation()

  const STYLE_OPTIONS = [
    { label: t('strategyOpts.formal'), value: 'formal' },
    { label: t('strategyOpts.casual'), value: 'casual' },
    { label: t('strategyOpts.concise'), value: 'concise' },
    { label: t('strategyOpts.detailed'), value: 'detailed' },
  ]

  const TONE_OPTIONS = [
    { label: t('strategyOpts.polite'), value: 'polite' },
    { label: t('strategyOpts.friendly'), value: 'friendly' },
    { label: t('strategyOpts.professional'), value: 'professional' },
    { label: t('strategyOpts.empathetic'), value: 'empathetic' },
    { label: t('strategyOpts.neutral'), value: 'neutral' },
  ]

  const LANG_OPTIONS = [
    { label: t('strategyOpts.auto'), value: 'auto' },
    { label: t('strategyOpts.zh'), value: 'zh' },
    { label: t('strategyOpts.en'), value: 'en' },
    { label: t('strategyOpts.mixed'), value: 'mixed' },
  ]
  const [form] = Form.useForm<StrategyConfig & { note?: string }>()
  const globalStrategy = useDashboardStore((s) => s.globalStrategy)
  const setGlobalStrategy = useDashboardStore((s) => s.setGlobalStrategy)
  const strategyHistory = useDashboardStore((s) => s.strategyHistory)
  const setStrategyHistory = useDashboardStore((s) => s.setStrategyHistory)
  const [applying, setApplying] = useState(false)
  const [rolling, setRolling] = useState(false)
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [rowLoading, setRowLoading] = useState<Record<number, boolean>>({})

  // Load current global strategy on mount
  useEffect(() => {
    fetchStrategy()
      .then((r) => {
        setGlobalStrategy(r.global)
        form.setFieldsValue(r.global)
      })
      .catch(() => {})

    loadHistory()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function loadHistory() {
    setLoadingHistory(true)
    try {
      const r = await fetchStrategyHistory()
      setStrategyHistory(r.history)
    } catch {
      setStrategyHistory([])
    } finally {
      setLoadingHistory(false)
    }
  }

  async function handleApply(values: StrategyConfig & { note?: string }) {
    const { note, ...config } = values
    setApplying(true)
    try {
      await postApplyGlobalStrategy(config, note)
      setGlobalStrategy(config)
      message.success(t('strategy.applied'))
      loadHistory()
    } catch {
      message.error(t('strategy.applyFailed'))
    } finally {
      setApplying(false)
    }
  }

  async function handleRollback() {
    setRolling(true)
    try {
      await postRollbackStrategy(null, 1)
      message.success(t('strategy.rolledBack'))
      // Refresh
      const r = await fetchStrategy()
      setGlobalStrategy(r.global)
      form.setFieldsValue(r.global)
      loadHistory()
    } catch {
      message.error(t('strategy.rollbackFailed'))
    } finally {
      setRolling(false)
    }
  }

  async function handleToggle(record: StrategyRecord) {
    setRowLoading((prev) => ({ ...prev, [record.id]: true }))
    try {
      const result = await patchToggleStrategy(record.id)
      // Update history in store: flip is_active for affected rows
      setStrategyHistory(
        strategyHistory.map((r) => {
          // The activated row
          if (r.id === record.id) return { ...r, is_active: result.is_active }
          // If we activated this row, deactivate others of same type/jid
          if (
            result.is_active === 1 &&
            r.strategy_type === record.strategy_type &&
            r.user_jid === record.user_jid &&
            r.id !== record.id
          ) {
            return { ...r, is_active: 0 as const }
          }
          return r
        }),
      )
      message.success(result.is_active ? t('strategy.enabled') : t('strategy.blocked'))
    } catch {
      message.error(t('strategy.actionFailed'))
    } finally {
      setRowLoading((prev) => ({ ...prev, [record.id]: false }))
    }
  }

  async function handleDelete(record: StrategyRecord) {
    setRowLoading((prev) => ({ ...prev, [record.id]: true }))
    try {
      await deleteStrategyRow(record.id)
      setStrategyHistory(strategyHistory.filter((r) => r.id !== record.id))
      message.success(t('strategy.deleted'))
    } catch {
      message.error(t('strategy.deleteFailed'))
    } finally {
      setRowLoading((prev) => ({ ...prev, [record.id]: false }))
    }
  }

  const columns = [
    {
      title: t('common.version'),
      dataIndex: 'version',
      width: 60,
      render: (v: number, r: StrategyRecord) => (
        <Tag color={r.is_active ? 'green' : 'default'}>{v}</Tag>
      ),
    },
    {
      title: t('common.status'),
      dataIndex: 'is_active',
      width: 72,
      render: (active: 0 | 1) =>
        active ? (
          <Tag color="green" icon={<CheckCircleOutlined />}>{t('strategy.activated')}</Tag>
        ) : (
          <Tag color="default" icon={<StopOutlined />}>{t('strategy.inactive')}</Tag>
        ),
    },
    {
      title: t('common.type'),
      dataIndex: 'strategy_type',
      width: 80,
      render: (tp: string) => (tp === 'global' ? <GlobalOutlined /> : tp),
    },
    {
      title: t('common.style'),
      render: (_: unknown, r: StrategyRecord) => (
        <Text style={{ fontSize: 12 }}>{r.config?.response_style ?? '—'}</Text>
      ),
    },
    {
      title: t('common.tone'),
      render: (_: unknown, r: StrategyRecord) => (
        <Text style={{ fontSize: 12 }}>{r.config?.tone ?? '—'}</Text>
      ),
    },
    {
      title: t('common.language'),
      render: (_: unknown, r: StrategyRecord) => (
        <Text style={{ fontSize: 12 }}>{r.config?.language ?? '—'}</Text>
      ),
    },
    {
      title: t('common.remark'),
      dataIndex: 'note',
      ellipsis: true,
      render: (n: string | null) => n ?? '—',
    },
    {
      title: t('common.time'),
      dataIndex: 'applied_at',
      render: (tp: string) => dayjs(tp).format('MM-DD HH:mm'),
    },
    {
      title: t('common.actions'),
      width: 110,
      fixed: 'right' as const,
      render: (_: unknown, record: StrategyRecord) => (
        <div style={{ display: 'flex', gap: 4 }}>
          <Button
            size="small"
            loading={rowLoading[record.id]}
            icon={record.is_active ? <StopOutlined /> : <CheckCircleOutlined />}
            onClick={() => handleToggle(record)}
            title={record.is_active ? t('strategy.blockStrategy') : t('strategy.enableStrategy')}
          >
            {record.is_active ? t('strategy.blockStrategy') : t('strategy.enableStrategy')}
          </Button>
          <Popconfirm
            title={t('strategy.deleteStrategy')}
            description={t('strategy.deleteStrategyDesc')}
            onConfirm={() => handleDelete(record)}
            okText={t('common.delete')}
            okButtonProps={{ danger: true }}
            cancelText={t('common.cancel')}
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              loading={rowLoading[record.id]}
            />
          </Popconfirm>
        </div>
      ),
    },
  ]

  return (
    <div style={{ padding: 16 }}>
      <Title level={4}>{t('strategy.title')}</Title>

      <Alert
        message={t('strategy.globalAlert')}
        type="info"
        showIcon
        style={{ marginBottom: 16 }}
      />

      <Row gutter={16}>
        <Col xs={24} md={12}>
          <Card title={t('strategy.editGlobal')} size="small">
            <Form
              form={form}
              layout="vertical"
              initialValues={globalStrategy}
              onFinish={handleApply}
            >
              <Form.Item name="response_style" label={t('strategy.responseStyle')}>
                <Select options={STYLE_OPTIONS} />
              </Form.Item>
              <Form.Item name="tone" label={t('common.tone')}>
                <Select options={TONE_OPTIONS} />
              </Form.Item>
              <Form.Item name="language" label={t('common.language')}>
                <Select options={LANG_OPTIONS} />
              </Form.Item>
              <Form.Item name="custom_instructions" label={t('strategy.customInstructions')}>
                <TextArea rows={3} placeholder={t('strategy.customInstructionsPlaceholder')} maxLength={500} showCount />
              </Form.Item>
              <Form.Item name="context_turns" label={t('strategy.contextTurns')}>
                <InputNumber min={1} max={50} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="context_days" label={t('strategy.contextDays')}>
                <InputNumber min={1} max={30} style={{ width: '100%' }} />
              </Form.Item>
              <Form.Item name="note" label={t('common.remark')}>
                <Input placeholder={t('strategy.notePlaceholder')} maxLength={200} />
              </Form.Item>

              <div style={{ display: 'flex', gap: 8 }}>
                <Button
                  type="primary"
                  htmlType="submit"
                  loading={applying}
                  icon={<GlobalOutlined />}
                >
                  {t('strategy.applyGlobal')}
                </Button>
                <Popconfirm
                  title={t('strategy.rollbackTitle')}
                  description={t('strategy.rollbackDesc')}
                  onConfirm={handleRollback}
                  okText={t('common.confirm')}
                  cancelText={t('common.cancel')}
                >
                  <Button icon={<RollbackOutlined />} loading={rolling} danger>
                    {t('common.rollback')}
                  </Button>
                </Popconfirm>
              </div>
            </Form>
          </Card>
        </Col>

        <Col xs={24} md={12}>
          <Card
            title={t('strategy.history')}
            size="small"
            extra={
              <Button
                size="small"
                icon={<ReloadOutlined />}
                onClick={loadHistory}
                loading={loadingHistory}
              >
                {t('common.refresh')}
              </Button>
            }
          >
            <Table
              dataSource={strategyHistory}
              columns={columns}
              rowKey="id"
              size="small"
              loading={loadingHistory}
              pagination={{ pageSize: 10, size: 'small' }}
              scroll={{ x: 500 }}
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}

export default StrategyPage
