import React, { useEffect, useState } from 'react'
import {
  Avatar,
  Descriptions,
  Empty,
  Spin,
  Table,
  Tag,
  Tooltip,
  Typography,
} from 'antd'
import { CrownOutlined, TeamOutlined, UserOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { fetchGroupInfo } from '../../api/endpoints'
import type { GroupInfo as GroupInfoType, GroupMember } from '../../types'
import { useTranslation } from 'react-i18next'

interface Props {
  jid: string
}

const { Text } = Typography

const GroupInfo: React.FC<Props> = ({ jid }) => {
  const { t } = useTranslation()
  const [info, setInfo] = useState<GroupInfoType | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!jid) return
    setLoading(true)
    setInfo(null)
    fetchGroupInfo(jid)
      .then(setInfo)
      .catch(() => setInfo(null))
      .finally(() => setLoading(false))
  }, [jid])

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
        {info.avatar_url ? (
          <Avatar size={48} src={info.avatar_url} />
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
          scroll={{ y: 220 }}
          style={{ fontSize: 12 }}
        />
      )}
    </div>
  )
}

export default GroupInfo
