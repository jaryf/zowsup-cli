/**
 * BotLoginPage.tsx
 * ─────────────────
 * Bot Management — account list, import/export, one-click start, login tabs
 *
 * Layout:
 *   Card 1 — Bot Account List  (list / import / export / one-click-start / mark-failed / delete)
 *   Card 2 — Login Tabs (Start Registered Bot / Scan QR / Link Code)
 */

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import type { ColumnsType } from 'antd/es/table'
import {
  ApartmentOutlined,
  CheckCircleOutlined,
  CloudDownloadOutlined,
  CloudUploadOutlined,
  DeleteOutlined,
  LinkOutlined,
  PlayCircleOutlined,
  QrcodeOutlined,
  ReloadOutlined,
  RobotOutlined,
  SearchOutlined,
  StopOutlined,
  WarningOutlined,
} from '@ant-design/icons'
import {
  postBotLoginScan,
  postBotLoginLinkcode,
  postBotStart,
  postBotLogout,
  fetchBotAccounts,
  deleteBotAccount,
  patchToggleAccountFailed,
  deleteFailedAccounts,
  importBotAccounts,
  exportBotAccounts,
  fetchAgents,
} from '../api/endpoints'
import type { BotAccount, AgentInfo } from '../api/endpoints'
import { getApiToken } from '../api/client'
import { useTranslation } from 'react-i18next'

const { Paragraph, Text } = Typography

// ────────────────────────────────────────────────────────────────────────────
// QR Tab
// ────────────────────────────────────────────────────────────────────────────

const QrLoginTab: React.FC<{ onLoginSuccess: (jid: string) => void }> = ({ onLoginSuccess }) => {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)
  const [qrLines, setQrLines] = useState<string[]>([])
  const [statusMsg, setStatusMsg] = useState<string>('')
  const [streamError, setStreamError] = useState<string | null>(null)
  const esRef = useRef<EventSource | null>(null)

  const startScan = useCallback(async () => {
    // Close any existing SSE connection
    esRef.current?.close()
    setQrLines([])
    setStatusMsg('')
    setStreamError(null)
    setLoading(true)

    try {
      await postBotLoginScan()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setStreamError(t('qr.startFailed', { msg }))
      setLoading(false)
      return
    }

    // Open SSE stream
    const token = getApiToken()
    const url = `/api/bot/qr-stream${token ? `?token=${encodeURIComponent(token)}` : ''}`
    const es = new EventSource(url)
    esRef.current = es

    es.addEventListener('qr', (e) => {
      setLoading(false)
      setQrLines((prev) => [...prev, e.data])
    })

    es.addEventListener('status', (e) => {
      try {
        const payload = JSON.parse(e.data) as { type: string; jid?: string; msg?: string }
        if (payload.type === 'login_success') {
          es.close()
          setStatusMsg(t('qr.loginSuccess', { jid: payload.jid ?? '' }))
          onLoginSuccess(payload.jid ?? '')
        } else if (payload.type === 'timeout') {
          es.close()
          setStreamError(t('qr.timeout'))
          setLoading(false)
        } else if (payload.type === 'error') {
          es.close()
          setStreamError(payload.msg ?? t('qr.unknown'))
          setLoading(false)
        }
      } catch {
        // ignore parse errors
      }
    })

    es.onerror = () => {
      es.close()
      setStreamError(t('qr.sseError'))
      setLoading(false)
    }
  }, [onLoginSuccess, t])

  useEffect(() => {
    return () => {
      esRef.current?.close()
    }
  }, [])

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Button
        type="primary"
        icon={<ReloadOutlined />}
        loading={loading}
        onClick={startScan}
      >
        {qrLines.length > 0 ? t('qr.refreshQr') : t('qr.generateQr')}
      </Button>

      {streamError && <Alert type="error" message={streamError} showIcon />}

      {statusMsg && <Alert type="success" message={statusMsg} showIcon />}

      {loading && <Spin tip={t('qr.waiting')} />}

      {qrLines.length > 0 && !statusMsg && (
        <pre
          style={{
            background: '#000',
            color: '#fff',
            padding: 16,
            borderRadius: 8,
            fontFamily: '"Courier New", Courier, monospace',
            fontSize: 10,
            lineHeight: '1.2em',
            letterSpacing: 0,
            whiteSpace: 'pre',
            overflowX: 'auto',
          }}
        >
          {qrLines.join('\n')}
        </pre>
      )}

      <Paragraph type="secondary" style={{ marginTop: 8 }}>
        {t('qr.hint')}
      </Paragraph>
    </Space>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// Link-code Tab
// ────────────────────────────────────────────────────────────────────────────

const LinkCodeTab: React.FC<{ onLoginSuccess: (jid: string) => void }> = ({ onLoginSuccess }) => {
  const { t } = useTranslation()
  const [loading, setLoading] = useState(false)
  const [linkCode, setLinkCode] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [form] = Form.useForm()

  const handleSubmit = async ({ phone }: { phone: string }) => {
    setLoading(true)
    setLinkCode(null)
    setError(null)
    try {
      const res = await postBotLoginLinkcode(phone.trim())
      if (res.ok) {
        setLinkCode(res.link_code)
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setError(t('link.failed', { msg }))
    } finally {
      setLoading(false)
    }
  }

  return (
    <Space direction="vertical" style={{ width: '100%' }}>
      <Form form={form} layout="inline" onFinish={handleSubmit}>
        <Form.Item
          name="phone"
          rules={[
            { required: true, message: t('link.phoneRequired') },
            { pattern: /^\+\d{7,15}$/, message: t('link.phoneFormat') },
          ]}
        >
          <Input
            placeholder="+86xxxxxxxxxx"
            prefix="📱"
            style={{ width: 220 }}
          />
        </Form.Item>
        <Form.Item>
          <Button type="primary" htmlType="submit" loading={loading} icon={<LinkOutlined />}>
            {t('link.getCode')}
          </Button>
        </Form.Item>
      </Form>

      {error && <Alert type="error" message={error} showIcon />}

      {linkCode && (
        <Card
          style={{ maxWidth: 300, textAlign: 'center', marginTop: 16 }}
          bordered
        >
          <div style={{ fontSize: 28, letterSpacing: 8, fontFamily: 'monospace', margin: 0, fontWeight: 700 }}>
            {linkCode}
          </div>
          <Text type="secondary" style={{ display: 'block', marginTop: 8 }}>
            {t('link.hint')}
          </Text>
          <Button
            type="link"
            style={{ marginTop: 8 }}
            onClick={() => onLoginSuccess(t('link.doneTitle'))}
          >
            {t('link.done')}
          </Button>
        </Card>
      )}
    </Space>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// Bot Accounts Table
// ────────────────────────────────────────────────────────────────────────────

const AccountsSection: React.FC = () => {
  const { t } = useTranslation()
  const [accounts, setAccounts] = useState<BotAccount[]>([])
  const [loading, setLoading] = useState(false)
  const [selectedPhones, setSelectedPhones] = useState<string[]>([])
  const [rowLoading, setRowLoading] = useState<Record<string, boolean>>({})

  const [searchQuery, setSearchQuery] = useState('')
  const [agentFilter, setAgentFilter] = useState<string | null>(null)
  // agent_id options derived from loaded accounts
  const agentOptions = React.useMemo(() => {
    const ids = new Set<string>()
    accounts.forEach((a) => { if (a.agent_id) ids.add(a.agent_id) })
    return [
      { value: '__ALL__', label: '全部' },
      { value: '__LOCAL__', label: 'LOCAL（本机）' },
      ...[...ids].sort().map((id) => ({ value: id, label: id })),
    ]
  }, [accounts])

  // Import modal
  const [importOpen, setImportOpen] = useState(false)
  const [importText, setImportText] = useState('')
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<string | null>(null)
  const [importAgentId, setImportAgentId] = useState<string | null>(null)
  const [agentList, setAgentList] = useState<AgentInfo[]>([])

  // Load agent list once for import selector
  React.useEffect(() => {
    fetchAgents().then((r) => setAgentList(r.agents)).catch(() => {})
  }, [])

  // Export modal
  const [exportOpen, setExportOpen] = useState(false)
  const [exportText, setExportText] = useState('')
  const [exporting, setExporting] = useState(false)

  const esRef = useRef<Map<string, EventSource>>(new Map())

  const [msgApi, contextHolder] = message.useMessage()

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetchBotAccounts()
      setAccounts(res.accounts)
    } catch {
      // ignore
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // Auto-refresh every 10 s so running status stays up to date
  useEffect(() => {
    const id = setInterval(load, 10_000)
    return () => clearInterval(id)
  }, [load])

  const setRowBusy = (phone: string, busy: boolean) =>
    setRowLoading((prev) => ({ ...prev, [phone]: busy }))

  // ── One-click start ──
  const handleQuickStart = async (phone: string, agentId: string | null) => {
    // For agent-managed bots, postBotStart already dispatches to the agent;
    // skip the SSE wait (which is local-only) and just poll via load().
    if (agentId) {
      setRowBusy(phone, true)
      try {
        const res = await postBotStart(phone)
        if (res.already_running) {
          msgApi.info(`Bot ${phone} 已在运行中`)
        } else if (res.ok) {
          msgApi.success(`Bot ${phone} 启动指令已发送至 Agent`)
        }
        await load()
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err)
        msgApi.error(msg)
      } finally {
        setRowBusy(phone, false)
      }
      return
    }
    // Local bot: close any existing SSE for this phone, then start with SSE wait.
    esRef.current.get(phone)?.close()
    esRef.current.delete(phone)
    setRowBusy(phone, true)
    try {
      const res = await postBotStart(phone)
      if (res.already_running) {
        msgApi.info(`Bot ${phone} 已在运行中`)
        await load()
        return
      }
      // Wait for the bot to actually reach connected state via SSE
      await new Promise<void>((resolve, reject) => {
        const token = getApiToken()
        const params = new URLSearchParams({ phone })
        if (token) params.set('token', token)
        const es = new EventSource(`/api/bot/start-stream?${params}`)
        esRef.current.set(phone, es)
        es.addEventListener('status', (e) => {
          try {
            const p = JSON.parse(e.data) as { type: string; jid?: string; msg?: string }
            if (p.type === 'connected') { es.close(); esRef.current.delete(phone); resolve() }
            else if (p.type === 'timeout') { es.close(); esRef.current.delete(phone); resolve() }
            else if (p.type === 'error') { es.close(); esRef.current.delete(phone); reject(new Error(p.msg ?? '启动失败')) }
          } catch { /* ignore parse errors */ }
        })
        es.onerror = () => { es.close(); esRef.current.delete(phone); reject(new Error('连接中断')) }
      })
      msgApi.success(`Bot ${phone} 已连接`)
      await load()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      msgApi.error(msg)
    } finally {
      setRowBusy(phone, false)
    }
  }

  // ── One-click stop ──
  const handleQuickStop = async (phone: string) => {
    setRowBusy(phone, true)
    try {
      await postBotLogout(phone)
      msgApi.success(`Bot ${phone} 已停止`)
      load()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      msgApi.error(msg)
    } finally {
      setRowBusy(phone, false)
    }
  }

  // ── Delete ──
  const handleDelete = async (phone: string) => {
    setRowBusy(phone, true)
    try {
      await deleteBotAccount(phone)
      setAccounts((prev) => prev.filter((a) => a.phone !== phone))
      msgApi.success(t('bot.deletedAccount', { phone }))
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      msgApi.error(msg)
    } finally {
      setRowBusy(phone, false)
    }
  }

  // ── Toggle failed mark ──
  const handleToggleFailed = async (phone: string) => {
    setRowBusy(phone, true)
    try {
      const res = await patchToggleAccountFailed(phone)
      setAccounts((prev) =>
        prev.map((a) =>
          a.phone === phone
            ? { ...a, is_failed: res.is_failed, failed_at: res.is_failed ? new Date().toISOString() : null }
            : a
        )
      )
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      msgApi.error(msg)
    } finally {
      setRowBusy(phone, false)
    }
  }

  // ── Delete all failed ──
  const handleDeleteAllFailed = async () => {
    try {
      const res = await deleteFailedAccounts()
      msgApi.success(t('bot.deleteFailedAccountsCount', { count: res.deleted.length }))
      load()
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      msgApi.error(msg)
    }
  }

  // ── Import ──
  const handleImport = async () => {
    const lines = importText.split('\n').map((l) => l.trim()).filter(Boolean)
    if (!lines.length) return
    setImporting(true)
    setImportResult(null)
    try {
      const res = await importBotAccounts(lines, importAgentId === '__local__' ? null : importAgentId)
      setImportResult(t('bot.importDone', { imported: res.imported, total: res.total }))
      if (res.imported > 0) {
        load()
        setImportText('')
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setImportResult(t('bot.importError', { msg }))
    } finally {
      setImporting(false)
    }
  }

  // ── Export ──
  const handleExport = async (phones: string[]) => {
    setExporting(true)
    setExportText('')
    setExportOpen(true)
    try {
      const res = await exportBotAccounts(phones)
      setExportText(res.lines.join('\n'))
      if (res.errors.length > 0) {
        msgApi.warning(t('bot.exportFailed', { count: res.errors.length }))
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      msgApi.error(msg)
    } finally {
      setExporting(false)
    }
  }

  const filteredAccounts = accounts.filter((a) => {
    if (searchQuery.trim() && !a.phone.includes(searchQuery.trim())) return false
    if (agentFilter && agentFilter !== '__ALL__') {
      if (agentFilter === '__LOCAL__') return !a.agent_id
      return a.agent_id === agentFilter
    }
    return true
  })

  const failedCount = accounts.filter((a) => a.is_failed).length

  const columns: ColumnsType<BotAccount> = [
    {
      title: 'Agent',
      dataIndex: 'agent_id',
      key: 'agent_id',
      width: 140,
      render: (agentId: string | null) =>
        agentId
          ? <Tag icon={<ApartmentOutlined />} color="blue" style={{ fontFamily: 'monospace', fontSize: 11 }}>{agentId}</Tag>
          : <Tag color="default" style={{ fontSize: 11 }}>LOCAL</Tag>,
    },
    {
      title: t('bot.phone'),
      dataIndex: 'phone',
      key: 'phone',
      render: (phone: string) => <Text code>{phone}</Text>,
    },
    {
      title: t('bot.pushname'),
      dataIndex: 'pushname',
      key: 'pushname',
      render: (v: string | null) => v ?? <Text type="secondary">—</Text>,
    },
    {
      title: t('common.status'),
      key: 'status',
      width: 110,
      render: (_: unknown, record: BotAccount) => {
        if (record.is_running)
          return <Tag color="green" icon={<CheckCircleOutlined />}>{t('bot.running')}</Tag>
        if (record.is_failed)
          return <Tag color="red" icon={<WarningOutlined />}>{t('bot.loginFailed')}</Tag>
        return <Tag color="default">{t('bot.offline')}</Tag>
      },
    },
    {
      title: t('common.actions'),
      key: 'actions',
      fixed: 'right' as const,
      width: 200,
      render: (_: unknown, record: BotAccount) => (
        <Space size={4}>
          {record.is_running ? (
            <Tooltip title={t('startBot.stop')}>
              <Button
                size="small"
                danger
                icon={<StopOutlined />}
                loading={rowLoading[record.phone]}
                onClick={() => handleQuickStop(record.phone)}
              >
                {t('bot.stop')}
              </Button>

            </Tooltip>
          ) : (
            <Tooltip title={t('bot.quickStart')}>
              <Button
                size="small"
                type="primary"
                icon={<PlayCircleOutlined />}
                disabled={record.is_failed}
                loading={rowLoading[record.phone]}
                onClick={() => handleQuickStart(record.phone, record.agent_id)}
              >
                {t('bot.start')}
              </Button>
            </Tooltip>
          )}
          <Tooltip title={t('bot.exportSegment')}>
            <Button
              size="small"
              icon={<CloudDownloadOutlined />}
              onClick={() => handleExport([record.phone])}
            />
          </Tooltip>
          <Popconfirm
            title={t('bot.deleteAccount')}
            description={t('bot.deleteAccountDesc')}
            onConfirm={() => handleDelete(record.phone)}
            okText={t('common.delete')}
            okButtonProps={{ danger: true }}
          >
            <Button
              size="small"
              danger
              icon={<DeleteOutlined />}
              loading={rowLoading[record.phone]}
            />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const rowSelection = {
    selectedRowKeys: selectedPhones,
    onChange: (keys: React.Key[]) => setSelectedPhones(keys as string[]),
  }

  return (
    <Card
      title={t('bot.accountList')}
      style={{ marginBottom: 24 }}
      extra={
        <Space wrap>
          <Button icon={<ReloadOutlined />} onClick={load} loading={loading}>
            {t('common.refresh')}
          </Button>
          <Button
            icon={<CloudUploadOutlined />}
            onClick={() => { setImportOpen(true); setImportResult(null); setImportAgentId(null) }}
          >
            {t('common.import')}
          </Button>
          <Button
            icon={<CloudDownloadOutlined />}
            disabled={selectedPhones.length === 0}
            onClick={() => handleExport(selectedPhones)}
          >
            {selectedPhones.length > 0
              ? t('bot.batchExportCount', { count: selectedPhones.length })
              : t('bot.batchExport')}
          </Button>
          <Popconfirm
            title={t('bot.deleteFailedAccounts', { count: failedCount })}
            onConfirm={handleDeleteAllFailed}
            disabled={failedCount === 0}
            okText={t('bot.deleteAll')}
            okButtonProps={{ danger: true }}
          >
            <Button danger disabled={failedCount === 0} icon={<DeleteOutlined />}>
              {failedCount > 0
                ? t('bot.deleteFailedAccountsCount', { count: failedCount })
                : t('bot.deleteFailedAccounts', { count: 0 })}
            </Button>
          </Popconfirm>
        </Space>
      }
    >
      {contextHolder}

      {/* Search + Agent filter row */}
      <Space style={{ marginBottom: 12 }} wrap>
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索账号"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          style={{ width: 220 }}
        />
        <Select
          style={{ width: 200 }}
          placeholder="筛选 Agent"
          value={agentFilter ?? '__ALL__'}
          onChange={(v) => setAgentFilter(v === '__ALL__' ? null : v)}
          options={agentOptions}
          suffixIcon={<ApartmentOutlined />}
        />
      </Space>

      {/* Account status summary */}
      {accounts.length > 0 && (() => {
        const runningCount = accounts.filter((a) => a.is_running).length
        const failedCount2 = accounts.filter((a) => a.is_failed).length
        const offlineCount = accounts.length - runningCount - failedCount2
        return (
          <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 12px', background: '#f6ffed', border: '1px solid #b7eb8f', borderRadius: 20 }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#52c41a', display: 'inline-block' }} />
              <Text style={{ fontSize: 13, color: '#389e0d' }}>{t('bot.running')}</Text>
              <Text strong style={{ fontSize: 13, color: '#389e0d' }}>{runningCount}</Text>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 12px', background: '#fafafa', border: '1px solid #d9d9d9', borderRadius: 20 }}>
              <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#d9d9d9', display: 'inline-block' }} />
              <Text style={{ fontSize: 13, color: '#595959' }}>{t('bot.offline')}</Text>
              <Text strong style={{ fontSize: 13, color: '#595959' }}>{offlineCount}</Text>
            </div>
            {failedCount2 > 0 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 12px', background: '#fff2f0', border: '1px solid #ffccc7', borderRadius: 20 }}>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: '#ff4d4f', display: 'inline-block' }} />
                <Text style={{ fontSize: 13, color: '#cf1322' }}>{t('bot.loginFailed')}</Text>
                <Text strong style={{ fontSize: 13, color: '#cf1322' }}>{failedCount2}</Text>
              </div>
            )}
          </div>
        )
      })()}

      <Table
        dataSource={filteredAccounts}
        columns={columns}
        rowKey="phone"
        rowSelection={rowSelection}
        loading={loading}
        size="small"
        pagination={{ pageSize: 10, hideOnSinglePage: true }}
        scroll={{ x: 700 }}
        locale={{ emptyText: t('bot.emptyText') }}
      />

      {/* ── Import modal ── */}
      <Modal
        title={t('bot.import6Segment')}
        open={importOpen}
        onOk={handleImport}
        onCancel={() => { setImportOpen(false); setImportResult(null) }}
        confirmLoading={importing}
        okText={t('common.import')}
        width={560}
      >
        <Paragraph type="secondary" style={{ marginBottom: 8 }}>
          {t('bot.importFormat')}
        </Paragraph>
        <div style={{ marginBottom: 12 }}>
          <div style={{ marginBottom: 4, fontWeight: 500 }}>导入目标 Agent</div>
          <Select
            style={{ width: '100%' }}
            placeholder="本机（不指定 Agent）"
            allowClear
            value={importAgentId ?? undefined}
            onChange={(v) => setImportAgentId(v ?? null)}
            options={[
              { value: '__local__', label: '本机（不指定 Agent）' },
              ...agentList.map((a) => ({
                value: a.agent_id,
                label: (
                  <span>
                    <ApartmentOutlined style={{ marginRight: 6 }} />
                    {a.agent_id}
                    {a.online
                      ? <Tag color="green" style={{ marginLeft: 6, fontSize: 11 }}>在线</Tag>
                      : <Tag color="default" style={{ marginLeft: 6, fontSize: 11 }}>离线</Tag>}
                  </span>
                ),
              })),
            ]}
          />
        </div>
        <Input.TextArea
          rows={8}
          value={importText}
          onChange={(e) => setImportText(e.target.value)}
          placeholder={t('bot.pasteHere')}
          style={{ fontFamily: 'monospace', fontSize: 12 }}
        />
        {importResult && (
          <Alert
            style={{ marginTop: 12 }}
            type={importResult.startsWith(t('bot.importError', { msg: '' }).split(':')[0]) ? 'error' : 'success'}
            message={importResult}
            showIcon
          />
        )}
      </Modal>

      {/* ── Export modal ── */}
      <Modal
        title={t('bot.export6Segment')}
        open={exportOpen}
        onCancel={() => setExportOpen(false)}
        footer={
          <Space>
            <Button
              onClick={() => {
                navigator.clipboard.writeText(exportText)
                msgApi.success(t('common.copied'))
              }}
              disabled={!exportText}
            >
              {t('common.copyAll')}
            </Button>
            <Button onClick={() => setExportOpen(false)}>{t('common.close')}</Button>
          </Space>
        }
        width={560}
      >
        {exporting ? (
          <Spin />
        ) : (
          <Input.TextArea
            rows={8}
            value={exportText}
            readOnly
            style={{ fontFamily: 'monospace', fontSize: 12 }}
          />
        )}
      </Modal>

    </Card>
  )
}

// ────────────────────────────────────────────────────────────────────────────
// Page root
// ────────────────────────────────────────────────────────────────────────────

const BotLoginPage: React.FC = () => {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const [msgApi, contextHolder] = message.useMessage()

  const handleSuccess = useCallback(
    (jid: string) => {
      msgApi.success(t('bot.loginSuccess', { jid: jid ? ` — ${jid}` : '' }))
      setTimeout(() => navigate('/'), 2000)
    },
    [navigate, msgApi, t],
  )

  return (
    <div style={{ padding: 24, background: '#f0f2f5', minHeight: '100vh' }}>
      {contextHolder}

      {/* Section 1: Account management */}
      <AccountsSection />

      {/* Section 2: Login management */}
      <Card
        title={
          <Space>
            <QrcodeOutlined style={{ fontSize: 18 }} />
            <span>{t('bot.loginManagement')}</span>
          </Space>
        }
      >
        <Tabs
          defaultActiveKey="scan"
          items={[
            {
              key: 'scan',
              label: t('bot.scanQr'),
              children: <QrLoginTab onLoginSuccess={handleSuccess} />,
            },
            {
              key: 'linkcode',
              label: t('bot.linkCodeLogin'),
              children: <LinkCodeTab onLoginSuccess={handleSuccess} />,
            },
          ]}
        />
      </Card>
    </div>
  )
}

export default BotLoginPage
