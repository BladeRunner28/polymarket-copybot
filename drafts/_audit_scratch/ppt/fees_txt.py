import re, sys
h = open('fees.html', encoding='utf-8', errors='ignore').read()
t = re.sub(r'<script.*?</script>|<style.*?</style>', ' ', h, flags=re.S)
t = re.sub(r'<[^>]+>', ' ', t)
t = re.sub(r'&\w+;', ' ', t)
t = re.sub(r'[ \t]+', ' ', t)
t = re.sub(r'\n\s*\n+', '\n', t)
print('LEN', len(t))
print(t[:7000])
