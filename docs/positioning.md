# Nivvi Positioning

## Category Definition

Nivvi is an AI money manager.

It is not a tracker, a neobank, a dashboard-only aggregator, or a chatbot that stops at advice. Nivvi understands a household's full financial picture, decides what matters across domains, prepares the right action, and executes after approval.

## Canonical Problem Statement

People juggle multiple accounts, cards, loans, investments, bills, and tax obligations without a single view or plan. They rely on spreadsheets or siloed apps that track spending or handle one task, but cannot coordinate cash flow, deadlines, or goals. The result is missed bills, idle cash, unnecessary fees, under-saving, and too much financial admin.

## Canonical Solution Statement

Nivvi is an agentic, supervised AI money manager for the whole household financial system. It connects to the financial products you already use, builds a unified view of your money, identifies what matters most, prepares the right action across providers, and handles it once you approve. It manages cash flow, bills, debt, taxes, and investing decisions as one system, not five separate problems.

## One-Sentence Positioning

Nivvi is an agentic, supervised AI money manager for the whole household financial system.

## What Nivvi Is

- A single operating layer for accounts, liabilities, investments, bills, deadlines, and goals.
- A system that reasons across domains instead of optimizing each money task in isolation.
- A supervised execution product that drafts and dispatches approved financial actions.
- A continuous management loop that monitors, adapts, and follows through over time.

## Locked Capability: Portfolio Opportunity Intelligence

Nivvi includes portfolio opportunity intelligence as a core money-management capability.

- Detects underperforming holdings and opportunity alternatives within a user-approved strategy scope.
- Optimizes proposed moves against mandate, risk limits, liquidity constraints, and tax impact.
- Drafts explicit sell/buy actions with impact previews before execution.
- Executes only after approval and suitability/policy gates pass.
- Does not default to momentum chasing or autonomous discretionary trading.

## What Nivvi Is Not

- Not a neobank that mainly sells accounts, cards, or deposits.
- Not a passive spending tracker or read-only dashboard.
- Not an AI assistant that answers questions but leaves all work with the user.
- Not a discretionary asset manager that moves money without approval.
- Not a tax filing engine pretending to replace regulated submission partners.

## Why This Category Exists

Most personal finance products solve one thin slice of the problem.

- Trackers show what already happened.
- Advisors tell you what to do next.
- Automation tools move one category of money on preset rules.
- Control towers aggregate accounts but still leave action-taking with the user.

Households do not need more fragmented money software. They need a manager that can understand the full system, prioritize tradeoffs, and handle the work with supervision.

That is the gap Nivvi exists to fill.

## Decision Ladder

- Tracker: shows what happened.
- Advisor: tells you what to do.
- Money manager: prepares and executes approved actions.

Nivvi only matters if it is the third one.

## Advisor-to-Agent Loop

1. Understand the current state across all connected money data.
2. Build and maintain a household plan using forecasts, obligations, and goals.
3. Recommend the next best move with rationale, confidence, and expected impact.
4. Request explicit approval before any consequential execution.
5. Execute through the right regulated partner rails.
6. Monitor outcomes, detect drift or anomalies, and adapt the plan.

## Household Mandate Layer

Nivvi is not complete until each customer has an explicit mandate that the system uses to decide what "better" means.

- Mandate defines priorities: liquidity safety, debt reduction, growth, tax timing, and deadline protection.
- Mandate sets constraints: risk limits, blocked actions, concentration caps, and approval requirements.
- Mandate prevents shallow optimization (for example, chasing yield while creating cashflow risk).
- Every recommendation and execution path is evaluated against the active mandate.

## Opportunity Intelligence Layer

Nivvi must continuously produce high-quality opportunity signals, not just snapshots of balances.

- Detects opportunities and risks across rates, bills, debt cost, tax timing, and portfolio drift.
- Scores each signal by expected impact, urgency, confidence, and mandate fit.
- Prioritizes signals into a ranked next-best-action queue.
- Keeps continuity during connector disruption using provider failover and last-good-state planning.

## Playbook Engine and Outcome Scoreboard

Signals only matter if they reliably turn into completed outcomes.

- Playbooks convert a signal into a managed run: detect, prepare, approve, execute, monitor, close.
- Each run is traceable to source facts, approvals, provider execution artifacts, and final outcome.
- Outcome scoreboard compares expected vs realized impact to improve future prioritization quality.
- Nivvi’s quality bar is completed approved outcomes, not message volume or dashboard activity.

## Why People Will Trust This

- Consequential actions require explicit approval before execution.
- Connector failures do not collapse the plan; provider failover and partial continuity are first-class.
- Regulated partner rails handle execution where licenses are required.
- Recommendations, approvals, and outcomes remain visible through an audit trail.

## Why People Will Pay

- Nivvi is a subscription-first product, not a lead funnel for deposits, cards, or hidden spreads.
- The business model is aligned with the user: better management, less fragmentation, less busy work.
- Nivvi does not need to push financial products to make the product work.

## Focus Discipline

- Consumer household money management is the product.
- Company finance and QuickBooks-style back office workflows are out of scope for now.
- DEX, prediction-market, and trading-agent positioning are out of scope for now.

## Product Principle

Connector failure must degrade gracefully, never collapse the household plan.

## V1 Must Include

- Unified money graph across accounts, bills, debt, investments, deadlines, and goals.
- Cross-domain prioritization instead of separate budget, tax, and investing silos.
- Cashflow forecasting and deadline protection.
- Bill and recurring-outflow management, including avoidable waste detection.
- Concrete action drafting with impact previews.
- Supervised execution with explicit user approval.
- Continuous monitoring with anomaly detection and follow-up interventions.
- Portfolio opportunity intelligence (proposal-level): detect holding drift/opportunity and draft mandate/risk/tax-aware rebalance actions for approval.

## V1 Must Not Pretend

- No discretionary execution.
- No fake autonomy or silent money movement.
- No bank-posture messaging if Nivvi is not the bank.
- No "AI assistant" framing that implies chat without management.
- No claims that Nivvi fully replaces regulated professionals where partner rails are still required.

## Competitive Frame

Nivvi competes against five product patterns:

- Trackers and budget apps: useful for visibility, weak on action and execution.
- Cleo-style assistants: useful for conversation and nudges, weak on whole-money management across domains.
- Aggregation and control-tower apps: useful for bringing accounts into one view, weak on delegated financial work.
- Narrow automation tools: useful for one workflow, weak on prioritization across cash, bills, debt, tax, and investing.
- Wealth-only products: useful for portfolio management, weak on the rest of the household money system.

Nivvi wins only if it combines:

- full financial context,
- whole-money management,
- cross-domain reasoning,
- supervised execution,
- graceful degradation when connectors fail,
- and continuous management.

If it degenerates into a prettier dashboard or a finance chatbot, it loses its reason to exist.

## Language Guide

### Use

- AI money manager
- supervised AI money manager
- manages your money with your approval
- brings your full financial life into one system
- identifies the next best move
- prepares and executes approved actions
- continuous money management

### Avoid

- personal finance AI agent
- AI assistant
- budgeting app
- aggregator
- smart dashboard
- autopilot without supervision
- manages money for you without approval

## Proof Standard

Claims must stay tied to what the product can actually prove.

- Safe claims: unified view, cross-domain planning, action drafting, supervised execution, approval controls, auditability, partner-rail dispatch, monitoring loops.
- Claims that require evidence before use: savings amounts, yield improvement, tax reduction, bill savings, missed-deadline reduction, accuracy rates, time saved.
- Unsafe claims without proof: "fully autonomous," "replaces your advisor," "best financial outcomes," "guaranteed savings," or fabricated traction/performance metrics.

## Practical Messaging Rule

Every important Nivvi surface should make the same promise legible:

"Bring all your money into Nivvi. Nivvi identifies the next best move. You approve it. Nivvi handles the work."
