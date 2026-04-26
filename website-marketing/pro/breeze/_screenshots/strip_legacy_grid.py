"""Remove the hidden legacy ecosystem grid block we marked earlier."""
from pathlib import Path
import re

p = Path('C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/index.html')
src = p.read_text(encoding='utf-8')

# Remove the legacy block marked between begin and end comments.
pattern = re.compile(
    r'<!-- legacy-grid-removed:begin --><div hidden>.*?</div><!-- legacy-grid-removed:end -->\n',
    re.DOTALL,
)
new, n = pattern.subn('', src)
print(f'replacements: {n}, len before: {len(src)}, len after: {len(new)}')
p.write_text(new, encoding='utf-8')
