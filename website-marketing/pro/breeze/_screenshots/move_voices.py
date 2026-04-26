"""Move the founder note from its standalone section into the DDC section."""
from pathlib import Path

p = Path("C:/Users/Artem Boiko/Desktop/CodeProjects/ERP_26030500/website-marketing/pro/breeze/index.html")
s = p.read_text(encoding='utf-8')

START_MARKER = '<!-- SECTION 9 (merged into Section 10 / Built by DDC)'
TEMPLATE_OPEN = '<template id="voices-merged-template" data-merged-into="ddc">'
SECTION_CLOSE = '</section>'  # the orphan closing of old section 9

start_idx = s.find(START_MARKER)
assert start_idx > 0, "start marker not found"
# Walk back to the line start (the comment row above)
line_start = s.rfind('\n', 0, start_idx) + 1
# Walk back further to include the leading "<!-- ====" comment line
prev_line_start = s.rfind('\n', 0, line_start - 1) + 1

# Extract the voices-wrap inner content
wrap_start = s.find('<div class="voices-wrap" id="voices">', start_idx)
assert wrap_start > 0, "wrap start not found"
# Find the matching closing </div> for voices-wrap, then the orphan </section>
# After the wrap closes, there's `\n  </section>\n` — find that exact sequence.
section_close_idx = s.find('\n  </section>\n', wrap_start)
assert section_close_idx > 0, "orphan section close not found"

# Inner block we want to relocate (the full voices-wrap including its closing </div>)
wrap_end = section_close_idx  # this is the position right before the orphan </section>
voices_block = s[wrap_start:wrap_end].rstrip()  # the wrap div with all content

# What we cut from the original location: from prev_line_start (the leading
# "<!-- =====" comment) through the orphan section close + trailing newline.
cut_end = section_close_idx + len('\n  </section>\n')
assert s[cut_end-1] == '\n'

placeholder = (
    '  <!-- ================================================================ -->\n'
    '  <!-- SECTION 9 \u2014 founder note: merged into Section 10 (Built by DDC).  -->\n'
    '  <!-- ================================================================ -->\n'
)
s2 = s[:prev_line_start] + placeholder + s[cut_end:]

# Now insert voices_block inside DDC, right after the section-head closing.
ddc_anchor = '<section class="section ddc-section" id="ddc"'
ddc_idx = s2.find(ddc_anchor)
assert ddc_idx > 0, "ddc section not found"
# Section-head ends with the </p> for ddc.lede + closing </div>. Insert after that.
head_close = s2.find('    </div>\n\n    <!-- Clients-and-users strip', ddc_idx)
assert head_close > 0, "ddc section-head close not found"
insert_at = head_close + len('    </div>\n')

new_block = '\n' + voices_block + '\n\n'
s3 = s2[:insert_at] + new_block + s2[insert_at:]

p.write_text(s3, encoding='utf-8')
print('OK', 'cut bytes:', cut_end - prev_line_start, 'inserted bytes:', len(new_block))
