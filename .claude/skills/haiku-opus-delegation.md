---
name: opus-code-task
description: Delegate code writing to Opus for complex tasks
model: opus
user_invocable: false
---

# Haiku → Opus Code Delegation

Haiku invokes this skill when code writing is complex or involves multiple files/systems. Opus handles the implementation; Haiku coordinates and verifies.

## When to delegate

- Multi-file refactors or features
- New subsystems (routes, services, pages)
- Cross-layer changes (DB migrations + API + web)
- Architecture decisions needing detailed analysis
- Large test suites

## When to handle inline (Haiku)

- Single-file edits
- Small bug fixes
- Config changes
- Documentation updates
- Review and verification

## Usage

Haiku spawns an Agent with `subagent_type: "opus"` and brief description, including:
- What to build (not how)
- Constraints (locked decisions, existing patterns)
- Expected output (files, tests, migrations)
- Link to CLAUDE.md if needed

Opus works in an isolated worktree, commits locally, does not push. Haiku reads result, verifies tests pass, then decides to merge or ask for changes.

## Example

```javascript
Agent({
  subagent_type: "opus",
  description: "Build phase 4b execute page (Angular)",
  prompt: `Build /command execute page (Angular component).
  - List saved commands (admin), execute on selected Pis
  - Per-Pi output table (exit code, stdout, stderr)
  - Progress bar during execution
  - Link to /actions/{id} for details
  Stack: Ionic 9 + Angular 22 (like other pages)
  Tests: unit only (local, no server)
  See CLAUDE.md for auth/roles/architecture`
})
```

Haiku then reads the branch, checks tests, decides merge.
