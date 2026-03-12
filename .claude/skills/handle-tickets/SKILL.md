---
name: handle-tickets
description: Handle sourcehut tickets for this project — add new tickets, open a ticket (create a branch), and close a ticket (squash merge, push, close on sourcehut). Use this skill when the user wants to create, start working on, or finish a ticket.
---

# Handle Sourcehut Tickets

This project tracks work via sourcehut tickets at https://todo.sr.ht/~radium226/vpn-passthrough. Three mise tasks in `mise/tasks/` automate the full ticket lifecycle. All tasks are Python scripts run via `uv run --script` and use `hut` (the sourcehut CLI) under the hood.

---

## Add a ticket

Creates a new ticket on the sourcehut tracker.

```bash
mise run add-ticket "<subject>"
mise run add-ticket "<subject>" "<body>"
mise run add-ticket --tracker other-tracker "<subject>"
```

- `<subject>` (required): ticket title
- `[body]` (optional): description, supports Markdown
- `--tracker` (optional): defaults to `vpn-passthrough`

Run this when the user wants to file a new ticket or track a new piece of work.

---

## Open a ticket

Creates a git branch from a ticket, checks it out, and pushes it to the remote.

```bash
mise run open-ticket <ticket_id>
mise run open-ticket                   # interactive picker via fzf
```

- `[ticket_id]` (optional): if omitted, lists open tickets and lets the user pick with fzf
- `--tracker` (optional): defaults to `vpn-passthrough`

Branch naming convention: `ticket/<id>-<slugified-subject>` (e.g. `ticket/3-add-ipv6-support`).

If the branch already exists locally, it checks it out instead of creating a new one.

Run this when the user wants to start working on a ticket.

---

## Close a ticket

Squash-merges the current ticket branch into `main`, pushes, closes the ticket on sourcehut, and deletes the branch.

```bash
mise run close-ticket
```

- Must be run from a `ticket/<id>-<slug>` branch (not `main`)
- `--tracker` (optional): defaults to `vpn-passthrough`

What it does, in order:
1. Parses the current branch name to extract the ticket ID
2. Fetches the ticket subject from sourcehut
3. Checks out `main` and runs `git merge --squash <branch>`
4. Commits with message `[#<id>] <subject>`
5. Pushes `main`
6. Closes the ticket on sourcehut (status: `resolved`, resolution: `fixed`)
7. Deletes the branch locally and on the remote

Run this when the user is done with a ticket and wants to land the work.

---

## Notes

- All three tasks require `hut` to be installed and authenticated (`hut init`).
- The tracker defaults to `vpn-passthrough` but can be overridden with `--tracker`.
- These tasks are meant to be run by the user from the terminal. When the user asks you to add, open, or close a ticket, tell them the exact `mise run` command to execute rather than trying to run it yourself (since `hut` and `fzf` may need terminal access).
