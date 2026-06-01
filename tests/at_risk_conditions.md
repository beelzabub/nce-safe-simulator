# At-Risk Condition Testing Guide

**Feature:** At-Risk Reason Column — [Issue #8](https://gitlab.com/saic-study-group/beelzabub-project/-/issues/8)

This guide explains how to manually trigger each at-risk condition so that the
reason column can be verified in the generated wiki reports.

Affected reports:
- **ART Feature Status** — `At Risk Reason` column on every Feature row
- **VS Capability Dashboard** — `At Risk Reason` column in Capability and Direct Feature detail sections
- **Risk Register** — `At Risk Reasons` column on every risk-level table row

After making any change in GitLab, re-run the relevant report (or `--report all`)
to refresh the wiki output — data is fetched live at generation time.

---

## Condition Matrix

| Condition | Indicator | Field to set | Where | Required state |
|-----------|-----------|-------------|-------|----------------|
| Behind Schedule | ⏱️ Behind Schedule | Close fewer issues than PI % elapsed | Linked issues on the Feature | Feature open, active PI |
| Past Due | 📅 Past Due | `Due date` on the epic | Epic sidebar | Epic open |
| Risk Label | 🔴/🟡/🟢 Risk Label | Apply `risk::high`, `risk::medium`, or `risk::low` | Epic labels | Any state |
| Blocked | 🔒 Blocked | Add "Blocked by" relationship | Epic relationships | Blocker must be open |
| Child Overdue | 📅 Child Overdue | `Due date` on a child Feature (past date) | Child Feature sidebar | Child Feature open |

---

## ⏱️ Behind Schedule

**Trigger:** Active-PI Feature whose `% done < % of PI elapsed`.

1. Find a Feature epic labelled with the **current** `PIID::` (e.g. `PIID::2025Q2`).
2. Confirm it has at least one linked issue with `weight > 0`.
3. Leave the majority of those issues **open** so the closed-weight fraction is below the PI's elapsed fraction.
   - Example: PI is 50 % elapsed → close fewer than 50 % of total issue weight.
4. Re-run the report — expect `⚠️ At Risk` status and `⏱️ Behind Schedule` in the reason column.

**Clear:** Close enough linked issues to push `% done ≥ % PI elapsed`, or move
the Feature's PIID label to a future PI.

---

## 📅 Past Due

**Trigger:** An open epic whose `due_date` is before today.

1. Open any Feature (or Epic/Capability for the Risk Register).
2. Epic sidebar → **Due date** → set to any date before today (e.g. `2025-01-01`).
3. Leave the epic state as **Open**.
4. Re-run — expect `📅 Past Due` in the reason column.

**Clear:** Close the epic, or push the due date into the future.

---

## 🏷️ Risk Label

**Trigger:** An epic carrying a `risk::` scoped label.

1. Open any epic (Feature, Capability, or Epic).
2. Labels → add `risk::high`, `risk::medium`, or `risk::low`.
   - If the label does not exist, create it under the group's **Labels** settings
     using that exact name (scoped labels require the `::` separator).
3. Re-run — the Risk Register groups the epic under the matching level;
   Feature/Capability detail rows show `🔴 High Risk`, `🟡 Med Risk`, or `🟢 Low Risk`.

**Clear:** Remove the risk label from the epic.

---

## 🔒 Blocked

**Trigger:** An epic with at least one open "Blocked by" relationship.

1. Open any Feature epic.
2. Scroll to **Linked items / Relationships** → **Add** → choose **is blocked by**
   → select any other open epic.
3. Re-run — expect status `🔒 Blocked` and `🔒 Blocked` in the reason column.

**Clear:** Remove the blocking relationship, or close the blocking epic (verify
whether GitLab auto-resolves the relationship when the blocker closes).

---

## 📅 Child Overdue *(Risk Register only)*

**Trigger:** A risk-labelled Epic or Capability that has a child Feature with a
past due date.

1. Find a risk-labelled Epic or Capability that has child Features.
2. Open one of those child Features → **Due date** → set to a date before today.
3. Leave the child Feature state as **Open**.
4. Re-run — in the Risk Register table the parent's reason column will show
   `📅 Child Overdue ·` prepended to any other active reasons.

**Clear:** Close the child Feature, or push its due date into the future.

---

## Combination Testing

Multiple conditions can be active simultaneously; the reason column displays all
that apply, separated by ` · `.

Example combination:
- Feature in active PI with insufficient closed issues → `⏱️ Behind Schedule`
- Same Feature also has a past due date → `⏱️ Behind Schedule · 📅 Past Due`
- Add a blocking relationship → `🔒 Blocked · ⏱️ Behind Schedule · 📅 Past Due`
