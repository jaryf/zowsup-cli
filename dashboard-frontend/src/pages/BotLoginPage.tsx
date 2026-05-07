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
} from '../api/endpoints'
import type { BotAccount } from '../api/endpoints'
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

  // Import modal
  const [importOpen, setImportOpen] = useState(false)
  const [importText, setImportText] = useState('')
  const [importing, setImporting] = useState(false)
  const [importResult, setImportResult] = useState<string | null>(null)

  // Export modal
  const [exportOpen, setExportOpen] = useState(false)
  const [exportText, setExportText] = useState('')
  const [exporting, setExporting] = useState(false)

  // One-click start modal
  const [startModalOpen, setStartModalOpen] = useState(false)
  const [startPhone, setStartPhone] = useState('')
  const [startLogs, setStartLogs] = useState<string[]>([])
  const [startPhase, setStartPhase] = useState<'starting' | 'streaming' | 'done' | 'error'>('starting')
  const esRef = useRef<EventSource | null>(null)
  const logsBottomRef = useRef<HTMLDivElement>(null)

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

  useEffect(() => {
    logsBottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [startLogs])

  // Auto-refresh every 10 s so running status stays up to date
  useEffect(() => {
    const id = setInterval(load, 10_000)
    return () => clearInterval(id)
  }, [load])

  const setRowBusy = (phone: string, busy: boolean) =>
    setRowLoading((prev) => ({ ...prev, [phone]: busy }))

  // ── One-click start ──
  const handleQuickStart = async (phone: string) => {
    esRef.current?.close()
    setStartPhone(phone)
    setStartLogs([])
    setStartPhase('starting')
    setStartModalOpen(true)

    let alreadyRunning = false
    try {
      const res = await postBotStart(phone)
      if (res.already_running) {
        alreadyRunning = true
        setStartModalOpen(false)
        msgApi.info(`Bot ${phone} 已在运行中`)
        load()
        return
      }
      setStartLogs([t('bot.startSuccess', { pid: res.pid })])
      setStartPhase('streaming')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      setStartLogs([t('bot.startFailed', { msg })])
      setStartPhase('error')
      return
    }
    if (alreadyRunning) return

    const token = getApiToken()
    const params = new URLSearchParams({ phone })
    if (token) params.set('token', token)
    const url = `/api/bot/start-stream?${params.toString()}`
    const es = new EventSource(url)
    esRef.current = es

    es.addEventListener('log', (e) => setStartLogs((p) => [...p, e.data]))
    es.addEventListener('status', (e) => {
      try {
        const p = JSON.parse(e.data) as { type: string; jid?: string; pid?: number; msg?: string }
        if (p.type === 'connected') {
          es.close()
          setStartLogs((prev) => [...prev, t('bot.connected', { jid: p.jid ?? '' })])
          setStartPhase('done')
          load()
        } else if (p.type === 'error') {
          es.close()
          setStartLogs((prev) => [...prev, t('bot.errorMsg', { msg: p.msg ?? '' })])
          setStartPhase('error')
        } else if (p.type === 'timeout') {
          es.close()
          setStartLogs((prev) => [...prev, t('startBot.logStreamEnded')])
          setStartPhase('done')
          load()
        }
      } catch { /* ignore */ }
    })
    es.onerror = () => {
      es.close()
      setStartLogs((p) => [...p, t('startBot.streamDisconnected')])
      setStartPhase('done')
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

  const closeStartModal = () => {
    esRef.current?.close()
    setStartModalOpen(false)
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
      const res = await importBotAccounts(lines)
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

  const filteredAccounts = searchQuery.trim()
    ? accounts.filter((a) => a.phone.includes(searchQuery.trim()))
    : accounts

  const failedCount = accounts.filter((a) => a.is_failed).length

  const columns: ColumnsType<BotAccount> = [
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
      width: 260,
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
                {t('startBot.stop')}
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
                onClick={() => handleQuickStart(record.phone)}
              >
                {t('bot.start')}
              </Button>
            </Tooltip>
          )}
          <Tooltip title={record.is_failed ? t('bot.unmarkFailed') : t('bot.markFailed')}>
            <Button
              size="small"
              icon={record.is_failed ? <CheckCircleOutlined /> : <WarningOutlined />}
              loading={rowLoading[record.phone]}
              onClick={() => handleToggleFailed(record.phone)}
            >
              {record.is_failed ? t('bot.unmarkFailed') : t('bot.markFailed')}
            </Button>
          </Tooltip>
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
            onClick={() => { setImportOpen(true); setImportResult(null) }}
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

      {/* Phone search */}
      <Input
        allowClear
        prefix={<SearchOutlined />}
        placeholder="搜索账号"
        value={searchQuery}
        onChange={(e) => setSearchQuery(e.target.value)}
        style={{ marginBottom: 12, maxWidth: 280 }}
      />

      {/* Running bots summary banner */}
      {accounts.some((a) => a.is_running) && (
        <div style={{ marginBottom: 12, padding: '8px 12px', background: '#f6ffed', borderRadius: 6, border: '1px solid #b7eb8f' }}>
          <Space wrap>
            <Text style={{ color: '#52c41a' }}>
              <RobotOutlined /> 运行中 ({accounts.filter((a) => a.is_running).length}):
            </Text>
            {accounts.filter((a) => a.is_running).map((b) => (
              <Tag
                key={b.phone}
                color="green"
                closable
                onClose={(e) => { e.preventDefault(); handleQuickStop(b.phone) }}
              >
                {b.phone}
              </Tag>
            ))}
          </Space>
        </div>
      )}

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

      {/* ── One-click start log modal ── */}
      <Modal
        title={t('bot.startBotTitle', { phone: startPhone })}
        open={startModalOpen}
        onCancel={closeStartModal}
        footer={
          <Button onClick={closeStartModal}>
            {startPhase === 'done' || startPhase === 'error' ? t('common.close') : t('common.cancel')}
          </Button>
        }
        width={560}
      >
        <div
          style={{
            background: '#111',
            color: '#d4d4d4',
            padding: '10px 14px',
            borderRadius: 8,
            fontFamily: 'monospace',
            fontSize: 12,
            lineHeight: 1.6,
            minHeight: 80,
            maxHeight: 300,
            overflowY: 'auto',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
          }}
        >
          {startLogs.length === 0 && startPhase === 'starting' && <Spin size="small" />}
          {startLogs.map((line, i) => <div key={i}>{line}</div>)}
          {startPhase === 'streaming' && <Spin size="small" tip={t('startBot.connecting')} style={{ marginTop: 4 }} />}
          <div ref={logsBottomRef} />
        </div>
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
