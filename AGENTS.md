# SRC-LEARNING Agent Instructions

## Graft context map

This repository is indexed by Graft. For every feature, bug fix, refactor,
test change, or review, use Graft before broad source exploration or editing.

### Development gate

1. Start with the smallest relevant query: `graft ask "<question>" --source`
   for behavior discovery, `graft grep "<symbol>"` for a known symbol, or
   `graft map` for unfamiliar architecture work.
2. Before a rename, deletion, signature change, or multi-file refactor, run
   `graft callers <symbol> --depth all` and include every affected caller in
   the change plan.
3. Implement only after Graft has identified the relevant symbols and files.
4. Run the narrowest relevant Python/PyQt5 tests, then run `graft check`.
5. Report changed symbols, tests, remaining risks, and Graft token savings.

### Command reference

- `graft map` for a repository overview.
- `graft ask "<question>" --source` when locating where a behavior lives.
- `graft grep "<symbol-or-literal>"` when every occurrence matters.
- `graft callers <symbol> --depth 2` for a normal impact check.
- `graft callers <symbol> --depth all` before renames, deletions, signature
  changes, or multi-file refactors.
- `graft check` when verifying that the graph is fresh.

The generated `graft/` directory is a local, regenerable cache and must not be
committed. This app is Python/PyQt5; do not introduce Node.js or web frontend
tooling for the SRC-LEARNING UI unless the user explicitly asks for a separate
web project.

## Local branch and Git ownership

- The required development branch for SRC-LEARNING is
  `local/ver2.1-integration`.
- Codex must verify the active branch and working-tree status before editing.
  If the active branch is different, stop before changing files.
- Antigravity is a UI implementation assistant only. It may edit UI-related
  source files in this workspace, but it must not run Git commands or modify
  Git state.
- Antigravity must not create or switch branches, create worktrees, commit,
  stash, merge, rebase, pull, push, reset, tag, or edit anything inside `.git`.
- Antigravity must open the checked-out `SRC-LEARNING` repository root
  directly. It must not create or use a separate Antigravity worktree.
- Codex is responsible for reviewing changes, running tests, and performing
  Git operations only when explicitly authorized by the user.
- Never commit or push local agent configuration from `.agents/`.

## UI V3 collaboration contract

- Figma file: `https://www.figma.com/design/8pN0vZFtubvtTE1XCgMLdi`
- Figma is the UI/UX source of truth for V3.
- Codex is the technical lead: it owns architecture, primary Figma
  orchestration, scopes work with Graft, reviews GAnti changes, runs acceptance
  tests, and manages Git only when the user authorizes it.
- GAnti is the PyQt5 UI implementation assistant: it reads approved Figma
  frames through the local `figma-desktop` MCP server and implements only the
  permitted Python UI scope.
- The workspace does not disable Figma write tools for GAnti. GAnti may write
  only when the official Figma MCP server exposes the required tool to the
  Antigravity client and the user has supplied an exact file/frame scope.
- If the official server does not expose `use_figma`, the canvas change must be
  handed to Codex; local permission settings cannot manufacture a missing
  server-side tool.
- Before handing a V3 screen to GAnti, follow
  `docs/UI_V3_FIGMA_HANDOFF.md` and provide a Figma frame/node plus acceptance
  criteria.
