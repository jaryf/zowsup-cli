// ============================================================
// Shared TypeScript types for the Dashboard frontend
// ============================================================

export interface ChatMessage {
  id: number
  user_jid: string
  bot_jid?: string | null
  direction: 'in' | 'out'
  content: string
  message_type: string
  timestamp: number
  created_at: string
  urgency_level?: string | null
  participant?: string | null
  resolved_jid?: string | null
  notify?: string | null
  media_path?: string | null
  /** Auto-translated content, set client-side when translation toggle is on. */
  translated_content?: string | null
  /** 'ai' = AI-generated reply, 'manual' = sent by human operator, null = incoming */
  source?: string | null
}

export interface AIThought {
  id: number
  user_jid: string
  message_id: number | null
  intent: string | null
  confidence: number | null
  detected_keywords: string[]
  strategy_selected: string | null
  strategy_reasoning: string | null
  tone: string | null
  response_quality_score: number | null
  raw_thought: string | null
  urgency_level: string | null
  created_at: string
}

export interface UserProfile {
  user_jid: string
  total_interactions: number
  first_seen: string | null
  last_seen: string | null
  user_category: string | null
  user_category_is_manual: boolean
  communication_style: string | null
  communication_style_is_manual: boolean
  topic_preferences: Record<string, number>
  satisfaction_score: number | null
  trend_7d: TrendData | null
  trend_30d: TrendData | null
  current_strategy: string | null
  updated_at: string | null
}

export interface TrendData {
  direction: 'up' | 'down' | 'flat'
  change_pct: number
  data_points: number[]
}

export interface Statistics {
  total_messages: number
  active_users: number
  ai_responses: number
  today_messages: number
  online_bots?: number
}

export interface DailyStatistic {
  date: string
  total_messages: number
  incoming_messages: number
  outgoing_messages: number
  total_active_users: number
  new_users: number
  ai_responses: number
  avg_response_quality: number | null
}

export interface StrategyConfig {
  response_style?: 'formal' | 'casual' | 'concise' | 'detailed'
  tone?: 'polite' | 'friendly' | 'professional' | 'empathetic' | 'neutral'
  language?: 'auto' | 'zh' | 'en' | 'mixed'
  custom_instructions?: string
}

export interface StrategyRecord {
  id: number
  user_jid: string | null
  strategy_type: 'global' | 'personal'
  config: StrategyConfig
  version: number
  is_active: 0 | 1
  applied_at: string
  note: string | null
}

export interface StrategyConflict {
  id: number
  user_jid: string
  message_id: number | null
  conflict_type: string
  description: string | null
  resolved: 0 | 1
  created_at: string
}

export interface GroupMember {
  participant: string
  role: 'admin' | null
  notify: string | null
  msg_count: number
  last_seen: number | null
}

export interface GroupInfo {
  jid: string
  display_name: string | null
  avatar_url: string | null
  message_count: number
  first_seen: number | null
  last_seen: number | null
  synced_at: number | null
  members: GroupMember[]
}

// ---- API response wrappers ----

export interface ChatHistoryResponse {
  jid: string
  page: number
  page_size: number
  total: number
  messages: ChatMessage[]
}

export interface AIThoughtsResponse {
  jid: string
  page: number
  page_size: number
  total: number
  thoughts: AIThought[]
}

export interface StrategyResponse {
  jid: string | null
  merged_strategy: StrategyConfig
  global: StrategyConfig
  personal: StrategyConfig | null
}

export interface StrategyHistoryResponse {
  jid: string | null
  history: StrategyRecord[]
}

export interface StrategyConflictsResponse {
  jid: string
  conflicts: StrategyConflict[]
}

// ---- WebSocket event payloads ----

export interface WsNewMessagePayload {
  jid: string
  message: ChatMessage
}

export interface WsProfileUpdatedPayload {
  jid: string
  profile: UserProfile
}

export interface WsStrategyAppliedPayload {
  jid: string | null
  strategy: StrategyConfig
}
