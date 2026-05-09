import React, { useEffect, useState } from 'react'
import {
  Card,
  Form,
  Input,
  Select,
  Button,
  Typography,
  Row,
  Col,
  Tag,
  message,
  Spin,
  Divider,
  Alert,
} from 'antd'
import {
  TranslationOutlined,
  SaveOutlined,
  ExperimentOutlined,
} from '@ant-design/icons'
import { useTranslation } from 'react-i18next'
import { useDashboardStore } from '../store'
import apiClient from '../api/client'

const { Title, Paragraph, Text } = Typography

// ---- Types -----------------------------------------------------------------

interface TranslationConfig {
  provider: string
  target_lang: string
  libretranslate_url: string
  libretranslate_key: string
  deepl_key: string
  openai_key: string
  openai_api_url: string
  openai_model: string
  glm_key: string
  glm_model: string
  qwen_key: string
  qwen_model: string
}

const DEFAULT_CONFIG: TranslationConfig = {
  provider: 'auto',
  target_lang: 'zh',
  libretranslate_url: '',
  libretranslate_key: '',
  deepl_key: '',
  openai_key: '',
  openai_api_url: '',
  openai_model: 'gpt-4o-mini',
  glm_key: '',
  glm_model: 'glm-4-flash',
  qwen_key: '',
  qwen_model: 'qwen-turbo',
}

const LANGUAGES = [
  { label: '中文 (zh)', value: 'zh' },
  { label: 'English (en)', value: 'en' },
  { label: '日本語 (ja)', value: 'ja' },
  { label: '한국어 (ko)', value: 'ko' },
  { label: 'Español (es)', value: 'es' },
  { label: 'Français (fr)', value: 'fr' },
  { label: 'Deutsch (de)', value: 'de' },
  { label: 'Português (pt)', value: 'pt' },
  { label: 'العربية (ar)', value: 'ar' },
  { label: 'हिन्दी (hi)', value: 'hi' },
]

// ---- Page ------------------------------------------------------------------

const TranslatePage: React.FC = () => {
  const { t } = useTranslation()
  const [form] = Form.useForm<TranslationConfig>()
  const setTranslationTargetLang = useDashboardStore((s) => s.setTranslationTargetLang)

  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testInput, setTestInput] = useState('')
  const [testOutput, setTestOutput] = useState('')
  const [testFromLang, setTestFromLang] = useState('auto')
  const [testError, setTestError] = useState('')
  // Keys reported as "********" by the server (i.e. already configured)
  const [configuredKeys, setConfiguredKeys] = useState<Set<string>>(new Set())

  useEffect(() => {
    setLoading(true)
    apiClient
      .get('/translation/config')
      .then(({ data }) => {
        const cleaned: Partial<TranslationConfig> = {}
        const masked = new Set<string>()
        for (const [k, v] of Object.entries(data)) {
          if ((v as string) === '********') {
            masked.add(k)
            cleaned[k as keyof TranslationConfig] = '' // keep field empty so user can retype
          } else {
            cleaned[k as keyof TranslationConfig] = v as string
          }
        }
        setConfiguredKeys(masked)
        form.setFieldsValue({ ...DEFAULT_CONFIG, ...cleaned })
        if (data.target_lang) setTranslationTargetLang(data.target_lang)
      })
      .catch(() => form.setFieldsValue(DEFAULT_CONFIG))
      .finally(() => setLoading(false))
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleSave = async () => {
    let values: TranslationConfig
    try {
      values = await form.validateFields()
    } catch {
      return
    }
    setSaving(true)
    try {
      await apiClient.post('/translation/config', values)
      setTranslationTargetLang(values.target_lang)
      message.success(t('translate.saved'))
      setTestOutput('')
      setTestError('')
    } catch {
      message.error(t('translate.saveFailed'))
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    if (!testInput.trim()) return
    setTesting(true)
    setTestOutput('')
    setTestError('')
    try {
      const provider = form.getFieldValue('provider') || 'auto'
      const targetLang = form.getFieldValue('target_lang') || 'zh'
      const { data } = await apiClient.post('/translation/translate', {
        text: testInput.trim(),
        from_lang: testFromLang,
        to_lang: targetLang,
        provider,
      })
      setTestOutput(data.translated ?? '')
    } catch {
      setTestError(t('translate.testFailed'))
    } finally {
      setTesting(false)
    }
  }

  if (loading) return <Spin style={{ display: 'block', margin: '60px auto' }} />

  /** Render a form label with a green "已配置" badge if the key is saved on the server. */
  const keyLabel = (label: string, fieldName: string) => (
    <span>
      {label}
      {configuredKeys.has(fieldName) && (
        <Tag color="success" style={{ marginLeft: 6, fontSize: 11, lineHeight: '18px', padding: '0 5px' }}>
          {t('translate.configured')}
        </Tag>
      )}
    </span>
  )

  return (
    <div style={{ padding: '24px 32px', maxWidth: 820 }}>
      <div style={{ marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>
          <TranslationOutlined style={{ marginRight: 8 }} />
          {t('translate.pageTitle')}
        </Title>
        <Paragraph type="secondary" style={{ marginTop: 4, marginBottom: 0 }}>
          {t('translate.pageDesc')}
        </Paragraph>
      </div>

      {/* ── Test panel (outside Form so it doesn't interfere with config form) ── */}
      <Card
        title={
          <span>
            <ExperimentOutlined style={{ marginRight: 8 }} />
            {t('translate.testPanel')}
          </span>
        }
        size="small"
      >
        <Row gutter={12} style={{ marginBottom: 12 }}>
          <Col xs={24} sm={8}>
            <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>{t('translate.fromLang')}</div>
            <Select
              value={testFromLang}
              onChange={setTestFromLang}
              style={{ width: '100%' }}
              options={[
                { label: t('translate.autoDetect'), value: 'auto' },
                ...LANGUAGES,
              ]}
            />
          </Col>
          <Col xs={24} sm={8}>
            <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>{t('translate.targetLang')}</div>
            <Select
              value={form.getFieldValue('target_lang') || 'zh'}
              onChange={(v) => { form.setFieldValue('target_lang', v); setTranslationTargetLang(v) }}
              style={{ width: '100%' }}
              options={LANGUAGES}
            />
          </Col>
          <Col xs={24} sm={8}>
            <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>{t('translate.provider')}</div>
            <Select
              value={form.getFieldValue('provider') || 'auto'}
              onChange={(v) => form.setFieldValue('provider', v)}
              style={{ width: '100%' }}
              options={[
                { label: t('translate.providerAuto'), value: 'auto' },
                { label: 'LibreTranslate', value: 'libretranslate' },
                { label: 'DeepL', value: 'deepl' },
                { label: 'OpenAI / Compatible', value: 'openai' },
                { label: 'GLM (智谱 AI)', value: 'glm' },
                { label: 'Qwen (通义千问)', value: 'qwen' },
              ]}
            />
          </Col>
        </Row>

        <Row gutter={12}>
          <Col xs={24} sm={11}>
            <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>{t('translate.inputText')}</div>
            <Input.TextArea
              value={testInput}
              onChange={(e) => setTestInput(e.target.value)}
              placeholder={t('translate.inputPlaceholder')}
              rows={5}
              allowClear
            />
          </Col>
          <Col xs={24} sm={2} style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', paddingTop: 20 }}>
            <Button
              type="primary"
              icon={<ExperimentOutlined />}
              loading={testing}
              onClick={handleTest}
              disabled={!testInput.trim()}
            />
          </Col>
          <Col xs={24} sm={11}>
            <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>{t('translate.outputText')}</div>
            <Input.TextArea
              value={testError || testOutput}
              readOnly
              rows={5}
              status={testError ? 'error' : undefined}
              placeholder={t('translate.outputPlaceholder')}
              style={{ background: testError ? undefined : '#fafafa', color: testError ? undefined : '#222' }}
            />
          </Col>
        </Row>
      </Card>

      <br/>


      <Form form={form} layout="vertical" initialValues={DEFAULT_CONFIG}>
        <Card title={t('translate.globalSettings')} style={{ marginBottom: 16 }} size="small">
          <Row gutter={16}>
            <Col xs={24} sm={12}>
              <Form.Item name="provider" label={t('translate.provider')}>
                <Select
                  options={[
                    { label: t('translate.providerAuto'), value: 'auto' },
                    { label: 'Google Translate', value: 'google' },
                    { label: 'LibreTranslate', value: 'libretranslate' },
                    { label: 'DeepL', value: 'deepl' },
                    { label: 'OpenAI / Compatible', value: 'openai' },
                    { label: 'GLM (智谱 AI)', value: 'glm' },
                    { label: 'Qwen (通义千问)', value: 'qwen' },
                  ]}
                />
              </Form.Item>
            </Col>
            <Col xs={24} sm={12}>
              <Form.Item name="target_lang" label={t('translate.targetLang')}>
                <Select options={LANGUAGES} />
              </Form.Item>
            </Col>
          </Row>
          <Alert type="info" showIcon style={{ marginTop: 0 }} message={t('translate.globalHint')} />
        </Card>

        <Card
          title="Google Translate"
          style={{ marginBottom: 16 }}
          size="small"
          extra={<Text type="secondary" style={{ fontSize: 12 }}>{t('translate.freeNoKey')}</Text>}
        >
          <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 0 }}>
            {t('translate.googleDesc')}
          </Paragraph>
        </Card>

        <Card
          title="LibreTranslate"
          style={{ marginBottom: 16 }}
          size="small"
          extra={<Text type="secondary" style={{ fontSize: 12 }}>{t('translate.freeAndOpen')}</Text>}
        >
          <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 12 }}>
            {t('translate.libreDesc')}
          </Paragraph>
          <Row gutter={16}>
            <Col xs={24} sm={14}>
              <Form.Item name="libretranslate_url" label={t('translate.libreUrl')}>
                <Input placeholder="https://libretranslate.com" allowClear />
              </Form.Item>
            </Col>
            <Col xs={24} sm={10}>
              <Form.Item
                name="libretranslate_key"
                label={
                  <span>
                    {keyLabel(t('translate.apiKey'), 'libretranslate_key')}
                    <Text type="secondary" style={{ fontSize: 11, marginLeft: 4 }}>
                      ({t('translate.optional')})
                    </Text>
                  </span>
                }
              >
                <Input.Password placeholder={configuredKeys.has('libretranslate_key') ? t('translate.leaveBlankToKeep') : 'xxxxxxxx'} />
              </Form.Item>
            </Col>
          </Row>
        </Card>

        <Card
          title="DeepL"
          style={{ marginBottom: 16 }}
          size="small"
          extra={
            <a href="https://www.deepl.com/pro-api" target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>
              {t('translate.getKey')}
            </a>
          }
        >
          <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 12 }}>
            {t('translate.deeplDesc')}
          </Paragraph>
          <Form.Item name="deepl_key" label={keyLabel(t('translate.apiKey'), 'deepl_key')} style={{ maxWidth: 440 }}>
            <Input.Password placeholder={configuredKeys.has('deepl_key') ? t('translate.leaveBlankToKeep') : 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx:fx'} />
          </Form.Item>
        </Card>

        <Card
          title="OpenAI / Compatible API"
          style={{ marginBottom: 24 }}
          size="small"
          extra={
            <a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>
              {t('translate.getKey')}
            </a>
          }
        >
          <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 12 }}>
            {t('translate.openaiDesc')}
          </Paragraph>
          <Row gutter={16}>
            <Col xs={24} sm={10}>
              <Form.Item name="openai_key" label={keyLabel(t('translate.apiKey'), 'openai_key')}>
                <Input.Password placeholder={configuredKeys.has('openai_key') ? t('translate.leaveBlankToKeep') : 'sk-...'} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={14}>
              <Form.Item
                name="openai_api_url"
                label={
                  <span>
                    {t('translate.openaiUrl')}
                    <Text type="secondary" style={{ fontSize: 11, marginLeft: 4 }}>
                      ({t('translate.optional')})
                    </Text>
                  </span>
                }
              >
                <Input placeholder="https://api.openai.com/v1 (default)" allowClear />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="openai_model" label={t('translate.model')} style={{ maxWidth: 280 }}>
            <Input placeholder="gpt-4o-mini" allowClear />
          </Form.Item>
        </Card>

        {/* ── GLM (Zhipu AI) ── */}
        <Card
          title="GLM · 智谱 AI"
          style={{ marginBottom: 16 }}
          size="small"
          extra={
            <a href="https://open.bigmodel.cn/" target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>
              {t('translate.getKey')}
            </a>
          }
        >
          <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 12 }}>
            {t('translate.glmDesc')}
          </Paragraph>
          <Row gutter={16}>
            <Col xs={24} sm={14}>
              <Form.Item name="glm_key" label={keyLabel(t('translate.apiKey'), 'glm_key')}>
                <Input.Password placeholder={configuredKeys.has('glm_key') ? t('translate.leaveBlankToKeep') : 'xxxxxxxx.xxxxxxxx'} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={10}>
              <Form.Item name="glm_model" label={t('translate.model')}>
                <Input placeholder="glm-4-flash" allowClear />
              </Form.Item>
            </Col>
          </Row>
        </Card>

        {/* ── Qwen (Alibaba) ── */}
        <Card
          title="Qwen · 通义千问"
          style={{ marginBottom: 24 }}
          size="small"
          extra={
            <a href="https://dashscope.aliyun.com/" target="_blank" rel="noreferrer" style={{ fontSize: 12 }}>
              {t('translate.getKey')}
            </a>
          }
        >
          <Paragraph type="secondary" style={{ fontSize: 12, marginBottom: 12 }}>
            {t('translate.qwenDesc')}
          </Paragraph>
          <Row gutter={16}>
            <Col xs={24} sm={14}>
              <Form.Item name="qwen_key" label={keyLabel(t('translate.apiKey'), 'qwen_key')}>
                <Input.Password placeholder={configuredKeys.has('qwen_key') ? t('translate.leaveBlankToKeep') : 'sk-...'} />
              </Form.Item>
            </Col>
            <Col xs={24} sm={10}>
              <Form.Item name="qwen_model" label={t('translate.model')}>
                <Input placeholder="qwen-turbo" allowClear />
              </Form.Item>
            </Col>
          </Row>
        </Card>

        <Divider />

        <div style={{ marginBottom: 24 }}>
          <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>
            {t('translate.save')}
          </Button>
        </div>
      </Form>

    </div>
  )
}

export default TranslatePage