import React, { useEffect, useRef, useState } from 'react'
import {
  Avatar,
  Button,
  Col,
  Descriptions,
  Divider,
  Empty,
  Form,
  Input,
  message,
  Modal,
  Popconfirm,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import {
  CheckCircleOutlined,
  CrownOutlined,
  DeleteOutlined,
  EditOutlined,
  HistoryOutlined,
  RollbackOutlined,
  StopOutlined,
  TeamOutlined,
  UserOutlined,
} from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  fetchGroupInfo,
  postApplyStrategy,
  postRollbackStrategy,
  fetchStrategyHistory,
  patchToggleStrategy,
  deleteStrategyRow,
} from '../../api/endpoints'
import type { GroupInfo as GroupInfoType, GroupMember } from '../../types'
import type { StrategyConfig, StrategyRecord } from '../../types'
import { useDashboardStore } from '../../store'
import { useTranslation } from 'react-i18next'

const STYLE_OPTIONS_STATIC = [
  { value: 'formal' }, { value: 'casual' }, { value: 'concise' }, { value: 'detailed' },
]
const TONE_OPTIONS_STATIC = [
  { value: 'polite' }, { value: 'friendly' }, { value: 'professional' }, { value: 'empathetic' }, { value: 'neutral' },
]
const LANG_OPTIONS_STATIC = [
  { value: 'auto' }, { value: 'zh' }, { value: 'en' }, { value: 'mixed' },
]

interface Props {
  jid: string
}

const { Text } = Typography

const GroupInfo: React.FC<Props> = ({ jid }) => {
  const { t } = useTranslation()
  const [info, setInfo] = useState<GroupInfoType | null>(null)
  const [loading, setLoading] = useState(false)
  const groupInfoRevision = useDashboardStore((s) => s.groupInfoRevision)
  const contacts = useDashboardStore((s) => s.contacts)
  const contactAvatarUrl = contacts.find((c) => c.jid === jid)?.avatar_url ?? null

  // Strategy state
  const [modalOpen, setModalOpen] = useState(false)
  const [applying, setApplying] = useState(false)
  const [rolling, setRolling] = useState(false)
  const [form] = Form.useForm<StrategyConfig & { note?: string }>()
  const [personalHistory, setPersonalHistory] = useState<StrategyRecord[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [rowLoading, setRowLoading] = useState<Record<number, boolean>>({})

  // Track which jid we last did a full load for, so revision bumps don't flash
  const loadedJidRef = useRef<string | null>(null)

  const STYLE_OPTIONS = STYLE_OPTIONS_STATIC.map((o) => ({ ...o, label: t(`strategyOpts.${o.value}`) }))
  const TONE_OPTIONS = TONE_OPTIONS_STATIC.map((o) => ({ ...o, label: t(`strategyOpts.${o.value}`) }))
  const LANG_OPTIONS = LANG_OPTIONS_STATIC.map((o) => ({ ...o, label: t(`strategyOpts.${o.value}`) }))

  useEffect(() => {
    if (!jid) return
    const isJidChange = loadedJidRef.current !== jid
    loadedJidRef.current = jid
    if (isJidChange) {
      // Full reset only when switching to a different group
      setLoading(true)
      setInfo(null)
    }
    fetchGroupInfo(jid)
      .then(setInfo)
      .catch(() => { if (isJidChange) setInfo(null) })
      .finally(() => { if (isJidChange) setLoading(false) })
    loadPersonalHistory(jid)
  }, [jid, groupInfoRevision]) // eslint-disable-line react-hooks/exhaustive-deps

  function loadPersonalHistory(groupJid: string) {
    setHistoryLoading(true)
    fetchStrategyHistory(groupJid)
      .then((r) => setPersonalHistory(r.history))
      .catch(() => setPersonalHistory([]))
      .finally(() => setHistoryLoading(false))
  }

  const handleOpenModal = () => {
    form.resetFields()
    setModalOpen(true)
  }

  const handleApply = async () => {
    try {
      const values = await form.validateFields()
      const { note, ...config } = values
      setApplying(true)
      await postApplyStrategy(jid, config as StrategyConfig, note)
      message.success(t('userProfile.strategyApplied'))
      setModalOpen(false)
      loadPersonalHistory(jid)
    } catch {
      // validation error
    } finally {
      setApplying(false)
    }
  }

  const handleRollback = async () => {
    setRolling(true)
    try {
      await postRollbackStrategy(jid)
      message.success(t('userProfile.strategyRolledBack'))
      loadPersonalHistory(jid)
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
          />
          <Popconfirm
            title={t('userProfile.deleteStrategy')}
            description={t('userProfile.deleteStrategyDesc')}
            onConfirm={() => handleDeleteRow(record)}
            okText={t('common.delete')}
            okButtonProps={{ danger: true }}
            cancelText={t('common.cancel')}
          >
            <Button size="small" danger icon={<DeleteOutlined />} loading={rowLoading[record.id]} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  if (loading) {
    return (
      <div style={{ display: 'flex', justifyContent: 'center', padding: 32 }}>
        <Spin />
      </div>
    )
  }

  if (!info) {
    return <Empty description={false} style={{ margin: '24px auto' }} />
  }

  const fmt = (ts: number | null) =>
    ts ? dayjs(ts * 1000).format('YYYY-MM-DD HH:mm') : '—'

  const sortedMembers = [...(info.members ?? [])].sort(
    (a, b) => (b.last_seen ?? 0) - (a.last_seen ?? 0),
  )

  const columns = [
    {
      title: t('groupInfo.memberJid'),
      dataIndex: 'participant',
      key: 'participant',
      render: (participant: string, row: GroupMember) => (
        <span style={{ display: 'flex', alignItems: 'flex-start', gap: 6 }}>
          <Avatar
            size={20}
            icon={<UserOutlined />}
            style={{ flexShrink: 0, marginTop: 1, backgroundColor: row.role === 'admin' ? '#722ed1' : '#87d068' }}
          />
          <span>
            {row.notify ? (
              <>
                <span style={{ fontWeight: 500, fontSize: 12 }}>{row.notify}</span>
                <br />
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {participant.replace(/@s\.whatsapp\.net$/, '')}
                </Text>
              </>
            ) : (
              <Text style={{ fontSize: 12 }}>{participant.replace(/@s\.whatsapp\.net$/, '')}</Text>
            )}
          </span>
        </span>
      ),
    },
    {
      title: t('groupInfo.memberLast'),
      dataIndex: 'last_seen',
      key: 'last_seen',
      width: 120,
      render: (ts: number | null) => (
        <Text type="secondary" style={{ fontSize: 11 }}>
          {fmt(ts)}
        </Text>
      ),
    },
    {
      title: t('groupInfo.memberRole'),
      dataIndex: 'role',
      key: 'role',
      width: 65,
      render: (role: string | null) =>
        role === 'admin' ? (
          <Tooltip title={t('groupInfo.roleAdmin')}>
            <Tag color="gold" icon={<CrownOutlined />} style={{ fontSize: 10, padding: '0 4px' }}>
              {t('groupInfo.roleAdmin')}
            </Tag>
          </Tooltip>
        ) : null,
    },
  ]

  return (
    <div style={{ padding: '8px 12px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
        {(contactAvatarUrl || info.avatar_url) ? (
          <Avatar size={48} src={contactAvatarUrl ?? info.avatar_url} />
        ) : (
          <Avatar size={48} icon={<TeamOutlined />} style={{ backgroundColor: '#722ed1' }} />
        )}
        <div>
          <Text strong style={{ fontSize: 15, display: 'block' }}>
            {info.display_name ?? jid.replace(/@g\.us$/, '')}
          </Text>
          <Text type="secondary" style={{ fontSize: 11 }}>
            {jid}
          </Text>
        </div>
      </div>

      {/* Basic stats */}
      <Descriptions
        size="small"
        column={1}
        bordered={false}
        labelStyle={{ color: '#8c8c8c', fontSize: 12, paddingBottom: 2 }}
        contentStyle={{ fontSize: 12, paddingBottom: 2 }}
        style={{ marginBottom: 12 }}
      >
        <Descriptions.Item label={t('groupInfo.messageCount')}>
          {info.message_count}
        </Descriptions.Item>
        <Descriptions.Item label={t('groupInfo.firstSeen')}>
          {fmt(info.first_seen)}
        </Descriptions.Item>
        <Descriptions.Item label={t('groupInfo.lastSeen')}>
          {fmt(info.last_seen)}
        </Descriptions.Item>
        {info.synced_at && (
          <Descriptions.Item label={t('groupInfo.syncedAt')}>
            <Text type="secondary">{fmt(info.synced_at)}</Text>
          </Descriptions.Item>
        )}
      </Descriptions>

      {/* Strategy buttons */}
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

      {/* Members */}
      <Text strong style={{ fontSize: 13, display: 'block', marginBottom: 6 }}>
        {t('groupInfo.members')}{' '}
        <Tag color="purple" style={{ fontSize: 11 }}>
          {sortedMembers.length}
        </Tag>
        {!info.synced_at && (
          <Tag color="orange" style={{ fontSize: 10, marginLeft: 4 }}>
            {t('groupInfo.fromHistory')}
          </Tag>
        )}
      </Text>
      {sortedMembers.length === 0 ? (
        <Empty
          description={t('groupInfo.noMembers')}
          imageStyle={{ height: 40 }}
          style={{ margin: '12px auto' }}
        />
      ) : (
        <Table<GroupMember>
          size="small"
          dataSource={sortedMembers}
          columns={columns}
          rowKey="participant"
          pagination={false}          
          style={{ fontSize: 12 }}
        />
      )}

      {/* Strategy modal */}
      <Modal
        title={t('userProfile.strategyModalTitle', { jid })}
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        onOk={handleApply}
        confirmLoading={applying}
        okText={t('userProfile.applyNow')}
        cancelText={t('common.cancel')}
        width={640}
      >
        <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          {t('userProfile.strategyOnlyFor', { jid })}
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
            <Input.TextArea rows={3} placeholder={t('userProfile.customInstructionsPlaceholder')} />
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

export default GroupInfo
