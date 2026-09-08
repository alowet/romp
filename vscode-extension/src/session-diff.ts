// Reviewing a session's uncommitted changes from the current window: parse
// `git status --porcelain=v1 -z` into pickable entries. Pure decision core —
// extension.ts runs git and opens the native diff editor.
//
// Why -z: without it git C-quotes any path it considers unusual — non-ASCII
// under core.quotePath (`"notes/\351\233\252.txt"`), an embedded `"` or `\`,
// a newline — and the newline-split parser that used to live here handed that
// quoted, escaped text straight to vscode.Uri.file, which opened the wrong
// file or none. Its rename arm also split on the FIRST " -> " (a path holding
// that text mis-parsed) and looked at X alone, so an unstaged rename (" R")
// never carried its source. Under -z git emits every path raw (no quoting, no
// escapes), ends every field with NUL, and puts a rename's source in the record
// AFTER its destination — so there is nothing to unquote.

export type ChangedFile = {
  path: string;          // repo-relative, exactly as git has it
  status: string;        // porcelain XY, trimmed (e.g. "M", "A", "??", "R")
  untracked: boolean;    // no HEAD side — diff against empty
  renamedFrom?: string;  // R/C: the source path, which is the HEAD side of the diff
};

// Records are NUL-separated; each is `XY<space>path`. A rename or copy — R or C
// in EITHER column — is followed by one more record holding the source path
// (git -z emits `to\0from\0`). git never emits an empty record, so an empty one
// is the terminator's artifact (or junk) and is skipped; so is a record without
// the separating space, which no `git status -z` output contains.
export function parsePorcelain(out: string): ChangedFile[] {
  const files: ChangedFile[] = [];
  const recs = String(out || "").split("\0");
  for (let i = 0; i < recs.length; i++) {
    const raw = recs[i];
    if (raw.length < 4 || raw[2] !== " ") continue;
    const xy = raw.slice(0, 2);
    const path = raw.slice(3);
    let renamedFrom: string | undefined;
    if (xy.includes("R") || xy.includes("C")) {
      // Consume the source record, whatever its shape: a source path may itself
      // look like `XY path`, so the record filter above must not run on it.
      // A rename with no record behind it cannot come from git (it always writes
      // the source) or from gitIn (execFile rejects on a maxBuffer overflow
      // instead of handing over a truncated stdout), so this arm is defensive
      // and nothing downstream can tell it apart: renamedFrom stays unset, the
      // caller asks HEAD for the DESTINATION path, which a pure rename does not
      // have there, and the romp-git provider turns that miss into an empty
      // left side, so the file reads as wholly added. (review find, 2026-09-08)
      const from = recs[++i];
      if (from) renamedFrom = from;
    }
    files.push({ path, status: xy.trim(), untracked: xy === "??", renamedFrom });
  }
  return files;
}
