# V3.62.13 — partner program reminder

- New scheduler job `_partner_nudge` (every 2h, 08–19 UTC): active adults with proactive on, account 2+ days old, active in last 3 days get «💰 здесь можно зарабатывать реальные деньги» with their link, a share button and «💰 Моя партнёрка». Max 3 times, 10 days apart; tracked as `partner_nudge_sent`.
