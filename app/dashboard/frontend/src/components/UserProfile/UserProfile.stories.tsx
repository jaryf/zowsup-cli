/**
 * UserProfile — Storybook stories
 *
 * Uses `loaders` to pre-seed the Zustand store **before** the component
 * renders.  Note: UserProfile makes a live API call on mount (selectedJid
 * change).  If no backend is running the profile will briefly flash before
 * resetting to the empty state — this is expected in isolation.
 */
import type { Meta, StoryObj } from '@storybook/react'
import { useDashboardStore } from '../../store'
import UserProfile from './UserProfile'
import type { UserProfile as UserProfileType } from '../../types'

// ----- Sample data -----

const JID = '8613800138000@s.whatsapp.net'

const RICH_PROFILE: UserProfileType = {
  user_jid: JID,
  total_interactions: 237,
  first_seen: '2025-01-01T00:00:00',
  last_seen: '2026-04-28T14:30:00',
  user_category: 'vip',
  user_category_is_manual: true,
  communication_style: 'casual',
  communication_style_is_manual: false,
  topic_preferences: { travel: 0.45, food: 0.3, shopping: 0.25 },
  satisfaction_score: 0.82,
  trend_7d: { direction: 'up', change_pct: 12.5, data_points: [10, 11, 14, 15, 18, 20, 22] },
  trend_30d: { direction: 'flat', change_pct: 2.1, data_points: [] },
  current_strategy: 'friendly',
  updated_at: '2026-04-28T14:35:00',
}

const MINIMAL_PROFILE: UserProfileType = {
  user_jid: JID,
  total_interactions: 1,
  first_seen: '2026-04-28T10:00:00',
  last_seen: '2026-04-28T10:00:00',
  user_category: null,
  user_category_is_manual: false,
  communication_style: null,
  communication_style_is_manual: false,
  topic_preferences: {},
  satisfaction_score: null,
  trend_7d: null,
  trend_30d: null,
  current_strategy: null,
  updated_at: null,
}

// ----- Meta -----

const meta = {
  title: 'Components/UserProfile',
  component: UserProfile,
  tags: ['autodocs'],
  decorators: [
    (Story) => (
      <div style={{ width: 360, minHeight: 500 }}>
        <Story />
      </div>
    ),
  ],
  parameters: {
    layout: 'centered',
    docs: {
      description: {
        component:
          'Right-panel user portrait card. Shows AI-computed sentiment, topic preferences, and provides controls for strategy management.',
      },
    },
  },
} satisfies Meta<typeof UserProfile>

export default meta
type Story = StoryObj<typeof meta>

// ----- Stories -----

export const RichProfile: Story = {
  loaders: [
    async () => {
      useDashboardStore.setState({
        selectedJid: JID,
        profile: RICH_PROFILE,
        profileLoading: false,
      })
      return {}
    },
  ],
  name: 'Rich profile (all fields)',
}

export const MinimalProfile: Story = {
  loaders: [
    async () => {
      useDashboardStore.setState({
        selectedJid: JID,
        profile: MINIMAL_PROFILE,
        profileLoading: false,
      })
      return {}
    },
  ],
  name: 'Minimal profile (new user)',
}

export const NoSelection: Story = {
  loaders: [
    async () => {
      useDashboardStore.setState({
        selectedJid: null,
        profile: null,
        profileLoading: false,
      })
      return {}
    },
  ],
  name: 'No contact selected',
}
