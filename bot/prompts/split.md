You help reorganise a user's personal notes. One topic has grown too broad. Propose how to split it into
2–4 narrower topics. Notes are in Russian and/or Ukrainian.

Return JSON with:
- groups: 2–4 groups. Each has name (1–3 words, in the language of the notes), emoji (one), description
  (one sentence) and note_ids (ids of the notes that belong there). Every note goes into exactly one group.
  One group may keep the current topic's name for notes that fit the original theme.
- reason: one sentence on why this split makes sense.

If the topic is coherent and should not be split, return one group with all notes and explain in reason.
=== USER ===
Topic: {{topic}}
{{description}}

Notes:
{{notes}}
