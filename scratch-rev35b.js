const { PrismaClient } = require('@prisma/client');
const p = new PrismaClient();
const CUT = new Date('2026-09-23T07:06:00-05:00');
(async () => {
  const copies = await p.decisionJournal.findMany({ where: { isDemo: false, createdAt: { gte: CUT }, decision: 'paper_copy' }, select: { id: true } });
  const legs = await p.paperTrade.findMany({ where: { decisionJournalId: { in: copies.map(c => c.id) } }, select: { decisionJournalId: true } });
  const s = new Set(legs.map(l => String(l.decisionJournalId)));
  const childless = copies.filter(c => !s.has(String(c.id)));
  console.log('copy decisions', copies.length, 'legs', legs.length, 'childless', childless.length);
  // legs per decision histogram
  const h = {}; for (const l of legs) h[l.decisionJournalId] = (h[l.decisionJournalId] || 0) + 1;
  console.log('legs-per-decision histogram:', JSON.stringify(Object.values(h).reduce((a, v) => (a[v] = (a[v] || 0) + 1, a), {})));
  // skip parity: log skips in-window vs journal skips
  const skips = await p.decisionJournal.findMany({ where: { isDemo: false, createdAt: { gte: CUT }, decision: 'skip' }, select: { ruleSetVersion: true } });
  const nul = skips.filter(s2 => s2.ruleSetVersion === null).length;
  console.log('journal skips', skips.length, 'null-version (coalesced)', nul);
  await p.$disconnect();
})();
