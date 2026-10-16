# V3.62.7 — one-tap answers under her first hello

Funnel 30d: 177 /start → 140 accepted 18+ → 70 wrote a first message. Her
hello after 18+ already asked a question, but the user had to invent an
answer. Three inline buttons («привет 🙂», «расскажи о себе», «мне скучно 😏»)
now sit under the hello; a tap removes them and goes through the normal chat
pipeline as his message (counts as chat_user_message), plus a
`first_reply_tapped` event.
