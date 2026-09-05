// Put text into the message box the way a native paste would — at the caret, over the box's own
// selection, caret left after it — and then tell the composer's bookkeeping about it. The box's
// `input` listener (render.ts) owns everything that follows ordinary typing: autosize, the
// per-tab draft and its persisted copy, the slash-command menu, the answering-vs-message cue. A
// synthetic insertion that skipped that event would leave a draft the reload forgets and a box
// that never grew. One owner here, so every non-native insertion stays in step with typing.
//
// Structural (not HTMLTextAreaElement) so a node test can hand it a plain object: the renderer
// has no jsdom harness.
export interface CaretBox {
  selectionStart: number;
  selectionEnd: number;
  setRangeText(replacement: string, start: number, end: number, selectionMode?: "select" | "start" | "end" | "preserve"): void;
  dispatchEvent(event: Event): boolean;
}

export function insertAtCaret(box: CaretBox, text: string): void {
  box.setRangeText(text, box.selectionStart, box.selectionEnd, "end");
  box.dispatchEvent(new Event("input", { bubbles: true }));
}
