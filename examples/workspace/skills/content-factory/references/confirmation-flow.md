# Prompt Confirmation Flow

This skill must not generate images immediately.

## Required Flow
1. Generate all card concepts and prompts.
2. Stage each card with `image_generate(action="stage", ...)`.
3. Show only the current pending card in full detail.
4. Ask the user to use:
- `/image-confirm`
- `/image-edit <feedback>`
- `/image-skip`
5. Only after `/image-confirm` may the tool call the actual image model.

## Editing Rule
- `/image-edit <feedback>` should revise the current prompt and re-show it.
- Do not silently generate after an edit.

## Completion Rule
- When the last pending card is confirmed or skipped, clear the pending queue.
