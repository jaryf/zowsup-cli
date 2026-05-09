import React, { useEffect, useState } from 'react'
import { List, Input, Badge, Avatar, Typography, Spin, Empty, Tag, Tooltip } from 'antd'
import { UserOutlined, TeamOutlined, SearchOutlined, RobotOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { fetchChatHistory, fetchContacts, fetchContactAvatar, refreshContactAvatar } from '../../api/endpoints'
import { useDashboardStore } from '../../store'
import { useTranslation } from 'react-i18next'

const { Text } = Typography

// ---- Helpers ----

/** True if this JID is a group conversation. */
function isGroup(jid: string): boolean {
  return jid.endsWith('@g.us')
}

/**
 * Return primary display name and optional secondary note for a contact.
 * - Individual with push_name  → primary = push_name,  secondary = number
 * - Group with display_name    → primary = display_name, secondary = group-id short
 * - Fallback                   → primary = jid short,   secondary = null
 */
function contactNames(contact: { jid: string; display_name: string; push_name?: string | null }): {
  primary: string
  secondary: string | null
} {
  const short = contact.jid.replace(/@.*$/, '')
  // Individual: prefer push_name
  if (!contact.jid.endsWith('@g.us') && contact.push_name) {
    return { primary: contact.push_name, secondary: short }
  }
  // Group or individual with display_name stored
  if (contact.display_name && contact.display_name !== short) {
    return { primary: contact.display_name, secondary: null }
  }
  return { primary: short, secondary: null }
}

/**
 * ContactList — shows all known sessions (groups + individuals) populated
 * from chat history.  Groups show a TeamOutlined icon; individuals show
 * UserOutlined.  Display names are resolved via the bot and stored in DB.
 */
const ContactList: React.FC = () => {
  const { t } = useTranslation()
  const contacts = useDashboardStore((s) => s.contacts)
  const selectedJid = useDashboardStore((s) => s.selectedJid)
  const selectJid = useDashboardStore((s) => s.selectJid)
  const setContacts = useDashboardStore((s) => s.setContacts)
  const updateContactAvatar = useDashboardStore((s) => s.updateContactAvatar)
  const setMessages = useDashboardStore((s) => s.setMessages)
  const setMessagesLoading = useDashboardStore((s) => s.setMessagesLoading)
  const clearUnread = useDashboardStore((s) => s.clearUnread)

  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)

  // Bootstrap contacts from /api/contacts on first load
  useEffect(() => {
    setLoading(true)
    fetchContacts()
      .then((list) => {
        if (list.length > 0) {
          setContacts(
            list.map((c) => ({
              jid: c.user_jid,
              display_name: c.display_name
                ? c.display_name
                : c.user_jid.replace(/@.*$/, ''),
              push_name: c.push_name ?? null,
              last_message: c.last_message,
              last_timestamp: c.last_timestamp,
              unread: 0,
              avatar_url: c.avatar_url ?? null,
              bot_jid: c.bot_jid ?? null,
            })),
          )
        }
      })
      .catch(() => {
        // If the API is unavailable, fall back gracefully to any WS-populated contacts
      })
      .finally(() => setLoading(false))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const filtered = contacts.filter((c) => {
    const { primary } = contactNames(c)
    const q = search.toLowerCase()
    return (
      primary.toLowerCase().includes(q) ||
      c.jid.replace(/@.*$/, '').includes(q) ||
      (c.push_name ?? '').toLowerCase().includes(q)
    )
  })

  async function handleSelect(jid: string) {
    if (jid === selectedJid) return
    selectJid(jid)
    clearUnread(jid)
    setMessagesLoading(true)
    try {
      const res = await fetchChatHistory(jid, 1, 50)
      setMessages(res.messages, res.page, res.total)
    } catch {
      setMessages([], 1, 0)
    } finally {
      setMessagesLoading(false)
    }

    // Refresh avatar for this contact once in the background
    refreshContactAvatar(jid).catch(() => null)
    // Poll for the updated URL at 4 s, 10 s, 20 s after enqueue
    const delays = [4000, 10000, 20000]
    delays.forEach((ms) => {
      setTimeout(() => {
        fetchContactAvatar(jid)
          .then(({ avatar_url }) => {
            if (avatar_url) updateContactAvatar(jid, avatar_url)
          })
          .catch(() => null)
      }, ms)
    })
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <div style={{ padding: '12px 8px' }}>
        <Input
          prefix={<SearchOutlined />}
          placeholder={t('contactList.search')}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          size="small"
          allowClear
        />
      </div>

      {loading ? (
        <Spin style={{ margin: 'auto' }} />
      ) : filtered.length === 0 ? (
        <Empty description={t('contactList.empty')} style={{ marginTop: 40 }} image={Empty.PRESENTED_IMAGE_SIMPLE} />
      ) : (
        <List
          style={{ overflow: 'auto', flex: 1 }}
          dataSource={filtered}
          renderItem={(contact) => (
            <List.Item
              key={contact.jid}
              style={{
                padding: '10px 12px',
                cursor: 'pointer',
                background: contact.jid === selectedJid ? '#e6f7ff' : undefined,
                borderLeft: contact.jid === selectedJid ? '3px solid #1890ff' : '3px solid transparent',
              }}
              onClick={() => handleSelect(contact.jid)}
            >
              <List.Item.Meta
                avatar={
                  <Badge count={contact.unread} size="small">
                    <Avatar
                      src={contact.avatar_url ?? undefined}
                      icon={isGroup(contact.jid) ? <TeamOutlined /> : <UserOutlined />}
                      size={36}
                      style={isGroup(contact.jid) ? { backgroundColor: '#722ed1' } : undefined}
                    />
                  </Badge>
                }
                title={
                  <span style={{ display: 'flex', alignItems: 'baseline', gap: 4, flexWrap: 'wrap' }}>
                    <Text strong style={{ fontSize: 13 }}>
                      {contactNames(contact).primary}
                    </Text>
                    {contactNames(contact).secondary && (
                      <Text type="secondary" style={{ fontSize: 11 }}>
                        ({contactNames(contact).secondary})
                      </Text>
                    )}
                  </span>
                }
                description={
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <Text type="secondary" ellipsis style={{ fontSize: 12 }}>
                      {contact.last_message ?? '—'}
                    </Text>
                    <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 4 }}>
                      {contact.bot_jid && (
                        <Tooltip title={contact.bot_jid}>
                          <Tag
                            icon={<RobotOutlined />}
                            color="blue"
                            style={{ fontSize: 10, margin: 0, padding: '0 4px', lineHeight: '16px' }}
                          >
                            {contact.bot_jid.replace(/@.*/, '')}
                          </Tag>
                        </Tooltip>
                      )}
                      {contact.last_timestamp && (
                        <Text type="secondary" style={{ fontSize: 11, flexShrink: 0 }}>
                          {dayjs.unix(contact.last_timestamp).format('HH:mm')}
                        </Text>
                      )}
                    </div>
                  </div>
                }
              />
            </List.Item>
          )}
        />
      )}
    </div>
  )
}

export default ContactList
