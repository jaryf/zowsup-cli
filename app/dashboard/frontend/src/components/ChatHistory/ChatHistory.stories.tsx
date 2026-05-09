/**
 * ChatHistory — Storybook stories
 *
 * Uses `loaders` to pre-seed the Zustand store **before** the component
 * renders, so ChatHistory always sees the correct state on its first paint.
 */
import type { Meta, StoryObj } from '@storybook/react'
import { useDashboardStore } from '../../store'
import ChatHistory from './ChatHistory'
import type { ChatMessage } from '../../types'

// ----- Sample data -----

const JID = '8613800138000@s.whatsapp.net'
const now = Math.floor(Date.now() / 1000)

function msg(id: number, direction: 'in' | 'out', content: string, offset = 0): ChatMessage {
  return {
    id,
    user_jid: JID,
    direction,
    content,
    message_type: 'text',
    timestamp: now - offset,
    created_at: new Date((now - offset) * 1000).toISOString(),
  }
}

// Newest-first (index 0 = newest) — matches the ORDER BY timestamp DESC
// that the API returns, and what the inverted-list renderer expects.
const SAMPLE_MESSAGES: ChatMessage[] = [
  msg(6, 'out', '价格非常实惠，具体如下：……', 2900),
  msg(5, 'in', '价格怎么样？', 3000),
  msg(4, 'out', '当然，我们的产品主要包括……', 3450),
  msg(3, 'in', '我想了解一下你们的产品。', 3500),
  msg(2, 'out', '您好！有什么可以帮您？', 3550),
  msg(1, 'in', '你好！', 3600),
]

// ----- Meta -----

const meta = {
  title: 'Components/ChatHistory',
  component: ChatHistory,
  tags: ['autodocs'],
  decorators: [
    (Story) => (
      <div style={{ width: 480, height: 600, border: '1px solid #f0f0f0' }}>
        <Story />
      </div>
    ),
  ],
  parameters: {
    layout: 'centered',
    docs: {
      description: {
        component:
          'Centre-panel chat transcript. Incoming messages appear on the left; bot replies appear on the right with a green background.',
      },
    },
  },
} satisfies Meta<typeof ChatHistory>

export default meta
type Story = StoryObj<typeof meta>

// ----- Stories -----

export const Default: Story = {
  loaders: [
    async () => {
      useDashboardStore.setState({
        selectedJid: JID,
        messages: SAMPLE_MESSAGES,
        messagesPage: 1,
        messagesTotal: SAMPLE_MESSAGES.length,
        messagesLoading: false,
      })
      return {}
    },
  ],
  name: 'Default conversation',
}

export const EmptyConversation: Story = {
  loaders: [
    async () => {
      useDashboardStore.setState({
        selectedJid: JID,
        messages: [],
        messagesPage: 1,
        messagesTotal: 0,
        messagesLoading: false,
      })
      return {}
    },
  ],
  name: 'Empty (no messages)',
}

export const LongConversation: Story = {
  loaders: [
    async () => {
      // Newest-first: reverse so index 0 = newest (smallest offset = most recent)
      const longMessages = Array.from({ length: 30 }, (_, i) =>
        msg(i + 1, i % 2 === 0 ? 'in' : 'out', `Message number ${i + 1}`, 3600 - i * 60),
      ).reverse()
      useDashboardStore.setState({
        selectedJid: JID,
        messages: longMessages,
        messagesPage: 1,
        messagesTotal: longMessages.length,
        messagesLoading: false,
      })
      return {}
    },
  ],
  name: 'Long conversation (scroll)',
}
