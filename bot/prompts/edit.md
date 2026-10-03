The user replied to the bot's message about one of their notes. Decide what the reply asks to do
with that note. Replies are in Russian and/or Ukrainian.

Intents:
- move_topic: move the note to another topic ("перенеси в Киа", "это про здоровье"). Set topic_id to an
  existing topic's id; if none fits, set new_topic_name instead.
- rename: change the note's title ("назови «Ремонт катализатора»"). Set title.
- merge_with: merge this note with another note ("объедини с заметкой про катализатор").
  Set merge_query to the words that describe the other note.
- add_tag: add a tag ("тег ремонт", "добавь тег #авто"). Set tag (lowercase, without #).
- delete: delete the note ("удали", "не нужно").
- set_task_date: give the note's task a date ("это на пятницу", "напомни 15-го в 10"). Set date resolved
  against today: YYYY-MM-DD, or YYYY-MM-DDTHH:MM if a time is given.
- none: anything else — the reply adds information to the note ("и ещё: мастер сказал, что гарантия год").

Leave fields that don't belong to the chosen intent null.
=== USER ===
Today: {{today}}

Topics:
{{topics}}

The note: #{{note_id}} «{{title}}» in topic «{{topic}}»
{{summary}}

The reply:
{{text}}
