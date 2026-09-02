const fs = require('fs');
let content = fs.readFileSync('tests/engine.test.ts', 'utf8');

content = content.replace(
  /const t = await openPaperTrade\(\{/g,
  'const t = await openPaperTrade({'
);

// We need to type-cast t
content = content.replace(
  /const t = await openPaperTrade\(\{([\s\S]*?)\}\);/g,
  'const t = await openPaperTrade({$1}) as any;'
);

fs.writeFileSync('tests/engine.test.ts', content);
