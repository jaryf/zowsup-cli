import React, { useEffect, useState } from 'react'
import {
  Avatar,
  Card,
  Descriptions,
  Tag,
  Progress,
  Spin,
  Empty,
  Typography,
  Statistic,
  Row,
  Col,
  Button,
  Modal,
  Form,
  Select,
  Input,
  message,
  Divider,
  Tooltip,
  Space,
  Table,
  Popconfirm,
} from 'antd'
import {
  ArrowUpOutlined,
  ArrowDownOutlined,
  MinusOutlined,
  EditOutlined,
  RollbackOutlined,
  CheckOutlined,
  CloseOutlined,
  StopOutlined,
  CheckCircleOutlined,
  DeleteOutlined,
  HistoryOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  fetchUserProfile,
  postApplyStrategy,
  postRollbackStrategy,
  patchUserProfile,
  fetchStrategyHistory,
  patchToggleStrategy,
  deleteStrategyRow,
} from '../../api/endpoints'
import { useDashboardStore } from '../../store'
import { useTranslation } from 'react-i18next'
import type { StrategyConfig, StrategyRecord } from '../../types'

const { Title, Text } = Typography
const { TextArea } = Input

const CATEGORY_COLOR: Record<string, string> = {
  VIP: 'gold',
  regular: 'blue',
  new: 'green',
  at_risk: 'red',
}

const STYLE_COLOR: Record<string, string> = {
  detailed: 'purple',
  concise: 'cyan',
  patient: 'geekblue',
  impatient: 'orange',
}

function InlineTagEditor({
  value,
  isManual,
  options,
  colorMap,
  defaultColor,
  onSave,
}: {
  value: string | null
  isManual: boolean
  options: { label: string; value: string }[]
  colorMap: Record<string, string>
  defaultColor: string
  onSave: (v: string | null) => Promise<void>
}) {
  const { t } = useTranslation()
  const [editing, setEditing] = useState(false)
  const [pending, setPending] = useState<string | null>(value)
  const [saving, setSaving] = useState(false)

  const tagColor = value ? (colorMap[value] ?? defaultColor) : 'default'
  const labelText = options.find((o) => o.value === value)?.label ?? value ?? '—'

  const handleConfirm = async () => {
    setSaving(true)
    try {
      await onSave(pending)
      setEditing(false)
    } finally {
      setSaving(false)
    }
  }

  if (editing) {
    return (
      <Space size={4}>
        <Select
          size="small"
          style={{ width: 120 }}
          value={pending}
          options={options}
          allowClear
          placeholder={t('userProfile.autoInfer')}
          onChange={(v) => setPending(v ?? null)}
          autoFocus
        />
        <Button
          size="small"
          type="primary"
          icon={<CheckOutlined />}
          loading={saving}
          onClick={handleConfirm}
        />
        <Button
          size="small"
          icon={<CloseOutlined />}
          onClick={() => { setPending(value); setEditing(false) }}
        />
      </Space>
    )
  }

  return (
    <Space size={4}>
      <Tag color={tagColor} style={{ margin: 0 }}>{labelText}</Tag>
      {isManual && (
        <Tooltip title={t('userProfile.manualHint')}>
          <Tag color="volcano" style={{ margin: 0, fontSize: 10, padding: '0 4px' }}>{t('userProfile.manual')}</Tag>
        </Tooltip>
      )}
      <Tooltip title={t('userProfile.setManually')}>
        <Button
          type="text"
          size="small"
          icon={<EditOutlined style={{ fontSize: 11, color: '#8c8c8c' }} />}
          style={{ padding: '0 2px', height: 'auto' }}
          onClick={() => { setPending(value); setEditing(true) }}
        />
      </Tooltip>
    </Space>
  )
}

const STYLE_OPTIONS_STATIC = [
  { value: 'formal' }, { value: 'casual' }, { value: 'concise' }, { value: 'detailed' },
]
const TONE_OPTIONS_STATIC = [
  { value: 'polite' }, { value: 'friendly' }, { value: 'professional' }, { value: 'empathetic' }, { value: 'neutral' },
]
const LANG_OPTIONS_STATIC = [
  { value: 'auto' }, { value: 'zh' }, { value: 'en' }, { value: 'mixed' },
]

function TrendIndicator({ direction, pct }: { direction: string; pct?: number | null }) {
  const pctStr = pct != null ? `${pct.toFixed(1)}%` : '—'
  if (direction === 'up')
    return <Text type="success"><ArrowUpOutlined /> {pctStr}</Text>
  if (direction === 'down')
    return <Text type="danger"><ArrowDownOutlined /> {pctStr}</Text>
  return <Text type="secondary"><MinusOutlined /> {pctStr}</Text>
}

const UserProfile: React.FC = () => {
  const { t } = useTranslation()
  const selectedJid = useDashboardStore((s) => s.selectedJid)
  const profile = useDashboardStore((s) => s.profile)
  const profileLoading = useDashboardStore((s) => s.profileLoading)
  const setProfile = useDashboardStore((s) => s.setProfile)
  const setProfileLoading = useDashboardStore((s) => s.setProfileLoading)
  const contacts = useDashboardStore((s) => s.contacts)
  const contact = contacts.find((c) => c.jid === selectedJid)

  // Translated option arrays (react to lang change)
  const CATEGORY_OPTIONS = [
    { label: 'VIP', value: 'VIP' },
    { label: t('categoryOpts.regular'), value: 'regular' },
    { label: t('categoryOpts.new'), value: 'new' },
    { label: t('categoryOpts.at_risk'), value: 'at_risk' },
  ]

  const COMM_STYLE_OPTIONS = [
    { label: t('commStyleOpts.detailed'), value: 'detailed' },
    { label: t('commStyleOpts.concise'), value: 'concise' },
    { label: t('commStyleOpts.patient'), value: 'patient' },
    { label: t('commStyleOpts.impatient'), value: 'impatient' },
  ]

  const STYLE_OPTIONS = STYLE_OPTIONS_STATIC.map((o) => ({ ...o, label: t(`strategyOpts.${o.value}`) }))
  const TONE_OPTIONS = TONE_OPTIONS_STATIC.map((o) => ({ ...o, label: t(`strategyOpts.${o.value}`) }))
  const LANG_OPTIONS = LANG_OPTIONS_STATIC.map((o) => ({ ...o, label: t(`strategyOpts.${o.value}`) }))

  const [modalOpen, setModalOpen] = useState(false)
  const [applying, setApplying] = useState(false)
  const [rolling, setRolling] = useState(false)
  const [form] = Form.useForm<StrategyConfig & { note?: string }>()

  const [personalHistory, setPersonalHistory] = useState<StrategyRecord[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [rowLoading, setRowLoading] = useState<Record<number, boolean>>({})

  useEffect(() => {
    if (!selectedJid) return
    setProfileLoading(true)
    fetchUserProfile(selectedJid)
      .then(setProfile)
      .catch(() => setProfile(null))
      .finally(() => setProfileLoading(false))
    loadPersonalHistory(selectedJid)
  }, [selectedJid]) // eslint-disable-line react-hooks/exhaustive-deps

  function loadPersonalHistory(jid: string) {
    setHistoryLoading(true)
    fetchStrategyHistory(jid)
      .then((r) => setPersonalHistory(r.history))
      .catch(() => setPersonalHistory([]))
      .finally(() => setHistoryLoading(false))
  }

  const handleOpenModal = () => {
    form.resetFields()
    setModalOpen(true)
  }

  const handleApply = async () => {
    if (!selectedJid) return
    try {
      const values = await form.validateFields()
      const { note, ...config } = values
      setApplying(true)
      await postApplyStrategy(selectedJid, config as StrategyConfig, note)
      message.success(t('userProfile.strategyApplied'))
      setModalOpen(false)
      fetchUserProfile(selectedJid).then(setProfile).catch(() => null)
      loadPersonalHistory(selectedJid)
    } catch {
      // validation error — form shows inline
    } finally {
      setApplying(false)
    }
  }

  const handleRollback = async () => {
    if (!selectedJid) return
    setRolling(true)
    try {
      await postRollbackStrategy(selectedJid)
      message.success(t('userProfile.strategyRolledBack'))
      fetchUserProfile(selectedJid).then(setProfile).catch(() => null)
      loadPersonalHistory(selectedJid)
    } catch {
      message.error(t('userProfile.rollbackFailed'))
    } finally {
      setRolling(false)
    }
  }

  async function handleToggleRow(record: StrategyRecord) {
    setRowLoading((prev) => ({ ...prev, [record.id]: true }))
    try {
      const result = await patchToggleStrategy(record.id)
      setPersonalHistory((prev) =>
        prev.map((r) => {
          if (r.id === record.id) return { ...r, is_active: result.is_active }
          if (result.is_active === 1 && r.id !== record.id) return { ...r, is_active: 0 as const }
          return r
        }),
      )
      message.success(result.is_active ? t('userProfile.enabledStrategy') : t('userProfile.blockedStrategy'))
    } catch {
      message.error(t('userProfile.actionFailed'))
    } finally {
      setRowLoading((prev) => ({ ...prev, [record.id]: false }))
    }
  }

  async function handleDeleteRow(record: StrategyRecord) {
    setRowLoading((prev) => ({ ...prev, [record.id]: true }))
    try {
      await deleteStrategyRow(record.id)
      setPersonalHistory((prev) => prev.filter((r) => r.id !== record.id))
      message.success(t('userProfile.deleted'))
    } catch {
      message.error(t('userProfile.deleteFailed'))
    } finally {
      setRowLoading((prev) => ({ ...prev, [record.id]: false }))
    }
  }

  const historyColumns = [
    {
      title: t('common.version'),
      dataIndex: 'version',
      width: 52,
      render: (v: number, r: StrategyRecord) => (
        <Tag color={r.is_active ? 'green' : 'default'} style={{ margin: 0 }}>v{v}</Tag>
      ),
    },
    {
      title: t('common.status'),
      dataIndex: 'is_active',
      width: 68,
      render: (active: 0 | 1) =>
        active ? (
          <Tag color="green" icon={<CheckCircleOutlined />} style={{ margin: 0, fontSize: 11 }}>{t('userProfile.activated')}</Tag>
        ) : (
          <Tag color="default" icon={<StopOutlined />} style={{ margin: 0, fontSize: 11 }}>{t('userProfile.inactive')}</Tag>
        ),
    },
    {
      title: t('common.remark'),
      dataIndex: 'note',
      ellipsis: true,
      render: (n: string | null) => <span style={{ fontSize: 12 }}>{n ?? '—'}</span>,
    },
    {
      title: t('common.time'),
      dataIndex: 'applied_at',
      width: 80,
      render: (ts: string) => <span style={{ fontSize: 11 }}>{dayjs(ts).format('MM-DD HH:mm')}</span>,
    },
    {
      title: t('common.actions'),
      width: 88,
      fixed: 'right' as const,
      render: (_: unknown, record: StrategyRecord) => (
        <Space size={4}>
          <Button
            size="small"
            loading={rowLoading[record.id]}
            icon={record.is_active ? <StopOutlined /> : <CheckCircleOutlined />}
            onClick={() => handleToggleRow(record)}
            title={record.is_active ? t('userProfile.blockStrategy') : t('userProfile.enableStrategy')}
          />
          <Popconfirm
            title={t('userProfile.deleteStrategy')}
            description={t('userProfile.deleteStrategyDesc')}
            onConfirm={() => handleDeleteRow(record)}
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
        </Space>
      ),
    },
  ]

  const handleSaveCategory = async (val: string | null) => {
    if (!selectedJid) return
    await patchUserProfile(selectedJid, { user_category: val })
    message.success(val ? t('userProfile.categorySaved', { val }) : t('userProfile.categoryClear'))
    fetchUserProfile(selectedJid).then(setProfile).catch(() => null)
  }

  const handleSaveStyle = async (val: string | null) => {
    if (!selectedJid) return
    await patchUserProfile(selectedJid, { communication_style: val })
    message.success(val ? t('userProfile.styleSaved', { val }) : t('userProfile.styleClear'))
    fetchUserProfile(selectedJid).then(setProfile).catch(() => null)
  }

  if (!selectedJid) return <Empty description={t('userProfile.empty')} style={{ marginTop: 40 }} />
  if (profileLoading) return <Spin style={{ display: 'block', marginTop: 40 }} />
  if (!profile) return <Empty description={t('userProfile.noProfile')} style={{ marginTop: 40 }} />

  const topTopics = Object.entries(profile.topic_preferences ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)

  return (
    <div style={{ padding: 12 }}>
      {/* 用户信息 */}
      <Text strong style={{ fontSize: 13, display: 'block', marginBottom: 8 }}>
        {t('userProfile.infoTitle')}
      </Text>
      <div style={{ background: '#fafafa', borderRadius: 8, padding: '8px 12px', marginBottom: 16 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
          <Avatar
            size={48}
            src={contact?.avatar_url ?? undefined}
            style={{ flexShrink: 0, backgroundColor: '#722ed1' }}
          >
            {!contact?.avatar_url ? selectedJid.replace(/@.*$/, '').slice(0, 2) : null}
          </Avatar>
          <div>
            {contact?.push_name && (
              <Text strong style={{ fontSize: 13, display: 'block' }}>{contact.push_name}</Text>
            )}
            <Text code style={{ fontSize: 12 }}>{selectedJid.replace(/@.*$/, '')}</Text>
          </div>
        </div>
      </div>

      {/* 用户画像 */}
      <Text strong style={{ fontSize: 13, display: 'block', marginBottom: 12 }}>
        {t('userProfile.title')}
      </Text>

      <Row gutter={[8, 8]} style={{ marginBottom: 12 }}>
        <Col span={12}>
          <Card size="small">
            <Statistic title={t('userProfile.totalInteractions')} value={profile.total_interactions} />
          </Card>
        </Col>
        <Col span={12}>
          <Card size="small">
            <Statistic
              title={t('userProfile.satisfaction')}
              value={
                profile.satisfaction_score != null
                  ? `${(profile.satisfaction_score * 100).toFixed(0)}%`
                  : '—'
              }
            />
          </Card>
        </Col>
      </Row>

      <Descriptions
        size="small"
        column={1}
        bordered
        labelStyle={{ width: 80, whiteSpace: 'nowrap' }}
        style={{ marginBottom: 12 }}
      >
        <Descriptions.Item label={t('userProfile.category')}>
          <InlineTagEditor
            value={profile.user_category}
            isManual={profile.user_category_is_manual ?? false}
            options={CATEGORY_OPTIONS}
            colorMap={CATEGORY_COLOR}
            defaultColor="blue"
            onSave={handleSaveCategory}
          />
        </Descriptions.Item>
        <Descriptions.Item label={t('userProfile.commStyle')}>
          <InlineTagEditor
            value={profile.communication_style}
            isManual={profile.communication_style_is_manual ?? false}
            options={COMM_STYLE_OPTIONS}
            colorMap={STYLE_COLOR}
            defaultColor="purple"
            onSave={handleSaveStyle}
          />
        </Descriptions.Item>
        <Descriptions.Item label={t('userProfile.currentStrategy')}>
          {profile.current_strategy && typeof profile.current_strategy === 'object'
            ? <Space size={4} wrap>
                {Object.entries(profile.current_strategy as Record<string, string>)
                  .filter(([, v]) => v)
                  .map(([k, v]) => (
                    <Tag key={k} color="green" style={{ margin: 0, fontSize: 11 }}>{k}={v}</Tag>
                  ))}
              </Space>
            : <Tag color="green">{profile.current_strategy ? String(profile.current_strategy) : t('userProfile.default')}</Tag>}
        </Descriptions.Item>
        <Descriptions.Item label={t('userProfile.firstSeen')}>
          {profile.first_seen ? dayjs(profile.first_seen).format('YYYY-MM-DD') : '—'}
        </Descriptions.Item>
        <Descriptions.Item label={t('userProfile.lastSeen')}>
          {profile.last_seen ? dayjs(profile.last_seen).format('YYYY-MM-DD HH:mm') : '—'}
        </Descriptions.Item>
      </Descriptions>

      {/* Strategy quick-action buttons */}
      <Row gutter={8} style={{ marginBottom: 12 }}>
        <Col span={14}>
          <Button
            type="primary"
            icon={<EditOutlined />}
            block
            size="small"
            onClick={handleOpenModal}
          >
            {t('userProfile.adjustStrategy')}
          </Button>
        </Col>
        <Col span={10}>
          <Button
            icon={<RollbackOutlined />}
            block
            size="small"
            loading={rolling}
            onClick={handleRollback}
          >
            {t('userProfile.rollbackStrategy')}
          </Button>
        </Col>
      </Row>

      {profile.trend_7d && (
        <div style={{ marginBottom: 8 }}>
          <Text type="secondary">{t('userProfile.trend7d')} </Text>
          <TrendIndicator
            direction={profile.trend_7d.direction}
            pct={profile.trend_7d.change_pct}
          />
        </div>
      )}

      {topTopics.length > 0 && (
        <div>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {t('userProfile.hotTopics')}
          </Text>
          {topTopics.map(([topic, count]) => {
            const maxCount = topTopics[0][1] || 1
            return (
              <div key={topic} style={{ marginTop: 6 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                  <Text style={{ fontSize: 12 }}>{topic}</Text>
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    {count}
                  </Text>
                </div>
                <Progress
                  percent={Math.round((count / maxCount) * 100)}
                  size="small"
                  showInfo={false}
                  strokeColor="#1890ff"
                />
              </div>
            )
          })}
        </div>
      )}

      {/* Per-user strategy modal */}
      <Modal
        title={t('userProfile.strategyModalTitle', { jid: selectedJid })}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleApply}
        confirmLoading={applying}
        okText={t('userProfile.applyNow')}
        cancelText={t('common.cancel')}
        width={640}
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          {t('userProfile.strategyOnlyFor', { jid: selectedJid })}
        </Text>
        <Form form={form} layout="vertical" size="small">
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label={t('userProfile.responseStyle')} name="response_style">
                <Select options={STYLE_OPTIONS} placeholder={t('userProfile.keepGlobal')} allowClear />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label={t('common.tone')} name="tone">
                <Select options={TONE_OPTIONS} placeholder={t('userProfile.keepGlobal')} allowClear />
              </Form.Item>
            </Col>
          </Row>
          <Row gutter={12}>
            <Col span={12}>
              <Form.Item label={t('common.language')} name="language">
                <Select options={LANG_OPTIONS} placeholder={t('strategyOpts.auto')} allowClear />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item label={t('userProfile.maxLength')} name="max_response_length">
                <Input type="number" placeholder={t('userProfile.unlimited')} min={1} />
              </Form.Item>
            </Col>
          </Row>
          <Divider style={{ margin: '8px 0' }} />
          <Form.Item label={t('userProfile.customInstructions')} name="custom_instructions">
            <TextArea
              rows={3}
              placeholder={t('userProfile.customInstructionsPlaceholder')}
            />
          </Form.Item>
          <Form.Item label={t('userProfile.noteLabel')} name="note">
            <Input placeholder={t('userProfile.notePlaceholder')} />
          </Form.Item>
        </Form>

        <Divider style={{ margin: '12px 0 8px' }}>
          <Space size={4}>
            <HistoryOutlined />
            <span style={{ fontSize: 12, color: '#8c8c8c' }}>{t('userProfile.strategyHistory')}</span>
          </Space>
        </Divider>

        {personalHistory.length === 0 && !historyLoading ? (
          <Empty description={t('userProfile.noHistory')} image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ margin: '8px 0' }} />
        ) : (
          <Table
            dataSource={personalHistory}
            columns={historyColumns}
            rowKey="id"
            size="small"
            loading={historyLoading}
            pagination={{ pageSize: 5, size: 'small', hideOnSinglePage: true }}
            scroll={{ x: 420 }}
          />
        )}
      </Modal>
    </div>
  )
}

export default UserProfile
