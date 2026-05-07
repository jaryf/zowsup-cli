import React, { useEffect, useRef, useState } from 'react'
import { Button, Space, Tag, Typography, Select } from 'antd'
import { ClearOutlined, VerticalAlignBottomOutlined, PauseOutlined, RobotOutlined } from '@ant-design/icons'
import { useDashboardStore } from '../store'
import type { BotLogEntry } from '../store'

const { Text } = Typography

const LEVEL_COLOR: Record<string, string> = {
  DEBUG: '#8c8c8c',
  INFO: '#52c41a',
  WARNING: '#faad14',
  ERROR: '#ff4d4f',
  CRITICAL: '#cf1322',
}

const LEVEL_OPTIONS = ['ALL', 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']

const LEVEL_ORDER: Record<string, number> = {
  DEBUG: 10,
  INFO: 20,
  WARNING: 30,
  ERROR: 40,
  CRITICAL: 50,
}

function LogLine({ entry }: { entry: BotLogEntry }) {
  const color = LEVEL_COLOR[entry.level] ?? '#d9d9d9'
  return (
    <div
      style={{ fontFamily: 'monospace', fontSize: 12, lineHeight: '20px', padding: '1px 8px',
        borderBottom: '1px solid #1f1f1f', display: 'flex', gap: 8, alignItems: 'flex-start' }}
    >
      <Text style={{ color: '#595959', flexShrink: 0, fontSize: 11 }}>{entry.ts}</Text>
      {entry.bot_id && (
        <Tag
          icon={<RobotOutlined />}
          color="blue"
          style={{ minWidth: 50, textAlign: 'center', margin: 0, flexShrink: 0, fontSize: 10, lineHeight: '18px' }}
        >
          {entry.bot_id.slice(-6)}
        </Tag>
      )}
      <Tag
        color={color}
        style={{ minWidth: 60, textAlign: 'center', margin: 0, flexShrink: 0, fontSize: 11 }}
      >
        {entry.level}
      </Tag>
      <Text style={{ color: '#8c8c8c', flexShrink: 0, fontSize: 11, maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {entry.logger}
      </Text>
      <Text style={{ color: '#d9d9d9', fontSize: 12, wordBreak: 'break-all' }}>
        {entry.message}
      </Text>
    </div>
  )
}

const BotLogsPage: React.FC = () => {
  const logs = useDashboardStore((s) => s.botLogs)
  const clearBotLogs = useDashboardStore((s) => s.clearBotLogs)
  const activeBots = useDashboardStore((s) => s.activeBots)
  const selectedLogBotId = useDashboardStore((s) => s.selectedLogBotId)
  const setSelectedLogBotId = useDashboardStore((s) => s.setSelectedLogBotId)
  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const [minLevel, setMinLevel] = useState('INFO')

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    if (autoScroll) {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logs, autoScroll])

  // Detect manual scroll-up to pause auto-scroll
  const handleScroll = () => {
    const el = containerRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    setAutoScroll(atBottom)
  }

  const minLevelNum = minLevel === 'ALL' ? 0 : (LEVEL_ORDER[minLevel] ?? 0)
  const filtered = logs.filter((e) => (LEVEL_ORDER[e.level] ?? 0) >= minLevelNum)

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', padding: 12, gap: 8 }}>
      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
        <Space>
          {/* Bot selector */}
          <Select
            size="small"
            value={selectedLogBotId ?? 'ALL'}
            onChange={(v) => setSelectedLogBotId(v === 'ALL' ? null : v)}
            options={[
              { value: 'ALL', label: '全部Bot' },
              ...activeBots.map((b) => ({
                value: b.phone,
                label: (
                  <span>
                    <RobotOutlined style={{ marginRight: 4, color: b.running ? '#52c41a' : '#aaa' }} />
                    {b.phone}
                  </span>
                ),
              })),
            ]}
            style={{ width: 160 }}
          />
          <Select
            size="small"
            value={minLevel}
            onChange={setMinLevel}
            options={LEVEL_OPTIONS.map((l) => ({ value: l, label: l }))}
            style={{ width: 100 }}
          />
          <Button
            size="small"
            icon={<VerticalAlignBottomOutlined />}
            type={autoScroll ? 'primary' : 'default'}
            onClick={() => {
              setAutoScroll(true)
              bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
            }}
          >
            自动滚动
          </Button>
          {!autoScroll && (
            <Tag color="warning" icon={<PauseOutlined />}>
              已暂停
            </Tag>
          )}
        </Space>
        <div style={{ flex: 1 }} />
        <Text style={{ color: '#8c8c8c', fontSize: 12 }}>{filtered.length} 条</Text>
        <Button
          size="small"
          danger
          icon={<ClearOutlined />}
          onClick={clearBotLogs}
        >
          清空
        </Button>
      </div>

      {/* Log viewport */}
      <div
        ref={containerRef}
        onScroll={handleScroll}
        style={{
          flex: 1,
          overflow: 'auto',
          background: '#141414',
          borderRadius: 6,
          border: '1px solid #303030',
        }}
      >
        {filtered.length === 0 ? (
          <div style={{ color: '#595959', fontFamily: 'monospace', padding: 16, fontSize: 12 }}>
            等待日志...
          </div>
        ) : (
          filtered.map((entry, i) => <LogLine key={i} entry={entry} />)
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}

export default BotLogsPage
