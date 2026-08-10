# Reference

This page lists every command and knob. It is here for driving Romp from the
terminal, for scripting against it, and for debugging: you do not need any of it
for ordinary use, where the user interface covers everything. Everything here
runs on the machine that hosts the kernel.

## The `romp` command

Run `romp` on its own and it opens the dashboard, which is all most days need.
Every other command is a bare word after it, and a session's name is always an
argument rather than the command itself, so the two can never collide: `romp new
update` starts a session called "update".

| Command | What it does |
|---|---|
| `romp` | Open the dashboard in your browser, printing the tokened link too |
| `romp new <name>` | Start a session, run by the kernel and watched from the dashboard |
| `romp new -d <dir> <name>` | Start it in `<dir>` instead of the current folder |
| `romp new -t <name>` | Start it as a terminal (tmux) session and attach; add `--detach` to leave it running |
| `romp resume` | Resume a past conversation, chosen from a full-screen picker |
| `romp status` | Manager and kernel status |
| `romp refresh` | Restart the postal bus and every kernel, picking up new code |
| `romp update [host…]` | Push this machine's committed Romp to attached remotes and restart them |
| `romp up` | Run the kernel manager in the foreground; rare, since the login service runs it |
| `romp version` | Version report across the moving parts |
| `romp help` | The same list, from the terminal |

These are for scripting and for agents rather than daily use:

| Command | What it does |
|---|---|
| `romp url` | Print only the tokened dashboard URL, for piping |
| `romp sessions [--json]` | The fleet with each session's state, identity colours, directory and backend |
| `romp mail …` | The postal service from the shell (below) |
| `romp send <session> <text>` | Hand a session a message, on either backend |
| `romp interrupt <session>` | Interrupt whatever turn a session is taking |
| `romp end <session>` | End a session |
| `romp checkin <host>` / `romp checkout <host>` | Publish this machine to an attached hub, or withdraw it |
| `romp default-dir [PATH]` | The default working directory for new sessions; no argument prints it, `""` clears it |
| `romp debug [on\|off\|status]` | Judge debug mode, where rejection rows carry the full input and reply |
| `romp resume <id> [--name <n>] [--detach]` | Resume one exact conversation by UUID |
| `romp refresh --now` | Refresh without waiting for sessions to finish their turns |

Two things to know before building on `romp sessions --json`. **`waiting` means
at rest**, the ordinary state of a session that has finished its turn, so
matching it as an alert badges the whole idle fleet as needing you; the states
that want a person are `awaiting`, a permission prompt, and `blocked`. And
**`id` is the durable key**, not `lastSid`: everything Romp files per session is
keyed by `id`, while `lastSid` is the live transcript's id and forks on
`/clear`.

That key opens the per-session records under `~/.local/state/romp/`. The
per-turn one-liners live in `captions/<id>.jsonl`, one JSON record a line, with
the text under `caption`. A record's own `id` field is not the session's: it
identifies the turn within it. There is no `summaries/` directory; an older
layout had one, and reading it fails silently, since a missing directory just
yields nothing rather than an error.

## The Romp Postal Service

How sessions message each other, from either side. Inside a session it is an MCP
server, so an agent calls the tools below directly; from a terminal the same
mailbox is behind `romp mail`. See
[Inter-agent communication](guide.md#inter-agent-communication-the-romp-postal-service)
for what it is for.

### Mail from the terminal

```bash
romp mail send [--kind delegate|coordinate|question] <name> "<text>"
romp mail inbox                  # read your messages, and clear them
romp mail peek                   # read them without clearing
romp mail agents                 # who is live, their branch and working-note
romp mail working "<note>"       # publish what this session is working on
romp mail sent                   # your sent messages, and whether each was read
romp mail recall <to> [id]       # unsend a message the recipient has not read
romp mail remote                 # connect this remote machine to your laptop's bus
```

### Mail inside a session (MCP tools)

| Tool | What it does |
|---|---|
| `send_message(to, body, kind)` | Message a live session by name; `kind` declares delegate / coordinate / question |
| `check_inbox()` | Read messages sent to you (also delivered at the end of each turn) |
| `list_agents()` | The live sessions, each with its branch and working-note |
| `set_working(text)` | Publish what you hold so peers steer clear |
| `check_sent()` | Whether your sent messages were read yet |
| `recall_message(to, id?)` | Unsend a message the recipient hasn't read |

## Configuration

### Folder click, in your terminal or editor

The chat statusline shows the session's working directory; clicking it opens
that folder. The default is the OS opener (`open` / `xdg-open`). To open it
elsewhere, set a command via the env var `ROMP_OPEN_FOLDER` or the first
non-comment line of `~/.config/romp/open-folder`; `{dir}` is replaced with
the clicked path (omitted, the path is appended). The command runs on the
kernel's machine.

```bash
# ~/.config/romp/open-folder: pick one line
open -a Ghostty {dir}               # macOS: a new Ghostty window there
ghostty --working-directory={dir}   # Linux: Ghostty
code {dir}                          # VS Code instead
```

### Wording the follow-up, per session

When a session stalls, romp asks it where the work stands ([automatic
nudges](guide.md#automatic-nudges)). One sentence serves every session. To give
one session its own wording, add a `text` map to
`${XDG_STATE_HOME:-~/.local/state}/romp/auto-nudge.json`, keyed by the session
name shown on its tab (case doesn't matter) or by its id:

```json
{
  "text": {
    "web": "Say it in one line if you can.",
    "api": {"mode": "replace", "text": "Where are we, and what do you need from me?"}
  }
}
```

A bare string is **appended** after romp's ask. `"mode": "replace"` sends yours
instead. Edits take effect on the next nudge; no restart.

Prefer appending. The reply to a follow-up is what tells romp whether the work
finished or needs you, so an ask that requests no status leaves nothing to read
and the card sits stalled. Replace when your own wording asks for the same
thing better, not to turn the follow-up into something other than a question.

### Install-time switches

For `./install.sh`:

- `ROMP_NO_SERVICE=1` skips the login service.
- `ROMP_NO_EXT=1` skips the VS Code / Cursor extension.
- `ROMP_NO_SDK=1` skips the SDK backend's venv (tmux sessions still work).

For the one-line installer (`bootstrap.sh`), which passes all of the above
through to `install.sh`:

- `ROMP_DIR=<path>` where to clone; default `~/romp`.
- `ROMP_REF=<tag|branch>` install a specific ref; default is the newest `v*`
  release tag, falling back to `main` when none is published.
- `ROMP_NO_PATH=1` leaves your shell rc alone.

### Ports

- `ROMP_KERNEL_PORT=<port>` moves the kernel and its dashboard off the default
  `29855`. `ROMP_SERVE_PORT` is a second name for the same port, the one the
  manager and the supervised service use. Set either and the other follows; set
  both to different values and the kernel refuses to start rather than picking
  one for you.
- `ROMP_POSTAL_PORT=<port>` moves the postal bus off the default `25302`.

Set these if something else on the machine already holds the default. Both have
to agree across everything that talks to the kernel, so export them where the
whole environment sees them rather than for one command.

Run `romp-service install` again after changing one. The service unit bakes in
whatever is set at install time, so a renumbered port that only lives in your
shell leaves the supervised manager on the old one, and the two collide.

## Where things live

State is written under `${XDG_STATE_HOME:-~/.local/state}/romp/`. Transcripts
are read in place from where Claude Code writes them (`~/.claude/projects/`)
and never copied.

## Switches

Effective immediately, no restart.

`touch` to **disable**, `rm` to re-enable:

- `~/.claude/romp-postal-off`: the postal service

`touch` to **enable**, `rm` to turn back off:

- `~/.claude/romp-summarize-on`: the live tmux activity phrase. Off by default,
  because it spends tokens on every turn and the SDK backend reports what a
  session is doing without it.
