/**
 * ContactList — Storybook stories
 *
 * Uses `loaders` to pre-seed the Zustand store **before** the component
 * renders, so ContactList always sees the correct contacts on its first paint.
 */
import type { Meta, StoryObj } from '@storybook/react'
import { useDashboardStore } from '../../store'
import ContactList from './ContactList'

// ContactEntry shape (mirrors the store's internal interface)
interface ContactEntry {
  jid: string
  display_name: string
  last_message: string | null
  last_timestamp: number | null
  unread: number
}

// ----- Meta -----

const meta = {
  title: 'Components/ContactList',
  component: ContactList,
  tags: ['autodocs'],
  decorators: [
    (Story) => (
      <div style={{ width: 280, height: 600, border: '1px solid #f0f0f0' }}>
        <Story />
      </div>
    ),
  ],
  parameters: {
    layout: 'centered',
    docs: {
      description: {
        component:
          'Left-panel contact list. Contacts are derived from the Zustand store and can be filtered by name or phone number.',
      },
    },
  },
} satisfies Meta<typeof ContactList>

export default meta
type Story = StoryObj<typeof meta>

// ----- Stories -----

export const Empty: Story = {
  loaders: [
    async () => {
      useDashboardStore.setState({ contacts: [], selectedJid: null })
      return {}
    },
  ],
  name: 'Empty state',
}

export const FewContacts: Story = {
  loaders: [
    async () => {
      const contacts: ContactEntry[] = [
        {
          jid: '8613800138000@s.whatsapp.net',
          display_name: 'Alice',
          last_message: '你好！',
          last_timestamp: Math.floor(Date.now() / 1000) - 300,
          unread: 0,
        },
        {
          jid: '8613900139000@s.whatsapp.net',
          display_name: 'Bob',
          last_message: '在吗？',
          last_timestamp: Math.floor(Date.now() / 1000) - 60,
          unread: 3,
        },
      ]
      useDashboardStore.setState({ contacts, selectedJid: null })
      return {}
    },
  ],
  name: 'A few contacts',
}

export const ManyContacts: Story = {
  loaders: [
    async () => {
      const now = Math.floor(Date.now() / 1000)
      const contacts: ContactEntry[] = Array.from({ length: 20 }, (_, i) => ({
        jid: `8613800138${String(i).padStart(3, '0')}@s.whatsapp.net`,
        display_name: `Contact ${i + 1}`,
        last_message: i % 2 === 0 ? `Last message from contact ${i + 1}` : null,
        last_timestamp: i % 2 === 0 ? now - i * 120 : null,
        unread: i % 3 === 0 ? i + 1 : 0,
      }))
      useDashboardStore.setState({ contacts, selectedJid: null })
      return {}
    },
  ],
  name: 'Many contacts (scrollable)',
}
