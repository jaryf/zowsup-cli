import React, { useEffect, useRef, useState } from 'react'
import { Typography, Tag, Spin, Empty, Pagination, Tooltip, Image } from 'antd'
import { RobotOutlined, UserOutlined, AlertOutlined, FileOutlined, AudioOutlined, VideoCameraOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { fetchChatHistory } from '../../api/endpoints'
import { useDashboardStore } from '../../store'
import { useTranslation } from 'react-i18next'
import type { ChatMessage } from '../../types'

const { Text } = Typography

const _URGENCY_COLOR: Record<string, string> = {
  high: 'red',
  medium: 'orange',
  low: 'default',
}

/** Build a URL for a media file stored on the server.
 *  media_path from the DB is an absolute local path; we only need the basename. */
function mediaUrl(mediaPath: string): string {
  // Strip Windows or POSIX directory portion, keep only the filename
  const filename = mediaPath.replace(/^.*[\\/]/, '')
  return `/api/media/${encodeURIComponent(filename)}`
}

/**
 * Renders the appropriate media widget based on message_type + media_path.
 * Falls back to a plain text label when the file isn't available yet.
 */
function MediaContent({ msg }: { msg: ChatMessage }) {
  const [errored, setErrored] = useState(false)
  const url = msg.media_path ? mediaUrl(msg.media_path) : null

  if (!url || errored) {
    // No file yet or failed to load — show placeholder label
    return (
      <Text type="secondary" style={{ fontSize: 13, fontStyle: 'italic' }}>
        {msg.content}
      </Text>
    )
  }

  const mt = msg.message_type?.toUpperCase()

  if (mt === 'IMAGE' || mt === 'STICKER') {
    return (
      <Image
        src={url}
        style={{ maxWidth: 240, maxHeight: 240, borderRadius: 6, display: 'block' }}
        onError={() => setErrored(true)}
        preview={mt === 'IMAGE'}
        fallback=""
      />
    )
  }

  if (mt === 'VIDEO') {
    return (
      <video
        src={url}
        controls
        style={{ maxWidth: 280, maxHeight: 200, borderRadius: 6, display: 'block' }}
        onError={() => setErrored(true)}
      />
    )
  }

  if (mt === 'AUDIO') {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <AudioOutlined style={{ color: '#1890ff' }} />
        <audio controls src={url} style={{ height: 32 }} onError={() => setErrored(true)} />
      </div>
    )
  }

  if (mt === 'DOCUMENT') {
    const filename = msg.media_path!.replace(/^.*[\\/]/, '')
    return (
      <a href={url} target="_blank" rel="noopener noreferrer" style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <FileOutlined />
        <Text style={{ fontSize: 13 }}>{filename}</Text>
      </a>
    )
  }

  // Fallback for unknown media types
  return (
    <Text type="secondary" style={{ fontSize: 13, fontStyle: 'italic' }}>
      {msg.content}
    </Text>
  )
}

function UrgencyTag({ level }: { level: string }) {
  const { t } = useTranslation()
  if (!level || level === 'low') return null
  return (
    <Tag
      color={_URGENCY_COLOR[level] ?? 'default'}
      icon={level === 'high' ? <AlertOutlined /> : undefined}
      style={{ margin: 0, fontSize: 11 }}
    >
      {t(`chatHistory.urgency.${level}`, level)}
    </Tag>
  )
}

function SourceTag({ direction }: { direction: 'in' | 'out' }) {
  const { t } = useTranslation()
  return direction === 'out' ? (
    <Tag color="green" icon={<RobotOutlined />} style={{ margin: 0, fontSize: 11 }}>AI</Tag>
  ) : (
    <Tag icon={<UserOutlined />} style={{ margin: 0, fontSize: 11, color: '#888', borderColor: '#d9d9d9', background: '#fafafa' }}>{t('chatHistory.user')}</Tag>
  )
}

function MessageItem({ msg }: { msg: ChatMessage }) {
  // Prefer resolved_jid (real JID resolved from LID) over raw participant
  const participantLabel = (msg.resolved_jid || msg.participant)
    ? (msg.resolved_jid || msg.participant)!.replace(/@.*$/, '')
    : null

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: msg.direction === 'out' ? 'row-reverse' : 'row',
        gap: 8,
        marginBottom: 12,
        alignItems: 'flex-start',
      }}
    >
      <div
        style={{
          maxWidth: '75%',
          background: msg.direction === 'out' ? '#d9f7be' : '#fff',
          border: '1px solid #f0f0f0',
          borderRadius: 8,
          padding: '6px 10px',
          boxShadow: '0 1px 2px rgba(0,0,0,0.06)',
        }}
      >
        {(participantLabel || msg.notify) && msg.direction === 'in' && (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4, gap: 8 }}>
            {participantLabel && (
              <Text
                style={{
                  fontSize: 10,
                  fontWeight: 600,
                  color: '#722ed1',
                  lineHeight: '14px',
                  maxWidth: 120,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {participantLabel}
              </Text>
            )}
            {msg.notify && (
              <Text
                style={{
                  fontSize: 10,
                  color: '#8c8c8c',
                  lineHeight: '14px',
                  maxWidth: 120,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  marginLeft: 'auto',
                }}
              >
                {msg.notify}
              </Text>
            )}
          </div>
        )}
        {/* Render rich media for downloadable types, plain text otherwise */}
        <div>
        {msg.media_path
          ? <MediaContent msg={msg} />
          : (
            <Text style={{ fontSize: 13, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {msg.content}
            </Text>
          )
        }
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6, marginTop: 4 }}>
          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            <SourceTag direction={msg.direction} />
            {msg.direction === 'out' && msg.urgency_level && (
              <UrgencyTag level={msg.urgency_level} />
            )}
          </div>
          <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexShrink: 0 }}>
            {msg.bot_jid && (
              <Tooltip title={msg.bot_jid}>
                <Tag
                  icon={<RobotOutlined />}
                  color="blue"
                  style={{ fontSize: 10, margin: 0, padding: '0 4px', lineHeight: '16px' }}
                >
                  {msg.bot_jid.replace(/@.*/, '')}
                </Tag>
              </Tooltip>
            )}
            <Tooltip title={dayjs.unix(msg.timestamp).format('YYYY-MM-DD HH:mm:ss')}>
              <Text type="secondary" style={{ fontSize: 11 }}>
                {dayjs.unix(msg.timestamp).format('HH:mm')}
              </Text>
            </Tooltip>
          </div>
        </div>
      </div>
    </div>
  )
}

const PAGE_SIZE = 50

const ChatHistory: React.FC = () => {
  const { t } = useTranslation()
  const selectedJid = useDashboardStore((s) => s.selectedJid)
  const messages = useDashboardStore((s) => s.messages)
  const messagesPage = useDashboardStore((s) => s.messagesPage)
  const messagesTotal = useDashboardStore((s) => s.messagesTotal)
  const messagesLoading = useDashboardStore((s) => s.messagesLoading)
  const setMessages = useDashboardStore((s) => s.setMessages)
  const setMessagesLoading = useDashboardStore((s) => s.setMessagesLoading)
  // Ref to the inverted scroll container — used to jump to visual-bottom (DOM scrollTop=0)
  const scrollRef = useRef<HTMLDivElement>(null)

  // Jump to newest messages (visual bottom = DOM top = scrollTop 0) on contact switch
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0
  }, [selectedJid])

  // scaleY(-1) flips the visual axis. React's onWheel is passive (preventDefault is a no-op),
  // so we must use a native non-passive listener to intercept and reverse wheel direction.
  // Depend on messagesLoading so the effect re-runs once the scroll div actually renders
  // (it is absent during loading/empty states, so scrollRef.current would be null on first mount).
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      // In scaleY(-1): scrollTop increase = visual-up = older messages.
      // Wheel-up (deltaY < 0): -= negative → scrollTop increases → older ✓
      // Wheel-down (deltaY > 0): -= positive → scrollTop decreases → newer ✓
      el.scrollTop -= e.deltaY
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [messagesLoading])

  async function handlePageChange(page: number) {
    if (!selectedJid) return
    setMessagesLoading(true)
    try {
      const res = await fetchChatHistory(selectedJid, page, PAGE_SIZE)
      setMessages(res.messages, res.page, res.total)
      // Jump to the newest end of the newly loaded page (instant, no animation jank)
      if (scrollRef.current) scrollRef.current.scrollTop = 0
    } catch {
      // keep existing
    } finally {
      setMessagesLoading(false)
    }
  }

  if (!selectedJid) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <Empty description={t('chatHistory.selectContact')} />
      </div>
    )
  }

  if (messagesLoading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <Spin tip={t('chatHistory.loading')} />
      </div>
    )
  }

  if (messages.length === 0) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <Empty description={t('chatHistory.empty')} />
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/*
        Inverted-list technique:
        1. The scroll container is flipped with scaleY(-1):
           - DOM top  → visual bottom  (newest messages always anchor here)
           - DOM bottom → visual top   (oldest messages scroll up to)
           - scrollTop=0 naturally shows the newest messages without any scrollIntoView call
        2. Each message item is flipped back with scaleY(-1) so text reads normally.
        3. Messages are rendered in store order (newest-first, index 0 at DOM top)
           so they appear oldest→newest top→bottom after the double-flip.
        Result: no scroll-jump on message load or live push.
      */}
      <div
        ref={scrollRef}
        tabIndex={0}
        style={{ flex: 1, overflowY: 'auto', padding: '12px 16px', transform: 'scaleY(-1)', outline: 'none' }}
        onKeyDown={(e) => {
          // PageUp/PageDown and arrow keys are also inverted by scaleY(-1); reverse them.
          const el = e.currentTarget
          const pageAmount = el.clientHeight * 0.9
          if (e.key === 'PageUp') {
            e.preventDefault()
            el.scrollTop += pageAmount
          } else if (e.key === 'PageDown') {
            e.preventDefault()
            el.scrollTop -= pageAmount
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            el.scrollTop += 60
          } else if (e.key === 'ArrowDown') {
            e.preventDefault()
            el.scrollTop -= 60
          }
        }}
      >
        {messages.map((msg) => (
          <div key={msg.id} style={{ transform: 'scaleY(-1)' }}>
            <MessageItem msg={msg} />
          </div>
        ))}
      </div>
      <div style={{ padding: '8px 16px', borderTop: '1px solid #f0f0f0', textAlign: 'right' }}>
        <Pagination
          current={messagesPage}
          pageSize={PAGE_SIZE}
          total={messagesTotal}
          onChange={handlePageChange}
          size="small"
          showTotal={(total) => t('common.totalItems', { count: total })}
          showSizeChanger={false}
        />
      </div>
    </div>
  )
}

export default ChatHistory
