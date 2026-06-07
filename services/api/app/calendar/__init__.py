"""Read-only iCalendar (ICS) subscription feed of a user's IP deadlines.

A per-user, unguessable token authorises an unauthenticated feed
(GET /calendar/feed/<token>.ics) that Google Calendar, Outlook and Apple
Calendar can subscribe to. The feed surfaces case deadlines and renewal
due dates as VEVENTs with VALARM reminders, so the IP Agent's reminders
also appear in counsel's external calendar.
"""
