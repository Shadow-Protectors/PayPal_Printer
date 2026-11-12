# UI writing preferences

- Keep UI text concise, professional, and focused on the user's task.
- Prefer clear labels and short action messages over explanatory paragraphs.
- Do not add routine workflow instructions, implementation details, or redundant subtitles to pages and forms.
- Show helper text only when needed for a meaningful decision or to prevent an input error; keep it brief and close to the relevant field.
- Fully implement requested functionality, but do not expose the user's instructions, implementation details, internal logic, or technical explanations in the application UI unless explicitly requested or essential to the user experience.
  Do not unnecessarily use emojis anywhere in the interface.
- Do not add unnecessary instructional text explaining what a button, feature, API, function, or operation does. Avoid narration such as "This will delete all associated records...", "Clicking this button will...", "This action removes X, Y, and Z...", or "This feature works by...".
- Keep confirmations brief: identify the action and selected record, with clear action buttons. Explain consequences only when essential to the user's decision; omit internal tables and implementation steps.
- Keep technical explanations in chat responses or developer documentation. Before finishing UI changes, remove redundant explanations while preserving necessary validation, accessibility labels, and essential warnings.
