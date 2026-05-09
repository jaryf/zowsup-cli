import apiClient from './client'
import type {
  UserProfile,
  ChatHistoryResponse,
  Statistics,
  AIThoughtsResponse,
  StrategyResponse,
  StrategyHistoryResponse,
  StrategyConflictsResponse,
  StrategyConfig,
  GroupInfo,
} from '../types'

// ---- Health ----

export async function fetchHealth(): Promise<{ status: string }> {
  const { data } = await apiClient.get('/health')
  return data
}

// ---- Contacts ----

export interface ContactSummary {
  user_jid: string
  display_name?: string | null
  push_name?: string | null
  last_message: string | null
  last_timestamp: number | null
  message_count: number
  avatar_url: string | null
  bot_jid?: string | null
}

export async function fetchContacts(): Promise<ContactSummary[]> {
  const { data } = await apiClient.get('/contacts')
  return data.contacts as ContactSummary[]
}

export async function fetchContactAvatar(
  jid: string,
): Promise<{ jid: string; avatar_url: string | null; fetched_at: number | null }> {
  const { data } = await apiClient.get('/contact/avatar', { params: { jid } })
  return data
}

export async function refreshContactAvatar(jid: string): Promise<void> {
  await apiClient.post('/contact/avatar/refresh', { jid })
}

// ---- User Profile ----

export async function fetchUserProfile(jid: string): Promise<UserProfile> {
  const { data } = await apiClient.get('/user-profile', { params: { jid } })
  return data
}

export async function patchUserProfile(
  jid: string,
  overrides: { user_category?: string | null; communication_style?: string | null },
): Promise<void> {
  await apiClient.patch('/user-profile', { jid, ...overrides })
}

// ---- Chat History ----

export async function fetchChatHistory(
  jid: string,
  page = 1,
  pageSize = 50,
): Promise<ChatHistoryResponse> {
  const { data } = await apiClient.get('/chat-history', {
    params: { jid, page, page_size: pageSize },
  })
  return data
}

// ---- Statistics ----

export async function fetchStatistics(): Promise<Statistics> {
  const { data } = await apiClient.get('/statistics')
  return data
}

// ---- AI Thoughts ----

export async function fetchUserAIThoughts(
  jid: string,
  page = 1,
  pageSize = 20,
): Promise<AIThoughtsResponse> {
  const { data } = await apiClient.get('/user-ai-thoughts', {
    params: { jid, page, page_size: pageSize },
  })
  return data
}

// ---- Strategy ----

export async function fetchStrategy(jid?: string): Promise<StrategyResponse> {
  const { data } = await apiClient.get('/strategy', { params: jid ? { jid } : {} })
  return data
}

export async function fetchStrategyHistory(jid?: string): Promise<StrategyHistoryResponse> {
  const { data } = await apiClient.get('/strategy/history', { params: jid ? { jid } : {} })
  return data
}

export async function postApplyStrategy(
  jid: string,
  config: StrategyConfig,
  note?: string,
): Promise<{ strategy_id: number; jid: string; config: StrategyConfig }> {
  const { data } = await apiClient.post('/apply-strategy', { jid, config, note })
  return data
}

export async function postApplyGlobalStrategy(
  config: StrategyConfig,
  note?: string,
): Promise<{ strategy_id: number; config: StrategyConfig }> {
  const { data } = await apiClient.post('/apply-global-strategy', { config, note })
  return data
}

export async function postRollbackStrategy(
  jid: string | null,
  steps = 1,
): Promise<{ rolled_back_to: number; jid: string | null }> {
  const { data } = await apiClient.post('/strategy/rollback', { jid, steps })
  return data
}

export async function patchToggleStrategy(id: number): Promise<{ id: number; is_active: 0 | 1 }> {
  const { data } = await apiClient.patch(`/strategy/${id}/toggle`)
  return data
}

export async function deleteStrategyRow(id: number): Promise<void> {
  await apiClient.delete(`/strategy/${id}`)
}

export async function fetchStrategyConflicts(jid: string): Promise<StrategyConflictsResponse> {
  const { data } = await apiClient.get('/strategy/conflicts', { params: { jid } })
  return data
}

// ---- Bot Control (Phase 5) ----

export interface BotStatus {
  running: boolean
  jid: string | null
  pid: number | null
  started_at: number | null
  uptime_seconds: number | null
}

export async function fetchBotStatus(): Promise<BotStatus> {
  const { data } = await apiClient.get('/bot/status')
  return data
}

export async function postBotLoginScan(): Promise<{ ok: boolean; pid: number }> {
  const { data } = await apiClient.post('/bot/login-scan')
  return data
}

export async function postBotLoginLinkcode(
  phone: string,
): Promise<{ ok: boolean; link_code: string }> {
  const { data } = await apiClient.post('/bot/login-linkcode', { phone })
  return data
}

export async function postBotLogout(phone?: string): Promise<{ ok: boolean; pid: number }> {
  const { data } = await apiClient.post('/bot/logout', phone ? { phone } : {})
  return data
}

export async function postBotStart(
  phone: string,
): Promise<{ ok: boolean; pid: number; already_running?: boolean }> {
  const { data } = await apiClient.post('/bot/start', { phone })
  return data
}

// ---- Bot Account Management ----

export interface BotAccount {
  phone: string
  pushname: string | null
  is_running: boolean
  is_failed: boolean
  failed_at: string | null
  last_seen: string | null
}

export interface ImportResult {
  line: string
  ok: boolean
  stdout: string
  stderr: string
}

export async function fetchBotAccounts(): Promise<{ accounts: BotAccount[] }> {
  const { data } = await apiClient.get('/bot/accounts')
  return data
}

export async function deleteBotAccount(phone: string): Promise<{ ok: boolean; phone: string }> {
  const { data } = await apiClient.delete(`/bot/accounts/${phone}`)
  return data
}

export async function patchToggleAccountFailed(
  phone: string,
): Promise<{ phone: string; is_failed: boolean }> {
  const { data } = await apiClient.patch(`/bot/accounts/${phone}/mark-failed`)
  return data
}

export async function deleteFailedAccounts(): Promise<{ deleted: string[]; skipped: string[] }> {
  const { data } = await apiClient.delete('/bot/accounts')
  return data
}

export async function importBotAccounts(
  lines: string[],
): Promise<{ imported: number; total: number; results: ImportResult[] }> {
  const { data } = await apiClient.post('/bot/import', { lines })
  return data
}

export async function exportBotAccounts(
  phones: string[],
): Promise<{ lines: string[]; errors: { phone: string; error: string }[] }> {
  const { data } = await apiClient.post('/bot/export', { phones })
  return data
}

// ---- Group Info ----

export async function fetchGroupInfo(jid: string): Promise<GroupInfo> {
  const { data } = await apiClient.get('/group-info', { params: { jid } })
  return data
}

// ---- Send Message ----

export interface SendMessageParams {
  to_jid: string
  message_type: 'text' | 'image' | 'video' | 'audio' | 'document'
  content?: string
  bot_jid?: string | null
  media_url?: string
  caption?: string
}

export async function sendMessage(params: SendMessageParams): Promise<{ ok: boolean; task_id: string }> {
  const { data } = await apiClient.post('/send-message', params)
  return data
}
