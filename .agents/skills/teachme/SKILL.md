---
name: teachme
description: Write or update a Folbum feature lesson in LEARNINGS.md when the user invokes teachme or asks to save a feature walkthrough.
---

Use the named feature if supplied. Otherwise use the feature most recently discussed or implemented. If the conversation gives no topic, inspect the current changes and ask which feature only if the target is still unclear.

Read the relevant implementation and existing lessons. Create LEARNINGS.md at the repository root if needed. Add a titled lesson, or revise the matching lesson in place, preserving other lessons and the user's notes.

Teach someone reading this code for the first time. Start with what the user can do. Explain the underlying principle in plain language, then trace one concrete example from its entry point through the actual functions to the visible or persisted result. Link to repository-relative files and name the symbols to inspect. Explain important edge cases and how the reader can verify the behavior, including the expected result. Ground claims in the current code and distinguish inferred design reasoning from documented decisions.

Finish by linking the updated lesson in chat.
