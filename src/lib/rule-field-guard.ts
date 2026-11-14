/**
 * Guard for STAGED Lane A apply scripts (rule field proposed, code that reads it
 * not yet landed).
 *
 * WHY THIS EXISTS: scripts/apply-v73-c200-cheap-band-clip.ts used `field: "..."
 * as const` against `RuleChangeProposal.field: keyof Rules` as a compile-time
 * interlock — "the field name will not even typecheck until the readers land, so
 * a field stored but read by nothing is impossible." The interlock worked and was
 * correct, but it turned `npx tsc --noEmit` red for the WHOLE REPO from v73's
 * proposal (2026-11-12) onward, i.e. it broke the finish condition every other
 * session's work is verified against. A guard must not cost the gate it sits in.
 *
 * So the same two questions are asked at RUNTIME, before anything is written:
 *   1. is the field a real member of the Rules shape (present in DEFAULT_RULES)?
 *      If not, a RuleSet write would be stored in rulesJson and read by nobody.
 *   2. does any module OTHER than the rules definition mention the field?
 *      A field can be in DEFAULT_RULES and still be inert; this is the check that
 *      actually catches "stored but nothing reads it".
 * Both refuse loudly (nonzero exit at the call site) instead of silently no-oping.
 *
 * Rollback: delete this module and the two guard calls in the apply script; the
 * compile-time error returns (the pre-2026-11-13 behaviour).
 */
import { DEFAULT_RULES, type Rules } from "./rules";

export class UnimplementedRuleFieldError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "UnimplementedRuleFieldError";
  }
}

/** Own-property test — an inherited member like "toString" is NOT a rule field. */
export function isRuleFieldImplemented(
  field: string,
  rules: Record<string, unknown> = DEFAULT_RULES as unknown as Record<string, unknown>
): field is keyof Rules {
  return Object.prototype.hasOwnProperty.call(rules, field);
}

export function assertRuleFieldImplemented(
  field: string,
  rules: Record<string, unknown> = DEFAULT_RULES as unknown as Record<string, unknown>
): void {
  if (!isRuleFieldImplemented(field, rules)) {
    throw new UnimplementedRuleFieldError(
      `rule field "${field}" is NOT implemented: it is absent from DEFAULT_RULES, so writing it to a RuleSet would store a value that nothing reads. Land the code edits that add AND consume the field, then re-run.`
    );
  }
}

/**
 * Number of mentions of `field` in the given source texts, excluding the module
 * that DEFINES the Rules shape (a definition is not a reader).
 */
export function countRuleFieldReaders(field: string, sources: Array<{ path: string; text: string }>): number {
  const needle = new RegExp(`\\b${field.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`);
  let n = 0;
  for (const s of sources) {
    if (/(^|\/)rules\.ts$/.test(s.path)) continue;
    if (needle.test(s.text)) n++;
  }
  return n;
}

export function assertRuleFieldHasReader(field: string, readers: number): void {
  if (readers <= 0) {
    throw new UnimplementedRuleFieldError(
      `rule field "${field}" is declared but READ BY NOTHING outside src/lib/rules.ts (${readers} reader files) — the change would be a silent no-op. Add the consumer first, then re-run.`
    );
  }
}
