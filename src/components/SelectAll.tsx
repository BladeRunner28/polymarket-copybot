"use client";

/**
 * SelectAll — toggles the bulk-approval checkboxes.
 *
 * WHY A CLIENT COMPONENT FOR ONE BUTTON: the queue page is a server component and React forbids event
 * handlers there, but "tick all 25" is worth having. This touches the DOM directly instead of holding
 * React state, so the checkboxes stay uncontrolled and the form keeps working with JavaScript off —
 * the server-rendered checkboxes and submit buttons need no JS at all.
 */
export function SelectAll({ formId, count }: { formId: string; count: number }) {
  function toggle() {
    const form = document.getElementById(formId);
    if (!form) return;
    const boxes = Array.from(
      form.querySelectorAll<HTMLInputElement>('input[name="id"]')
    );
    const allOn = boxes.length > 0 && boxes.every((b) => b.checked);
    for (const box of boxes) box.checked = !allOn;
  }

  return (
    <button
      type="button"
      onClick={toggle}
      className="rounded border border-neutral-700 px-3 py-1.5 text-sm text-neutral-300 hover:text-white"
    >
      Toggle all ({count})
    </button>
  );
}
